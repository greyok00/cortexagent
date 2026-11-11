#!/usr/bin/env python3
"""doctor.py - the one health/doctor/smoke script for Greysearch.

Everything that used to be called health / doctor / smoke lives here, under
one name. Run it regularly:

    ./doctor.py
    ./doctor.py --fix
    ./doctor.py --json

Checks, in order:

1. LOCAL SEARXNG (127.0.0.1:8888) - up? median latency over 3 real queries?
   how many engines responsive? Down + --fix = searxng/start.sh start.
2. BROWSER SLOTS - which Greysearch ports (9351-9354) answer CDP, which
   profile dirs exist; foreign session ports (9331-9334) are REPORTED ONLY,
   never probed further, never touched.
3. SEARX.SPACE DISCOVERY - can we still fetch the instance list? (No instance
   is contacted by the doctor - that is the anti-tarpit rule.)
4. INSTANCE BENCH - which public instances are currently benched (limiter
   walls) and why.
5. SLOWDOWNS - system load, memory, and a thread-bloat scan of python
   daemons (a runaway python daemon can leak thousands of worker threads,
   driving load high enough to slow every session to a crawl). Bloat above
   OVERSEER_LIMIT + --fix = systemctl --user restart of that unit.
6. SELF-TUNE - when --fix is given, write research/tuning.json from the
   findings so the engine obeys: stressed host / slow lane / benched
   instances / heavy engine loss raise gaps via slow_factor (up to 3x) and,
   where needed, absolute gaps. Floors in tuning.py HARD_FLOORS are never
   crossed; a fully healthy system keeps defaults (tuning never speeds
   anything up).
"""

from __future__ import annotations

import argparse
import os
import re
import json
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
LOCAL = "http://127.0.0.1:8888"
FOREIGN_PORTS = (9331, 9332, 9333, 9334)
OUR_PORTS = (9351, 9352, 9353, 9354)
PROBE_QS = ("rust borrow checker", "osint email tracing", "dns tunnel detection")
OVERSEER_THREAD_LIMIT = 80

report: dict = {"ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                "checks": {}, "tuning_applied": None, "fixes": []}
FINDINGS_BAD = []
JSON_MODE = False

def _verdict(ok: bool, name: str, detail: str) -> None:
    report["checks"][name] = {"ok": ok, "detail": detail}
    if not JSON_MODE:
        print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
    if not ok:
        FINDINGS_BAD.append(name)

def _load_avg():
    with open("/proc/loadavg") as f:
        return [float(x) for x in f.read().split()[:3]]

USE_LOCAL = os.environ.get("GREYSEARCH_LOCAL_SEARX", "").lower() in ("1", "true", "yes")

def check_local_searxng():
    if not USE_LOCAL:
        _verdict(True, "searxng", "local lane disabled (optional); set "
                "GREYSEARCH_LOCAL_SEARX=1 to check a local instance")
        report["searxng"] = {"enabled": False}
        return None
    lat, nres = [], 0
    unresponsive_all = set()
    for q in PROBE_QS:
        t0 = time.time()
        try:
            url = f"{LOCAL}/search?" + urllib.parse.urlencode(
                {"q": q, "format": "json"})
            with urllib.request.urlopen(url, timeout=45) as r:
                d = json.loads(r.read().decode("utf-8"))
            lat.append(time.time() - t0)
            nres += len(d.get("results", []))
            for e in d.get("unresponsive_engines", []):
                unresponsive_all.add(e[0] if isinstance(e, list) else str(e))
        except Exception as e:
            _verdict(False, "searxng", f"query failed: {e}")
            return None
    med = statistics.median(lat)
    detail = (f"median {med:.1f}s, {nres} results over 3 queries, "
              f"{len(unresponsive_all)} engines unresponsive (regional/forbidden "
              f"engines legitimately count here; not a fault by itself)")
    _verdict(med <= 12.0 and nres >= 20, "searxng", detail)
    report["searxng"] = {"median_s": round(med, 1), "results": nres,
                         "unresponsive": sorted(unresponsive_all)}
    return report["searxng"]

def check_slots():
    foreign = {}
    for p in FOREIGN_PORTS:
        if _cdp(p):
            foreign[p] = "in use (another session)"
    up = [p for p in OUR_PORTS if _cdp(p)]
    _verdict(True, "browser_slots",
             f"our ports up={up or 'none (launched on demand)'}; "
             f"foreign ports seen={sorted(foreign) or 'none'} (reported only)")
    report["slots"] = {"our_ports_up": up,
                       "foreign_ports_seen": sorted(foreign)}

def _cdp(port) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=2):
            return True
    except Exception:
        return False

def check_searspace():
    try:
        req = urllib.request.Request(
            "https://searx.space/data/instances.json",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        names = [u for u in data.get("instances", {}) if u.startswith("https://")]
        _verdict(len(names) >= 10, "searspace_discovery",
                 f"{len(names)} https instances listed on searx.space")
    except Exception as e:
        _verdict(False, "searspace_discovery", f"instances.json fetch failed: {e}")

def check_portal():
    """Portal must answer (it is the end-user facing surface)."""
    port = int(os.environ.get("GREYSEARCH_PORTAL_PORT") or 8791)
    ok = False  # pre-initialized to False so the down path never raises UnboundLocalError; the doctor must still report the very failure it exists to diagnose
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/",
                                    timeout=3) as r:
            ok = r.status == 200
        _verdict(ok, "portal", f"up on 127.0.0.1:{port}")
    except Exception as e:
        _verdict(False, "portal", f"down on :{port} "
                 f"(start: python3 portal/server.py): {e}")
    report["portal"] = {"port": port, "up": bool(ok)}

def check_kit_source():
    """Grey-kit source must be vendored, readable, and carry every theme."""
    from site_render import KIT_THEMES, KIT_SRC
    css = KIT_SRC / "theme.css"
    ok = css.is_file() and (KIT_SRC / "site-kit.js").is_file()
    txt = css.read_text(errors="ignore") if ok else ""
    themes_found = len(re.findall(r'\[data-theme="([a-z-]+)"\]', txt))
    _verdict(ok and themes_found >= len(KIT_THEMES) - 1,
             "kit_source",
             f"{len(KIT_THEMES)} kit themes expected, {themes_found + 1} "
             f"palette blocks in vendored theme.css at {KIT_SRC}")
    report["kit_source"] = {"themes": themes_found + 1, "src": str(KIT_SRC)}

def check_llm_audit():
    """OPTIONAL lane (post-research audit only). Research runs without it;
    absence is never a fault. Reports whether the configured local model
    endpoint is currently usable for the audit stage."""
    try:
        import llm_audit
    except Exception as e:
        _verdict(True, "llm_audit", f"module absent, deterministic path ({e})")
        return
    # Report the mode the server will actually run, not the configured one.
    # Rules are the default; the model lane is an opt-in enhancer (audit
    # gate) that a NO_MODEL kill switch can close at any moment. None of
    # this is a fault.
    if llm_audit.no_model():
        _mode = "cpu/ram mode (GREYSEARCH_NO_MODEL, model lane closed)"
    elif llm_audit.audit_allowed():
        _mode = "rules default + llm-fallback (opted in)"
    else:
        _mode = "rules (default; model lane off by policy)"
    up = llm_audit.endpoint_ok()
    model = llm_audit.resolve_model() if up else ""
    try:
        from llm import oneshot
        b = oneshot.llama_bin()
        m = oneshot.find_model()
        vram = oneshot._vram_used_mib()
    except Exception:
        b = m = vram = None
    shot = (f"oneshot: bin={'yes' if b else 'NO'}, gguf="
            f"{'installed' if m else 'none (llm/start.sh --pull)'}, "
            f"gpu_free={'-' if vram is None else str(16384 - vram) + 'MiB'}")
    _ep = f"endpoint UP ({model})" if up else "endpoint down"
    _assist = ("assist will use the model"
               if _mode.startswith("rules default") and up
               else "assist stays deterministic")
    _verdict(True, "llm_audit",
             f"mode: {_mode}; {_ep}; {shot}; {_assist}")
    report["llm_audit"] = {"endpoint_up": up, "model": model,
                           "oneshot_bin": bool(b), "gguf": bool(m),
                           "gpu_used_mib": vram, "mode": llm_audit.MODE,
                           "effective_mode": _mode}

def check_bench():
    try:
        import searxng_integrated as sx
        benched = dict(sx._BENCHED_REASONS)
        _verdict(True, "instance_bench",
                 f"{len(benched)} benched now: "
                 f"{benched or 'none, no limiter walls hit this process'}"
                 if benched else "0 benched, clean")
    except Exception as e:
        _verdict(False, "instance_bench", f"bench state unreadable: {e}")

def check_slowdowns():
    load = _load_avg()
    memtotal = _mem_gb()
    own_heavy, foreign_heavy = [], []
    try:
        out = subprocess.run(
            ["ps", "-eo", "nlwp=,pid=,args="], capture_output=True, text=True,
            timeout=15).stdout.splitlines()
    except Exception:
        out = []
    for line in out:
        try:
            nlwp, pid, args = line.strip().split(None, 2)
            nlwp = int(nlwp)
        except ValueError:
            continue
        low = args.lower()
        if nlwp <= OVERSEER_THREAD_LIMIT:
            continue
        if "greysearch" in low or "cortex" in low:
            # The membership form matters here: an inverted test (matching a
            # MISSING 'cortex') would count every heavy third-party process
            # with no 'cortex' in its args as one of ours, making it
            # restart-eligible under --fix.
            own_heavy.append((pid, nlwp, args.split()[0]))
        else:
            foreign_heavy.append((pid, nlwp, args.split()[0]))
    ok = load[0] < 20 and not own_heavy
    note = (f", FOREIGN thread-bloat (observed only, not restarted from "
            f"here): {foreign_heavy}") if foreign_heavy else ""
    _verdict(ok, "slowdowns",
             f"load 1m={load[0]:.0f}, mem free={memtotal}G" + note)
    report["slowdowns"] = {"load": load, "own_bloat": own_heavy,
                           "foreign_bloat_observed": foreign_heavy}
    return {"load": load, "bloat": own_heavy + foreign_heavy}

def _mem_gb() -> str:
    try:
        out = subprocess.run(["free", "-g"], capture_output=True, text=True,
                             timeout=10).stdout
        return out.splitlines()[1].split()[6]
    except Exception:
        return "?"

def self_tune(searxng, slow):
    """Write research/tuning.json from findings. Floors in tuning.py hold."""
    import tuning
    tuning.values()  # validates tuning.json and warms the floor-enforced cache
    sf = 1.0
    reasons = []
    if searxng:
        med = searxng["median_s"]
        if med > 20:
            sf = max(sf, 2.5); reasons.append(f"local lane slow ({med}s)")
        elif med > 12:
            sf = max(sf, 1.8); reasons.append(f"local lane elevated ({med}s)")
        if searxng.get("results", 0) < 20:
            sf = max(sf, 2.0); reasons.append(
                f"thin result flow ({searxng.get('results', 0)})")
    if slow:
        l1 = slow["load"][0]
        if l1 > 100:
            sf = max(sf, 2.5); reasons.append(f"host load {l1:.0f}")
        elif l1 > 20:
            sf = max(sf, 1.8); reasons.append(f"host load {l1:.0f}")
    try:
        import searxng_integrated as sx
        if len(sx._BENCHED_REASONS) > 0:
            sf = max(sf, 2.0)
            reasons.append("limiter walls benched this process")
    except Exception:
        pass
    updates = {}
    if sf > 1.0:
        updates["slow_factor"] = sf
    else:
        updates["slow_factor"] = 1.0
    if reason_txt := "; ".join(reasons):
        updates["_last_tune_reason"] = reason_txt
    eff = tuning.write(updates)
    report["tuning_applied"] = {
        "slow_factor": eff["slow_factor"],
        "reasons": reasons or ["all healthy, defaults held"],
    }
    tail = ("; ".join(reasons) or "all healthy, defaults held")
    if not JSON_MODE:
        print(f"  [TUNE] slow_factor={eff['slow_factor']} ({tail})")

def fix_steps():
    if not _cdp_ish(LOCAL):
        rc = _run([str(REPO / "searxng" / "start.sh"), "start"])
        report["fixes"].append(f"searxng start rc={rc}")
    blo = report.get("slowdowns", {}).get("foreign_bloat_observed", [])
    if blo:
        report["fixes"].append(
            "NOTE: foreign daemons thread-bloated; not restarted from "
            "Greysearch (isolation rule, they are managed elsewhere)")

def _cdp_ish(base) -> bool:
    try:
        with urllib.request.urlopen(base + "/", timeout=30):
            return True
    except Exception:
        return False

def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=120).returncode
    except Exception:
        return -1

def main() -> int:
    ap = argparse.ArgumentParser(description="Greysearch doctor")
    ap.add_argument("--fix", action="store_true",
                    help="remediate what is safe (start lane, restart leaked daemons)")
    ap.add_argument("--json", action="store_true", help="JSON only")
    a = ap.parse_args()

    global JSON_MODE
    JSON_MODE = bool(a.json)
    if not JSON_MODE:
        print("Greysearch doctor")
    searxng = check_local_searxng()
    check_slots()
    check_searspace()
    check_bench()
    check_portal()
    check_kit_source()
    check_llm_audit()
    slow = check_slowdowns()
    # A plain check-only run must not write tuning.json: tuning on every
    # run rewrote slow_factor/last_tune_reason even when healthy.
    if a.fix:
        self_tune(searxng, slow)
    if a.fix:
        fix_steps()
        if any("searxng start" in f for f in report["fixes"]):
            if not JSON_MODE:
                print(" rechecking lane after fix...")
            searxng = check_local_searxng()
    verdict_bad = FINDINGS_BAD
    report["_bad"] = verdict_bad
    if a.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f" verdict: {'ISSUES: ' + ', '.join(verdict_bad) if verdict_bad else 'ALL HEALTHY'}")
        if report["fixes"]:
            print(" fixes applied:", "; ".join(report["fixes"]))
    return 1 if verdict_bad else 0

if __name__ == "__main__":
    sys.exit(main())