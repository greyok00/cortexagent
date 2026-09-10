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




_CLX_LEGACY = Path.home() / "cortexllm" / "repo" / "legacy"
if _CLX_LEGACY.is_dir() and str(_CLX_LEGACY) not in sys.path:
    sys.path.insert(0, str(_CLX_LEGACY))
if str(_CWD / "lib") not in sys.path:
    sys.path.insert(0, str(_CWD / "lib"))





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


class GraphStore:

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_graph import GraphStore as _GS
            self._store = _GS()
        except Exception:
            self._store = None

    @classmethod
    def get(cls) -> 'GraphStore':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


class VectorStore:

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_vector import VectorStore as _VS
            self._store = _VS()
        except Exception:
            self._store = None

    @classmethod
    def get(cls) -> 'VectorStore':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


class OntologyEngine:

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_ontology import OntologyEngine as _OE
            self._engine = _OE()
        except Exception:
            self._engine = None

    @classmethod
    def get(cls) -> 'OntologyEngine':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance






def memory_read(tier: str, platform: str = "default", category: str = None) -> dict:

    try:
        from memory_manager import MemoryManager
        mm = MemoryManager()
        if tier == "hot":
            data = mm.get_hot_messages(platform)
        elif tier == "warm":
            data = mm.get_warm_messages()
        elif tier == "cold":
            data = mm.get_cold_knowledge(category) if category else mm.get_all_cold_categories()
        else:
            return {"error": f"Invalid tier: {tier}"}
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"error": str(e)}


def memory_write(tier: str, content: str, platform: str = "default",
                 category: str = None, role: str = "user") -> dict:

    try:
        from memory_manager import MemoryManager
        mm = MemoryManager()
        if tier == "hot":
            mm.add_to_hot(platform, content, role)
            result = {"status": "written", "tier": "hot", "platform": platform}
        elif tier == "warm":
            mm.add_to_hot(platform, content, role)
            result = {"status": "written", "tier": "warm"}
        elif tier == "cold":
            try:
                knowledge = json.loads(content)
            except Exception:
                knowledge = {"content": content}
            mm.save_to_cold(category or "general", knowledge)
            result = {"status": "written", "tier": "cold", "category": category}
        else:
            result = {"error": f"Invalid tier: {tier}"}
        return result
    except Exception as e:
        return {"error": str(e)}


def memory_search(query: str, limit: int = 10) -> dict:

    try:
        from domain_db import search
        results = search("default", query, limit)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}


def memory_clear(tier: str, platform: str = None) -> dict:

    try:
        from cortexllm_db import db
        db.initialize()
        w = db.writer
        if tier == "hot":
            w.execute("DELETE FROM Memory_Hot" + (" WHERE platform = ?" if platform else ""),
                      (platform,) if platform else ())
        elif tier == "warm":
            w.execute("DELETE FROM Memory_Warm")
        elif tier == "all":
            w.execute("DELETE FROM Memory_Hot")
            w.execute("DELETE FROM Memory_Warm")
        w.commit()
        return {"status": "cleared", "tier": tier}
    except Exception as e:
        return {"error": str(e)}


def memory_search_semantic(query: str, limit: int = 10, platform: str = None) -> dict:

    try:
        vs = VectorStore.get()._store
        if vs is None:
            return {"error": "VectorStore not available"}
        results = vs.search(query, limit, platform)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}


def memory_graph_query(action: str, entity: str = None, text: str = None,
                       target: str = None, depth: int = 2,
                       platform: str = None) -> dict:

    try:
        gs = GraphStore.get()._store
        if gs is None:
            return {"error": "GraphStore not available"}
        if action == "query":
            result = gs.query_entity(entity or "", depth, platform)
        elif action == "extract":
            result = gs.extract_and_store(text or "", platform)
        elif action == "path":
            result = gs.find_path(entity or "", target or "")
        elif action == "stats":
            result = gs.get_stats()
        else:
            result = {"error": f"Unknown action: {action}"}
        return result
    except Exception as e:
        return {"error": str(e)}


def memory_ontology(action: str, text: str = None) -> dict:

    try:
        oe = OntologyEngine.get()._engine
        if oe is None:
            return {"error": "OntologyEngine not available"}
        if action == "categorize":
            result = oe.categorize(text or "")
        elif action == "taxonomy":
            result = oe.build_taxonomy()
        elif action == "gaps":
            result = oe.find_gaps()
        elif action == "tag":
            result = oe.auto_tag_practices()
        elif action == "tagmem":
            result = oe.tag_memory()
        elif action == "discover":
            result = oe.discover_categories()
        elif action == "stats":
            result = oe.get_stats()
        else:
            result = {"error": f"Unknown action: {action}"}
        return result
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






def magicui_generate(description: str, format: str = "html") -> dict:

    backend = os.environ.get("CORTEXAGENT_MAGICUI_BACKEND", "").strip().lower()
    if not backend:
        return {"error": (
            "magicui_generate is not configured. Set CORTEXAGENT_MAGICUI_BACKEND=llm "
            "to render via the local model, or =template for a static template shell.")}
    try:
        if backend == "llm":
            from lib.overseer import _query_llm
            prompt = (
                f"Generate clean, self-contained {format} UI for the following "
                f"description. Output only the {format} code, no markdown fences.\n\n"
                f"Description: {description}")
            html = _query_llm(prompt, max_tokens=1024, temperature=0.2, timeout=90)
            if not html:
                return {"error": "LLM returned empty UI"}
            return {"status": "ok", "html": html, "format": format, "backend": "llm"}
        if backend == "template":
            import html as _h
            title = _h.escape(description[:60])
            body = _h.escape(description)
            html = (
                f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                f"<title>{title}</title></head><body><h1>{title}</h1>"
                f"<p>{body}</p></body></html>")
            return {"status": "ok", "html": html, "format": format, "backend": "template"}
        return {"error": f"Unknown magicui backend: {backend}"}
    except Exception as e:
        return {"error": str(e)}






class TradingSession:

    _instances: Dict[str, 'TradingSession'] = {}
    _lock = threading.Lock()

    def __init__(self, broker: str = "alpaca"):
        self.broker = broker
        self.account_id = None
        self.positions = {}

    @classmethod
    def get(cls, broker: str = "alpaca") -> 'TradingSession':
        with cls._lock:
            if broker not in cls._instances:
                cls._instances[broker] = cls(broker)
            return cls._instances[broker]


def alpaca_get_account() -> dict:

    import json as _json
    import urllib.request
    api_key = (os.environ.get("CORTEXAGENT_ALPACA_API_KEY")
               or os.environ.get("ALPACA_API_KEY") or "")
    secret = (os.environ.get("CORTEXAGENT_ALPACA_SECRET_KEY")
              or os.environ.get("ALPACA_SECRET_KEY") or "")
    if not api_key or not secret:
        return {"error": (
            "Alpaca not configured. Set CORTEXAGENT_ALPACA_API_KEY and "
            "CORTEXAGENT_ALPACA_SECRET_KEY (paper: also CORTEXAGENT_ALPACA_PAPER=1).")}
    try:
        paper = os.environ.get("CORTEXAGENT_ALPACA_PAPER", "1") in ("1", "true", "yes")
        base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        req = urllib.request.Request(f"{base}/v2/account")
        req.add_header("APCA-API-KEY-ID", api_key)
        req.add_header("APCA-API-SECRET-KEY", secret)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=15) as r:
            account = _json.loads(r.read().decode())
        return {"status": "ok", "account": account, "paper": paper}
    except Exception as e:
        return {"error": f"Alpaca request failed: {e}"}


def ibkr_get_positions() -> dict:

    import json as _json
    import urllib.request
    try:
        base = os.environ.get(
            "CORTEXAGENT_IBKR_GATEWAY_URL", "http://127.0.0.1:5000/v1/api").rstrip("/")
        req = urllib.request.Request(f"{base}/portfolio/accounts")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=15) as r:
            accounts = _json.loads(r.read().decode())
        positions = []
        for acct in accounts:
            aid = str(acct.get("id", "")).strip()
            if not aid:
                continue
            preq = urllib.request.Request(f"{base}/portfolio/{aid}/positions/0")
            preq.add_header("Accept", "application/json")
            with urllib.request.urlopen(preq, timeout=15) as pr:
                positions += _json.loads(pr.read().decode())
        return {"status": "ok", "positions": positions}
    except Exception as e:
        return {"error": (
            f"IBKR gateway not reachable/configured: {e}. Set "
            "CORTEXAGENT_IBKR_GATEWAY_URL to the IBKR Web API gateway "
            "(default http://127.0.0.1:5000/v1/api).")}


def quant_trader_strategy(symbol: str, timeframe: str = "1d") -> dict:

    import json as _json
    import urllib.request
    api_key = (os.environ.get("CORTEXAGENT_ALPACA_API_KEY")
               or os.environ.get("ALPACA_API_KEY") or "")
    secret = (os.environ.get("CORTEXAGENT_ALPACA_SECRET_KEY")
              or os.environ.get("ALPACA_SECRET_KEY") or "")
    if not api_key or not secret:
        return {"error": (
            "quant_trader_strategy needs a broker to source bars. Configure Alpaca "
            "(CORTEXAGENT_ALPACA_API_KEY / CORTEXAGENT_ALPACA_SECRET_KEY).")}
    try:
        limit = 120
        url = (f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
               f"?timeframe={timeframe}&limit={limit}")
        req = urllib.request.Request(url)
        req.add_header("APCA-API-KEY-ID", api_key)
        req.add_header("APCA-API-SECRET-KEY", secret)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read().decode())
        closes = [float(b["c"]) for b in data.get("bars", [])]
        if len(closes) < 51:
            return {"error": f"Not enough bars for {symbol} ({len(closes)} < 51)"}

        def sma(n):
            return sum(closes[-n:]) / n

        fast, slow = sma(20), sma(50)
        prev_fast = sum(closes[-21:-1]) / 20
        prev_slow = sum(closes[-51:-1]) / 50
        if fast > slow and prev_fast <= prev_slow:
            signal = "buy"
        elif fast < slow and prev_fast >= prev_slow:
            signal = "sell"
        else:
            signal = "hold"
        return {"status": "ok", "symbol": symbol, "timeframe": timeframe,
                "signal": signal, "sma_fast": round(fast, 4),
                "sma_slow": round(slow, 4), "bars": len(closes)}
    except Exception as e:
        return {"error": f"Quant strategy failed: {e}"}






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
        import siem.db as siem_db  # type: ignore
        rows = siem_db.list_findings(limit=limit, source=source)
        return {"status": "ok", "count": len(rows), "findings": rows,
                "counts": siem_db.finding_counts()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def siem_posture() -> dict:

    try:
        import siem.db as siem_db  # type: ignore
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
                        "description": "Read from CortexLLM memory (hot/warm/cold tiers)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "warm",
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
                        "description": "Write to CortexLLM memory tier",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "warm",
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
                        "description": "Search across all CortexLLM memory tiers",
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
                        "description": "Clear CortexLLM memory",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "tier": {
                                                "type": "string",
                                                "enum": [
                                                        "hot",
                                                        "warm",
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
                        "name": "memory_search_semantic",
                        "description": "Semantic (BM25) search across CortexLLM memory",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "query": {
                                                "type": "string"
                                        },
                                        "limit": {
                                                "type": "integer"
                                        },
                                        "platform": {
                                                "type": "string"
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
                        "name": "memory_graph_query",
                        "description": "Query the CortexLLM knowledge graph",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "action": {
                                                "type": "string",
                                                "enum": [
                                                        "query",
                                                        "extract",
                                                        "path",
                                                        "stats"
                                                ]
                                        },
                                        "entity": {
                                                "type": "string"
                                        },
                                        "text": {
                                                "type": "string"
                                        },
                                        "target": {
                                                "type": "string"
                                        },
                                        "depth": {
                                                "type": "integer"
                                        },
                                        "platform": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "action"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "memory_ontology",
                        "description": "Ontology operations (categorize, taxonomy, gaps, tags)",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "action": {
                                                "type": "string",
                                                "enum": [
                                                        "categorize",
                                                        "taxonomy",
                                                        "gaps",
                                                        "tag",
                                                        "tagmem",
                                                        "discover",
                                                        "stats"
                                                ]
                                        },
                                        "text": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "action"
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
                        "name": "magicui_generate",
                        "description": "Generate UI from description",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "description": {
                                                "type": "string"
                                        },
                                        "format": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "description"
                                ]
                        }
                }
        },
{
                "type": "function",
                "function": {
                        "name": "alpaca_get_account",
                        "description": "Get Alpaca trading account info",
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
                        "name": "ibkr_get_positions",
                        "description": "Get Interactive Brokers positions",
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
                        "name": "quant_trader_strategy",
                        "description": "Run quant strategy on a symbol",
                        "parameters": {
                                "type": "object",
                                "properties": {
                                        "symbol": {
                                                "type": "string"
                                        },
                                        "timeframe": {
                                                "type": "string"
                                        }
                                },
                                "required": [
                                        "symbol"
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
    "memory_search_semantic": memory_search_semantic,
    "memory_graph_query": memory_graph_query,
    "memory_ontology": memory_ontology,
    "session_broadcast": session_broadcast,
    "session_check": session_check,
    "session_log": session_log,

    "adapter_list": adapter_list,
    "adapter_search": adapter_search,
    "firecrawl_search": firecrawl_search,
    "firecrawl_scrape": firecrawl_scrape,
    "magicui_generate": magicui_generate,
    "alpaca_get_account": alpaca_get_account,
    "ibkr_get_positions": ibkr_get_positions,
    "quant_trader_strategy": quant_trader_strategy,
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


    r = execute_converted_tool("memory_read", {"tier": "warm"})
    print(f"memory_read: {r}")

    r = execute_converted_tool("memory_search", {"query": "test", "limit": 5})
    print(f"memory_search: {r}")

    r = execute_converted_tool("memory_search_semantic", {"query": "test", "limit": 5})
    print(f"memory_search_semantic: {r}")

    r = execute_converted_tool("memory_graph_query", {"action": "stats"})
    print(f"memory_graph_query: {r}")

    r = execute_converted_tool("memory_ontology", {"action": "stats"})
    print(f"memory_ontology: {r}")

    print("\nConverted MCP tools: OK")
