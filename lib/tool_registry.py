#!/usr/bin/env python3

"""Tool registry: declares the tool schema catalogue and dispatches each tool call to its implementation with guardrails enforced."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MAX_TOOL_OUTPUT = None

TOOLS: Dict[str, Dict[str, Any]] = {}


_DISABLED: set = {s.strip() for s in os.environ.get("CORTEXAGENT_DISABLED_TOOLS", "").split(",") if s.strip()}

def register_tool(name: str, schema: Dict[str, Any], handler: Callable,
                  priority: int = 0, trust: str = "high") -> None:

    TOOLS[name] = {"schema": schema, "handler": handler,
                   "priority": priority, "trust": trust}

def list_tools(limit: Optional[int] = None, stub: bool = False) -> List[Dict[str, Any]]:

    tools = []
    for name, t in sorted(TOOLS.items(),
                          key=lambda kv: (kv[1].get("priority", 0), kv[0])):
        if name in _DISABLED:
            continue
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
    if name in _DISABLED:
        return {"ok": False, "output": "", "error": f"tool disabled: {name}"}
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

    from lib.overseer import _query_llm
    result = _query_llm(prompt, system, max_tokens)
    if result:
        return {"ok": True, "output": result, "error": ""}
    return {"ok": False, "output": "", "error": "LLM unavailable"}

from lib.config import CFG as _CFG
_ALLOWED_SUBAGENT_MODELS = {os.environ.get("CORTEXAGENT_CLOUD_MODEL", "") or _CFG.model_cloud}
_VENDOR_MODEL_ALIASES = {"sonnet", "opus", "haiku"}
_MAX_SUBAGENT_TIMEOUT = 1800

def _spawn_subagent(prompt: str, model: str = "",
                    timeout: int = 600) -> Dict[str, Any]:

    if not model:
        from lib.config import CFG
        model = CFG.model_cloud
    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "output": "", "error": "prompt must be a non-empty string"}
    if model in _VENDOR_MODEL_ALIASES:
        from lib.config import CFG
        model = CFG.model_cloud
    if model not in _ALLOWED_SUBAGENT_MODELS:
        return {"ok": False, "output": "",
                "error": ("model must be an ollama cloud model; one of "
                          f"{sorted(_ALLOWED_SUBAGENT_MODELS)}")}
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return {"ok": False, "output": "", "error": "timeout must be an integer"}
    timeout = min(max(timeout, 1), _MAX_SUBAGENT_TIMEOUT)
    from lib.overseer import _spawn_subagent as _spawn
    return _spawn(prompt, model=model, timeout=timeout)

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

def _patchright_scrape(url: str, max_chars: int = 20000) -> Dict[str, Any]:

    from lib.scraper.research_integration import research_scrape
    r = research_scrape(url, max_chars=max_chars)
    r.setdefault("trust", "high")
    return r


def _patchright_search(query: str,
                       category: str = "general",
                       max_results: int = 12,
                       time_range: str = "",
                       language: str = "") -> Dict[str, Any]:

    from lib.scraper.research_integration import research_search
    r = research_search(query, category=category, max_results=max_results,
               time_range=time_range, language=language)
    r.setdefault("trust", "high")
    return r


def _patchright_deep(question: str,
                     categories: Optional[List[str]] = None,
                     max_pages: int = 8,
                     max_chars_per_page: int = 8000) -> Dict[str, Any]:

    from lib.scraper.research_integration import research_deep
    r = research_deep(question, categories=categories, max_pages=max_pages,
            max_chars_per_page=max_chars_per_page)
    r.setdefault("trust", "high")
    return r


def _searxng_engine_test(force: bool = False) -> Dict[str, Any]:

    from lib.scraper.searxng_integrated import SearXNGEngineManager
    m = SearXNGEngineManager()
    result = m.test_engines(force=force)
    result.setdefault("trust", "high")
    return result


def _scraper_health() -> Dict[str, Any]:

    from lib.scraper.research_integration import ResearchScraperBridge
    r = ResearchScraperBridge().health_check()
    r.setdefault("trust", "high")
    return r


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

    for searxng in ("http://127.0.0.1:8888",):
        try:
            url = (f"{searxng}/search?q={urllib.parse.quote(query)}"
                   f"&format=rss&safesearch=0&basicauth=0")
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
        from lib import slimtoken_module as _slim
        _eng = _slim("slimtoken.memory.engine")
        _search, _cold_get = _eng.search, _eng.cold_get
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
        db = Path.home() / ".cortexagent" / "memory" / "memory.db"
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

def _download(urls: List[str], dest: str, sha256: str = "",
              workers: int = 6, wait: bool = False) -> Dict[str, Any]:
    script = str(Path(__file__).resolve().parent / "download_verified.py")
    log_dir = Path.home() / ".cortexagent" / "downloads"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"dl-{int(time.time())}.log"
    cmd = [sys.executable, script, *urls, "--dest", dest,
           "--workers", str(max(1, int(workers)))]
    if sha256:
        cmd += ["--sha256", sha256]
    if wait:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=600)
            (log.write_text(r.stdout + r.stderr))
            ok = r.returncode == 0
            return {"ok": ok, "output": (r.stdout or "")[-4000:], "error":
                    "" if ok else f"exit {r.returncode} — see {log}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error":
                    f"wait=true timed out (600s) — download continues in "
                    f"background? check {log}"}
    proc = subprocess.Popen(cmd, stdout=open(log, "w"),
                            stderr=subprocess.STDOUT)
    return {"ok": True,
            "output": (f"download started in background (pid {proc.pid}). "
                       f"Log: {log} — poll it or read {dest}/MANIFEST.json "
                       f"for per-file verify status (verified / "
                       f"unverified_no_hash / hash_mismatch / failed)."),
            "error": ""}



def _greysearch_tool(query: str = "", url: str = "", scrape_all: bool = True,
                     max_results: int = 10, max_seconds: float = 300.0,
                     write_guide_to: str = "", task_id: str = "",
                     pinned_sources=None) -> Dict[str, Any]:

    from lib.scraper.research_integration import (
        get_bridge, research_deep)
    from lib.scraper.greysearch_mcp import (
        _attach_guide, _bind_slot, _resolve_guide_path, _thin_fill, _shape_response)
    if url and url.strip():
        return get_bridge().research_scrape(url.strip(), max_chars=0)
    if not str(query).strip():
        return {"ok": False, "error": "provide query (research) or url (single-page scrape)"}
    if not scrape_all:
        return get_bridge().research_search(query, category="general",
                                            max_results=max(1, int(max_results)))
    slot_note = ""
    if str(task_id).strip():
        tid = _bind_slot(task_id)
        slot_note = f"task slot bound: {tid}"
    result = research_deep(query, max_pages=max(1, min(int(max_results), 25)),
                           max_total_seconds=float(max_seconds),
                           pinned_sources=list(pinned_sources or []))
    if len(result.get("pages_fetched", [])) < 3:
        _thin_fill(query, result)
    out = _resolve_guide_path(write_guide_to, query)
    result = _attach_guide(result, query, out)
    result = _shape_response(result, keep_raw=False)
    if slot_note:
        result["slot"] = slot_note
    return result


def _greysearch_health_tool() -> Dict[str, Any]:

    from lib.scraper.research_integration import get_bridge
    return get_bridge().health_check()


def _register_all() -> None:

    register_tool("patchright_scrape", _schema(
        "Fetch one URL with patchright Chromium (stealth, no API keys); "
        "returns readable text with title, domain, and tier metadata.",
        {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 20000)"}
        },
        ["url"]), _patchright_scrape, trust="high")

    register_tool("patchright_search", _schema(
        "Search via local SearXNG with automatic engine testing and validation; "
        "returns deduped results with domain/tier metadata.",
        {
            "query": {"type": "string", "description": "Search query"},
            "category": {"type": "string", "description": "Search category (default general)"},
            "max_results": {"type": "integer", "description": "Max results (default 12)"},
            "time_range": {"type": "string", "description": "Time range filter (optional)"},
            "language": {"type": "string", "description": "Language filter (optional)"}
        },
        ["query"]), _patchright_search, trust="high")

    register_tool("patchright_deep", _schema(
        "Full research pipeline: multiple searches, diverse-domain selection, "
        "page fetching, fact extraction with source URLs, and unverified list for "
        "claims without sources.",
        {
            "question": {"type": "string", "description": "Research question"},
            "categories": {"type": "array", "items": {"type": "string"}, "description": "Search categories (auto-selected if omitted)"},
            "max_pages": {"type": "integer", "description": "Max pages to fetch (default 8)"},
            "max_chars_per_page": {"type": "integer", "description": "Max chars per page (default 8000)"}
        },
        ["question"]), _patchright_deep, trust="high")

    register_tool("searxng_engine_test", _schema(
        "Test all configured SearXNG engines to determine which ones are working.",
        {"force": {"type": "boolean", "description": "Force retesting (default false)"}},
        []), _searxng_engine_test, trust="high")

    register_tool("scraper_health", _schema(
        "Health check for patchright scraper, SearXNG integration, and research bridge.",
        {},
        []), _scraper_health, trust="high")


    register_tool("greysearch", _schema(
        "THE ONE WEB RESEARCHER — the DEFAULT for every research question "
        "(supersedes patchright_*/web_search for research): deep search + "
        "scraping + Master Guide by default; url= scrapes one page; "
        "scrape_all=false = ranked search results only.",
        {
            "query": {"type": "string", "description": "Research question (required unless url is given)"},
            "url": {"type": "string", "description": "Scrape ONE page instead of researching"},
            "scrape_all": {"type": "boolean", "description": "true (default) = deep run + Master Guide; false = search-only"},
            "max_results": {"type": "integer", "description": "Max pages scraped (default 10, max 25)"},
            "max_seconds": {"type": "number", "description": "Budget seconds (default 300)"},
            "write_guide_to": {"type": "string", "description": "Master Guide output path (optional)"},
            "task_id": {"type": "string", "description": "Optional task-1..task-4 slot binding"},
            "pinned_sources": {"type": "array", "items": {"type": "string"},
                               "description": "Exact primary-domain URLs fetched first (search fallback only)"}
        },
        []), _greysearch_tool, trust="high")

    register_tool("greysearch_health", _schema(
        "Status for the greysearch researcher: SearXNG lanes, searx.space, "
        "private stealth browser, research bridge.",
        {}, []), _greysearch_health_tool, trust="high")



    register_tool("run_command", _schema(
        "Run a shell command, return stdout/stderr",
        {"command": {"type": "string", "description": "shell command to run"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 3600)"}},
        ["command"]), _run_command, trust="low")
    register_tool("query_llm", _schema(
        "Query the local LLM (overseer reasoning engine)",
        {"prompt": {"type": "string", "description": "prompt"},
         "system": {"type": "string", "description": "system prompt (optional)"},
         "max_tokens": {"type": "integer", "description": "max output tokens (default 256)"}},
        ["prompt"]), _query_llm, trust="high")
    register_tool("spawn_subagent", _schema(
        "Delegate to a CortexAgent local subagent (full tool access)",
        {"prompt": {"type": "string", "description": "task for the subagent"},
         "model": {"type": "string", "description": "ollama CLOUD model (default: conf [provider] ollama_model); vendor model aliases are ignored"},
         "timeout": {"type": "integer", "description": "timeout seconds (default 600)"}},
        ["prompt"]), _spawn_subagent, trust="medium")
    register_tool("web_search", _schema(
        "Quick helper: local SearXNG (:8888) first, then DuckDuckGo HTML "
        "fallback. For real research, the default is the greysearch tool "
        "(deep search + Master Guide).",
        {"query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 5)"}},
        ["query"]), _web_search, trust="high")
    register_tool("download", _schema(
        "Download ANY http(s) file(s): parallel range-chunks for speed, "
        "resumable (.part + HTTP Range), SHA256-verified — uses the caller's "
        "hash when given, else a sibling .sha256 file, else records the real "
        "hash as unverified_no_hash. A hash mismatch DELETES the corrupt "
        "file and fails. Runs in the background by default (never hangs the "
        "chat); wait=true for small files.",
        {"urls": {"type": "array", "items": {"type": "string"},
                  "description": "file URLs (no repo/provider restrictions)"},
         "dest": {"type": "string", "description": "target directory"},
         "sha256": {"type": "string", "description":
                    "expected sha256 (single-URL downloads; optional)"},
         "workers": {"type": "integer", "description":
                     "parallel workers (default 6)"},
         "wait": {"type": "boolean", "description":
                  "block until done (small files; 600s cap)"}},
        ["urls", "dest"]), _download, trust="medium")
    register_tool("rag_query", _schema(
        "Search agent memory + domain knowledge for a query",
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
    register_tool("add_llm_provider", _schema(
        "Return the step-by-step checklist for adding a new LLM provider to packages/ai",
        {"provider": {"type": "string", "description": "provider name (optional)"}},
        []), _add_llm_provider, trust="high")

_register_all()

from lib.converted_mcp_tools import execute_converted_tool as _exec

_MCP_TOOL_DEFS = [
    {"name": "memory_read", "desc": "Read from hot or cold memory (no caps)",
     "params": {"type": "object", "properties": {
         "tier": {"type": "string", "enum": ["hot", "cold"]},
         "limit": {"type": "integer", "description": "Max rows (default 20)."},
         "category": {"type": "string", "description": "Cold category filter."}
     }, "required": ["tier"]}},
    {"name": "memory_write", "desc": "Append to hot or cold memory (no caps)",
     "params": {"type": "object", "properties": {
         "tier": {"type": "string", "enum": ["hot", "cold"]},
         "content": {"type": "string"},
         "role": {"type": "string", "enum": ["user", "assistant", "system", "cold"]},
         "category": {"type": "string", "description": "Category for cold facts."}
     }, "required": ["tier", "content"]}},
    {"name": "memory_search", "desc": "Search across hot + cold memory",
     "params": {"type": "object", "properties": {
         "query": {"type": "string"},
         "limit": {"type": "integer"}
     }, "required": ["query"]}},
    {"name": "memory_clear", "desc": "Clear agent memory",
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

# ~25 designed tools (CVE intel + MITRE mapping,
# hardening posture, SIEM/SOAR queries, API adapters) shipped in
# converted_mcp_tools.TOOL_MAP with shipped schemas but were never REGISTERED
# — a whole dead tool layer ("features not working as designed"). Register
# every TOOL_MAP entry that has a shipped schema, skipping ones already
# registered above, and skipping the two side-effect-bearing families (SOAR
# playbook execution, firecrawl dedupe) are scaffolded but not yet registered.
_CONVERTED_SKIP = {"soar_run_on_recent", "soar_run_posture",
                   "firecrawl_search", "firecrawl_scrape",
                   "memory_read", "memory_write", "memory_search", "memory_clear"}
try:
    from lib.converted_mcp_tools import (CONVERTED_TOOLS as _CONVERTED_TOOLS,
                                         TOOL_MAP as _TOOL_MAP)
    _conv_defs = {}
    for _t in _CONVERTED_TOOLS:
        _f = (_t.get("function") or {}) if isinstance(_t, dict) else {}
        if _f.get("name"):
            _conv_defs[_f["name"]] = _t
    for _name in _TOOL_MAP:
        if _name in _CONVERTED_SKIP or _name in TOOLS:
            continue
        _tdef = _conv_defs.get(_name)
        if not _tdef:
            continue
        register_tool(_name, _tdef, _conv_tool(_name), priority=5)
except Exception as _e:
    print(f"tool_registry: converted tool registration skipped: {_e}",
          file=sys.stderr)


from lib.kali_bank import bank_query as _kali_bank_query

register_tool("kali_bank", _schema(
    "Query the Kali playbook command bank: 847 tools / 2,078 documented lab-only "
    "command forms with {{VAR}} slip-in slots (cortexagent-commands.json). "
    "kali_bank(query='handshake capture') searches names, purposes and commands; "
    "kali_bank(tool='airodump-ng') returns a tool's exact forms + slots + source; "
    "kali_bank(phase='9') lists a phase; kali_bank(slot='IP') explains a slip-in token.",
    {"query": {"type": "string", "description": "free-text search (tool names, purposes, command text)"},
     "tool": {"type": "string", "description": "exact/partial tool name or slug — returns that tool's command forms"},
     "phase": {"type": "string", "description": "phase 0-9 — lists tools in that phase"},
     "slot": {"type": "string", "description": "a {{TOKEN}} name — returns its grammar meaning"},
     "limit": {"type": "integer", "description": "max results shown (default 6, max 12)"}},
    []), _kali_bank_query, trust="high")

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
        print("✅ query_llm works (LLM up)")
    else:
        print("⚠️ query_llm graceful (LLM down): " + r.get("error", ""))

    names = [t.get("function", {}).get("name") for t in list_tools()]
    for want in ("spawn_subagent", "web_search"):
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
