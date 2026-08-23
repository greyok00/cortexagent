# Tool Registry + `rag_query` (CortexLLM half) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build step 1 of the SlimToken orchestration layer — a declarative tool registry (`lib/tool_registry.py`) that wraps the overseer's existing task dispatch, plus a real `rag_query` tool that searches CortexLLM memory.

**Architecture:** A stdlib-only registry module holds OpenAI-compatible function schemas + handler functions. `lib/overseer.py`'s `_execute_task()` becomes a thin wrapper over `execute_tool()`, so the queue/scheduler/state machinery stays untouched. Later steps (ReAct loop, domain DBs, adapters, SOC analyst) register real handlers via `register_tool()`.

**Tech Stack:** Python 3 stdlib only (subprocess, urllib, json, sqlite3 via cortexllm). No new dependencies. Talks to the existing tiny LLM on :8082 and the existing cortexllm package.

## Global Constraints

- **stdlib-only** for the registry module — no new pip deps (matches codebase style).
- **Localhost-only bindings** — nothing on 0.0.0.0; all 127.0.0.1.
- **No PII** — use `Path.home()` / env vars; never hardcode the user home path.
- **Two-models-only** — this step adds no models; it wraps existing ones.
- **GPU reserved for the big model** — no GPU work in this step.
- **`cortexagent doctor` + full smoke must pass** after every task.
- **Every commit appends a ✅ row** to `docs/superpowers/specs/2026-08-10-daily-changelog.md`.
- **Queue bookkeeping unchanged** — `_execute_task` still returns `bool`; the queue's completed/failed logic is untouched.

---

### Task 1: Registry core + `run_command` + `query_llm` + stubs + `--smoke`

**Files:**
- Create: `lib/tool_registry.py`

**Interfaces:**
- Produces: `TOOLS: Dict[str, Dict]`, `register_tool(name, schema, handler) -> None`, `list_tools() -> List[Dict]` (OpenAI function-schema list), `execute_tool(name, args) -> Dict` (returns `{"ok": bool, "output": str, "error": str}`). Handlers `_run_command(command, timeout=3600)` and `_query_llm(prompt, system="", max_tokens=256)` both return the same `{"ok", "output", "error"}` shape. Stubs `describe_image` / `transcribe_audio` / `parse_document` / `ingest_domain` return `{"ok": False, "error": "<name>: not implemented yet"}`.

- [ ] **Step 1: Write the failing test — the `--smoke` mode**

Create `lib/tool_registry.py` with the `--smoke` mode that asserts the expected behavior, but leave the core functions raising `NotImplementedError`:

```python
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

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def register_tool(name: str, schema: Dict[str, Any], handler: Callable) -> None:
    raise NotImplementedError


def list_tools() -> List[Dict[str, Any]]:
    raise NotImplementedError


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    raise NotImplementedError


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 lib/tool_registry.py --smoke`
Expected: FAIL — `NotImplementedError` from `list_tools()`.

- [ ] **Step 3: Implement the registry core + handlers**

Replace the three `raise NotImplementedError` stubs with the real implementation, and add the handlers + schemas + `_register_all()`:

```python
import json
import subprocess
from typing import Any, Callable, Dict, List, Optional

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 lib/tool_registry.py --smoke`
Expected: PASS — "✅ tool_registry smoke PASS". `run_command` prints `registry-ok`; `query_llm` either works (tiny up) or reports graceful (tiny down); stubs return not-implemented; unknown tool handled.

- [ ] **Step 5: Commit**

```bash
git add lib/tool_registry.py
git commit -m "feat(step1): tool registry core + run_command/query_llm + stubs + --smoke"
```

---

### Task 2: Add `spawn_subagent` + media tools + `web_search`

**Files:**
- Modify: `lib/tool_registry.py` (add handlers + schemas to `_register_all`)

**Interfaces:**
- Consumes: `lib.overseer._spawn_subagent(prompt, model="sonnet", timeout=600) -> {"ok", "output", "error"}` (lazy import), `lib.media_pipeline.MediaPipeline().submit(prompt, model_type) -> dict` (lazy import), `lib.firecrawl_proxy._call_firecrawl(method, args) -> (ok, payload)` (lazy import).
- Produces: handlers `_spawn_subagent(prompt, model="sonnet", timeout=600)`, `_generate_image(prompt)`, `_generate_video(prompt)`, `_generate_media(prompt)`, `_web_search(query, limit=5)` — all return `{"ok", "output", "error"}`.

- [ ] **Step 1: Write the failing test — extend `--smoke`**

Add to `_smoke()` in `lib/tool_registry.py`, after the existing `query_llm` check:

```python
    names = [t.get("function", {}).get("name") for t in list_tools()]
    for want in ("spawn_subagent", "generate_image", "generate_video",
                 "generate_media", "web_search"):
        if want not in names:
            print(f"❌ missing tool: {want}")
            fails += 1
    print("✅ step-2 tools registered")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 lib/tool_registry.py --smoke`
Expected: FAIL — "❌ missing tool: spawn_subagent" (and the others).

- [ ] **Step 3: Implement the handlers + schemas**

Add these handlers above `_not_implemented`, and register them in `_register_all()`:

```python
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
```

Register them in `_register_all()` (after the `query_llm` registration):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 lib/tool_registry.py --smoke`
Expected: PASS — "✅ step-2 tools registered" and the full smoke passes.

- [ ] **Step 5: Commit**

```bash
git add lib/tool_registry.py
git commit -m "feat(step1): registry spawn_subagent + media tools + web_search"
```

---

### Task 3: Add `rag_query` (CortexLLM half)

**Files:**
- Modify: `lib/tool_registry.py` (add `_rag_query` handler + schema)

**Interfaces:**
- Consumes: `cortexllm.engine.search(query, *, tier, platform, limit) -> List[dict]` (returns `{role, content, timestamp, line_no}`), `cortexllm.engine.cold_get(category) -> {"category", "entries": [{"knowledge", ...}]}`, `cortexllm_vector.VectorStore().search(query, limit) -> List[dict]` (returns `{id, memory_id, platform, content, score, doc_len}`). The legacy `cortexllm_vector` module is imported by adding `CFG.cortexllm_dir/legacy` to `sys.path` (same pattern as `tests/run_smoke.py:test_regression_cortexllm_apis`).
- Produces: handler `_rag_query(domain, query, limit=10) -> {"ok", "output", "error"}` where `output` is ranked plain text.

- [ ] **Step 1: Write the failing test — extend `--smoke`**

Add to `_smoke()` in `lib/tool_registry.py`, after the step-2 check:

```python
    r = execute_tool("rag_query", {"domain": "dfir", "query": "blocked ip", "limit": 3})
    if "ok" not in r:
        print(f"❌ rag_query malformed: {r}")
        fails += 1
    else:
        print("✅ rag_query returns well-formed result (may be empty)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 lib/tool_registry.py --smoke`
Expected: FAIL — "❌ missing tool: rag_query" (from the step-2 name check) or "❌ rag_query malformed".

- [ ] **Step 3: Implement the handler + schema**

Add `_rag_query` above `_not_implemented`, and register it in `_register_all()`:

```python
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
```

Register it in `_register_all()` (after `web_search`):

```python
    register_tool("rag_query", _schema(
        "Search CortexLLM memory + domain knowledge for a query",
        {"domain": {"type": "string", "description": "domain category (e.g. dfir, osint)"},
         "query": {"type": "string", "description": "search query"},
         "limit": {"type": "integer", "description": "max results (default 10)"}},
        ["domain", "query"]), _rag_query)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 lib/tool_registry.py --smoke`
Expected: PASS — "✅ rag_query returns well-formed result (may be empty)".

- [ ] **Step 5: Commit**

```bash
git add lib/tool_registry.py
git commit -m "feat(step1): rag_query tool — CortexLLM memory search (hot/warm/cold/vector)"
```

---

### Task 4: Refactor `_execute_task` + smoke test + changelog

**Files:**
- Modify: `lib/overseer.py:1049-1120` (`_execute_task`)
- Modify: `tests/run_smoke.py` (add `test_tool_registry` + register in `TESTS`)
- Modify: `docs/superpowers/specs/2026-08-10-daily-changelog.md` (add row)

**Interfaces:**
- Consumes: `lib.tool_registry.execute_tool(name, args) -> {"ok", "output", "error"}` (from Tasks 1-3).
- Produces: `_execute_task(task) -> bool` with identical behavior to the original (queue bookkeeping unchanged).

- [ ] **Step 1: Write the failing test — add `test_tool_registry` to `tests/run_smoke.py`**

Add this function near the other regression tests (e.g. after `test_regression_cortexllm_apis` at line ~780):

```python
def test_tool_registry() -> R:
    """Tool registry: schemas valid, run_command works, stubs not-implemented."""
    from lib.tool_registry import list_tools, execute_tool
    tools = list_tools()
    if not tools:
        return R("tool registry schemas", "registry", False, "empty")
    bad = []
    for t in tools:
        f = t.get("function", {})
        if (t.get("type") != "function" or not f.get("name")
                or not f.get("description") or not f.get("parameters")):
            bad.append(f.get("name", "?"))
    if bad:
        return R("tool registry schemas", "registry", False, f"bad: {bad}")
    r = execute_tool("run_command", {"command": "echo registry-ok"})
    if not r.get("ok") or "registry-ok" not in r.get("output", ""):
        return R("tool registry run_command", "registry", False, str(r))
    r = execute_tool("describe_image", {})
    if r.get("ok") or "not implemented" not in r.get("error", ""):
        return R("tool registry stubs", "registry", False, str(r))
    return R("tool registry", "registry", True, f"{len(tools)} tools")
```

Register it in the `TESTS` dict (line ~1790) by adding a new area:

```python
    "registry": [test_tool_registry],
```

- [ ] **Step 2: Run test to verify it passes (registry already works from Tasks 1-3)**

Run: `python3 tests/run_smoke.py --area registry`
Expected: PASS — "✅ [registry] tool registry".

- [ ] **Step 3: Refactor `_execute_task` in `lib/overseer.py`**

Replace the body of `_execute_task` (lines 1049-1120) with a thin wrapper over the registry. Keep the `_log` calls and the `bool` return so the queue bookkeeping is unchanged:

```python
def _execute_task(task: Dict) -> bool:
    """Execute a single task. Returns True on success.

    Step-1 refactor: thin wrapper over the tool registry (lib/tool_registry.py).
    The queue/scheduler/state machinery is untouched — this still returns bool
    so the queue's completed/failed bookkeeping is unchanged.
    """
    task_type = task.get("type", "command")
    prompt = task.get("prompt", "")
    command = task.get("command", "")
    output = task.get("output", "")

    _log(f"Running {task_type} task...", "▶️", MAGENTA)

    from lib.tool_registry import execute_tool

    if task_type == "command":
        result = execute_tool("run_command", {"command": command})
    elif task_type == "llm":
        result = execute_tool("query_llm", {
            "prompt": prompt,
            "system": task.get("system", ""),
            "max_tokens": task.get("max_tokens", 256),
        })
    elif task_type == "subagent":
        result = execute_tool("spawn_subagent", {
            "prompt": prompt,
            "model": task.get("model", "sonnet"),
            "timeout": int(task.get("timeout", 600)),
        })
    elif task_type == "image":
        result = execute_tool("generate_image", {"prompt": prompt})
    elif task_type == "video":
        result = execute_tool("generate_video", {"prompt": prompt})
    elif task_type == "media":
        result = execute_tool("generate_media", {"prompt": prompt})
    else:
        _log(f"Unknown task type: {task_type}", "❌", RED)
        return False

    if result.get("ok"):
        _log(f"{task_type} task completed", "✅", GREEN)
        return True
    _log(f"{task_type} task failed: {result.get('error', '')[:120]}", "❌", RED)
    return False
```

- [ ] **Step 4: Run the smoke gate to verify the refactor**

Run: `python3 tests/run_smoke.py --area registry --area static --area overseer --area cli`
Expected: ALL PASS — the refactor preserves `_execute_task` behavior (the existing overseer/cli tests still pass).

- [ ] **Step 5: Add the changelog row**

Add a row to the DONE table in `docs/superpowers/specs/2026-08-10-daily-changelog.md` (after row 26):

```markdown
| 27 | Aug 12 | **Step 1: tool registry + `rag_query` (CortexLLM half)** — `lib/tool_registry.py` (stdlib-only): declarative `TOOLS` dict, `list_tools()` (OpenAI function schemas), `execute_tool(name, args)`, `register_tool()`. v1 tools: `run_command`, `query_llm`, `spawn_subagent`, `generate_image/video/media`, `web_search` (firecrawl → DuckDuckGo fallback), `rag_query` (CortexLLM hot/warm/cold/vector search); stubs `describe_image`/`transcribe_audio`/`parse_document`/`ingest_domain` return not-implemented. `_execute_task` refactored to a thin wrapper over the registry (queue bookkeeping unchanged). `--smoke` + `tests/run_smoke.py` registry area. | `lib/tool_registry.py`, `lib/overseer.py`, `tests/run_smoke.py` | Spec: `2026-08-12-slimtoken-orchestration-design.md` §4-5. Foundation for ReAct loop (step 2), domain DBs (step 3), adapters (step 4), SOC analyst. |
```

- [ ] **Step 6: Commit**

```bash
git add lib/overseer.py tests/run_smoke.py docs/superpowers/specs/2026-08-10-daily-changelog.md
git commit -m "refactor(step1): _execute_task over tool registry + smoke test + changelog"
```

- [ ] **Step 7: Full smoke gate**

Run: `python3 tests/run_smoke.py`
Expected: ALL PASS (29/29 + the new registry test). If any pre-existing test fails, report it honestly — do not mask it.
