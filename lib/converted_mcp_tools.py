#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

_CWD = Path(__file__).resolve().parent.parent
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))


if str(_CWD / "lib") not in sys.path:
    sys.path.insert(0, str(_CWD / "lib"))

from lib.memory_readers import read_jsonl_tail

class HTTPSession:

    _instances: Dict[str, 'HTTPSession'] = {}
    _lock = threading.Lock()

    def __init__(self, base_url: str = ""):
        self.base_url = base_url
        self.session = None

    @classmethod
    def get(cls, base_url: str = "") -> 'HTTPSession':
        with cls._lock:
            if base_url not in cls._instances:
                cls._instances[base_url] = cls(base_url)
            return cls._instances[base_url]

    def get_session(self):

        if self.session is None:
            import requests
            self.session = requests.Session()
            if self.base_url:
                self.session.base_url = self.base_url
        return self.session



_COLD_PROFILES_STATIC = ("shared", "platform:cortexagent")
_READ_PREVIEW = 400


def _preview(text, limit: int = _READ_PREVIEW) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


_ENV_MEMORY_DIR_REMOVED = True

def _store_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get(
        "CORTEXAGENT_MEMORY_DIR",
        str(Path.home() / ".cortexagent" / "memory"))))

def _read_tail(path: Path, n: int):
    # Shared per-row-tolerant reader: one copy of the
    # tail logic now lives in lib/memory_readers.py.
    if not path.exists() or n <= 0:
        return []
    from lib.memory_readers import read_jsonl_tail
    return read_jsonl_tail(path, n)["rows"]

def _append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = path.open("a", encoding="utf-8")
    try:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
    finally:
        fp.close()

def memory_read(tier: str, platform: str = "cortexagent", category: str = None,
                limit: int = 20) -> dict:

    try:
        limit = max(1, min(int(limit or 20), 200))
        store = _store_dir()
        if tier == "hot":
            hot_res = read_jsonl_tail(store / "hot" / f"{platform}.jsonl", limit)
            data = [{"role": r.get("role", "user"),
                     "timestamp": r.get("timestamp", ""),
                     "content": _preview(r.get("content", ""))}
                    for r in hot_res["rows"]]
            if hot_res["status"] == "corrupt":
                return {"error": f"hot store unreadable "
                                 f"({hot_res['dropped']} corrupt row(s))"}
        elif tier == "cold":
            cold_res = read_jsonl_tail(store / "cold" / f"{platform}.jsonl", limit)
            data = [{"category": r.get("category", "general"),
                     "timestamp": r.get("timestamp", ""),
                     "fact": _preview(r.get("fact", r.get("content", "")))}
                    for r in cold_res["rows"]]
            if cold_res["status"] == "corrupt":
                return {"error": f"cold store unreadable "
                                 f"({cold_res['dropped']} corrupt row(s))"}
        else:
            return {"error": f"Invalid tier: {tier} (hot + cold only)"}
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"error": str(e)}

def memory_write(tier: str, content: str, platform: str = "cortexagent",
                 category: str = None, role: str = "user") -> dict:

    try:
        from time import strftime
        store = _store_dir()
        if not (content or "").strip():
            return {"error": "empty content"}
        if tier in ("hot", "warm"):

            _append_jsonl(store / "hot" / f"{platform}.jsonl",
                          {"role": role, "content": content,
                           "timestamp": strftime("%Y-%m-%d %H:%M:%S"),
                           "platform": platform})
            result = {"status": "written", "tier": "hot", "platform": platform}
        elif tier == "cold":
            _append_jsonl(store / "cold" / f"{platform}.jsonl",
                          {"fact": content, "category": category or "general",
                           "timestamp": strftime("%Y-%m-%d %H:%M:%S"),
                           "source": "agent", "platform": platform})
            result = {"status": "written", "tier": "cold", "category": category or "general"}
        else:
            result = {"error": f"Invalid tier: {tier} (hot + cold only)"}
        return result
    except Exception as e:
        return {"error": str(e)}

def memory_search(query: str, limit: int = 10) -> dict:

    try:
        import re as _re
        store = _store_dir()
        platform = os.environ.get("CORTEXAGENT_PLATFORM", "cortexagent")
        tokens = _re.findall(r"\w{2,}", (query or "").lower())
        if not tokens:
            tokens = [(query or "").strip().lower()] if query.strip() else []
        if not tokens:
            return {"status": "ok", "results": []}
        results = []
        seen = set()

        def _collect(path: Path, tier: str, extract):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            for line in text.split("\n"):
                if not line.strip():
                    continue
                low = line.lower()
                if not all(t in low for t in tokens):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = {"content": line}
                item = extract(entry)
                key = (tier, str(item.get("content"))[:80])
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= limit * 2:
                    return True

        def _hot_extract(e):
            return {"tier": "hot", "role": e.get("role", "user"),
                    "content": _preview(e.get("content", "")),
                    "timestamp": e.get("timestamp", "")}

        def _cold_extract(e):
            return {"tier": "cold", "category": e.get("category", "general"),
                    "content": _preview(e.get("fact", e.get("content", ""))),
                    "timestamp": e.get("timestamp", "")}

        try:
            _collect(store / "hot" / f"{platform}.jsonl", "hot", _hot_extract)
            _collect(store / "cold" / f"{platform}.jsonl", "cold", _cold_extract)
        except Exception:
            pass
        return {"status": "ok", "results": results[:limit]}
    except Exception as e:
        return {"error": str(e)}

def memory_stats() -> dict:

    try:
        store = _store_dir()
        platform = os.environ.get("CORTEXAGENT_PLATFORM", "cortexagent")
        def count(path: Path):
            return sum(1 for l in path.open("rb")) if path.exists() else 0
        return {"status": "ok", "platform": platform, "store": str(store),
                "hot": count(store / "hot" / f"{platform}.jsonl"),
                "cold": count(store / "cold" / f"{platform}.jsonl"),
                "tiers": ["hot", "cold"]}
    except Exception as e:
        return {"error": str(e)}

def memory_clear(tier: str, platform: str = None) -> dict:

    try:
        store = _store_dir()
        hot = store / "hot" / f"{platform or 'cortexagent'}.jsonl"
        cold = store / "cold" / f"{platform or 'cortexagent'}.jsonl"
        if tier in ("hot", "all") and hot.exists():
            hot.write_text("")
        if tier in ("cold", "all") and cold.exists():
            cold.write_text("")
        return {"status": "cleared", "tier": tier}
    except Exception as e:
        return {"error": str(e)}

def adapter_list() -> dict:

    try:
        from lib.adapters import all_adapters_dict
        items = all_adapters_dict(only_enabled=False)
        return {"status": "ok", "adapters": items, "count": len(items)}
    except Exception as e:
        return {"error": str(e)}

def adapter_search(query: str, limit: int = 5,
                    adapter_name: Optional[str] = None) -> dict:

    try:
        from lib.adapters import (
            get as _get,
            list_adapters,
            search_all as _search_all,
        )
        if adapter_name:
            adapter = _get(adapter_name)
            if adapter is None:
                names = [a.name for a in list_adapters()]
                return {"error": f"unknown adapter: {adapter_name!r}",
                        "available": names}
            if not adapter.enabled:
                return {"error": f"adapter {adapter_name} is disabled",
                        "health": adapter.health_check()}
            try:
                results = adapter.search(query, limit=limit)
                return {"status": "ok", "results": {adapter_name: results}}
            except Exception as e:
                return {"error": str(e), "source": adapter_name}

        enabled = list_adapters(only_enabled=True)
        if not enabled:
            return {"status": "noop",
                    "reason": "no enabled adapters — set adapter env vars "
                              "(GOOGLE_API_KEY+GOOGLE_CSE_ID, etc.) or run "
                              "adapter_list() to see what is available"}
        results = _search_all(query, limit=limit, only_enabled=True)
        return {"status": "ok", "results": results,
                "backends": [a.name for a in enabled]}
    except Exception as e:
        return {"error": str(e)}

def firecrawl_search(query: str, limit: int = 10) -> dict:

    try:
        from lib.firecrawl_proxy import FirecrawlClient
        fc = FirecrawlClient()
        results = fc.search(query, limit)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}

def firecrawl_scrape(url: str) -> dict:

    try:
        from lib.firecrawl_proxy import FirecrawlClient
        fc = FirecrawlClient()
        content = fc.scrape(url)
        return {"status": "ok", "content": content}
    except Exception as e:
        return {"error": str(e)}

def slimtoken_minify(messages: list) -> dict:

    try:
        from slimtoken.pipeline import minify_request, MinifyConfig
        out, stats = minify_request({"messages": messages}, MinifyConfig())
        msgs = out.get("messages", messages) if isinstance(out, dict) else messages
        return {"status": "ok", "minified": msgs, "stats": stats}
    except Exception as e:
        return {"error": str(e)}

def slimtoken_maxify(messages: list) -> dict:

    import re
    DEDUP_RE = re.compile(
        r"\[slimtoken: identical to a later tool_result; omitted (\d+) chars\]")
    DISTILL_RE = re.compile(r"\[slimtoken: distilled from (\d+) chars\]")
    dedup = distill = 0
    expanded = []
    for m in messages:
        if not isinstance(m, dict):
            expanded.append(m)
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            def repl_dd(mm):
                nonlocal dedup
                dedup += 1
                return (f"[slimtoken: this tool_result was byte-identical to a LATER "
                        f"result and deduplicated (~{mm.group(1)} chars removed). "
                        f"Re-fetch from source to restore the full content.]")
            def repl_di(mm):
                nonlocal distill
                distill += 1
                return (f"[slimtoken: this turn was distilled from {mm.group(1)} chars. "
                        f"The original prose is gone; regenerate or re-source to restore it.]")
            content = DEDUP_RE.sub(repl_dd, content)
            content = DISTILL_RE.sub(repl_di, content)
        expanded.append({**m, "content": content})
    return {
        "status": "ok",
        "expanded": expanded,
        "expanded_markers": {"dedup": dedup, "distill": distill},
    }

def session_broadcast(status: str = "working", task: str = None) -> dict:

    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        result = coord.broadcast(status=status, task=task or status)
        return result
    except Exception as e:
        return {"error": str(e)}

def session_check() -> dict:

    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return {
            "sessions": coord.poll(),
            "summary": coord.summarize_activity()
        }
    except Exception as e:
        return {"error": str(e)}

def session_log(message: str, level: str = "info") -> dict:

    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return coord.log_awareness(message, level)
    except Exception as e:
        return {"error": str(e)}

def cve_recent(since: str = "7d", min_cvss: float = 0.0,
               kev_only: bool = False, limit: int = 50) -> dict:

    try:
        from lib import cve_intel
        entries = cve_intel.recent(since=since, min_cvss=min_cvss,
                                   kev_only=kev_only, limit=limit)
        return {"status": "ok", "count": len(entries), "cves": entries}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def cve_lookup(cve_id: str) -> dict:

    try:
        from lib import cve_intel
        entry = cve_intel.lookup(cve_id)
        if not entry:
            return {"status": "not_found", "cve_id": cve_id}
        return {
            "status": "ok",
            "cve": entry,
            "mitre_techniques": entry.get("mitre_techniques", []),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def mitre_techniques_for_cve(cve_id: str) -> dict:

    try:
        from lib import cve_intel
        techniques = cve_intel.mitre_for_cve(cve_id)
        return {"status": "ok", "cve_id": cve_id, "techniques": techniques}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def mitre_mitigations_coverage() -> dict:

    try:
        from lib import cve_intel
        return {"status": "ok", **cve_intel.mitre_coverage()}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def cve_poll_now(since: str = "7d", include_osv: bool = False) -> dict:

    try:
        from lib import cve_intel
        new_entries = cve_intel.poll_cve_feeds(since=since, skip_osv=not include_osv)
        critical = sum(1 for e in new_entries
                       if (e.get("cvss_v3") or 0) >= 9.0 or e.get("severity") == "critical")
        kev = sum(1 for e in new_entries if e.get("kev"))
        summary = {"new_count": len(new_entries), "critical": critical, "kev": kev}

        try:
            from lib.memory_thin import write_cold
            from datetime import datetime
            cat = f"cve_{datetime.now().strftime('%Y-%m-%d')}"
            write_cold(category=cat,
                       content=f"{summary}",
                       replace=False)
        except Exception as mem_err:
            summary["cold_write_error"] = str(mem_err)
        return {"status": "ok", **summary, "new": new_entries[:10]}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def hardening_status(subsystem: str = "all") -> dict:

    try:
        from lib import hardening_status as hs
        if subsystem == "all" or not subsystem:
            snap = hs.hardening_snapshot()
        else:
            snap = hs.hardening_snapshot(subsystems=[subsystem])
        return {"status": "ok", **snap}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def nftables_list() -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["nftables"])
        return {"status": "ok", **snap["subsystems"].get("nftables", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def auditd_query() -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["auditd"])
        return {"status": "ok", **snap["subsystems"].get("auditd", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def sshd_config_dump() -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["sshd"])
        return {"status": "ok", **snap["subsystems"].get("sshd", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def sysctl_current(keys: list[str] | None = None) -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["sysctl"])
        if not keys:
            return {"status": "ok", **snap["subsystems"].get("sysctl", {})}

        out = {k: hs._read_proc_sys(k) for k in keys}
        return {"status": "ok", "values": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def unbound_status() -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["unbound"])
        return {"status": "ok", **snap["subsystems"].get("unbound", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def capabilities_list(paths: list[str] | None = None) -> dict:

    try:
        from lib import hardening_status as hs
        if paths:
            import shutil as _sh
            out_lines: list[str] = []
            for p in paths:
                if not _sh.which("getcap"):
                    break
                rc, txt, _ = hs._safe_run(["getcap", "-r", p], timeout=30.0)
                if rc == 0:
                    out_lines.extend(txt.splitlines())
            risky = []
            for line in out_lines:
                if "=" not in line:
                    continue
                pp, cp = line.split("=", 1)
                cap_set = {c.strip().lower() for c in cp.strip().split(",")}
                hit = cap_set & {c.lower() for c in hs.RISKY_CAPS}
                if hit:
                    risky.append({"path": pp.strip(), "risky_caps": sorted(hit),
                                  "all_caps": cp.strip()})
            return {"status": "ok", "risky_count": len(risky), "risky": risky[:50]}
        snap = hs.hardening_snapshot(subsystems=["capabilities"])
        return {"status": "ok", **snap["subsystems"].get("capabilities", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def lsm_stack() -> dict:

    try:
        from lib import hardening_status as hs
        snap = hs.hardening_snapshot(subsystems=["lsms"])
        return {"status": "ok", **snap["subsystems"].get("lsms", {})}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def siem_recent(source: str | None = None, limit: int = 50) -> dict:

    try:
        import siem.db as siem_db
        rows = siem_db.list_findings(limit=limit, source=source)
        return {"status": "ok", "count": len(rows), "findings": rows,
                "counts": siem_db.finding_counts()}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def siem_posture() -> dict:

    try:
        import siem.db as siem_db
        rows = siem_db.list_findings(limit=500, source="hardening_status")
        latest: dict[str, dict] = {}
        for r in rows:
            tok = r.get("token") or ""
            if tok not in latest or r.get("id", 0) > latest[tok].get("id", 0):
                latest[tok] = r
        subsystems = [{
            "subsystem": tok.split(":", 1)[1] if ":" in tok else tok,
            "severity": r.get("severity"),
            "detail": r.get("detail"),
            "ts": r.get("ts"),
            "id": r.get("id"),
        } for tok, r in sorted(latest.items())]
        return {"status": "ok", "count": len(subsystems), "subsystems": subsystems}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def siem_push_recent(since: str = "7d") -> dict:

    try:
        from lib import siem_bridge
        n = siem_bridge.push_recent_cves(since=since)
        return {"status": "ok", "pushed": n, "since": since}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def soar_run_on_recent(since: str = "7d", dry_run: bool = False) -> dict:

    try:
        from lib import soar_playbooks
        r = soar_playbooks.run_on_recent(since=since, dry_run=dry_run)
        return {"status": "ok", **r}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def soar_run_posture(dry_run: bool = False) -> dict:

    try:
        from lib import soar_playbooks
        r = soar_playbooks.run_on_posture(dry_run=dry_run)
        return {"status": "ok", **r}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def soar_history(limit: int = 20) -> dict:

    try:
        from lib import soar_playbooks
        return {"status": "ok", "count": min(limit, len(soar_playbooks.load_history(limit))),
                "runs": soar_playbooks.load_history(limit)}
    except Exception as e:
        return {"status": "error", "error": str(e)}

CONVERTED_TOOLS = [
{
                "type": "function",
                "function": {
                        "name": "memory_read",
                        "description": "Read from memory store (hot/cold)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "cold"
                                                ]
                                        },
                                        "platform": {
                                                "type": "string"
                                        },
                                        "category": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "tier"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "memory_write",
                        "description": "Write to memory (hot/cold)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "cold"
                                                ]
                                        },
                                        "content": {
                                                "type": "string"
                                        },
                                        "platform": {
                                                "type": "string"
                                        },
                                        "category": {
                                                "type": "string"
                                        },
                                        "role": {
                                                "type": "string",
                                                "enum": [
                                                        "user",
                                                        "assistant",
                                                        "system"
                                                ]
                                        }
                                },
                                "required": [
                                        "tier",
                                        "content"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "memory_search",
                        "description": "Search hot and cold memory",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "query": {
                                                "type": "string"
                                        },
                                        "limit": {
                                                "type": "integer"
                                        }
                                },
                                "required": [
                                        "query"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "memory_clear",
                        "description": "Clear hot/cold memory",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "all"
                                                ]
                                        },
                                        "platform": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "tier"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "adapter_list",
                        "description": "List every registered API adapter and its live health status (Google CSE, SearXNG, etc.)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                },
                                "required": [
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "adapter_search",
                        "description": "Search/lookup via the API adapter layer. adapter_name omitted → fan-out across every enabled backend. One failing adapter never blocks the rest.",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "query": {
                                                "type": "string"
                                        },
                                        "limit": {
                                                "type": "integer"
                                        },
                                        "adapter_name": {
                                                "type": "string",
                                                "description": "Target one adapter by name (e.g. 'google_cse'). Omit to fan-out."
                                        }
                                },
                                "required": [
                                        "query"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "firecrawl_search",
                        "description": "Search the web using Firecrawl",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "query": {
                                                "type": "string"
                                        },
                                        "limit": {
                                                "type": "integer"
                                        }
                                },
                                "required": [
                                        "query"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "firecrawl_scrape",
                        "description": "Scrape content from a URL",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "url": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "url"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "slimtoken_minify",
                        "description": "Minify messages for slim token usage",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "messages": {
                                                "type": "array"
                                        }
                                },
                                "required": [
                                        "messages"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "slimtoken_maxify",
                        "description": "Expand slimtoken minified markers back into self-describing placeholders",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "messages": {
                                                "type": "array"
                                        }
                                },
                                "required": [
                                        "messages"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "session_broadcast",
                        "description": "Broadcast session status to other sessions",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "status": {
                                                "type": "string",
                                                "enum": [
                                                        "idle",
                                                        "working",
                                                        "thinking",
                                                        "blocked"
                                                ]
                                        },
                                        "task": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "status"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "session_check",
                        "description": "Check what other sessions are doing",
                        "parameters": {
                                "type": "object",
                                "properties": {}
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "session_log",
                        "description": "Log inter-session awareness message",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "message": {
                                                "type": "string"
                                        },
                                        "level": {
                                                "type": "string",
                                                "enum": [
                                                        "info",
                                                        "warn",
                                                        "critical"
                                                ]
                                        }
                                },
                                "required": [
                                        "message"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "cve_recent",
                        "description": "Return recent CVEs from local intel cache (NVD+KEV+EPSS+GHSA+OSV)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "since": {"type": "string", "description": "window like 7d/24h"},
                                        "min_cvss": {"type": "number", "description": "CVSS floor"},
                                        "kev_only": {"type": "boolean"},
                                        "limit": {"type": "integer"}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "cve_lookup",
                        "description": "Look up a single CVE by ID (e.g. CVE-2024-3094) plus MITRE technique mapping",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "cve_id": {"type": "string"}
                                },
                                "required": ["cve_id"]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "mitre_techniques_for_cve",
                        "description": "Return ATT&CK Enterprise technique IDs mapped to the given CVE",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "cve_id": {"type": "string"}
                                },
                                "required": ["cve_id"]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "mitre_mitigations_coverage",
                        "description": "Return MITRE M-code coverage of local hardening (nftables/systemd/seccomp/etc.)",
                        "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "cve_poll_now",
                        "description": "Trigger a fresh CVE feed poll (network). Writes new entries to intel.jsonl + cold memory",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "since": {"type": "string"},
                                        "include_osv": {"type": "boolean"}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "hardening_status",
                        "description": "Read-only snapshot of hardening subsystems (nftables/sshd/sysctl/auditd/lsms/etc.)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "subsystem": {"type": "string", "description": "'all' or subsystem name"}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "nftables_list",
                        "description": "Live nftables ruleset snapshot: tables, chains, rule count",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "auditd_query",
                        "description": "Active auditd rule count + staged rules.d files",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "sshd_config_dump",
                        "description": "Parse sshd_config + sshd_config.d; grade vs hardening baseline",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "sysctl_current",
                        "description": "Read live sysctl values; if keys omitted, return baseline comparison",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "keys": {"type": "array", "items": {"type": "string"}}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "unbound_status",
                        "description": "unbound presence + harden-* directives + service state",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "capabilities_list",
                        "description": "Enumerate file capabilities; flag binaries holding risky caps (CAP_SYS_ADMIN etc.)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "paths": {"type": "array", "items": {"type": "string"}}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "lsm_stack",
                        "description": "Active LSM stack (landlock/lockdown/yama/apparmor/tomoyo/bpf/ipe/ima)",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "siem_recent",
                        "description": "Recent SIEM findings (optionally filtered by source: cve_intel, hardening_status, etc.)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "source": {"type": "string"},
                                        "limit": {"type": "integer"}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "siem_posture",
                        "description": "Latest posture_event per hardening subsystem (newest by id)",
                        "parameters": {
                                "type": "object", "properties": {}, "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "siem_push_recent",
                        "description": "Pull recent CVEs from local cache into SIEM (writes to ~/security-console/siem/siem.db)",
                        "parameters": {
                                "type": "object",
                                "properties": {"since": {"type": "string"}},
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "soar_run_on_recent",
                        "description": "Run SOAR playbooks against recent CVEs (critical/KEV → notify/block-IOC)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "since": {"type": "string"},
                                        "dry_run": {"type": "boolean"}
                                },
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "soar_run_posture",
                        "description": "Run SOAR playbooks for hardening posture fails (enqueues audit reviews)",
                        "parameters": {
                                "type": "object",
                                "properties": {"dry_run": {"type": "boolean"}},
                                "required": []
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "soar_history",
                        "description": "Last N SOAR playbook runs (newest first)",
                        "parameters": {
                                "type": "object",
                                "properties": {"limit": {"type": "integer"}},
                                "required": []
                        }
                }
        },
]

TOOL_MAP = {
    "memory_read": memory_read,
    "memory_write": memory_write,
    "memory_search": memory_search,
    "memory_clear": memory_clear,
    "session_broadcast": session_broadcast,
    "session_check": session_check,
    "session_log": session_log,

    "adapter_list": adapter_list,
    "adapter_search": adapter_search,
    "firecrawl_search": firecrawl_search,
    "firecrawl_scrape": firecrawl_scrape,
    "slimtoken_minify": slimtoken_minify,
    "slimtoken_maxify": slimtoken_maxify,

    "cve_recent": cve_recent,
    "cve_lookup": cve_lookup,
    "mitre_techniques_for_cve": mitre_techniques_for_cve,
    "mitre_mitigations_coverage": mitre_mitigations_coverage,
    "cve_poll_now": cve_poll_now,

    "hardening_status": hardening_status,
    "nftables_list": nftables_list,
    "auditd_query": auditd_query,
    "sshd_config_dump": sshd_config_dump,
    "sysctl_current": sysctl_current,
    "unbound_status": unbound_status,
    "capabilities_list": capabilities_list,
    "lsm_stack": lsm_stack,

    "siem_recent": siem_recent,
    "siem_posture": siem_posture,
    "siem_push_recent": siem_push_recent,
    "soar_run_on_recent": soar_run_on_recent,
    "soar_run_posture": soar_run_posture,
    "soar_history": soar_history,
}

def execute_converted_tool(name: str, args: dict) -> dict:

    if name not in TOOL_MAP:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = TOOL_MAP[name](**args)
        return result
    except Exception as e:
        return {"error": str(e)}

def list_converted_tools(limit: int = 16, stub: bool = True) -> list:

    tools = CONVERTED_TOOLS[:limit]
    if stub:

        return [
            {"type": "function", "function": {
                "name": t["function"]["name"],
                "description": t["function"]["description"][:80] + "...",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }}
            for t in tools
        ]
    return tools

if __name__ == "__main__":

    print("Testing converted MCP tools...")

    r = execute_converted_tool("memory_read", {"tier": "hot"})
    print(f"memory_read: {r}")

    r = execute_converted_tool("memory_search", {"query": "test", "limit": 5})
    print(f"memory_search: {r}")

    print("\nConverted MCP tools: OK")
