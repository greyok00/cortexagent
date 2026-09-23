#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import control
from lib.config import CFG

if sys.stderr.isatty():
    CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
        "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
else:
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""

def _err(msg: str) -> None:
    print(f"{RED}✗ {msg}{RST}", file=sys.stderr)

def _need_daemon() -> bool:

    if not control.daemon_present(timeout=2):
        _err("daemon not running — start it with `cortexagent daemon start`")
        return False
    return True

def _print_status(prefetched: "dict | None" = None) -> int:
    s = prefetched
    if s is None:
        try:
            s = control.send_request("status", timeout=5)
        except Exception as e:
            _err(f"daemon unreachable: {e}")
            return 1
    if not s or not s.get("ok"):
        _err(f"status error: {s}")
        return 1
    print(f"{BOLD}CortexAgent status{RST}")
    print("  lanes : slimtoken :11435/:11436 → ollama :11600")
    print(f"  sessions: {s['active_sessions']}  idle: {s['idle_sec'] or 0}s")
    return 0

def cmd_daemon(args) -> int:

    action = args.action
    if action == "status":

        try:
            s = control.send_request("status", timeout=5)
        except Exception:
            s = None
        if not s or not s.get("ok"):
            print(f"{DIM}daemon not running{RST}  ({CFG.control_socket})")
            print(f"  start with: {BOLD}cortexagent daemon start{RST}")
            return 1
        return _print_status(s)
    return _run_module_main("lib.daemon", [action])

def _run_module_main(mod: str, argv: list) -> int:

    import importlib
    m = importlib.import_module(mod)

    old = sys.argv
    sys.argv = [mod] + argv
    try:
        rc = m.main() if hasattr(m, "main") else 1
    finally:
        sys.argv = old
    return int(rc or 0)

def cmd_status(args) -> int:
    if not control.daemon_present(timeout=2):
        print(f"{RED}● daemon down{RST}  socket: {CFG.control_socket}")
        print(f"  {DIM}start: cortexagent daemon start{RST}")
        return 1
    return _print_status()

def cmd_queue(args) -> int:

    from lib import prompt_queue as pq
    action = args.action
    if action == "list":
        items = pq.list_items()
        if not items:
            print(f"{DIM}(queue empty){RST}")
            return 0
        icons = {"queued": "⏳", "active": "▶️", "done": "✅",
                 "superseded": "↩️", "dropped": "🗑️"}
        for it in items:
            print(f"  {icons.get(it.status, '·')} {it.id} [{it.status}] {it.text[:80]}")
        return 0
    if action == "context":
        ctx = pq.agenda_context()
        print(ctx if ctx else f"{DIM}(queue empty){RST}")
        return 0
    if action == "clear":
        n = pq.clear()
        print(f"{GREEN}cleared {n} items{RST}")
        return 0
    if action == "done":
        if not args.item_id:
            _err("done requires an item id: cortexagent queue done Q-001")
            return 2
        ok = pq.mark_done(args.item_id)
        print(f"{GREEN}done{RST}" if ok else f"{RED}no such item: {args.item_id}{RST}")
        return 0 if ok else 1
    if action == "drop":
        if not args.item_id:
            _err("drop requires an item id: cortexagent queue drop Q-001")
            return 2
        ok = pq.drop(args.item_id)
        print(f"{YELLOW}dropped{RST}" if ok else f"{RED}no such item: {args.item_id}{RST}")
        return 0 if ok else 1
    _err(f"unknown queue action: {action}")
    return 2

def cmd_doctor(args) -> int:

    from lib import doctor
    checks = doctor.run(dry=args.dry_run, no_patch=args.no_patch)
    if args.json:
        import json as _json
        print(_json.dumps([{"name": c.name, "status": c.status, "detail": c.detail,
                            "ok": c.ok} for c in checks], indent=2))
    else:
        print(doctor._format(checks, dry=args.dry_run))
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0

def cmd_install(args) -> int:

    plat = os.uname().sysname if hasattr(os, "uname") else os.name
    if plat in ("Linux", "Darwin") or plat == "posix":
        installer = _REPO_ROOT / "install.sh"
        if not installer.exists():
            _err(f"installer not found: {installer}")
            return 1
        print(f"{CYAN}running {installer}…{RST}")
        return subprocess.call(["bash", str(installer), *args.install_args])

    print(f"{YELLOW}Windows install (manual):{RST}")
    print(f"  1. Ensure Python 3.10+ is on PATH.")
    print(f"  2. Copy {CFG.config_dir} templates into %APPDATA%\\cortexagent-config")
    print(f"  3. Register the daemon as a service:")
    print(f"     sc create cortexagent binPath= \"python {_REPO_ROOT}\\lib\\daemon.py run\"")
    print(f"  4. Symlink/alias: cortexagent -> python {_REPO_ROOT}\\engine\\cli.py")
    print(f"  ({DIM}a native Windows installer is a later pass{RST})")
    return 0

def cmd_run(args) -> int:
    launcher = _REPO_ROOT / "bin" / "cortexagent"
    if not launcher.exists():
        _err(f"launcher not found: {launcher}")
        return 1
    pass_through = list(args.run_args)

    return subprocess.call(["bash", str(launcher), *pass_through])

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cortexagent",
        description="CortexAgent — local coding agent on llama.cpp (no cloud).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    dp = sub.add_parser("daemon", help="start/stop/status the persistent backend daemon")
    dp.add_argument("action", choices=["start", "stop", "status", "run"])
    dp.set_defaults(func=cmd_daemon)

    sp = sub.add_parser("status", help="one-shot daemon + session status")
    sp.set_defaults(func=cmd_status)

    qp = sub.add_parser("queue", help="manage the prompt queue (list/clear/done/drop/context)")
    qp.add_argument("action", choices=["list", "clear", "done", "drop", "context"])
    qp.add_argument("item_id", nargs="?", default=None, help="item id for done/drop")
    qp.set_defaults(func=cmd_queue)

    ip = sub.add_parser("install", help="OS-aware install (systemd unit / service)")
    ip.add_argument("install_args", nargs=argparse.REMAINDER)
    ip.set_defaults(func=cmd_install)

    docp = sub.add_parser("doctor", help="detect + repair Claude Code settings drift")
    docp.add_argument("--dry-run", action="store_true", help="report only, no writes")
    docp.add_argument("--no-patch", action="store_true",
                     help="skip the claude binary banner/tips patch step")
    docp.add_argument("--json", action="store_true", help="machine-readable output")
    docp.set_defaults(func=cmd_doctor)

    rp = sub.add_parser("run", help="run the agent (default; passes args to the launcher)")
    rp.add_argument("run_args", nargs=argparse.REMAINDER)
    rp.set_defaults(func=cmd_run)

    return p

_LAUNCHER_SUBCOMMANDS = ("daemon", "status", "queue",
                         "install", "doctor", "run")

def _passthrough(argv) -> int:
    launcher = _REPO_ROOT / "bin" / "cortexagent"
    if not launcher.exists():
        _err(f"launcher not found: {launcher}")
        return 1
    return subprocess.call(["bash", str(launcher), *argv])

def main() -> int:
    parser = _build_parser()
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0
    if argv and argv[0] not in _LAUNCHER_SUBCOMMANDS:
        return _passthrough(argv)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return _passthrough(argv)
    return int(args.func(args) or 0)

if __name__ == "__main__":
    sys.exit(main())
