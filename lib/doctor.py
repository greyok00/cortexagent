#!/usr/bin/env python3
"""lib/doctor.py — `cortexagent doctor`: detect + repair Claude Code settings drift.

Claude Code can mutate its own settings across runs (statusLine, hooks,
claudeMdExcludes, welcome chrome, even the onboarding banner strings in the
binary). This doctor re-asserts the **CortexAgent custom** versions of every
Claude-facing setting, rendered fresh from the repo templates that
``install.sh`` / ``bin/cortexagent`` already use — so the source of truth is
one place, not three.

What it repairs (idempotent — re-running is a no-op when everything matches):
  1. Isolated config dir exists (``$CORTEXAGENT_CONFIG_DIR`` / ~/.cortexagent-config).
  2. ``CLAUDE.md`` in the config dir == repo ``config/CLAUDE.md`` (byte compare);
     on drift → backup + copy + re-lock (chmod 444 / chattr +i) so Claude can't
     re-edit it.
  3. ``settings.json`` in the config dir == rendered template ({{HOME}}→$HOME);
     on drift → backup + re-render. Verifies the key custom fields:
     quiet, spinnerTipsEnabled=false, claudeMdExcludes the global CLAUDE.md,
     statusLine → our lib/statusline.py, the 3 hooks (SessionStart /
     UserPromptSubmit / Stop).
  4. ``mcp.json`` in the config dir has the cortexagent server (or is correctly
     skipped when the MCP script is absent); on drift → backup + re-render.
  5. The ``claude`` binary banner/tips patch (``lib/patch_binary.py``) — re-applies
     if ``--check`` says NOT PATCHED. Opt out with --no-patch or
     ``CORTEXAGENT_PATCH_BINARY=0``.
  6. The ``assets/cortexagentsquarelogo.jpg`` asset exists (tray + webui need it).
  7. (report-only) ``bin/cortexagent`` still has the env wiring the brand depends
     on (IS_DEMO, ALT_SCREEN, banner call, MCP guard). The doctor does NOT
     rewrite repo source — it flags tampering so a human re-runs install.

Non-destructive: every overwritten live file is copied to ``<name>.doctor.bak``
first. NEVER touches the user's global ``~/.claude/CLAUDE.md``, memory DBs,
or any PII — only the isolated CortexAgent config dir + the claude binary.

CLI:
  python3 -m lib.doctor             # check + repair, print a table
  python3 -m lib.doctor --dry-run   # report only, no writes
  python3 -m lib.doctor --json      # machine-readable
  python3 -m lib.doctor --no-patch  # skip the claude binary patch step
"""
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

# ── Colors (best-effort) ──────────────────────────────────────────────────────
if sys.stderr.isatty():
    CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
        "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
else:
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""

# Statuses for a check.
HEALTHY = "healthy"      # was correct, nothing done
FIXED = "fixed"          # was drifted, repaired
DRY = "would-fix"        # --dry-run: drifted, would repair
FLAG = "flag"            # report-only tamper detection (not auto-fixed)
FAIL = "fail"           # couldn't repair (e.g. patch failed)


class Check:
    __slots__ = ("name", "status", "detail")

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name, self.status, self.detail = name, status, detail

    @property
    def ok(self) -> bool:
        return self.status in (HEALTHY, FIXED, DRY, FLAG)


# ── helpers ──────────────────────────────────────────────────────────────────
def _bak(path: Path) -> Path:
    """Copy path → path.doctor.bak (timestamped) before overwriting. No-op if missing."""
    if not path.exists():
        return path
    bak = path.with_suffix(path.suffix + f".doctor.bak.{int(time.time())}")
    try:
        shutil.copy2(path, bak)
    except Exception:
        pass
    return bak


def _same(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()
    except Exception:
        return False


def _render_settings(home: str) -> str:
    tpl = (_REPO_ROOT / "config" / "settings.json.template").read_text()
    return tpl.replace("{{HOME}}", home)


def _render_mcp(memory_cmd: str, fire_enabled: str, brave_enabled: str) -> tuple[str, bool]:
    """Return (mcp_json_str, has_cortexagent). Mirrors bin/cortexagent's block."""
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
        servers["playwright_brave"] = {
            "command": f"{venv_py} {os.path.join(str(_REPO_ROOT), 'lib', 'playwright_brave_mcp.py')}"}
    lazy = os.path.expanduser("~/.cortexagent/config/lazy_mcp_servers.json")
    if os.path.exists(lazy):
        try:
            for entry in json.load(open(lazy)):
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


# ── checks ───────────────────────────────────────────────────────────────────
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


def _check_claude_md(cfg_dir: Path, dry: bool) -> Check:
    src = _REPO_ROOT / "config" / "CLAUDE.md"
    dst = cfg_dir / "CLAUDE.md"
    if not src.exists():
        return Check("CLAUDE.md (isolated)", FAIL, "repo config/CLAUDE.md missing")
    if _same(src, dst):
        return Check("CLAUDE.md (isolated)", HEALTHY, "matches repo template")
    if dry:
        return Check("CLAUDE.md (isolated)", DRY, "would overwrite drifted CLAUDE.md")
    _bak(dst)
    shutil.copy2(src, dst)
    # Re-lock so Claude can't edit it (best-effort; chattr needs sudo/cap).
    try:
        subprocess.run(["chattr", "+i", str(dst)], capture_output=True, timeout=3)
    except Exception:
        pass
    try:
        os.chmod(dst, 0o444)
    except Exception:
        pass
    return Check("CLAUDE.md (isolated)", FIXED, "restored + re-locked (chmod 444)")


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
    # Field-level report even when we're going to repair.
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
    # --check prints "Status: PATCHED"/"NOT PATCHED"/"UNKNOWN".
    r = subprocess.run([sys.executable, str(pb), "--check"],
                       capture_output=True, text=True, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if "Status: PATCHED" in out:
        return Check("claude binary patch", HEALTHY, "banner/tips hidden")
    if dry:
        return Check("claude binary patch", DRY, "would patch (banner/tips)")
    pr = subprocess.run([sys.executable, str(pb)], capture_output=True, text=True, timeout=60)
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
    """Report-only: bin/cortexagent still has the brand env wiring. Not auto-fixed
    (it's repo source) — flags tampering so a human re-runs install."""
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


# ── runner ───────────────────────────────────────────────────────────────────
def run(dry: bool = False, no_patch: bool = False) -> list[Check]:
    cfg_dir = Path(os.environ.get("CORTEXAGENT_CONFIG_DIR", str(Path.home() / ".cortexagent-config")))
    home = str(Path.home())
    memory_cmd = f"python3 {_REPO_ROOT}/memory/mcp_server.py"
    brave = os.environ.get("CORTEXAGENT_BRAVE_ENABLED", "0")
    fire_enabled = os.environ.get("CORTEXAGENT_FIRECRAWL_ENABLED", "0")
    checks: list[Check] = []
    checks.append(_check_config_dir(cfg_dir, dry))
    checks.append(_check_claude_md(cfg_dir, dry))
    checks.append(_check_settings(cfg_dir, home, dry))
    checks.append(_check_mcp(cfg_dir, memory_cmd, fire_enabled, brave, dry))
    checks.append(_check_binary_patch(no_patch, dry))
    checks.append(_check_asset())
    checks.append(_check_launcher_wiring())
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
    # Exit non-zero only on real failures (not dry/flag — those are informational).
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())