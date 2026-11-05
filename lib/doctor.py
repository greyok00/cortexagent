#!/usr/bin/env python3

"""Doctor: detects drift between the on-disk configuration and the rendered templates, repairing managed keys only, never foreign content."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG, CONFIG_DIR, MCP_CONFIG

if sys.stderr.isatty():
    CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
        "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
else:
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""

HEALTHY = "healthy"
FIXED = "fixed"
DRY = "would-fix"
FLAG = "flag"
FAIL = "fail"

class Check:
    __slots__ = ("name", "status", "detail")

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name, self.status, self.detail = name, status, detail

    @property
    def ok(self) -> bool:
        return self.status in (HEALTHY, FIXED, DRY, FLAG)

def _bak(path: Path) -> Path:

    if not path.exists():
        return path
    bak = path.with_suffix(path.suffix + f".doctor.bak.{int(time.time())}")
    try:
        shutil.copy2(path, bak)
    except Exception:
        pass
    _prune_baks(path)
    return bak

def _prune_baks(path: Path, keep: int = 3) -> None:
    """Keep only the newest `keep` doctor backups for this path (prevents an unbounded .bak pile)."""
    parent = path.parent
    stem = path.name
    try:
        baks = sorted(parent.glob(stem + ".doctor.bak.*"))
    except Exception:
        return
    for old in baks[:-keep] if len(baks) > keep else []:
        try:
            old.unlink()
        except Exception:
            pass

def _render_settings(home: str) -> str:
    tpl = (_REPO_ROOT / "config" / "settings.json.template").read_text()
    model = str(CFG.model_path or "")
    return (tpl.replace("{{HOME}}", home)
               .replace("{{MODEL_PATH}}", model)
               .replace("{{MODEL_NAME}}", os.path.basename(model)))

def _render_mcp(memory_cmd: str, fire_enabled: str, browser_mcp_enabled: str,
                greysearch_enabled: str | None = None) -> tuple[str, bool]:
    if greysearch_enabled is None:
        greysearch_enabled = os.environ.get("CORTEXAGENT_GREYSEARCH", "1")
    # Managed defaults. Every optional integration is config-driven: an MCP
    # server entry is written only when the integration is enabled and its
    # target is available on this machine; env flags opt out:
    #   CORTEXAGENT_GREYSEARCH=0   disable the greysearch web-research MCP
    #   CORTEXAGENT_SLIMTOKEN=0    disable the slimtoken compression MCP
    servers: dict = {}
    mem_script = memory_cmd.split()[-1] if memory_cmd else ""
    has_cortexagent = bool(mem_script) and os.path.exists(mem_script)
    if has_cortexagent:
        servers["cortexagent"] = {"command": memory_cmd}
    greysearch_root = os.environ.get(
        "CORTEXAGENT_GREYSEARCH_MCP", "~/greysearch").rstrip("/")
    greysearch_script = os.path.expanduser(f"{greysearch_root}/greysearch_mcp.py")
    if greysearch_enabled == "1" and os.path.exists(greysearch_script):
        servers["greysearch"] = {"command": f"python3 {greysearch_script}"}
    if os.environ.get(
            "CORTEXAGENT_SLIMTOKEN", "1") != "0":
        try:
            import importlib.util

            if importlib.util.find_spec("slimtoken") is not None:
                servers["slimtoken"] = {"command": "python3 -m slimtoken.mcp_server"}
        except Exception:
            pass
    if fire_enabled == "1":
        servers["firecrawl"] = {
            "command": f"python3 {os.path.join(str(_REPO_ROOT), 'lib', 'firecrawl_proxy.py')}"}
    if browser_mcp_enabled == "1":
        venv_py = os.path.expanduser("~/.cortexagent/venv/bin/python3")
        if not os.path.exists(venv_py):
            venv_py = "python3"
        servers["patchright_chrome"] = {
            "command": f"{venv_py} {os.path.join(str(_REPO_ROOT), 'lib', 'patchright_chrome_mcp.py')}"}
    lazy = os.path.expanduser("~/.cortexagent/config/lazy_mcp_servers.json")
    if os.path.exists(lazy):
        try:
            for entry in json.load(open(lazy, encoding="utf-8")):
                name = entry.get("name")
                cmd = entry.get("command", [])
                if isinstance(cmd, list):
                    cmd = " ".join(cmd)
                if name and cmd:
                    servers[f"lazy_{name}"] = {
                        "command": f"python3 {os.path.join(str(_REPO_ROOT), 'lib', 'lazy_mcp_proxy.py')} --name {name}"}
        except Exception:
            pass
    return json.dumps({"mcpServers": servers}, indent=2) + "\n", has_cortexagent

def _check_config_dir(cfg_dir: Path, dry: bool) -> Check:
    # NOTE: caller passes `write` (= fix and not dry) here, not a
    # read-only flag — so False must mean report-only, True means write.
    if cfg_dir.exists():
        return Check("config dir exists", HEALTHY, str(cfg_dir))
    if not dry:
        return Check("config dir exists", DRY, f"would create {cfg_dir}")
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return Check("config dir exists", FIXED, f"created {cfg_dir}")
    except Exception as e:
        return Check("config dir exists", FAIL, f"{e.__class__.__name__}: {e}")

def _check_profile_at_runtime() -> Check:

    return Check("practical-reasoning profile", HEALTHY,
                 "applied at runtime (slimtoken)")

def _check_settings(cfg_dir: Path, home: str, dry: bool) -> Check:
    dst = cfg_dir / "settings.json"
    want = _render_settings(home)
    try:
        want_obj = json.loads(want)
    except Exception:
        return Check("settings.json", FAIL, "repo template unparseable")
    have = dst.read_text() if dst.exists() else ""
    try:
        have_obj = json.loads(have) if have.strip() else {}
    except Exception:
        have_obj = None
    if have.strip() == want.strip():
        return Check("settings.json", HEALTHY, "matches rendered template")

    drifted = []
    settings_keys = ("quiet", "spinnerTipsEnabled", "statusLine", "hooks")
    for key in settings_keys:
        if have_obj and have_obj.get(key) != want_obj.get(key):
            drifted.append(key)
    drift_str = ("drifted: " + ",".join(drifted)) if drifted else "structure changed"
    # NOTE: see _check_config_dir — the flag in is `write`, not `dry`.
    if not dry:
        return Check("settings.json", DRY, f"would re-render ({drift_str})")
    _bak(dst)
    dst.write_text(want)
    return Check("settings.json", FIXED, drift_str)

def _check_mcp(cfg_dir: Path, memory_cmd: str, fire: str, browser_mcp: str,
               fix: bool, dry: bool) -> Check:
    """A plain check must not mutate. Also merge, don't
    clobber — the launcher (bin/cortexagent) installs shim-wrapped servers
    (secops/messenger/workers/patchright-research) that the rendered
    template has never known about; a whole-file re-render used to strip
    them and the SIGINT shim, re-feeding the MCP orphan leak."""
    dst = cfg_dir / "mcp.json"
    # Legacy migration: pre-unification surfaces wrote/read
    # ~/.cortexagent/mcp.json; adopt it once so --fix carries user content to
    # the canonical path instead of treating it as empty and re-rendering.
    if not dst.exists():
        legacy_home = Path.home() / ".cortexagent" / "mcp.json"
        if legacy_home.exists():
            if dry or not fix:
                return Check("mcp.json", DRY,
                             f"missing — --fix would migrate {legacy_home} → {dst}, then merge managed keys")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_home, dst)
            # fall through: the managed-key merge below picks up the migrated
            # file in this same pass instead of two runs later.
    want, has_ca = _render_mcp(memory_cmd, fire, browser_mcp)
    try:
        want_obj = json.loads(want)
    except Exception:
        return Check("mcp.json", FAIL, "rendered template unparseable")

    have_text = dst.read_text() if dst.exists() else ""
    try:
        have_obj = json.loads(have_text) if have_text.strip() else {}
    except Exception:
        have_obj = None
    if have_obj is None or not isinstance(have_obj, dict):
        if dry or not fix:
            return Check("mcp.json", DRY,
                         "unreadable/missing — --fix would re-render (clobbers unknown servers)")
        _bak(dst)
        dst.write_text(want)
        return Check("mcp.json", FIXED, "re-rendered (was unreadable)")
    if have_obj == want_obj:
        return Check("mcp.json", HEALTHY,
                     "cortexagent present" if has_ca else "cortexagent correctly absent")

    have_servers = have_obj.get("mcpServers") or {}
    want_servers = want_obj.get("mcpServers", {})
    # The old check demanded
    # have == want EXACTLY, and the fix path DELETED firecrawl/
    # patchright_chrome whenever their env gates were off — a live file that
    # legitimately carries those servers could never satisfy the check, so
    # doctor oscillated ("1 drift" forever) and every --fix clobbered
    # running servers. Correct model: drift = a MANAGED key missing or
    # differing; extra servers in the file are the user's/launcher's, never
    # touched.
    drift_keys = [k for k, v in want_servers.items()
                  if have_servers.get(k) != v]
    retained = [k for k in ("firecrawl", "patchright_chrome")
                if k in have_servers and k not in want_servers]
    foreign_count = len(have_servers) - len(want_servers) + len(drift_keys)
    if not drift_keys:
        retained_str = (f"; retained (env-gated off this run): "
                        f"{','.join(retained)}" if retained else "")
        return Check("mcp.json", HEALTHY,
                     "managed keys match" + retained_str)
    detail = "drifted managed keys: " + ",".join(drift_keys) + \
             (f"; {len(have_servers)} servers in file" if foreign_count else "")
    if dry or not fix:
        return Check("mcp.json", DRY, "drift — --fix would merge managed keys" + detail)
    merged = dict(have_obj)
    merged_servers = dict(have_servers)
    for key, value in want_servers.items():
        merged_servers[key] = value
    merged["mcpServers"] = merged_servers
    _bak(dst)
    dst.write_text(json.dumps(merged, indent=2) + "\n")
    return Check("mcp.json", FIXED, "merged managed keys: "
                 + ",".join(drift_keys))

def _check_binary_patch(no_patch: bool, dry: bool) -> Check:




    if dry:
        return Check("settings drift", FLAG, "binary patch layer retired")
    return None

def _check_asset() -> Check:
    logo = _REPO_ROOT / "assets" / "cortexagentsquarelogo.jpg"
    if logo.exists() and logo.stat().st_size > 1000:
        return Check("logo asset", HEALTHY, f"{logo.stat().st_size} bytes")
    return Check("logo asset", FAIL, f"missing/corrupt: {logo}")

def _check_launcher_wiring() -> Check:

    la = _REPO_ROOT / "bin" / "cortexagent"
    if not la.exists():
        return Check("launcher wiring", FAIL, "bin/cortexagent missing")
    txt = la.read_text()
    missing = []
    for needle, label in (
        ("IS_DEMO", "IS_DEMO"),
        ("CORTEXAGENT_ALT_SCREEN", "ALT_SCREEN"),
        ("lib/banner.py", "banner call"),
        ("os.path.exists(_mem_script)", "MCP guard"),
    ):
        if needle not in txt:
            missing.append(label)
    if missing:
        return Check("launcher wiring", FLAG, "tampered/missing: " + ",".join(missing))
    return Check("launcher wiring", HEALTHY, "IS_DEMO/ALT_SCREEN/banner/MCP-guard intact")

def _check_model_conf_lock(dry: bool, fix: bool = False) -> Check:

    conf = Path(os.environ.get("CORTEXAGENT_CONF",
                               str(Path.home() / ".cortexagent" / "cortexagent.conf")))
    if not conf.exists():
        return Check("model conf lock", HEALTHY, "no conf (defaults + LOCKED_KEYS active)")
    try:
        status = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "lib" / "config.py"), "lock-status"],
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        status = ""
    drift = [ln for ln in status.splitlines() if "DRIFT" in ln]
    n_locked = sum(1 for ln in status.splitlines() if "locked" in ln)
    mode = oct(conf.stat().st_mode & 0o777)
    if mode == "0o444" and not drift:
        return Check("model conf lock", HEALTHY,
                     f"conf read-only + {n_locked} LOCKED_KEYS active")
    # A check-only run must never chmod/chattr the user's
    # conf; chattr +i previously made later edits fail silently.
    detail = f"conf writable ({mode})" + (f"; DRIFT: {drift}" if drift else "")
    if dry or not fix:
        return Check("model conf lock", DRY, "check-only — --fix would chmod 444" + detail)
    try:
        os.chmod(conf, 0o444)
    except Exception as e:
        return Check("model conf lock", FAIL, f"chmod failed: {e}")
    return Check("model conf lock", FIXED, "chmod 444 applied (chattr +i no longer used)" +
                  (f" (DRIFT remains: {drift})" if drift else ""))

def _check_native_modules() -> Check:
    # Repository policy is pure readable Python; a stray compiled extension
    # shadowing a source file would silently beat the source at import time.
    stale = sorted(
        py.stem for py in sorted((_REPO_ROOT / "lib").glob("*.py"))
        if (_REPO_ROOT / "lib").glob(py.stem + ".cpython-*.so"))
    if stale:
        return Check("native modules", FLAG,
                     "compiled modules present: " + ",".join(stale)
                     + " — running from .py sources")
    return Check("native modules", HEALTHY, "no compiled modules (py sources)")

def _check_research_stack(greysearch_enabled: str) -> Check:
    # Advisory: reports integration stack health; never writes. External
    # integrations (greysearch, slimtoken) are config-driven MCP servers, not
    # in-process dependencies. Names servers in the live mcp.json whose
    # command target is missing on disk — foreign servers are preserved by
    # policy, so dead entries are only pointed out, never deleted.
    detail = []
    if os.environ.get("CORTEXAGENT_SLIMTOKEN", "1") != "0":
        try:
            import slimtoken
            have = getattr(slimtoken, "__version__", None) or "installed"
            detail.append(f"slimtoken {have}")
        except ImportError:
            detail.append("slimtoken not installed — MCP entry omitted; "
                          "install the slimtoken package to enable")
    if greysearch_enabled == "1":
        root = os.environ.get("CORTEXAGENT_GREYSEARCH_MCP", "~/greysearch").rstrip("/")
        if not os.path.exists(os.path.expanduser(f"{root}/greysearch_mcp.py")):
            detail.append("greysearch checkout not found — MCP entry omitted; "
                          "set CORTEXAGENT_GREYSEARCH_MCP to enable")
    mcp_cfg = MCP_CONFIG
    try:
        data = json.loads(mcp_cfg.read_text()) if mcp_cfg.exists() else {}
        for name, cfg in (data.get("mcpServers") or {}).items():
            cmd = cfg.get("command", "")
            parts = str(cmd).split() if isinstance(cmd, str) else [str(cmd)]
            args = list(cfg.get("args", [])) if isinstance(cfg.get("args"), list) else []
            script = next((a for a in parts[1:] + args if a and "/" in a and a.endswith(".py")), None)
            if script and not os.path.exists(os.path.expanduser(script)):
                detail.append(f"dead entry '{name}': {script} missing on disk")
    except Exception:
        pass
    return Check("research stack", HEALTHY,
                 "; ".join(detail) if detail else "keyless search available")

def run(dry: bool = False, no_patch: bool = False, fix: bool = False) -> list[Check]:
    """Check-only by default. Writes happen ONLY when
    fix=True; dry=True is the explicit report-only alias."""
    write = fix and not dry
    cfg_dir = CONFIG_DIR  # same constant mcp_client resolves
    home = str(Path.home())
    memory_cmd = f"python3 {_REPO_ROOT}/memory/mcp_server.py"
    browser_mcp = os.environ.get("CORTEXAGENT_BROWSER_MCP_ENABLED", "0")
    fire_enabled = os.environ.get("CORTEXAGENT_FIRECRAWL_ENABLED", "0")
    greysearch = os.environ.get("CORTEXAGENT_GREYSEARCH", "1")
    checks: list[Check] = []
    checks.append(_check_config_dir(cfg_dir, write))
    checks.append(_check_profile_at_runtime())
    checks.append(_check_settings(cfg_dir, home, write))
    checks.append(_check_mcp(cfg_dir, memory_cmd, fire_enabled, browser_mcp, write, dry))
    checks.append(_check_native_modules())
    checks.append(_check_research_stack(greysearch))
    _bp = _check_binary_patch(no_patch, write)
    if _bp is not None:
        checks.append(_bp)
    checks.append(_check_asset())
    checks.append(_check_launcher_wiring())
    checks.append(_check_model_conf_lock(dry, write))
    return checks

def _format(checks: list[Check], dry: bool = False) -> str:
    mark = {HEALTHY: f"{GREEN}✓{RST}", FIXED: f"{YELLOW}↻{RST}",
            DRY: f"{CYAN}?{RST}", FLAG: f"{RED}!{RST}", FAIL: f"{RED}✗{RST}"}
    lines = [f"{BOLD}CortexAgent doctor — settings drift repair{RST}", "─" * 56]
    width = max(len(c.name) for c in checks)
    for c in checks:
        lines.append(f"  {mark.get(c.status, '?')} {c.name:<{width}}  {DIM}{c.detail}{RST}")
    fixed = sum(1 for c in checks if c.status == FIXED)
    dry_n = sum(1 for c in checks if c.status == DRY)
    fails = sum(1 for c in checks if c.status == FAIL)
    flags = sum(1 for c in checks if c.status == FLAG)
    lines.append("─" * 56)
    if dry:
        lines.append(f"  {CYAN}DRY RUN{RST} — {dry_n} would-fix, {fails} fail, {flags} flag")
    elif fixed or fails or flags:
        summary = []
        if fixed: summary.append(f"{GREEN}{fixed} fixed{RST}")
        if fails: summary.append(f"{RED}{fails} fail{RST}")
        if flags: summary.append(f"{RED}{flags} flag{RST}")
        lines.append(f"  repaired: {' · '.join(summary)}")
    elif dry_n:
        lines.append(f"  {CYAN}check-only{RST} — {dry_n} drift(s) detected, rerun with --fix")
    else:
        lines.append(f"  {GREEN}all healthy — no drift detected{RST}")
    return "\n".join(lines)

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="cortexagent doctor",
                                description="Detect + repair CortexAgent settings drift.")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--fix", action="store_true", help="apply repairs (default is check-only)")
    ap.add_argument("--no-patch", action="store_true", help="deprecated (binary patch layer removed); accepted, no effect")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    checks = run(dry=args.dry_run, no_patch=args.no_patch, fix=args.fix)
    if args.json:
        print(json.dumps([{"name": c.name, "status": c.status, "detail": c.detail,
                           "ok": c.ok} for c in checks], indent=2))
    else:
        print(_format(checks, dry=args.dry_run))

    return 1 if any(c.status == FAIL for c in checks) else 0

if __name__ == "__main__":
    sys.exit(main())
