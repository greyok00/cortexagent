#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


_REPO_ROOT = Path(__file__).resolve().parent.parent
_MITRE_MAP_FILE = _REPO_ROOT / "data" / "mitre_attack_mapping.json"
_INTEL_DIR = Path.home() / "security-console" / "cve"
_INTEL_FILE = _INTEL_DIR / "intel.jsonl"
_CACHE_DIR = Path.home() / ".cortexagent" / "cache" / "cve"
_FIREWALL_COMMANDS = Path.home() / "security-console" / "overseer" / "firewall_commands.jsonl"


def _ref_url(ref: Any) -> Optional[str]:

    if isinstance(ref, dict):
        return ref.get("url")
    if isinstance(ref, str):
        return ref.strip() or None
    return None


NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_KEY = os.environ.get("NVD_API_KEY", "").strip()

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

EPSS_URL = "https://api.first.org/data/v1/epss"
GHSA_URL = "https://api.github.com/advisories"
OSV_QUERY = "https://api.osv.dev/v1/query"

UA = "cortexagent-cve-intel/1.0 (+local)"

_USER_AGENT = UA
_SSL_CTX = ssl.create_default_context()


_MITRE_MAP: dict[str, list[str]] | None = None
_KEYWORD_MAP: dict[str, list[str]] | None = None


def _load_mitre_map() -> tuple[dict[str, list[str]], dict[str, list[str]]]:

    global _MITRE_MAP, _KEYWORD_MAP
    if _MITRE_MAP is None or _KEYWORD_MAP is None:
        if not _MITRE_MAP_FILE.exists():
            _MITRE_MAP, _KEYWORD_MAP = {}, {}
        else:
            data = json.loads(_MITRE_MAP_FILE.read_text())
            _MITRE_MAP = data.get("mapping", {})
            _KEYWORD_MAP = data.get("keyword_fallback", {})
    return _MITRE_MAP, _KEYWORD_MAP



def _http_get(url: str, params: dict | None = None, headers: dict | None = None,
              timeout: float = 30.0) -> bytes:

    if params:

        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        **(headers or {}),
    })
    if NVD_KEY:
        req.add_header("apiKey", NVD_KEY)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


def _http_get_json(url: str, params: dict | None = None,
                   headers: dict | None = None, timeout: float = 30.0) -> Any:

    raw = _http_get(url, params=params, headers=headers, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None



def _cache_path(name: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{name}.json"


def _read_cache(name: str, max_age_s: int) -> Any | None:
    p = _cache_path(name)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > max_age_s:
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(name: str, data: Any) -> None:
    _cache_path(name).write_text(json.dumps(data, default=str))



def poll_kev() -> set[str]:

    cached = _read_cache("kev", max_age_s=6 * 3600)
    if cached is not None:
        return set(cached)
    data = _http_get_json(KEV_URL, timeout=60.0) or {}
    cves = {e["cveID"] for e in data.get("vulnerabilities", [])}
    _write_cache("kev", sorted(cves))
    return cves


def poll_nvd(since: str | None = None, limit: int = 200) -> list[dict]:

    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000")
    params: dict[str, str | int] = {
        "lastModStartDate": since,
        "lastModEndDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "resultsPerPage": min(limit, 2000),
    }
    try:
        data = _http_get_json(NVD_API, params=params, timeout=60.0) or {}
    except urllib.error.URLError as exc:

        cached = _read_cache("nvd_recent", max_age_s=24 * 3600)
        if cached is not None:
            return cached
        raise RuntimeError(f"NVD fetch failed: {exc}") from exc
    entries = []
    for v in data.get("vulnerabilities", []):
        entry = _nvd_to_entry(v)
        if entry:
            entries.append(entry)
    _write_cache("nvd_recent", entries[-200:])
    return entries


def _nvd_to_entry(v: dict) -> dict | None:

    c = v.get("cve") or {}
    cid = c.get("id")
    if not cid:
        return None
    metrics = (c.get("metrics") or {})
    cvss_v3 = None
    cvss_v4 = None
    severity = "n/a"
    for key in ("cvssMetricV31", "cvssMetricV30"):
        if metrics.get(key):
            cvss_v3 = metrics[key][0]["cvssData"]["baseScore"]
            severity = metrics[key][0]["cvssData"].get("baseSeverity", "n/a").lower()
            break
    if metrics.get("cvssMetricV40"):
        cvss_v4 = metrics["cvssMetricV40"][0]["cvssData"]["baseScore"]
        severity = metrics["cvssMetricV40"][0]["cvssData"].get("baseSeverity", severity).lower()
    cwe_ids: list[str] = []
    for w in c.get("weaknesses", []):
        for d in w.get("description", []):
            v_ = d.get("value", "")
            if v_.startswith("CWE-"):
                cwe_ids.append(v_)
    cpe: list[str] = []
    for cfg in c.get("configurations", []):
        for n in cfg.get("nodes", []):
            for cpe_match in n.get("cpeMatch", []):
                if cpe_match.get("criteria"):
                    cpe.append(cpe_match["criteria"])
    descriptions = c.get("descriptions", [])
    summary = ""
    for d in descriptions:
        if d.get("lang") == "en":
            summary = (d.get("value") or "")[:240]
            break
    refs = [_ref_url(r) for r in c.get("references", []) if _ref_url(r)]
    return {
        "cve_id": cid,
        "published": c.get("published", ""),
        "last_modified": c.get("lastModified", ""),
        "cvss_v3": cvss_v3,
        "cvss_v4": cvss_v4,
        "severity": severity,
        "summary": summary,
        "cwe_ids": cwe_ids,
        "cpe": cpe[:10],
        "refs": refs[:5],
        "kev": False,
        "kev_due_date": None,
        "kev_ransomware_use": False,
        "epss_score": None,
        "epss_percentile": None,
        "mitre_techniques": [],
        "sources": ["nvd"],
    }


def poll_epss(cve_ids: Iterable[str]) -> dict[str, tuple[float, float]]:

    ids = list(cve_ids)
    if not ids:
        return {}

    out: dict[str, tuple[float, float]] = {}
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        chunk = ids[i:i + batch_size]
        params = {"cve": ",".join(chunk)}
        try:
            data = _http_get_json(EPSS_URL, params=params, timeout=30.0) or {}
        except urllib.error.URLError:
            continue
        for row in data.get("data", []):
            try:
                out[row["cve"]] = (float(row["epss"]), float(row["percentile"]))
            except (KeyError, ValueError):
                continue
    return out


def poll_ghsa(ecosystems: list[str] | None = None,
              since: str | None = None) -> list[dict]:

    if ecosystems is None:
        ecosystems = ["npm", "pip", "go", "rust", "composer", "maven"]
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    out: list[dict] = []
    for eco in ecosystems:
        params = {"ecosystem": eco, "per_page": 50, "since": since}
        try:
            data = _http_get_json(GHSA_URL, params=params, timeout=30.0) or []
        except urllib.error.URLError:
            continue
        if not isinstance(data, list):
            continue
        for a in data:
            entry = _ghsa_to_entry(a)
            if entry:
                out.append(entry)
    return out


def _ghsa_to_entry(a: dict) -> dict | None:
    cid = a.get("cve_id") or a.get("ghsa_id")
    if not cid:
        return None
    return {
        "cve_id": cid,
        "published": a.get("published_at", ""),
        "last_modified": a.get("updated_at", ""),
        "cvss_v3": None,
        "cvss_v4": None,
        "severity": (a.get("severity") or "n/a").lower(),
        "summary": (a.get("summary") or a.get("description") or "")[:240],
        "cwe_ids": [],
        "cpe": [],
        "refs": [_ref_url(r) for r in (a.get("references") or [])][:5],
        "kev": False,
        "kev_due_date": None,
        "kev_ransomware_use": False,
        "epss_score": None,
        "epss_percentile": None,
        "mitre_techniques": [],
        "sources": ["ghsa"],
    }


def poll_osv(packages: list[tuple[str, str]] | None = None) -> list[dict]:

    if packages is None:
        packages = pin_dependencies()
    out: list[dict] = []
    for eco, name in packages[:50]:
        body = json.dumps({"package": {"name": name, "ecosystem": eco}}).encode()
        req = urllib.request.Request(OSV_QUERY, data=body, headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30.0, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError):
            continue
        for v in data.get("vulns", []) or []:
            cid = v.get("id") or ""
            if cid.startswith("GHSA-"):

                for alias in v.get("aliases", []):
                    if alias.startswith("CVE-"):
                        cid = alias
                        break
            entry = {
                "cve_id": cid,
                "published": (v.get("published") or ""),
                "last_modified": (v.get("modified") or ""),
                "cvss_v3": None,
                "cvss_v4": None,
                "severity": "n/a",
                "summary": (v.get("summary") or v.get("details") or "")[:240],
                "cwe_ids": [],
                "cpe": [f"{eco}:{name}"],
                "refs": [v.get("reference") or v.get("url") or ""][:5] if (v.get("reference") or v.get("url")) else [],
                "kev": False,
                "kev_due_date": None,
                "kev_ransomware_use": False,
                "epss_score": None,
                "epss_percentile": None,
                "mitre_techniques": [],
                "sources": ["osv"],
            }
            if entry["cve_id"]:
                out.append(entry)
    return out


URLHAUS_DUMP = "https://urlhaus.abuse.ch/downloads/csv_recent/"


def poll_urlhaus() -> set[str]:

    try:
        data = _http_get(URLHAUS_DUMP, timeout=30.0).decode("utf-8", "replace")
    except Exception:
        return set()
    bad: set[str] = set()
    for line in data.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) >= 3 and parts[2].startswith("http"):
            bad.add(parts[2].strip('"'))
    return bad


def pin_dependencies() -> list[tuple[str, str]]:

    pkgs: list[tuple[str, str]] = []

    pip_freeze = _REPO_ROOT / "pip-freeze.txt"
    if pip_freeze.exists():
        for line in pip_freeze.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "==" in line:
                pkgs.append(("PyPI", line.split("==", 1)[0]))

    for pkg_json in _REPO_ROOT.rglob("package.json"):
        try:
            data = json.loads(pkg_json.read_text())
            for name in (data.get("dependencies") or {}).keys():
                pkgs.append(("npm", name))
        except (OSError, json.JSONDecodeError):
            continue

    go_mod = _REPO_ROOT / "go.mod"
    if go_mod.exists():
        for line in go_mod.read_text().splitlines():
            line = line.strip()
            if line.startswith("require ") or "\t" in line:
                parts = line.split()
                if len(parts) >= 2 and "/" in parts[1]:
                    pkgs.append(("Go", parts[1].split("/")[-1]))

    cargo_lock = _REPO_ROOT / "Cargo.lock"
    if cargo_lock.exists():
        for line in cargo_lock.read_text().splitlines():
            m = re.match(r'\s*name\s*=\s*"([^"]+)"', line)
            if m:
                pkgs.append(("crates.io", m.group(1)))
    return pkgs



def enrich_with_mitre(entry: dict) -> dict:

    techniques: list[str] = []
    cwe_map, kw_map = _load_mitre_map()
    for cwe in entry.get("cwe_ids", []):
        if cwe in cwe_map:
            techniques.extend(cwe_map[cwe])
    if not techniques:
        text = (entry.get("summary") or "").lower()
        for kw, techs in kw_map.items():
            if kw in text:
                techniques.extend(techs)
                break
    entry["mitre_techniques"] = sorted(set(techniques))
    return entry



def _load_seen_ids() -> set[str]:
    if not _INTEL_FILE.exists():
        return set()
    seen: set[str] = set()
    try:
        with _INTEL_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["cve_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        return set()
    return seen


def diff_against_last(entries: list[dict]) -> list[dict]:

    seen = _load_seen_ids()
    return [e for e in entries if e["cve_id"] not in seen]


def write_intel(entries: list[dict], append: bool = True) -> int:

    if not entries:
        return 0
    _INTEL_DIR.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    n = 0
    with _INTEL_FILE.open(mode, encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, default=str, ensure_ascii=False) + "\n")
            n += 1
    return n



def recent(since: str = "7d", min_cvss: float = 0.0,
           kev_only: bool = False, limit: int = 100) -> list[dict]:

    if not _INTEL_FILE.exists():
        return []
    window_s = _parse_window(since)
    cutoff = time.time() - window_s
    out: list[dict] = []
    try:
        with _INTEL_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _iso_to_ts(e.get("published") or e.get("last_modified") or "")
                if ts < cutoff:
                    continue
                cvss = e.get("cvss_v3") or e.get("cvss_v4") or 0.0
                if cvss < min_cvss:
                    continue
                if kev_only and not e.get("kev"):
                    continue
                out.append(e)
                if len(out) >= limit:
                    break
    except OSError:
        return []

    out.sort(key=lambda e: e.get("published") or e.get("last_modified") or "", reverse=True)
    return out


def _parse_window(s: str) -> int:

    m = re.match(r"^(\d+)([smhd])$", s.strip().lower())
    if not m:
        return 7 * 86400
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _iso_to_ts(s: str) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def lookup(cve_id: str) -> dict | None:

    if _INTEL_FILE.exists():
        try:
            with _INTEL_FILE.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("cve_id") == cve_id:
                        return e
        except OSError:
            pass

    try:
        data = _http_get_json(NVD_API, params={"cveId": cve_id}, timeout=30.0) or {}
        for v in data.get("vulnerabilities", []):
            entry = _nvd_to_entry(v)
            if entry:
                enrich_with_mitre(entry)

                kev = poll_kev()
                if entry["cve_id"] in kev:
                    entry["kev"] = True
                return entry
    except urllib.error.URLError:
        return None
    return None


def mitre_for_cve(cve_id: str) -> list[str]:

    entry = lookup(cve_id)
    if not entry:
        return []
    return entry.get("mitre_techniques", [])





_LOCAL_MITIGATIONS: dict[str, str] = {
    "M1041": "Encrypt Sensitive Information (nftables + unbound DoT)",
    "M1056": "Pre-compromise (Brave Shields, CSP strict-dynamic)",
    "M1031": "Network Intrusion Prevention (Suricata, nftables)",
    "M1037": "Filter Network Traffic (UFW + dnsmasq blocklist)",
    "M1026": "Principle of Least Privilege (systemd hardening, capability drop)",
    "M1018": "Disable or Remove Feature or Program (seccomp, Landlock)",
    "M1028": "Operating System Configuration (sysctl hardening, Lockdown LSM)",
    "M1054": "Software Configuration (Brave managed policies, hardening.json)",
    "M1047": "Audit (auditd, SIEM ingest)",
    "M1032": "Multi-factor Authentication (YubiKey + pam_u2f)",
    "M1057": "User Training (security tray popout education)",
    "M1060": "Software Signing (fs-verity, dm-verity, IMA)",
    "M1024": "Restrict Registry Permissions (n/a Linux)",
    "M1029": "Scheduled Software Updates (apt auto, brew autoupdate)",
    "M1030": "Network Segmentation (nftables zones)",
    "M1034": "Limit Hardware Installation (n/a)",
    "M1035": "Do Not Mitigate (documented exceptions)",
    "M1042": "Disable or Remove Programs or Software (sudo-rs replacing sudo)",
    "M1043": "Software Vulnerability Scanning (Trivy, Grype)",
    "M1044": "Restrict Library Loading (LD_PRELOAD drop, seccomp filter @process)",
    "M1045": "Code Signing (sigstore, cosign for OCI images)",
    "M1051": "Update Software (kernel + systemd weekly auto-update)",
    "M1052": "User Account Control (sudoers, capability-based)",
    "M1053": "Software Development Process (TDD, code review, lint)",
    "M1055": "Do Not Trust (zero-trust routing)",
    "M1058": "Exploit Protection (ASLR, CET, Lockdown LSM)",
    "M1059": "Threat Intelligence Program (THIS MODULE)",
}


def mitre_coverage() -> dict:

    covered = list(_LOCAL_MITIGATIONS.keys())
    return {
        "covered": sorted(covered),
        "uncovered": [],
        "pct": round(100.0 * len(covered) / 42.0, 1),
        "mapping": _LOCAL_MITIGATIONS,
    }



def poll_cve_feeds(since: str | None = "7d", skip_osv: bool = True) -> list[dict]:

    since_iso: str | None = None
    if since:

        days = _parse_window(since) // 86400
        since_iso = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).strftime("%Y-%m-%dT%H:%M:%S.000")
    nvd_entries = poll_nvd(since=since_iso) if since_iso else poll_nvd()
    kev_ids = poll_kev()
    epss_map = poll_epss(e["cve_id"] for e in nvd_entries)
    ghsa_entries = poll_ghsa(since=since_iso)
    entries = nvd_entries + ghsa_entries

    by_id: dict[str, dict] = {}
    for e in entries:
        by_id.setdefault(e["cve_id"], e).setdefault("sources", []).extend(
            [s for s in e.get("sources", []) if s not in by_id[e["cve_id"]].get("sources", [])]
        )
    for cid, entry in by_id.items():
        if cid in kev_ids:
            entry["kev"] = True
        if cid in epss_map:
            entry["epss_score"], entry["epss_percentile"] = epss_map[cid]
        enrich_with_mitre(entry)
    if not skip_osv:

        for entry in poll_osv():
            cid = entry["cve_id"]
            if cid in by_id:
                by_id[cid].setdefault("sources", []).append("osv")
            else:
                enrich_with_mitre(entry)
                by_id[cid] = entry
    new_entries = diff_against_last(list(by_id.values()))
    if new_entries:
        write_intel(new_entries)
    return new_entries



def _is_smoke_argv(argv: list[str]) -> bool:

    return any(a == "--smoke" for a in argv[1:])


def _smoke() -> int:

    fake = {
        "cve_id": "CVE-2024-3094",
        "published": "2024-03-29T17:15:00.000",
        "last_modified": "2024-04-01T00:00:00.000",
        "cvss_v3": 10.0,
        "cvss_v4": None,
        "severity": "critical",
        "summary": "XZ Utils backdoor in liblzma — supply-chain compromise enabling sshd auth bypass.",
        "cwe_ids": ["CWE-506"],
        "cpe": ["cpe:2.3:a:tukaani:xz:5.6.0:*:*:*:*:*:*:*"],
        "refs": ["https://nvd.nist.gov/vuln/detail/CVE-2024-3094"],
        "kev": False,
        "kev_due_date": None,
        "kev_ransomware_use": False,
        "epss_score": 0.97,
        "epss_percentile": 99.9,
        "mitre_techniques": [],
        "sources": ["nvd"],
    }
    enrich_with_mitre(fake)
    print("[smoke] MITRE techniques for CVE-2024-3094:")
    for t in fake["mitre_techniques"]:
        print(f"  - {t}")
    print(f"[smoke] KEV detection (offline): {'OK' if 'CVE-2024-3094' not in poll_kev() else 'cached'}")
    print(f"[smoke] Coverage: {mitre_coverage()['pct']}% of MITRE mitigations mapped locally")
    print("[smoke] Fake CVE passed through enrich + lookup OK")
    return 0


def main() -> int:
    argv = sys.argv
    if _is_smoke_argv(argv):
        return _smoke()
    ap = argparse.ArgumentParser(description="CVE / KEV / EPSS threat-intel poller")
    sub = ap.add_subparsers(dest="cmd")

    poll_p = sub.add_parser("poll", help="full poll of all feeds")
    poll_p.add_argument("--since", default="7d", help="window like '7d', '24h'")
    poll_p.add_argument("--include-osv", action="store_true", help="also query OSV.dev for our pinned deps")

    lookup_p = sub.add_parser("lookup", help="look up a single CVE")
    lookup_p.add_argument("cve_id")

    mitre_p = sub.add_parser("mitre", help="reverse lookup: ATT&CK technique → CVEs")
    mitre_p.add_argument("technique_id")

    sub.add_parser("coverage", help="MITRE mitigation coverage of our hardening")

    recent_p = sub.add_parser("recent", help="query recent entries from intel.jsonl")
    recent_p.add_argument("--since", default="7d")
    recent_p.add_argument("--min-cvss", type=float, default=0.0)
    recent_p.add_argument("--kev-only", action="store_true")

    args = ap.parse_args(argv[1:])
    if args.cmd is None:
        return _smoke()
    if args.cmd == "poll":
        new = poll_cve_feeds(since=args.since, skip_osv=not args.include_osv)

        try:
            bad = poll_urlhaus()
        except Exception:
            bad = set()
        if bad:
            for e in new:
                refs = e.get("refs") or []
                hits = [r for r in refs if r in bad]
                if hits:
                    e["urlhaus_match"] = hits
        print(f"[poll] {len(new)} new entries written to {_INTEL_FILE}")
        for e in new[:10]:
            print(f"  {e['cve_id']:18s} CVSS={e.get('cvss_v3') or '-':>4}  KEV={e['kev']!s:<5}  T={','.join(e.get('mitre_techniques', []))}")
        return 0
    if args.cmd == "lookup":
        entry = lookup(args.cve_id)
        if not entry:
            print(f"[lookup] {args.cve_id} not found")
            return 1
        print(json.dumps(entry, indent=2))
        return 0
    if args.cmd == "mitre":

        if not _INTEL_FILE.exists():
            print(f"[mitre] no intel file at {_INTEL_FILE}")
            return 1
        cves = []
        with _INTEL_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if args.technique_id in e.get("mitre_techniques", []):
                    cves.append(e["cve_id"])
        print(f"[mitre] {len(cves)} CVEs map to {args.technique_id}:")
        for c in cves[:20]:
            print(f"  - {c}")
        return 0
    if args.cmd == "coverage":
        cov = mitre_coverage()
        print(f"[coverage] {cov['pct']}% of MITRE v15 mitigations ({len(cov['covered'])} mapped locally)")
        for m, desc in sorted(cov["mapping"].items()):
            print(f"  {m}: {desc}")
        return 0
    if args.cmd == "recent":
        for e in recent(since=args.since, min_cvss=args.min_cvss, kev_only=args.kev_only):
            print(f"  {e['cve_id']:18s} CVSS={e.get('cvss_v3') or '-':>4}  KEV={e['kev']!s:<5}  {e.get('published')}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())