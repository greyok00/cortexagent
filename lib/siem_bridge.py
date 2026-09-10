#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_SIEM_PATH = Path.home() / "security-console" / "siem-soar"
if str(_SIEM_PATH) not in sys.path:
    sys.path.insert(0, str(_SIEM_PATH))


def _import_siem_db():

    try:
        from siem import db
        return db
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot import siem.db from {_SIEM_PATH}: {exc}. "
            "Ensure ~/security-console is on sys.path."
        ) from exc


def _severity_for_cve(entry: dict) -> str:

    if entry.get("kev"):
        return "critical"
    cvss = entry.get("cvss_v3") or entry.get("cvss_v4") or 0.0
    if cvss >= 9.0:
        return "critical"
    if cvss >= 7.0:
        return "high"
    if cvss >= 4.0:
        return "medium"
    if cvss > 0:
        return "low"
    return "n/a"


def push_cve_finding(entry: dict, db_mod=None, auto_soar: bool = True) -> int | None:

    db_mod = db_mod or _import_siem_db()
    cid = entry.get("cve_id") or "CVE-?"
    severity = _severity_for_cve(entry)
    cvss = entry.get("cvss_v3") or entry.get("cvss_v4") or 0.0
    kev_flag = " [KEV]" if entry.get("kev") else ""
    epss = entry.get("epss_score")
    epss_str = f" EPSS={epss:.2f}" if epss is not None else ""
    summary = (entry.get("summary") or "")[:200]
    techniques = entry.get("mitre_techniques") or []
    detail = (
        f"{cid}{kev_flag} CVSS={cvss:.1f}{epss_str} | {summary}"
        + (f" | MITRE: {','.join(techniques)}" if techniques else "")
    )
    raw = json.dumps({
        "cve_id": cid,
        "cvss_v3": entry.get("cvss_v3"),
        "cvss_v4": entry.get("cvss_v4"),
        "severity_native": entry.get("severity"),
        "cwe_ids": entry.get("cwe_ids", []),
        "cpe": entry.get("cpe", []),
        "kev": entry.get("kev", False),
        "kev_due_date": entry.get("kev_due_date"),
        "epss_score": entry.get("epss_score"),
        "epss_percentile": entry.get("epss_percentile"),
        "mitre_techniques": techniques,
        "refs": entry.get("refs", []),
        "sources": entry.get("sources", []),
    }, default=str)
    finding_id = db_mod.add_finding(
        source="cve_intel",
        kind="vulnerability_finding",
        severity=severity,
        detail=detail,
        token=f"cve:{cid}",
        raw=raw,
    )
    if auto_soar and finding_id is not None:
        _trigger_soar(finding_id, source="cve_intel", kind="vulnerability_finding",
                      severity=severity, detail=detail, raw=raw)
    return finding_id


def _trigger_soar(finding_id: int, **finding_fields) -> list:

    try:
        from siem import soar  # type: ignore


        try:
            soar.seed_default_playbooks()
        except Exception:
            pass


        finding = {
            "id": finding_id,
            "source": finding_fields.get("source"),
            "kind": finding_fields.get("kind"),
            "severity": finding_fields.get("severity"),
            "detail": finding_fields.get("detail"),
            "raw": finding_fields.get("raw"),
        }
        return soar.run_playbooks(finding)
    except Exception as exc:  # noqa: BLE001

        return [{"playbook": "<unavailable>", "error": str(exc)}]


def push_hardening_snapshot(snap: dict | None = None, db_mod=None,
                           auto_soar: bool = True) -> list[int]:

    from lib import hardening_status as hs
    if snap is None:
        snap = hs.hardening_snapshot()
    db_mod = db_mod or _import_siem_db()
    ids: list[int] = []
    for name, v in snap.get("subsystems", {}).items():
        status = v.get("status", "unknown")
        sev = {"fail": "critical", "warn": "high",
               "unknown": "medium", "ok": "low"}.get(status, "medium")
        detail = f"{name}: {v.get('summary', '')}"
        raw = json.dumps({"subsystem": name, "status": status,
                          "details": v.get("details", {}),
                          "snapshot_ts": snap.get("ts")})
        try:
            fid = db_mod.add_finding(
                source="hardening_status",
                kind="posture_event",
                severity=sev,
                detail=detail,
                token=f"posture:{name}",
                raw=raw,
            )
            ids.append(fid)
            if auto_soar and sev in ("critical", "high"):
                _trigger_soar(fid, source="hardening_status",
                              kind="posture_event", severity=sev,
                              detail=detail, raw=raw)
        except Exception:

            pass
    return ids


def push_recent_cves(since: str = "7d", db_mod=None) -> int:

    from lib import cve_intel
    db_mod = db_mod or _import_siem_db()
    entries = cve_intel.recent(since=since, limit=500)
    pushed = 0
    for e in entries:
        try:
            push_cve_finding(e, db_mod=db_mod)
            pushed += 1
        except Exception as exc:
            print(f"  ⚠ skip {e.get('cve_id')}: {exc}", file=sys.stderr)
    return pushed



def _stats(db_mod=None) -> dict:
    db_mod = db_mod or _import_siem_db()
    return db_mod.finding_counts()


def _test(db_mod=None) -> int:

    db_mod = db_mod or _import_siem_db()
    fake_cve = {
        "cve_id": "CVE-2026-TEST01",
        "published": "2026-08-18T00:00:00.000",
        "cvss_v3": 9.8,
        "severity": "critical",
        "summary": "Bridge smoke test entry — synthetic only.",
        "cwe_ids": ["CWE-787"],
        "cpe": ["cpe:2.3:a:test:test:1.0:*:*:*:*:*:*:*"],
        "refs": [],
        "kev": True,
        "kev_due_date": None,
        "epss_score": 0.95,
        "epss_percentile": 99.5,
        "mitre_techniques": ["T1190"],
        "sources": ["nvd"],
    }
    fid = push_cve_finding(fake_cve, db_mod=db_mod)
    print(f"  ✓ CVE finding id={fid}")
    snap = {"overall": "warn", "ts": "2026-08-18T16:00:00+00:00",
            "subsystems": {"test_sys": {"status": "warn",
                                        "summary": "bridge smoke test",
                                        "details": {}}}}
    ids = push_hardening_snapshot(snap, db_mod=db_mod)
    print(f"  ✓ hardening posture ids={ids}")
    print(f"  ✓ counts: {_stats(db_mod)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CortexAgent → SIEM bridge")
    ap.add_argument("--test", action="store_true", help="round-trip smoke")
    ap.add_argument("--push-recent", action="store_true", help="push recent CVEs to SIEM")
    ap.add_argument("--push-hardening", action="store_true", help="push hardening snapshot")
    ap.add_argument("--since", default="7d", help="window for --push-recent")
    ap.add_argument("--stats", action="store_true", help="show SIEM finding counts")
    args = ap.parse_args()
    if args.test:
        return _test()
    if args.push_recent:
        n = push_recent_cves(since=args.since)
        print(f"✓ pushed {n} CVE findings (since={args.since})")
        return 0
    if args.push_hardening:
        ids = push_hardening_snapshot()
        print(f"✓ pushed {len(ids)} hardening posture events")
        return 0
    if args.stats:
        print(json.dumps(_stats(), indent=2))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())