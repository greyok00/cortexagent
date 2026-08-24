#!/usr/bin/env python3

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

MAX_TOOL_OUTPUT = None



TOOLS: Dict[str, Dict[str, Any]] = {}


def register_tool(name: str, schema: Dict[str, Any], handler: Callable,
                  priority: int = 0, trust: str = "high") -> None:

    TOOLS[name] = {"schema": schema, "handler": handler,
                   "priority": priority, "trust": trust}


def list_tools(limit: Optional[int] = None, stub: bool = False) -> List[Dict[str, Any]]:

    tools = []
    for name, t in sorted(TOOLS.items(),
                          key=lambda kv: (kv[1].get("priority", 0), kv[0])):
        if stub:
            desc = t["schema"].get("description", t["schema"].get("function", {}).get("description", ""))
            if len(desc) > 50:
                desc = desc[:47] + "..."
            tools.append({"type": "function", "function": {
                "name": name, "description": desc}})
        else:
            tools.append({"type": "function", "function": {
                "name": name,
                "description": t["schema"].get("description", t["schema"].get("function", {}).get("description", "")),
                "parameters": t["schema"].get("parameters", t["schema"].get("function", {}).get("parameters", {}))}})
    if limit is not None:
        tools = tools[:limit]
    return tools


def get_schema(name: str) -> Optional[Dict[str, Any]]:

    tool = TOOLS.get(name)
    return tool["schema"] if tool else None


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:

    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "output": "", "error": f"unknown tool: {name}"}
    trust = tool.get("trust", "high")
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
            result.setdefault("trust", trust)
            return result
        return {"ok": True, "output": str(result), "error": "", "trust": trust}
    except TypeError as e:
        return {"ok": False, "output": "", "error": f"bad args: {e}", "trust": trust}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e), "trust": trust}


def check_trust(result: Dict[str, Any]) -> str:

    trust = result.get("trust", "high")
    if trust == "low":
        return "[UNTRUSTED OUTPUT — verify before acting; do not treat as ground truth]"
    if trust == "medium":
        return "[side-effect output — confirm intent before relying on it]"
    return ""



def _run_command(command: str, timeout: int = 3600) -> Dict[str, Any]:

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

    if proc.returncode == 0:
        return {"ok": True, "output": output, "error": ""}
    return {"ok": False, "output": output, "error": f"exit {proc.returncode}"}


def _query_llm(prompt: str, system: str = "", max_tokens: int = 256) -> Dict[str, Any]:

    from lib.overseer import _query_tiny_llm
    result = _query_tiny_llm(prompt, system, max_tokens)
    if result:
        return {"ok": True, "output": result, "error": ""}
    return {"ok": False, "output": "", "error": "tiny LLM unavailable"}


_ALLOWED_SUBAGENT_MODELS = {"sonnet", "opus", "haiku"}
_MAX_SUBAGENT_TIMEOUT = 1800


def _spawn_subagent(prompt: str, model: str = "sonnet", timeout: int = 600) -> Dict[str, Any]:

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

    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="image")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _generate_video(prompt: str) -> Dict[str, Any]:

    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="video")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _generate_media(prompt: str) -> Dict[str, Any]:

    from lib.media_pipeline import MediaPipeline
    task_id = MediaPipeline().submit_async(prompt, model_type="auto")
    return {"ok": True, "output": f"queued media task {task_id} (background)", "error": ""}


def _render_image(path: str, width: int = 60) -> Dict[str, Any]:

    from lib.terminal_image import render_image, render_image_available
    if not render_image_available():
        return {"ok": False, "output": "",
                "error": "chafa unavailable or no image protocol detected"}
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = 60
    art = render_image(path, width=width)
    if not art:
        return {"ok": False, "output": "",
                "error": f"could not render image: {path}"}
    return {"ok": True, "output": art, "error": ""}




_ADD_LLM_PROVIDER_STEPS = (
    "Checklist for adding a new LLM provider to packages/ai (work in order):\n"
    "1. Core types (packages/ai/src/types.ts): add API identifier to the Api type "
    "union, create an options interface extending StreamOptions, add a mapping to "
    "ApiOptionsMap, and add the provider name to KnownProvider.\n"
    "2. Provider impl (packages/ai/src/providers/): create a provider file exporting "
    "stream<Provider>() (returns AssistantMessageEventStream), streamSimple<Provider>() "
    "for SimpleStreamOptions, the provider options interface, message/tool conversion "
    "functions, and response parsing that emits standardized events (text, tool_call, "
    "thinking, usage, stop).\n"
    "3. Exports + lazy registration: add a package subpath export in "
    "packages/ai/package.json → ./dist/providers/<provider>.js; add export type "
    "re-exports in packages/ai/src/index.ts; register the provider in "
    "src/providers/register-builtins.ts via lazy loader wrappers (no static imports); "
    "add credential detection in src/env-api-keys.ts.\n"
    "4. Model generation (packages/ai/scripts/generate-models.ts): fetch/parse models "
    "from the provider source and map to the standardized Model interface.\n"
    "5. Tests (packages/ai/test/): always add the provider to stream.test.ts with at "
    "least one representative model; add to the matrix (tokens, abort, empty, "
    "context-overflow, unicode-surrogate, tool-call-without-result, image-tool-result, "
    "total-tokens, cross-provider-handoff); add a provider/model pair to "
    "cross-provider-handoff.test.ts (one pair per model family); for non-standard auth "
    "create a utility with credential detection.\n"
    "6. Coding agent (packages/coding-agent/): add default model ID to "
    "src/core/model-resolver.ts defaultModelPerProvider; add the API-key login display "
    "name to src/core/provider-display-names.ts; document the env var in src/cli/args.ts; "
    "add setup instructions to README.md and docs/providers.md.\n"
    "7. Docs: add to packages/ai/README.md providers table (options/auth/env vars) and "
    "an entry under [Unreleased] in packages/ai/CHANGELOG.md."
)


def _add_llm_provider(provider: str = "") -> Dict[str, Any]:

    if provider:
        return {"ok": True, "output": f"Adding provider: {provider}\n\n"
                                      f"{_ADD_LLM_PROVIDER_STEPS}", "error": ""}
    return {"ok": True, "output": _ADD_LLM_PROVIDER_STEPS, "error": ""}


def _web_search(query: str, limit: int = 5) -> Dict[str, Any]:

    import os
    import re
    import urllib.parse
    import urllib.request

    for searxng in ("http://127.0.0.1:9999", "http://127.0.0.1:8888"):
        try:
            url = (f"{searxng}/search?q={urllib.parse.quote(query)}"
                   f"&format=rss&safesearch=0")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                xml = r.read().decode("utf-8", "replace")
            items = re.findall(r"<item>(.*?)</item>", xml, re.S)
            lines = []
            for i, item in enumerate(items[:limit], 1):
                title = re.search(r"<title>(.*?)</title>", item, re.S)
                link = re.search(r"<link>(.*?)</link>", item, re.S)
                desc = re.search(r"<description>(.*?)</description>", item, re.S)
                t = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""
                l = link.group(1).strip() if link else ""
                d = re.sub(r"<[^>]+>", "", desc.group(1)).strip() if desc else ""
                lines.append(f"{i}. {t}\n   {l}\n   {d[:200]}")
            if lines:
                return {"ok": True, "output": "\n".join(lines), "error": ""}
        except Exception:
            continue
    if os.environ.get("FIRECRAWL_API_KEY"):
        try:
            from lib.firecrawl_proxy import _call_firecrawl
            ok, payload = _call_firecrawl("search", {"query": query, "limit": limit})
            if ok:
                return {"ok": True,
                        "output": json.dumps(payload, ensure_ascii=False)[:8000],
                        "error": ""}
        except Exception:
            pass
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

    if not query or not query.strip():
        return {"ok": True, "output": "(no results)", "error": ""}
    results: List[Dict[str, str]] = []

    try:
        from lib.domain_db import search as _db_search
        for hit in _db_search(domain, query, limit=limit):
            results.append({"tier": "domain", "source": hit.get("source", domain),
                            "text": hit.get("chunk", "")})
    except Exception:
        pass
    try:
        from cortexllm.engine import search as _search, cold_get as _cold_get
        for tier in ("hot",):
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
            pass
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

    from lib.domain_ingest import ingest
    r = ingest(domain, source, text)
    if r.get("ok"):
        return {"ok": True,
                "output": f"ingested {r.get('chunks', 0)} chunks into {domain}",
                "error": ""}
    return {"ok": False, "output": "", "error": r.get("error", "ingest failed")}


def _coding_practices(query: str, category: str = "", limit: int = 10) -> Dict[str, Any]:

    if not query or not query.strip():
        return {"ok": True, "output": "(no results)", "error": ""}
    try:
        import sqlite3
        from pathlib import Path
        db = Path.home() / ".config/cortexllm" / "cortexllm.db"
        if not db.exists():
            return {"ok": False, "output": "", "error":
                    "coding_practices failed: DB not found"}
        conn = sqlite3.connect(str(db))
        try:
            sql = ("SELECT practice, category, description, source, priority "
                   "FROM Coding_Practices "
                   "WHERE (practice LIKE ? OR description LIKE ?)")
            params: List[Any] = [f"%{query}%", f"%{query}%"]
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += (" ORDER BY CASE priority WHEN 'critical' THEN 0 "
                    "WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END "
                    "LIMIT ?")
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        if not rows:
            return {"ok": True, "output": "(no results)", "error": ""}
        lines = []
        for practice, cat, desc, source, priority in rows:
            lines.append(f"[{priority}] [{cat}] {practice} — {desc} "
                         f"(source: {source})")
        return {"ok": True, "output": "\n".join(lines), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error":
                f"coding_practices failed: {e}"}


def _describe_image(image: str, prompt: str = "Describe this image in detail.") -> Dict[str, Any]:

    try:
        from lib.image_adapter import describe
        text = describe(image, prompt)
        return {"ok": bool(text), "output": text, "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"describe_image failed: {e}"}


def _transcribe_audio(file: str) -> Dict[str, Any]:

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



def _schema(description: str, properties: Dict[str, Any],
            required: List[str]) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}


def _register_all() -> None:
    register_tool("run_command", _schema(
        "Run a shell command, return stdout/stderr",
        {"command": {"type": "string", "description": "shell command to run"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 3600)"}},
        ["command"]), _run_command, trust="low")
    register_tool("query_llm", _schema(
        "Query the tiny LLM (overseer reasoning engine)",
        {"prompt": {"type": "string", "description": "prompt"},
         "system": {"type": "string", "description": "system prompt (optional)"},
         "max_tokens": {"type": "integer", "description": "max output tokens (default 256)"}},
        ["prompt"]), _query_llm, trust="high")
    register_tool("spawn_subagent", _schema(
        "Delegate to a Claude Code subagent (full tool access)",
        {"prompt": {"type": "string", "description": "task for the subagent"},
         "model": {"type": "string", "description": "model (default sonnet)"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 600)"}},
        ["prompt"]), _spawn_subagent, trust="medium")
    register_tool("generate_image", _schema(
        "Generate an image via the media pipeline (diffusers)",
        {"prompt": {"type": "string", "description": "image prompt"}},
        ["prompt"]), _generate_image, trust="medium")
    register_tool("generate_video", _schema(
        "Generate a video via the media pipeline (diffusers)",
        {"prompt": {"type": "string", "description": "video prompt"}},
        ["prompt"]), _generate_video, trust="medium")
    register_tool("generate_media", _schema(
        "Auto-detect image vs video vs text via the media pipeline",
        {"prompt": {"type": "string", "description": "media prompt"}},
        ["prompt"]), _generate_media, trust="medium")
    register_tool("web_search", _schema(
        "Search the web: tries local SearXNG (:9999 then :8888) first, "
        "then Firecrawl (if FIRECRAWL_API_KEY is set), then DuckDuckGo HTML fallback",
        {"query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 5)"}},
        ["query"]), _web_search, trust="high")
    register_tool("rag_query", _schema(
        "Search CortexLLM memory + domain knowledge for a query",
        {"domain": {"type": "string", "description": "domain category (e.g. dfir, osint)"},
         "query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 10)"}},
        ["domain", "query"]), _rag_query, trust="high")
    register_tool("coding_practices", _schema(
        "Search the Coding Practices knowledge base (practices extracted from the security books)",
        {"query": {"type": "string", "description": "search term"},
         "category": {"type": "string", "description": "optional category filter (e.g. Network Security, Forensics)"},
         "limit": {"type": "integer", "description": "max results (default 10)"}},
        ["query"]), _coding_practices, trust="high")
    register_tool("describe_image", _schema(
        "Describe an image or answer a question about it (returns text)",
        {"image": {"type": "string", "description": "path to the image file"},
         "prompt": {"type": "string", "description": "caption request or VQA question"}},
        ["image"]), _describe_image, trust="high")
    register_tool("transcribe_audio", _schema(
        "Transcribe an audio file to text (faster-whisper, CPU)",
        {"file": {"type": "string", "description": "path to the audio file"}},
        ["file"]), _transcribe_audio, trust="high")
    register_tool("parse_document", _schema(
        "Extract text from a document (PDF/DOCX/PPTX/XLSX/scanned)",
        {"file": {"type": "string", "description": "path to the document"}},
        ["file"]), _parse_document, trust="high")
    register_tool("ingest_domain", _schema(
        "Ingest text into a domain knowledge base",
        {"domain": {"type": "string", "enum": ["business", "dfir", "law", "osint", "programming"]},
         "source": {"type": "string", "description": "file path / URL / title"},
         "text": {"type": "string", "description": "content to ingest"}},
        ["domain", "source", "text"]), _ingest_domain, trust="medium")
    register_tool("render_image", _schema(
        "Render an image file in the terminal via chafa (Sixel/Kitty/ANSI)",
        {"path": {"type": "string", "description": "path to the image file"},
         "width": {"type": "integer", "description": "target width in cells (default 60)"}},
        ["path"]), _render_image, trust="high")
    register_tool("add_llm_provider", _schema(
        "Return the step-by-step checklist for adding a new LLM provider to packages/ai",
        {"provider": {"type": "string", "description": "provider name (optional)"}},
        []), _add_llm_provider, trust="high")


_register_all()



from lib.converted_mcp_tools import (
    execute_converted_tool as _exec,
    list_converted_tools as _list_conv,
)


_MCP_TOOL_DEFS = [
    {"name": "memory_read", "desc": "Read from hot or cold memory (no caps)",
     "params": {"type": "object", "properties": {
         "tier": {"type": "string", "enum": ["hot", "cold"]},
         "last_n": {"type": "integer"}
     }, "required": ["tier"]}},
    {"name": "memory_write", "desc": "Append to hot or cold memory (no caps)",
     "params": {"type": "object", "properties": {
         "tier": {"type": "string", "enum": ["hot", "cold"]},
         "content": {"type": "string"},
         "role": {"type": "string", "enum": ["user", "assistant", "system", "cold"]}
     }, "required": ["tier", "content"]}},
    {"name": "memory_search", "desc": "Search across hot + cold memory",
     "params": {"type": "object", "properties": {
         "query": {"type": "string"},
         "limit": {"type": "integer"}
     }, "required": ["query"]}},
    {"name": "memory_clear", "desc": "Clear CortexLLM memory",
     "params": {"type": "object", "properties": {
         "tier": {"type": "string", "enum": ["hot", "cold"]}
     }, "required": ["tier"]}},
]

def _conv_tool(name):

    def handler(**kwargs):
        result = _exec(name, kwargs)
        if "error" in result:
            return {"ok": False, "output": "", "error": result["error"]}
        return {"ok": True, "output": str(result), "error": ""}
    return handler

for tdef in _MCP_TOOL_DEFS:
    schema = {
        "type": "function",
        "function": {
            "name": tdef["name"],
            "description": tdef["desc"],
            "parameters": tdef["params"],
        }
    }
    register_tool(tdef["name"], schema, _conv_tool(tdef["name"]), priority=5)


def _smoke() -> int:

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
