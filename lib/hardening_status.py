#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


_PROC_CMDLINE = Path("/proc/cmdline")
_PROC_SECURITY_LSM = Path("/sys/kernel/security/lsm")
_SYSCTL_BASE = Path("/proc/sys")
_RESOLV_CONF = Path("/etc/resolv.conf")
_SSHD_CONFIG = Path("/etc/ssh/sshd_config")
_SSHD_CONFIG_D = Path("/etc/ssh/sshd_config.d")
_AUDIT_RULES_D = Path("/etc/audit/rules.d")
_NFTABLES_CONF = Path("/etc/nftables.conf")
_DNSMASQ_CONF = Path("/etc/dnsmasq.conf")
_UNBOUND_CONF = Path("/etc/unbound/unbound.conf")


SYSCTL_BASELINE: dict[str, int] = {

    "kernel/kptr_restrict": 2,
    "kernel/dmesg_restrict": 1,
    "kernel/perf_event_paranoid": 3,
    "kernel/unprivileged_bpf_disabled": 1,
    "kernel/yama/ptrace_scope": 1,
    "kernel/apparmor_restrict_unprivileged_userns": 1,
    "vm/unprivileged_userfaultfd": 0,

    "net/ipv4/tcp_syncookies": 1,
    "net/ipv4/ip_forward": 0,
    "net/ipv4/conf/all/rp_filter": 1,
    "net/ipv4/conf/default/rp_filter": 1,
    "net/ipv4/conf/all/accept_source_route": 0,
    "net/ipv4/conf/all/accept_redirects": 0,
    "net/ipv4/conf/all/send_redirects": 0,
    "net/ipv4/conf/all/log_martians": 1,
    "net/ipv6/conf/all/accept_source_route": 0,
    "net/ipv6/conf/all/accept_redirects": 0,
}

SSHD_BASELINE: dict[str, str] = {
    "PermitRootLogin": "prohibit-password",
    "PasswordAuthentication": "no",
    "ChallengeResponseAuthentication": "no",
    "UsePAM": "yes",
    "MaxAuthTries": "3",
    "ClientAliveInterval": "300",
    "X11Forwarding": "no",
    "PermitEmptyPasswords": "no",
    "HostKeyAlgorithms": "ssh-ed25519-cert-v01@openssh.com,ssh-ed25519",
    "KexAlgorithms": "curve25519-sha256,sntrup761x25519-sha512@openssh.com",
    "Ciphers": "chacha20-poly1305@openssh.com",
    "MACs": "*-etm@openssh.com",
}



RISKY_CAPS = {
    "cap_sys_admin", "cap_sys_ptrace", "cap_sys_module", "cap_sys_rawio",
    "cap_sys_boot", "cap_dac_read_search", "cap_linux_immutable",
    "cap_net_admin", "cap_net_raw", "cap_sys_chroot", "cap_mknod",
    "cap_audit_write", "cap_sys_resource", "cap_sys_time",
    "cap_sys_tty_config", "cap_lease", "cap_audit_control",
    "cap_mac_override", "cap_mac_admin",
}



def _safe_run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:

    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)


def _read_proc_sys(key: str) -> int | None:

    p = _SYSCTL_BASE / key
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def _check_tool(name: str) -> str | None:
    return shutil.which(name)



def check_nftables() -> dict[str, Any]:

    if not _check_tool("nft"):
        return {"status": "unknown", "summary": "nft not installed", "details": {}}
    rc, out, err = _safe_run(["nft", "--json", "list", "ruleset"], timeout=10.0)
    if rc != 0 or not out.strip():

        rc, out, err = _safe_run(["nft", "list", "ruleset"], timeout=10.0)
        if rc != 0:
            return {"status": "fail", "summary": f"nft list failed: {err.strip()[:120]}",
                    "details": {}}
    tables: list[str] = []
    chains: list[str] = []
    rules = 0
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("table "):
            tables.append(s.split()[1] if len(s.split()) > 1 else s)
        elif s.startswith("chain "):
            chains.append(s.split()[1] if len(s.split()) > 1 else s)
        elif s and not s.startswith(("table", "chain", "type", "hook", "policy",
                                      "elements", "set", "map", "flowtable",
                                      "}", "{", "#")):
            rules += 1
    status = "ok" if tables else "warn"
    return {
        "status": status,
        "summary": f"{len(tables)} tables, {len(chains)} chains, ~{rules} rules",
        "details": {"tables": tables, "chains_count": len(chains), "rules_approx": rules},
    }


def check_sshd() -> dict[str, Any]:

    files = []
    if _SSHD_CONFIG.exists():
        files.append(_SSHD_CONFIG)
    if _SSHD_CONFIG_D.exists():
        for f in sorted(_SSHD_CONFIG_D.glob("*.conf")):
            files.append(f)
    if not files:
        return {"status": "unknown", "summary": "no sshd_config found", "details": {}}
    cfg: dict[str, str] = {}
    for f in files:
        try:
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([A-Za-z][A-Za-z0-9]*)\s+(.+?)\s*$", line)
                if m:
                    cfg[m.group(1)] = m.group(2).strip()
        except OSError:
            continue
    bad: list[str] = []
    for key, expected in SSHD_BASELINE.items():
        actual = cfg.get(key)
        if actual is None:
            bad.append(f"{key}=MISSING (want={expected})")
        elif expected not in actual:
            bad.append(f"{key}={actual} (want contains={expected})")
    if not bad:
        return {"status": "ok", "summary": "all baseline keys match",
                "details": {"checked": len(SSHD_BASELINE)}}
    if len(bad) <= 2:
        return {"status": "warn", "summary": f"{len(bad)} baseline deviations",
                "details": {"issues": bad}}
    return {"status": "fail", "summary": f"{len(bad)} baseline deviations",
            "details": {"issues": bad}}


def check_sysctl() -> dict[str, Any]:

    bad: list[str] = []
    ok_count = 0
    miss_count = 0
    for key, want in SYSCTL_BASELINE.items():
        actual = _read_proc_sys(key)
        if actual is None:
            miss_count += 1
            continue
        if actual == want:
            ok_count += 1
        else:
            bad.append(f"{key}={actual} (want={want})")
    status = "ok" if not bad else ("warn" if len(bad) <= 3 else "fail")
    return {
        "status": status,
        "summary": (f"{ok_count}/{len(SYSCTL_BASELINE)} match, "
                    f"{len(bad)} differ, {miss_count} missing"),
        "details": {"issues": bad, "ok": ok_count, "missing": miss_count},
    }


def check_auditd() -> dict[str, Any]:

    rc, out, _ = _safe_run(["auditctl", "-l"], timeout=5.0)
    if rc != 0:
        return {"status": "warn", "summary": "auditctl not queryable (auditd not running?)",
                "details": {"rc": rc}}
    rule_count = sum(1 for line in out.splitlines() if line.strip())

    staged = []
    if _AUDIT_RULES_D.exists():
        for f in sorted(_AUDIT_RULES_D.glob("*.rules")):
            try:
                staged.append((f.name, sum(1 for ln in f.read_text().splitlines()
                                           if ln.strip() and not ln.strip().startswith("#"))))
            except OSError:
                continue
    status = "ok" if rule_count >= 5 else "warn"
    return {
        "status": status,
        "summary": f"{rule_count} active rules, {len(staged)} staged files",
        "details": {"active": rule_count, "staged": staged},
    }


def check_capabilities() -> dict[str, Any]:

    if not _check_tool("getcap"):
        return {"status": "unknown", "summary": "getcap not installed", "details": {}}

    rc, out, err = _safe_run(["getcap", "-r", "/usr/bin", "/usr/sbin", "/usr/local/bin"],
                             timeout=30.0)
    if rc != 0:
        return {"status": "warn", "summary": f"getcap failed: {err.strip()[:120]}",
                "details": {}}
    risky: list[dict[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        path_part, cap_part = line.split("=", 1)
        path = path_part.strip()
        caps = cap_part.strip()
        cap_set = {c.strip().lower() for c in caps.split(",")}
        hit = cap_set & {c.lower() for c in RISKY_CAPS}
        if hit:
            risky.append({"path": path, "risky_caps": sorted(hit), "all_caps": caps})
    status = "ok" if not risky else "warn"
    return {
        "status": status,
        "summary": f"{len(risky)} binaries with risky caps (scanned /usr/*)",
        "details": {"risky": risky[:20]},
    }


def check_unbound() -> dict[str, Any]:

    has_bin = bool(_check_tool("unbound"))
    has_conf = _UNBOUND_CONF.exists()
    if not has_bin and not has_conf:
        return {"status": "unknown", "summary": "unbound not installed", "details": {}}
    details: dict[str, Any] = {"binary": has_bin, "config": has_conf}
    if has_conf:
        try:
            text = _UNBOUND_CONF.read_text()
            details["harden_glue"] = "harden-glue: yes" in text
            details["qname_minimisation"] = "qname-minimisation: yes" in text
            details["dnssec"] = "trust-anchor" in text or "auto-trust-anchor-file" in text
        except OSError:
            pass
    rc, _, _ = _safe_run(["systemctl", "is-active", "unbound"], timeout=3.0)
    running = rc == 0
    details["running"] = running
    if not has_conf:
        return {"status": "unknown", "summary": "no unbound config", "details": details}
    if not running:
        return {"status": "warn", "summary": "unbound not running", "details": details}
    return {"status": "ok", "summary": "unbound active", "details": details}


def check_dnsmasq() -> dict[str, Any]:

    has_bin = bool(_check_tool("dnsmasq"))
    rc, _, _ = _safe_run(["systemctl", "is-active", "dnsmasq"], timeout=3.0)
    running = rc == 0
    resolv_ok = False
    if _RESOLV_CONF.exists():
        try:
            text = _RESOLV_CONF.read_text()
            resolv_ok = "127.0.0.1" in text and "# Managed by" in text
        except OSError:
            pass
    if not has_bin:
        return {"status": "unknown", "summary": "dnsmasq not installed", "details": {}}
    if not running:
        return {"status": "warn", "summary": "dnsmasq not running",
                "details": {"running": False, "resolv_local": resolv_ok}}
    return {
        "status": "ok" if resolv_ok else "warn",
        "summary": f"dnsmasq running, resolv.conf→127.0.0.1: {resolv_ok}",
        "details": {"running": running, "resolv_local": resolv_ok},
    }


def check_lsms() -> dict[str, Any]:

    lsm_active: list[str] = []
    if _PROC_SECURITY_LSM.exists():
        try:
            lsm_active = _PROC_SECURITY_LSM.read_text().strip().split(",")
        except OSError:
            pass
    cmdline_lsm: str | None = None
    if _PROC_CMDLINE.exists():
        try:
            text = _PROC_CMDLINE.read_text()
            m = re.search(r"lsm=([\w,]+)", text)
            if m:
                cmdline_lsm = m.group(1)
        except OSError:
            pass
    has_landlock = "landlock" in [x.strip().lower() for x in lsm_active]
    has_lockdown = "lockdown" in [x.strip().lower() for x in lsm_active]
    score = sum([has_landlock, has_lockdown, bool(lsm_active)])
    status = "ok" if score >= 2 else ("warn" if score == 1 else "fail")
    return {
        "status": status,
        "summary": f"active={','.join(lsm_active) or '(none)'}, "
                   f"landlock={has_landlock}, lockdown={has_lockdown}",
        "details": {"active": lsm_active, "cmdline_lsm": cmdline_lsm},
    }


def check_dns_blocklist() -> dict[str, Any]:

    hosts_file = Path("/etc/hosts.adblock")
    if not hosts_file.exists():
        return {"status": "warn", "summary": "/etc/hosts.adblock not installed",
                "details": {}}
    try:
        text = hosts_file.read_text()
        count = sum(1 for line in text.splitlines()
                    if re.match(r"^\s*\d+\.\d+\.\d+\.\d+\s+\S", line))
    except OSError:
        count = 0
    status = "ok" if count >= 50 else "warn"
    return {
        "status": status,
        "summary": f"{count} block entries in /etc/hosts.adblock",
        "details": {"path": str(hosts_file), "count": count},
    }



CHECKERS: dict[str, Callable[[], dict[str, Any]]] = {
    "nftables": check_nftables,
    "sshd": check_sshd,
    "sysctl": check_sysctl,
    "auditd": check_auditd,
    "capabilities": check_capabilities,
    "unbound": check_unbound,
    "dnsmasq": check_dnsmasq,
    "lsms": check_lsms,
    "dns_blocklist": check_dns_blocklist,
}


def hardening_snapshot(subsystems: list[str] | None = None) -> dict[str, Any]:

    keys = subsystems or sorted(CHECKERS.keys())
    out: dict[str, Any] = {}
    for k in keys:
        try:
            out[k] = CHECKERS[k]()
        except Exception as exc:
            out[k] = {"status": "fail", "summary": f"checker raised: {exc}",
                      "details": {}}
    overall = "ok"
    for v in out.values():
        if v["status"] == "fail":
            overall = "fail"
            break
        if v["status"] == "warn" and overall == "ok":
            overall = "warn"
    return {"overall": overall, "subsystems": out, "ts": _now_iso()}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()



def _cli_summary(snap: dict[str, Any]) -> None:
    print(f"Overall: {snap['overall'].upper()}")
    for name, v in snap["subsystems"].items():
        icon = {"ok": "✓", "warn": "⚠", "fail": "✗", "unknown": "?"}.get(v["status"], "?")
        print(f"  {icon} {name:14s} {v['summary']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only hardening status snapshot")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    ap.add_argument("--subsystem", help="only check one subsystem")
    ap.add_argument("--summary", action="store_true", help="human summary")
    args = ap.parse_args()
    subs = [args.subsystem] if args.subsystem else None
    snap = hardening_snapshot(subsystems=subs)
    if args.json:
        print(json.dumps(snap, indent=2, default=str))
        return 0
    if args.summary or not args.json:
        _cli_summary(snap)
    return 0


if __name__ == "__main__":
    sys.exit(main())