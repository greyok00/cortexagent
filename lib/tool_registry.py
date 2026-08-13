#!/usr/bin/env python3
"""lib/tool_registry.py — declarative tool registry for the overseer.

Each tool is an OpenAI-compatible function schema (what the tiny model's chat
template renders for tool_calls) + a handler function. The ReAct loop (step 2)
calls tools via execute_tool(); later steps (adapters, RAG, domain DBs)
register real handlers via register_tool().

Usage:
  python3 lib/tool_registry.py --smoke   # self-test
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MAX_TOOL_OUTPUT = 100_000  # chars — cap tool output to protect the model's context


# ── Registry ────────────────────────────────────────────────────────────────
TOOLS: Dict[str, Dict[str, Any]] = {}


def register_tool(name: str, schema: Dict[str, Any], handler: Callable,
                  priority: int = 0) -> None:
    """Add a tool at runtime. Later steps (adapters, RAG) register here.

    ``priority`` orders the tool surface: lower sorts first. Core tools
    register at 0; harness tools (browser/skills/MCP) at 1 so the core
    surface always survives the react loop's tool cap.
    """
    TOOLS[name] = {"schema": schema, "handler": handler, "priority": priority}


def list_tools(limit: Optional[int] = None, stub: bool = False) -> List[Dict[str, Any]]:
    """OpenAI function-schema list — what the model sees for tool_calls.

    ``limit`` caps the number of tools returned (sorted by priority, then
    name). The react loop uses this to keep the tool surface inside the tiny
    model's context window — the full registry can hold hundreds of MCP
    tools, but the model only sees the top ``limit`` (core + browser first,
    then MCP/skills).

    ``stub=True`` returns MINIFIED entries — name + truncated description,
    NO parameters. The full schema stays in the registry (the "database
    indexed of all the information"); ``execute_tool`` resolves it on call
    (the "tiny call that calls the large call"). A stub is ~35 tokens vs
    ~180 for a full schema — the whole 168-tool surface drops from ~30k to
    ~6k tokens, and the default 21-tool surface to ~700.
    """
    tools = []
    for name, t in sorted(TOOLS.items(),
                          key=lambda kv: (kv[1].get("priority", 0), kv[0])):
        if stub:
            desc = t["schema"]["description"]
            if len(desc) > 50:
                desc = desc[:47] + "..."
            tools.append({"type": "function", "function": {
                "name": name, "description": desc}})
        else:
            tools.append({"type": "function", "function": {
                "name": name,
                "description": t["schema"]["description"],
                "parameters": t["schema"]["parameters"]}})
    if limit is not None:
        tools = tools[:limit]
    return tools


def get_schema(name: str) -> Optional[Dict[str, Any]]:
    """Return a tool's full schema (the stub-mode resolution target)."""
    tool = TOOLS.get(name)
    return tool["schema"] if tool else None


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch to handler. Returns {"ok": bool, "output": str, "error": str}.

    Stub-mode resolution: validates required args against the full schema
    (missing → helpful error listing the required params so the model can
    retry), coerces integer/number/string types, then dispatches. Empty
    strings pass through — handlers keep their own validation (e.g.
    run_command's "non-empty" guard).
    """
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "output": "", "error": f"unknown tool: {name}"}
    schema = tool["schema"]
    params = schema.get("parameters") or {}
    props = params.get("properties") or {}
    required = params.get("required") or []
    missing = [p for p in required if p not in args or args[p] is None]
    if missing:
        hints = ", ".join(f"{p} ({props.get(p, {}).get('type', '?')})"
                          for p in missing)
        return {"ok": False, "output": "",
                "error": f"missing required args: {hints}"}
    for p, spec in props.items():
        if p not in args or args[p] is None:
            continue
        t = spec.get("type")
        if t == "integer" and not isinstance(args[p], int):
            try:
                args[p] = int(args[p])
            except (TypeError, ValueError):
                pass
        elif t == "number" and not isinstance(args[p], (int, float)):
            try:
                args[p] = float(args[p])
            except (TypeError, ValueError):
                pass
        elif t == "string" and not isinstance(args[p], str):
            args[p] = str(args[p])
    try:
        result = tool["handler"](**args)
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, "output": str(result), "error": ""}
    except TypeError as e:
        return {"ok": False, "output": "", "error": f"bad args: {e}"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


# ── Handlers ────────────────────────────────────────────────────────────────
def _run_command(command: str, timeout: int = 3600) -> Dict[str, Any]:
    """Run a shell command, return stdout/stderr.

    Guardrails (step 2): (1) arg validation — command must be a non-empty
    string, timeout coerced to int; (2) process-group kill — the shell runs
    in its own session (start_new_session=True) so a timeout kills the whole
    group (killpg), not just the direct child, preventing orphaned
    shell-spawned children.
    """
    if not isinstance(command, str) or not command.strip():
        return {"ok": False, "output": "", "error": "command must be a non-empty string"}
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return {"ok": False, "output": "", "error": "timeout must be an integer"}
    if timeout < 1:
        timeout = 3600
    proc = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        stdout, stderr = proc.communicate()
        return {"ok": False, "output": (stdout or "") + (stderr or ""),
                "error": f"timeout after {timeout}s (process group killed)"}
    output = stdout
    if stderr:
        output += ("\n" if output else "") + stderr
    if len(output) > MAX_TOOL_OUTPUT:
        output = output[:MAX_TOOL_OUTPUT] + f"\n…[truncated {len(output) - MAX_TOOL_OUTPUT} chars]"
    if proc.returncode == 0:
        return {"ok": True, "output": output, "error": ""}
    return {"ok": False, "output": output, "error": f"exit {proc.returncode}"}


def _query_llm(prompt: str, system: str = "", max_tokens: int = 256) -> Dict[str, Any]:
    """Query the tiny LLM (overseer's reasoning engine)."""
    from lib.overseer import _query_tiny_llm
    result = _query_tiny_llm(prompt, system, max_tokens)
    if result:
        return {"ok": True, "output": result, "error": ""}
    return {"ok": False, "output": "", "error": "tiny LLM unavailable"}


_ALLOWED_SUBAGENT_MODELS = {"sonnet", "opus", "haiku"}
_MAX_SUBAGENT_TIMEOUT = 1800


def _spawn_subagent(prompt: str, model: str = "sonnet", timeout: int = 600) -> Dict[str, Any]:
    """Delegate to a Claude Code subagent (full tool access).

    Guardrails (step 2): model must be in the allowlist (this tool runs
    `claude -p --dangerously-skip-permissions` — the highest-severity combo
    if prompt-injected); timeout coerced to int and capped at 1800s.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "output": "", "error": "prompt must be a non-empty string"}
    if model not in _ALLOWED_SUBAGENT_MODELS:
        return {"ok": False, "output": "",
                "error": f"model must be one of {sorted(_ALLOWED_SUBAGENT_MODELS)}"}
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return {"ok": False, "output": "", "error": "timeout must be an integer"}
    timeout = min(max(timeout, 1), _MAX_SUBAGENT_TIMEOUT)
    from lib.overseer import _spawn_subagent as _spawn
    return _spawn(prompt, model=model, timeout=timeout)


def _generate_image(prompt: str) -> Dict[str, Any]:
    """Generate an image via the media pipeline (diffusers, background)."""
    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="image")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _generate_video(prompt: str) -> Dict[str, Any]:
    """Generate a video via the media pipeline (diffusers, background)."""
    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="video")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _generate_media(prompt: str) -> Dict[str, Any]:
    """Auto-detect image vs video vs text via the media pipeline (background)."""
    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="auto")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _web_search(query: str, limit: int = 5) -> Dict[str, Any]:
    """Search the web. Tries firecrawl if configured, else DuckDuckGo HTML."""
    import os
    import re
    import urllib.parse
    import urllib.request
    if os.environ.get("FIRECRAWL_API_KEY"):
        try:
            from lib.firecrawl_proxy import _call_firecrawl
            ok, payload = _call_firecrawl("search", {"query": query, "limit": limit})
            if ok:
                return {"ok": True,
                        "output": json.dumps(payload, ensure_ascii=False)[:8000],
                        "error": ""}
        except Exception:
            pass  # fall through to DuckDuckGo
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "replace")
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
        snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
        lines = []
        for i, (href, title) in enumerate(links[:limit], 1):
            title = re.sub(r"<[^>]+>", "", title).strip()
            snip = ""
            if i - 1 < len(snips):
                snip = re.sub(r"<[^>]+>", "", snips[i - 1]).strip()
            lines.append(f"{i}. {title}\n   {href}\n   {snip}")
        if not lines:
            return {"ok": True, "output": "(no results)", "error": ""}
        return {"ok": True, "output": "\n".join(lines), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"web_search failed: {e}"}


def _rag_query(domain: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """Composite RAG: domain DB (FTS5 + vec0) + CortexLLM memory.

    Domain-DB hits are appended FIRST so they survive the results[:limit]
    truncation below — the memory half can return up to ~3×limit results and
    would otherwise crowd out the domain hits (the point of the domain layer).
    """
    if not query or not query.strip():
        return {"ok": True, "output": "(no results)", "error": ""}
    results: List[Dict[str, str]] = []
    # Domain-DB half (step 3) — FTS5 + vec0 hybrid, RRF-merged internally.
    try:
        from lib.domain_db import search as _db_search
        for hit in _db_search(domain, query, limit=limit):
            results.append({"tier": "domain", "source": hit.get("source", domain),
                            "text": hit.get("chunk", "")})
    except Exception:
        pass  # domain DB optional — memory search still works
    try:
        from cortexllm.engine import search as _search, cold_get as _cold_get
        for tier in ("hot", "warm"):
            for hit in _search(query, tier=tier, platform="cortexagent", limit=limit):
                results.append({"tier": tier, "source": "memory",
                                "text": hit.get("content", "")})
        cold = _cold_get(domain)
        for entry in cold.get("entries", []):
            text = entry.get("knowledge", "")
            if isinstance(text, dict):
                text = json.dumps(text, ensure_ascii=False)
            if query.lower() in str(text).lower():
                results.append({"tier": "cold", "source": domain, "text": str(text)})
        try:
            from lib.config import CFG
            legacy_dir = CFG.cortexllm_dir / "legacy"
            if legacy_dir.is_dir() and str(legacy_dir) not in sys.path:
                sys.path.insert(0, str(legacy_dir))
            from cortexllm_vector import VectorStore
            for hit in VectorStore().search(query, limit=limit):
                results.append({"tier": "vector", "source": "vector",
                                "text": hit.get("content", "")})
        except Exception:
            pass  # vector index optional — keyword search still works
    except Exception as e:
        return {"ok": False, "output": "", "error": f"rag_query failed: {e}"}
    lines = []
    for i, r in enumerate(results[:limit], 1):
        text = r["text"].strip().replace("\n", " ")[:500]
        lines.append(f"[{i}] ({r['tier']}/{r['source']}) {text}")
    if not lines:
        return {"ok": True, "output": "(no results)", "error": ""}
    return {"ok": True, "output": "\n".join(lines), "error": ""}


def _ingest_domain(domain: str, source: str, text: str) -> Dict[str, Any]:
    """Ingest text into a domain knowledge base (chunk → embed → store)."""
    from lib.domain_ingest import ingest
    r = ingest(domain, source, text)
    if r.get("ok"):
        return {"ok": True,
                "output": f"ingested {r.get('chunks', 0)} chunks into {domain}",
                "error": ""}
    return {"ok": False, "output": "", "error": r.get("error", "ingest failed")}


def _describe_image(image: str, prompt: str = "Describe this image in detail.") -> Dict[str, Any]:
    """Describe an image or answer a VQA question about it (Moondream, GPU-when-budget-allows)."""
    try:
        from lib.image_adapter import describe
        text = describe(image, prompt)
        return {"ok": bool(text), "output": text, "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"describe_image failed: {e}"}


def _transcribe_audio(file: str) -> Dict[str, Any]:
    """Transcribe an audio file to text (faster-whisper, CPU)."""
    from pathlib import Path
    if not Path(file).is_file():
        return {"ok": False, "output": "", "error": f"transcribe_audio failed: file not found: {file}"}
    try:
        from lib import stt
        text = stt.transcribe(file)
        return {"ok": bool(text), "output": text, "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"transcribe_audio failed: {e}"}


def _parse_document(file: str) -> Dict[str, Any]:
    """Extract text from a document (PDF/DOCX/PPTX/XLSX/scanned)."""
    try:
        from lib.document_adapter import parse_document
        r = parse_document(file)
        if r.get("ok"):
            text = r.get("text", "")
            return {"ok": True, "output": text or "(no text layer — OCR unavailable)",
                    "error": r.get("error", "")}
        return {"ok": False, "output": "", "error": f"parse_document failed: {r.get('error', 'parse failed')}"}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"parse_document failed: {e}"}


def _not_implemented(name: str) -> Callable:
    def _stub(**kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "output": "", "error": f"{name}: not implemented yet"}
    return _stub


# ── Tool schemas ────────────────────────────────────────────────────────────
def _schema(description: str, properties: Dict[str, Any],
            required: List[str]) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}


def _register_all() -> None:
    register_tool("run_command", _schema(
        "Run a shell command, return stdout/stderr",
        {"command": {"type": "string", "description": "shell command to run"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 3600)"}},
        ["command"]), _run_command)
    register_tool("query_llm", _schema(
        "Query the tiny LLM (overseer reasoning engine)",
        {"prompt": {"type": "string", "description": "prompt"},
         "system": {"type": "string", "description": "system prompt (optional)"},
         "max_tokens": {"type": "integer", "description": "max output tokens (default 256)"}},
        ["prompt"]), _query_llm)
    register_tool("spawn_subagent", _schema(
        "Delegate to a Claude Code subagent (full tool access)",
        {"prompt": {"type": "string", "description": "task for the subagent"},
         "model": {"type": "string", "description": "model (default sonnet)"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 600)"}},
        ["prompt"]), _spawn_subagent)
    register_tool("generate_image", _schema(
        "Generate an image via the media pipeline (diffusers)",
        {"prompt": {"type": "string", "description": "image prompt"}},
        ["prompt"]), _generate_image)
    register_tool("generate_video", _schema(
        "Generate a video via the media pipeline (diffusers)",
        {"prompt": {"type": "string", "description": "video prompt"}},
        ["prompt"]), _generate_video)
    register_tool("generate_media", _schema(
        "Auto-detect image vs video vs text via the media pipeline",
        {"prompt": {"type": "string", "description": "media prompt"}},
        ["prompt"]), _generate_media)
    register_tool("web_search", _schema(
        "Search the web (firecrawl if configured, else DuckDuckGo)",
        {"query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 5)"}},
        ["query"]), _web_search)
    register_tool("rag_query", _schema(
        "Search CortexLLM memory + domain knowledge for a query",
        {"domain": {"type": "string", "description": "domain category (e.g. dfir, osint)"},
         "query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 10)"}},
        ["domain", "query"]), _rag_query)
    register_tool("describe_image", _schema(
        "Describe an image or answer a question about it (returns text)",
        {"image": {"type": "string", "description": "path to the image file"},
         "prompt": {"type": "string", "description": "caption request or VQA question"}},
        ["image"]), _describe_image)
    register_tool("transcribe_audio", _schema(
        "Transcribe an audio file to text (faster-whisper, CPU)",
        {"file": {"type": "string", "description": "path to the audio file"}},
        ["file"]), _transcribe_audio)
    register_tool("parse_document", _schema(
        "Extract text from a document (PDF/DOCX/PPTX/XLSX/scanned)",
        {"file": {"type": "string", "description": "path to the document"}},
        ["file"]), _parse_document)
    register_tool("ingest_domain", _schema(
        "Ingest text into a domain knowledge base",
        {"domain": {"type": "string", "enum": ["business", "dfir", "law", "osint", "programming"]},
         "source": {"type": "string", "description": "file path / URL / title"},
         "text": {"type": "string", "description": "content to ingest"}},
        ["domain", "source", "text"]), _ingest_domain)


_register_all()


def _smoke() -> int:
    """Self-test: schema shape, run_command, query_llm, stubs."""
    fails = 0
    tools = list_tools()
    if not tools:
        print("❌ list_tools() empty")
        fails += 1
    for t in tools:
        f = t.get("function", {})
        if (t.get("type") != "function" or not f.get("name")
                or not f.get("description") or not f.get("parameters")):
            print(f"❌ bad schema: {f.get('name')}")
            fails += 1
    print(f"✅ {len(tools)} tools registered, schemas valid")

    r = execute_tool("run_command", {"command": "echo registry-ok"})
    if not r.get("ok") or "registry-ok" not in r.get("output", ""):
        print(f"❌ run_command: {r}")
        fails += 1
    else:
        print("✅ run_command works")

    r = execute_tool("query_llm", {"prompt": "say ok", "max_tokens": 8})
    if "ok" not in r:
        print(f"❌ query_llm malformed: {r}")
        fails += 1
    elif r.get("ok"):
        print("✅ query_llm works (tiny up)")
    else:
        print("⚠️ query_llm graceful (tiny down): " + r.get("error", ""))

    names = [t.get("function", {}).get("name") for t in list_tools()]
    for want in ("spawn_subagent", "generate_image", "generate_video",
                 "generate_media", "web_search"):
        if want not in names:
            print(f"❌ missing tool: {want}")
            fails += 1
    print("✅ step-2 tools registered")

    names = [t.get("function", {}).get("name") for t in list_tools()]
    if "rag_query" not in names:
        print("❌ missing tool: rag_query")
        fails += 1
    r = execute_tool("rag_query", {"domain": "dfir", "query": "blocked ip", "limit": 3})
    if "ok" not in r:
        print(f"❌ rag_query malformed: {r}")
        fails += 1
    else:
        print("✅ rag_query returns well-formed result (may be empty)")

    # ── multimodal adapters (step 4) ────────────────────────────────────────
    r = execute_tool("describe_image", {"image": "/nonexistent.png"})
    if r.get("ok") or "failed" not in r.get("error", ""):
        print(f"❌ describe_image error path: {r}")
        fails += 1
    r = execute_tool("transcribe_audio", {"file": "/nonexistent.wav"})
    if r.get("ok") or "failed" not in r.get("error", ""):
        print(f"❌ transcribe_audio error path: {r}")
        fails += 1
    r = execute_tool("parse_document", {"file": "/nonexistent.pdf"})
    if r.get("ok") or "failed" not in r.get("error", ""):
        print(f"❌ parse_document error path: {r}")
        fails += 1
    print("✅ adapters return clean errors")

    r = execute_tool("no_such_tool", {})
    if r.get("ok") or "unknown tool" not in r.get("error", ""):
        print(f"❌ unknown tool: {r}")
        fails += 1
    else:
        print("✅ unknown tool handled")

    # ── guardrails (step 2) ────────────────────────────────────────────────
    r = execute_tool("run_command", {"command": "echo guard-ok", "timeout": "5"})
    if not r.get("ok") or "guard-ok" not in r.get("output", ""):
        print(f"❌ run_command timeout coercion: {r}")
        fails += 1
    r = execute_tool("run_command", {"command": ""})
    if r.get("ok") or "non-empty" not in r.get("error", ""):
        print(f"❌ run_command empty-command guard: {r}")
        fails += 1
    r = execute_tool("spawn_subagent", {"prompt": "x", "model": "gpt-4"})
    if r.get("ok") or "model" not in r.get("error", ""):
        print(f"❌ spawn_subagent model allowlist: {r}")
        fails += 1
    r = execute_tool("rag_query", {"domain": "dfir", "query": "   "})
    if not r.get("ok") or "(no results)" not in r.get("output", ""):
        print(f"❌ rag_query empty-query guard: {r}")
        fails += 1
    print("✅ guardrails enforced")

    # ── domain DBs (step 3) ────────────────────────────────────────────────
    r = execute_tool("ingest_domain",
                     {"domain": "dfir", "source": "smoke.txt", "text": "blocked IP 10.0.0.5 beaconing"})
    if not r.get("ok"):
        print(f"❌ ingest_domain: {r}")
        fails += 1
    else:
        print("✅ ingest_domain works")
    r = execute_tool("rag_query", {"domain": "dfir", "query": "blocked IP", "limit": 3})
    if not r.get("ok"):
        print(f"❌ rag_query composite: {r}")
        fails += 1
    else:
        print("✅ rag_query domain half works")
    r = execute_tool("ingest_domain", {"domain": "nope", "source": "s", "text": "t"})
    if r.get("ok") or "unknown domain" not in r.get("error", ""):
        print(f"❌ ingest_domain bad domain: {r}")
        fails += 1

    # ── stub mode (minified tool surface) ─────────────────────────────────
    stubs = list_tools(stub=True)
    if not stubs:
        print("❌ list_tools(stub=True) empty")
        fails += 1
    for t in stubs:
        f = t.get("function", {})
        if (t.get("type") != "function" or not f.get("name")
                or not f.get("description") or "parameters" in f):
            print(f"❌ stub leaked parameters: {f.get('name')}")
            fails += 1
    full = list_tools()
    stub_chars = sum(len(json.dumps(t, ensure_ascii=False)) for t in stubs)
    full_chars = sum(len(json.dumps(t, ensure_ascii=False)) for t in full)
    if stub_chars >= full_chars:
        print(f"❌ stub mode not smaller: {stub_chars} vs {full_chars}")
        fails += 1
    else:
        print(f"✅ stub mode: {len(stubs)} tools, {stub_chars:,} chars vs {full_chars:,} full "
              f"({100 - stub_chars * 100 // full_chars}% smaller)")

    # stub resolution: missing required → helpful error; coercion works
    r = execute_tool("run_command", {})
    if r.get("ok") or "missing required args" not in r.get("error", ""):
        print(f"❌ stub missing-arg error: {r}")
        fails += 1
    else:
        print("✅ stub missing-arg resolution: " + r.get("error", ""))
    r = execute_tool("run_command", {"command": "echo stub-ok", "timeout": "5"})
    if not r.get("ok") or "stub-ok" not in r.get("output", ""):
        print(f"❌ stub coercion: {r}")
        fails += 1
    else:
        print("✅ stub type coercion works")
    if get_schema("run_command") is None:
        print("❌ get_schema('run_command') None")
        fails += 1
    else:
        print("✅ get_schema resolves full schema")

    print("✅ tool_registry smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/tool_registry.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
