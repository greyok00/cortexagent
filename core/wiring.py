from __future__ import annotations

import sys

from core import registry
from core.registry import _schema

_state = {"done": False}


def register_all() -> int:
    if _state["done"]:
        return len(registry.list_tools())

    # 2026-11-21 audit: this tree does not ship every Python tool family
    # (tools/ and services/ only carry what was ported; core.subagent was
    # never part of it). The old head-first imports made register_all()
    # die on the first missing module, which killed the whole turn with a
    # bare ModuleNotFoundError. Import each family in its own try, register
    # what imports, and name the absent ones once on stderr — the tool
    # surface shrinks instead of the session dying.
    absent: list[str] = []

    try:
        from core.subagent import spawn as _spawn
        registry.register_tool("spawn_subagent", _schema(
            "Run a sub-task with the local model.",
            {"prompt": {"type": "string"}}, ["prompt"]), _spawn)
    except ImportError:
        absent.append("core.subagent")

    try:
        from tools import files as files_mod
        registry.register_tool("files_read", _schema(
            "Read file. args: path", {"path": {"type": "string"}}, ["path"]),
            files_mod.read_file)
        registry.register_tool("files_write", _schema(
            "Write file. args: path, content",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"]), files_mod.write_file)
        registry.register_tool("files_edit", _schema(
            "Edit file. args: path, old, new",
            {"path": {"type": "string"}, "old": {"type": "string"},
             "new": {"type": "string"}}, ["path", "old", "new"]),
            files_mod.edit_file)
        registry.register_tool("files_list", _schema(
            "List dir. args: path", {"path": {"type": "string"}}, ["path"]),
            files_mod.list_dir)
        registry.register_tool("files_delete", _schema(
            "Delete path.",
            {"path": {"type": "string"}}, ["path"]), files_mod.delete_file)
    except ImportError:
        absent.append("tools.files")

    try:
        from tools import search as search_mod
        registry.register_tool("search_files", _schema(
            "Glob files. args: pattern",
            {"pattern": {"type": "string"}, "base": {"type": "string"}},
            ["pattern"]), search_mod.glob)
        registry.register_tool("search_grep", _schema(
            "Grep files. args: pattern, base, glob_filter",
            {"pattern": {"type": "string"}, "base": {"type": "string"},
             "glob_filter": {"type": "string"}}, ["pattern"]), search_mod.grep)
    except ImportError:
        absent.append("tools.search")

    def shell_kw(**kw) -> dict:
        cmd = kw.get("command") or kw.get("cmd") or kw.get("bash") or kw.get("script")
        if cmd is None and isinstance(kw.get("args"), str):
            cmd = kw["args"]
        if cmd is None:
            return {"ok": False, "output": "", "error": "missing argument: command"}
        return registry._run_command(str(cmd), int(kw.get("timeout") or 3600))

    registry.register_tool("shell", _schema(
        "Bash. args: command",
        {"command": {"type": "string"}}, ["command"]), shell_kw)

    # Web lane: the handlers used to import tools.research_integration at
    # call time, so the tools advertised an ImportError instead of a usable
    # refusal when the module is absent. Resolve it once, here.
    try:
        from tools import research_integration as research_mod

        def web_search(query: str = "", max_results: int = 12, **kw) -> dict:
            q = query or kw.get("q") or kw.get("search")
            if not q:
                return {"ok": False, "output": "", "error": "missing argument: query"}
            r = research_mod.research_search(q, max_results=max_results)
            r.setdefault("trust", "high")
            return r

        def web_fetch(url: str = "", max_chars: int = 20000, **kw) -> dict:
            u = url or kw.get("uri") or kw.get("page")
            if not u:
                return {"ok": False, "output": "", "error": "missing argument: url"}
            r = research_mod.research_scrape(u, max_chars=max_chars)
            r.setdefault("trust", "high")
            return r

        registry.register_tool("web_search", _schema(
            "Web search via local lanes and the browser scraper; results are "
            "cleaned and relevance-filtered. Parameter: query (string).",
            {"query": {"type": "string"}}, ["query"]), web_search)
        registry.register_tool("web_fetch", _schema(
            "Fetch one URL in the headless browser; returns cleaned text. "
            "Parameter: url (string).",
            {"url": {"type": "string"}}, ["url"]), web_fetch)
    except ImportError:
        absent.append("tools.research_integration")

    try:
        from tools import browser_tools as browser_mod
        browser_mod.register_browser_tools()
    except ImportError:
        absent.append("tools.browser_tools")

    try:
        from services import memory_thin
        registry.register_tool("memory_append", _schema(
            "Save memory. args: content",
            {"content": {"type": "string"}}, ["content"]),
            lambda content, role="user", **kw:
            {"ok": True, "output": memory_thin.append(content, role), "error": ""})
        registry.register_tool("memory_search", _schema(
            "Search memory. args: query",
            {"query": {"type": "string"}}, ["query"]),
            lambda query, **kw: {"ok": True, "output": memory_thin.search(query),
                                 "error": ""})
        registry.register_tool("memory_read", _schema(
            "Recent memory.", {}, []),
            lambda n=5, **kw: {"ok": True, "output": memory_thin.read_last(n),
                               "error": ""})
    except ImportError:
        absent.append("services.memory_thin")

    try:
        from services.scheduler_store import Store
        _sched = Store()
        registry.register_tool("scheduler_add", _schema(
            "Schedule task. args: title, prompt",
            {"title": {"type": "string"}, "kind": {"type": "string"},
             "prompt": {"type": "string"}}, ["title"]),
            lambda title, kind="user", prompt="", **kw: {"ok": True,
                "output": str(_sched.create(title=title, kind=kind,
                                            payload={"prompt": prompt} if prompt else None)),
                "error": ""})
        registry.register_tool("scheduler_list", _schema(
            "List scheduler tasks.", {}, []),
            lambda **kw: {"ok": True, "output": str(_sched.list()), "error": ""})
    except ImportError:
        absent.append("services.scheduler_store")

    try:
        from tools.kali_bank import bank_query
        registry.register_tool("kali_bank", _schema(
            "Query the Kali playbook command bank: 847 tools documented with "
            "exact forms. Parameter: query (string) or tool (string name).",
            {"query": {"type": "string"}, "tool": {"type": "string"}}, []),
            bank_query)
    except ImportError:
        absent.append("tools.kali_bank")

    try:
        from tools.document_adapter import parse_document as _parse_doc
        registry.register_tool("parse_document", _schema(
            "Parse doc. args: file",
            {"file": {"type": "string"}}, ["file"]), _parse_doc)
    except ImportError:
        absent.append("tools.document_adapter")

    try:
        import tools.charts as charts_mod
        registry.register_tool("charts", _schema(
            "Chart data. args: series",
            {"series": {"type": "string"}}, ["series"]),
            lambda series, **kw: {"ok": True, "output": str(
                getattr(charts_mod, "render_series", None)(series)
                if hasattr(charts_mod, "render_series") else series), "error": ""})
    except ImportError:
        absent.append("tools.charts")

    def vision(image_path: str = "", question: str = "Describe this image.", **kw) -> dict:
        import base64
        from core.llm import _post
        img = image_path or kw.get("image") or kw.get("file")
        p = _safe_img(img)
        if p is None:
            return {"ok": False, "output": "", "error": "missing or bad image path"}
        b64 = base64.b64encode(p.read_bytes()).decode()
        # _post returns the assistant message dict directly (2026-11-21
        # audit: the old code re-indexed data["choices"][0]["message"] on a
        # value that was already that dict — KeyError on every call).
        msg = _post({"model": "qwen3.8-27b",
                     "messages": [{"role": "user", "content": [
                         {"type": "text", "text": question},
                         {"type": "image_url",
                          "image_url": {"url": "data:image;base64," + b64}}]}],
                     "max_tokens": 512, "stream": False}, 120)
        if not msg:
            return {"ok": False, "output": "", "error": "vision unavailable"}
        return {"ok": True, "output": msg.get("content") or "", "error": ""}

    def _safe_img(path: str):
        from pathlib import Path as _Path
        p = _Path(path).expanduser()
        if not p.is_absolute():
            p = _Path(__file__).resolve().parent.parent / p
        if p.exists() and p.suffix.lower() in (".png", ".jpg", ".jpeg",
                                               ".webp", ".gif"):
            return p
        return None

    registry.register_tool("vision", _schema(
        "Vision. args: image_path",
        {"image_path": {"type": "string"}}, ["image_path"]), vision)

    def system_status(**kw) -> dict:
        from model.server import is_ready, server_url
        from core import llm as llm_mod
        return {"ok": True, "output": "model=%s tps=%.1f calls=%d" % (
            is_ready() and server_url() or "down", llm_mod.LAST_TPS,
            llm_mod.USAGE["calls"]), "error": ""}

    registry.register_tool("system", _schema(
        "Status.",
        {}, []), system_status)

    if absent:
        # One line, once per process — the absent families are a tree fact,
        # not a per-call error.
        sys.stderr.write("wiring: tool families not in this tree: %s\n"
                         % ", ".join(absent))

    _state["done"] = True
    return len(registry.list_tools())
