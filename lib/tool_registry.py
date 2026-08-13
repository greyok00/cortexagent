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
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Registry ────────────────────────────────────────────────────────────────
TOOLS: Dict[str, Dict[str, Any]] = {}


def register_tool(name: str, schema: Dict[str, Any], handler: Callable) -> None:
    """Add a tool at runtime. Later steps (adapters, RAG) register here."""
    TOOLS[name] = {"schema": schema, "handler": handler}


def list_tools() -> List[Dict[str, Any]]:
    """OpenAI function-schema list — what the model sees for tool_calls."""
    return [
        {"type": "function", "function": {
            "name": name,
            "description": t["schema"]["description"],
            "parameters": t["schema"]["parameters"],
        }}
        for name, t in sorted(TOOLS.items())
    ]


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch to handler. Returns {"ok": bool, "output": str, "error": str}."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "output": "", "error": f"unknown tool: {name}"}
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
    """Run a shell command, return stdout/stderr."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode == 0:
            return {"ok": True, "output": output, "error": ""}
        return {"ok": False, "output": output, "error": f"exit {result.returncode}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


def _query_llm(prompt: str, system: str = "", max_tokens: int = 256) -> Dict[str, Any]:
    """Query the tiny LLM (overseer's reasoning engine)."""
    from lib.overseer import _query_tiny_llm
    result = _query_tiny_llm(prompt, system, max_tokens)
    if result:
        return {"ok": True, "output": result, "error": ""}
    return {"ok": False, "output": "", "error": "tiny LLM unavailable"}


def _spawn_subagent(prompt: str, model: str = "sonnet", timeout: int = 600) -> Dict[str, Any]:
    """Delegate to a Claude Code subagent (full tool access)."""
    from lib.overseer import _spawn_subagent as _spawn
    return _spawn(prompt, model=model, timeout=timeout)


def _generate_image(prompt: str) -> Dict[str, Any]:
    """Generate an image via the media pipeline (diffusers, in-process)."""
    from lib.media_pipeline import MediaPipeline
    result = MediaPipeline().submit(prompt, model_type="image")
    if result.get("status") == "completed":
        return {"ok": True, "output": json.dumps(result, ensure_ascii=False), "error": ""}
    return {"ok": False, "output": "", "error": result.get("status", "unknown")}


def _generate_video(prompt: str) -> Dict[str, Any]:
    """Generate a video via the media pipeline."""
    from lib.media_pipeline import MediaPipeline
    result = MediaPipeline().submit(prompt, model_type="video")
    if result.get("status") == "completed":
        return {"ok": True, "output": json.dumps(result, ensure_ascii=False), "error": ""}
    return {"ok": False, "output": "", "error": result.get("status", "unknown")}


def _generate_media(prompt: str) -> Dict[str, Any]:
    """Auto-detect image vs video vs text via the media pipeline."""
    from lib.media_pipeline import MediaPipeline
    result = MediaPipeline().submit(prompt, model_type="auto")
    if result.get("status") == "completed":
        return {"ok": True, "output": json.dumps(result, ensure_ascii=False), "error": ""}
    return {"ok": False, "output": "", "error": result.get("status", "unknown")}


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
    """Composite RAG: CortexLLM memory (hot/warm/cold) + vector index.

    Domain-DB half (SQLite FTS5 + vec0) lands in step 3 of the orchestration
    spec; until then it returns empty gracefully.
    """
    results: List[Dict[str, str]] = []
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
    # Stubs — real handlers land in later steps (adapters spec, domain-db spec).
    register_tool("describe_image", _schema(
        "Describe an image or answer a question about it (returns text)",
        {"image": {"type": "string", "description": "path to the image file"},
         "prompt": {"type": "string", "description": "caption request or VQA question"}},
        ["image"]), _not_implemented("describe_image"))
    register_tool("transcribe_audio", _schema(
        "Transcribe an audio file to text (faster-whisper, CPU)",
        {"file": {"type": "string", "description": "path to the audio file"}},
        ["file"]), _not_implemented("transcribe_audio"))
    register_tool("parse_document", _schema(
        "Extract text from a document (PDF/DOCX/PPTX/XLSX/scanned)",
        {"file": {"type": "string", "description": "path to the document"}},
        ["file"]), _not_implemented("parse_document"))
    register_tool("ingest_domain", _schema(
        "Ingest text into a domain knowledge base",
        {"domain": {"type": "string", "enum": ["business", "dfir", "law", "osint", "programming"]},
         "source": {"type": "string", "description": "file path / URL / title"},
         "text": {"type": "string", "description": "content to ingest"}},
        ["domain", "source", "text"]), _not_implemented("ingest_domain"))


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

    r = execute_tool("rag_query", {"domain": "dfir", "query": "blocked ip", "limit": 3})
    if "ok" not in r:
        print(f"❌ rag_query malformed: {r}")
        fails += 1
    else:
        print("✅ rag_query returns well-formed result (may be empty)")

    for name in ("describe_image", "transcribe_audio", "parse_document", "ingest_domain"):
        r = execute_tool(name, {})
        if r.get("ok") or "not implemented" not in r.get("error", ""):
            print(f"❌ stub {name}: {r}")
            fails += 1
    print("✅ stubs return not-implemented")

    r = execute_tool("no_such_tool", {})
    if r.get("ok") or "unknown tool" not in r.get("error", ""):
        print(f"❌ unknown tool: {r}")
        fails += 1
    else:
        print("✅ unknown tool handled")

    print("✅ tool_registry smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/tool_registry.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
