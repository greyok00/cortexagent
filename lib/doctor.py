#!/usr/bin/env python3

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

from lib.config import CFG  # noqa: F401,E402  (config dir resolution kept consistent with CFG defaults)


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
    return bak




def _render_settings(home: str) -> str:
    tpl = (_REPO_ROOT / "config" / "settings.json.template").read_text()
    return tpl.replace("{{HOME}}", home)


def _render_mcp(memory_cmd: str, fire_enabled: str, brave_enabled: str) -> tuple[str, bool]:

    servers: dict = {}
    mem_script = memory_cmd.split()[-1] if memory_cmd else ""
    has_cortexagent = bool(mem_script) and os.path.exists(mem_script)
    if has_cortexagent:
        servers["cortexagent"] = {"command": memory_cmd}
    if fire_enabled == "1":
        servers["firecrawl"] = {
            "command": f"python3 {os.path.join(str(_REPO_ROOT), 'lib', 'firecrawl_proxy.py')}"}
    if brave_enabled == "1":
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
    if cfg_dir.exists():
        return Check("config dir exists", HEALTHY, str(cfg_dir))
    if dry:
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
    for key in ("quiet", "spinnerTipsEnabled", "claudeMdExcludes", "statusLine", "hooks"):
        if have_obj and have_obj.get(key) != want_obj.get(key):
            drifted.append(key)
    drift_str = ("drifted: " + ",".join(drifted)) if drifted else "structure changed"
    if dry:
        return Check("settings.json", DRY, f"would re-render ({drift_str})")
    _bak(dst)
    dst.write_text(want)
    return Check("settings.json", FIXED, drift_str)


def _check_mcp(cfg_dir: Path, memory_cmd: str, fire: str, brave: str, dry: bool) -> Check:
    dst = cfg_dir / "mcp.json"
    want, has_ca = _render_mcp(memory_cmd, fire, brave)
    if dst.exists() and dst.read_text() == want:
        return Check("mcp.json", HEALTHY,
                     "cortexagent present" if has_ca else "cortexagent correctly absent")
    if dry:
        return Check("mcp.json", DRY, "would re-render")
    _bak(dst)
    dst.write_text(want)
    return Check("mcp.json", FIXED, "re-rendered" + ("" if has_ca else " (cortexagent absent — MCP script missing)"))


def _check_binary_patch(no_patch: bool, dry: bool) -> Check:
    if no_patch or os.environ.get("CORTEXAGENT_PATCH_BINARY", "1") == "0":
        return Check("claude binary patch", FLAG, "skipped (--no-patch / CORTEXAGENT_PATCH_BINARY=0)")
    pb = _REPO_ROOT / "lib" / "patch_binary.py"
    if not pb.exists():
        return Check("claude binary patch", FAIL, "lib/patch_binary.py missing")

    try:
        r = subprocess.run([sys.executable, str(pb), "--check"],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return Check("claude binary patch", FAIL, "patch --check timed out (15s)")
    out = (r.stdout + r.stderr).strip()
    if "Status: PATCHED" in out:
        return Check("claude binary patch", HEALTHY, "banner/tips hidden")
    if dry:
        return Check("claude binary patch", DRY, "would patch (banner/tips)")
    try:
        pr = subprocess.run([sys.executable, str(pb)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return Check("claude binary patch", FAIL, "patch timed out (60s)")
    if pr.returncode == 0:
        return Check("claude binary patch", FIXED, "banner/tips hidden")
    return Check("claude binary patch", FAIL,
                 f"patch failed rc={pr.returncode}: {pr.stderr[-160:]}")


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


def _check_model_conf_lock(dry: bool) -> Check:

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
    detail = f"chmod 444 (now {mode})" + (f"; DRIFT: {drift}" if drift else "")
    if dry:
        return Check("model conf lock", DRY, "would " + detail)
    try:
        os.chmod(conf, 0o444)
    except Exception as e:
        return Check("model conf lock", FAIL, f"chmod failed: {e}")
    try:
        subprocess.run(["chattr", "+i", str(conf)], capture_output=True, timeout=3)
    except Exception:
        pass
    return Check("model conf lock", FIXED, "chmod 444 applied" +
                  (f" (DRIFT remains: {drift})" if drift else ""))



def run(dry: bool = False, no_patch: bool = False) -> list[Check]:
    cfg_dir = Path(os.environ.get("CORTEXAGENT_CONFIG_DIR", str(Path.home() / ".cortexagent-config")))
    home = str(Path.home())
    memory_cmd = f"python3 {_REPO_ROOT}/memory/mcp_server.py"
    brave = os.environ.get("CORTEXAGENT_BRAVE_ENABLED", "0")
    fire_enabled = os.environ.get("CORTEXAGENT_FIRECRAWL_ENABLED", "0")
    checks: list[Check] = []
    checks.append(_check_config_dir(cfg_dir, dry))
    checks.append(_check_profile_at_runtime())
    checks.append(_check_settings(cfg_dir, home, dry))
    checks.append(_check_mcp(cfg_dir, memory_cmd, fire_enabled, brave, dry))
    checks.append(_check_binary_patch(no_patch, dry))
    checks.append(_check_asset())
    checks.append(_check_launcher_wiring())
    checks.append(_check_model_conf_lock(dry))
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
    else:
        lines.append(f"  {GREEN}all healthy — no drift detected{RST}")
    return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="cortexagent doctor",
                                description="Detect + repair Claude Code settings drift.")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--no-patch", action="store_true", help="skip the claude binary patch step")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    checks = run(dry=args.dry_run, no_patch=args.no_patch)
    if args.json:
        print(json.dumps([{"name": c.name, "status": c.status, "detail": c.detail,
                           "ok": c.ok} for c in checks], indent=2))
    else:
        print(_format(checks, dry=args.dry_run))

    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())