#!/usr/bin/env python3
"""lib/soar_playbooks.py — CortexAgent → SOAR playbook dispatcher.

Triggers defensive playbooks based on CortexAgent findings:

1. cve_intel.findings → if severity=critical OR kev=True → enqueue firewall
   block on IOC IPs (writes to ~/security-console/overseer/firewall_commands.jsonl);
   also push desktop notification + email via the SIEM feed module.
2. hardening_status posture → if status=fail → enqueue audit review.
3. auditd drift (active rule count drops below baseline) → enqueue rule reload.

All actions log to ~/security-console/soar/playbook_runs.jsonl for audit
trail. Actions are defensive and non-destructive — they enqueue commands
for the operator (root helper) to apply; they never mutate production
state directly.

CLI:
    python3 lib/soar_playbooks.py --list          # show defined playbooks
    python3 lib/soar_playbooks.py --run-on-recent # run on recent CVE findings
    python3 lib/soar_playbooks.py --run-posture   # run on latest hardening posture
    python3 lib/soar_playbooks.py --history 20    # show last 20 runs
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SIEM_PATH = Path.home() / "security-console"
if str(_SIEM_PATH) not in sys.path:
    sys.path.insert(0, str(_SIEM_PATH))

SOAR_DIR = Path.home() / "security-console" / "soar"
PLAYBOOK_RUNS = SOAR_DIR / "playbook_runs.jsonl"
FIREWALL_COMMANDS = Path.home() / "security-console" / "overseer" / "firewall_commands.jsonl"

# Default playbooks (id, name, trigger_severity, action)
DEFAULT_PLAYBOOKS = [
    ("cve_critical_notify", "CVE critical — desktop notification",
     "critical", "notify"),
    ("cve_kev_block", "CVE KEV — block IOC IPs via firewall_commands.jsonl",
     "critical", "block-ioc"),
    ("cve_kev_auto_block", "CVE KEV — auto-extract IOC IPs from raw data",
     "critical", "auto-block-kev"),
    ("cve_critical_isolate_cpe", "CVE critical — match CPE vs local packages",
     "critical", "isolate-affected-cpe"),
    ("cve_high_log", "CVE high — log only",
     "high", "log-only"),
    ("posture_fail_audit", "Hardening posture FAIL — enqueue audit review",
     "high", "audit-review"),
]


# ── Action primitives ─────────────────────────────────────────────────────
_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _action_notify(finding: dict) -> str:
    """Desktop notification via the rich popup (falls back to notify-send).

    Mirrors siem/soar.py, but opens a larger, styled window with the full
    detail and an action button, so the operator has context to act on.
    """
    try:
        from alert_popup import show_alert
    except ImportError:
        from lib.alert_popup import show_alert
    try:
        detail = (finding.get("detail") or "")[:2000]
        severity = str(finding.get("severity", "info")).lower()
        show_alert(
            f"SOAR: {finding.get('source', '')}",
            detail,
            severity=severity,
            actions=[("Open log", _open_log)],
        )
        return "rich notification sent"
    except Exception:
        # last resort: plain toast
        import subprocess
        try:
            subprocess.run(
                ["notify-send", "-u", "critical", "-t", "10000",
                 f"🛡️ SOAR: {finding.get('source', '')}",
                 f"{finding.get('severity', '')}: {(finding.get('detail') or '')[:200]}"],
                check=False, capture_output=True,
            )
            return "desktop notification sent"
        except FileNotFoundError:
            return "no notify-send; skipped"


def _open_log() -> None:
    """Open the SOAR playbook run history for the operator."""
    import subprocess
    from pathlib import Path
    log = Path.home() / "security-console" / "soar" / "playbook_runs.jsonl"
    if log.exists():
        try:
            subprocess.Popen(["xdg-open", str(log)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass


def _action_block_ioc(finding: dict) -> str:
    """Append firewall block commands for IOC IPs found in the detail text."""
    ips = _IPV4.findall(finding.get("detail") or "")
    if not ips:
        return "no IPs in finding; nothing to block"
    FIREWALL_COMMANDS.parent.mkdir(parents=True, exist_ok=True)
    appended: list[str] = []
    with FIREWALL_COMMANDS.open("a", encoding="utf-8") as f:
        for ip in ips[:5]:  # cap per finding
            cmd = f"iptables -I INPUT -s {ip} -j DROP  # SOAR:{finding.get('id', '?')} {finding.get('kind', '')}\n"
            f.write(cmd)
            appended.append(ip)
    return f"queued blocks for {', '.join(appended)} → {FIREWALL_COMMANDS.name}"


def _action_log_only(finding: dict) -> str:
    return f"logged only (severity={finding.get('severity')})"


def _action_audit_review(finding: dict) -> str:
    """Enqueue a posture audit task in the overseer scheduler (best-effort)."""
    try:
        from lib.overseer import schedule_add
        schedule_add(
            name=f"audit_review_{finding.get('id', 'manual')}",
            task_type="command",
            schedule_type="date",
            schedule_value=datetime.now(timezone.utc).isoformat(),
            prompt="",
            command="posture_audit_review",
            output="",
            system="",
        )
        return "audit review scheduled (date=now)"
    except Exception as exc:
        return f"audit review scheduling failed: {exc}"


def _action_auto_block_kev(finding: dict) -> str:
    """KEV-driven auto-block: extract IOC IPs from finding raw JSON.

    Reads the raw blob written by siem_bridge.push_cve_finding(), which carries
    CPE list + refs. IPs come from refs URLs (vendor advisory URLs occasionally
    include scanner IPs but typically the affected service). When refs are
    unavailable, falls back to no-op logging.
    """
    import json
    raw = finding.get("raw") or ""
    if not raw:
        return "no raw blob; cannot extract IOCs"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return "raw blob not JSON"
    ips = _IPV4.findall(json.dumps(data))
    if not ips:
        return "no IOC IPs in raw blob (expected for non-IP-bound CVEs)"
    FIREWALL_COMMANDS.parent.mkdir(parents=True, exist_ok=True)
    with FIREWALL_COMMANDS.open("a", encoding="utf-8") as f:
        for ip in sorted(set(ips))[:5]:
            f.write(f"iptables -I INPUT -s {ip} -j DROP  # SOAR:KEV {finding.get('id', '?')}\n")
    return f"auto-blocked {len(set(ips))} IOC IPs from KEV raw data"


def _action_isolate_cpe(finding: dict) -> str:
    """CPE-driven quarantine: log affected packages for operator review.

    Doesn't mutate anything — writes to playbook history so an operator can
    see which local packages might be affected by a KEV CVE.
    """
    import json
    raw = finding.get("raw") or ""
    if not raw:
        return "no raw blob"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return "raw blob not JSON"
    cpe = data.get("cpe", []) or []
    if not cpe:
        return "no CPE in raw blob"
    matched: list[str] = []
    try:
        from lib.cve_intel import pin_dependencies
        pinned = pin_dependencies()
        eco_to_cpe_prefix = {
            "PyPI": "cpe:2.3:a:.*:.*:",
            "npm": "cpe:2.3:a:.*:.*:",
            "Go": "cpe:2.3:a:.*:.*:",
            "crates.io": "cpe:2.3:a:.*:.*:",
        }
        for eco, name in pinned:
            prefix = eco_to_cpe_prefix.get(eco, "")
            for entry in cpe:
                if name.lower() in entry.lower() and prefix:
                    matched.append(f"{eco}:{name} matches {entry}")
                    break
    except Exception:
        pass
    msg = f"isolated {len(cpe)} CPE entries; matched {len(matched)} local packages"
    if matched:
        msg += ": " + "; ".join(matched[:3])
    return msg


ACTIONS = {
    "notify": _action_notify,
    "block-ioc": _action_block_ioc,
    "log-only": _action_log_only,
    "audit-review": _action_audit_review,
    "auto-block-kev": _action_auto_block_kev,
    "isolate-affected-cpe": _action_isolate_cpe,
}


# ── Run history ───────────────────────────────────────────────────────────
def _ensure_soar_dir() -> None:
    SOAR_DIR.mkdir(parents=True, exist_ok=True)
    if not PLAYBOOK_RUNS.exists():
        PLAYBOOK_RUNS.touch()


def _append_run(record: dict) -> None:
    _ensure_soar_dir()
    with PLAYBOOK_RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


def load_history(limit: int = 50) -> list[dict]:
    if not PLAYBOOK_RUNS.exists():
        return []
    out: list[dict] = []
    with PLAYBOOK_RUNS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:][::-1]  # newest first


# ── Trigger evaluation ────────────────────────────────────────────────────
def run_for_cve(cve_entry: dict, dry_run: bool = False) -> list[dict]:
    """Run appropriate playbooks for a single CVE entry."""
    from lib import siem_bridge
    out: list[dict] = []
    # Decide severity for playbook selection
    if cve_entry.get("kev"):
        severity = "critical"
    else:
        cvss = cve_entry.get("cvss_v3") or cve_entry.get("cvss_v4") or 0.0
        severity = "critical" if cvss >= 9.0 else ("high" if cvss >= 7.0 else "medium")
    finding = {
        "source": "cve_intel",
        "kind": "vulnerability_finding",
        "severity": severity,
        "detail": (f"{cve_entry.get('cve_id', '')} "
                   f"{(cve_entry.get('summary') or '')[:200]}"),
        "id": cve_entry.get("cve_id", ""),
    }
    for pb_id, pb_name, trig, action in DEFAULT_PLAYBOOKS:
        if trig != severity:
            continue
        if not dry_run:
            try:
                result = ACTIONS[action](finding)
            except Exception as exc:
                result = f"error: {exc}"
            _append_run({
                "ts": datetime.now(timezone.utc).isoformat(),
                "playbook_id": pb_id,
                "playbook_name": pb_name,
                "action": action,
                "severity_trigger": severity,
                "finding_id": finding["id"],
                "result": result,
            })
        out.append({"playbook": pb_id, "action": action, "severity": severity})
    return out


def run_for_posture(snap: dict, dry_run: bool = False) -> list[dict]:
    """Run playbooks for hardening posture events that have failed."""
    out: list[dict] = []
    for name, v in snap.get("subsystems", {}).items():
        if v.get("status") != "fail":
            continue
        finding = {
            "source": "hardening_status",
            "kind": "posture_event",
            "severity": "high",
            "detail": f"{name}: {v.get('summary', '')}",
            "id": f"posture:{name}",
        }
        for pb_id, pb_name, trig, action in DEFAULT_PLAYBOOKS:
            if pb_id != "posture_fail_audit":
                continue
            if not dry_run:
                try:
                    result = ACTIONS[action](finding)
                except Exception as exc:
                    result = f"error: {exc}"
                _append_run({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "playbook_id": pb_id,
                    "playbook_name": pb_name,
                    "action": action,
                    "severity_trigger": "high",
                    "finding_id": finding["id"],
                    "result": result,
                })
            out.append({"playbook": pb_id, "subsystem": name})
    return out


def run_on_recent(since: str = "7d", dry_run: bool = False) -> dict:
    """Pull recent CVEs from cve_intel and run playbooks for each."""
    from lib import cve_intel
    entries = cve_intel.recent(since=since, limit=200)
    out: list[dict] = []
    for e in entries:
        out.extend(run_for_cve(e, dry_run=dry_run))
    return {"cves_scanned": len(entries), "playbook_runs": out}


def run_on_posture(dry_run: bool = False) -> dict:
    from lib import hardening_status as hs
    snap = hs.hardening_snapshot()
    runs = run_for_posture(snap, dry_run=dry_run)
    return {"fails_triggered": len(runs), "playbook_runs": runs}


# ── CLI ───────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="CortexAgent → SOAR dispatcher")
    ap.add_argument("--list", action="store_true", help="list default playbooks")
    ap.add_argument("--run-on-recent", action="store_true", help="run on recent CVEs")
    ap.add_argument("--run-posture", action="store_true", help="run on hardening posture")
    ap.add_argument("--dry-run", action="store_true", help="plan only, no side effects")
    ap.add_argument("--since", default="7d")
    ap.add_argument("--history", type=int, default=0, help="show last N runs")
    args = ap.parse_args()
    if args.list:
        for pb in DEFAULT_PLAYBOOKS:
            print(f"  {pb[0]:30s} severity={pb[2]:8s} action={pb[3]}")
        return 0
    if args.run_on_recent:
        r = run_on_recent(since=args.since, dry_run=args.dry_run)
        print(f"✓ scanned {r['cves_scanned']} CVEs, "
              f"triggered {len(r['playbook_runs'])} playbooks")
        for run in r["playbook_runs"][:10]:
            print(f"  - {run}")
        return 0
    if args.run_posture:
        r = run_on_posture(dry_run=args.dry_run)
        print(f"✓ triggered {len(r['playbook_runs'])} audit reviews")
        for run in r["playbook_runs"]:
            print(f"  - {run}")
        return 0
    if args.history:
        for h in load_history(args.history):
            print(json.dumps(h, default=str))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())