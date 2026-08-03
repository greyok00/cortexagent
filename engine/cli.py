#!/usr/bin/env python3
"""engine/cli.py — the unified CortexAgent CLI dispatcher.

This is the single cross-platform entry point (the thing a future Nuitka pass
compiles). It owns the *control plane* — everything that talks to the persistent
daemon over the AF_UNIX control socket — and delegates the *data plane* (running
the agent with all env/hooks/memory wiring) to the proven ``bin/cortexagent``
bash launcher.

Subcommands
-----------
  cortexagent                       run the agent (default → bin/cortexagent)
  cortexagent run [args...]         same, explicit
  cortexagent models status         show big/tiny/proxy state
  cortexagent models load   big|tiny|all
  cortexagent models unload big|tiny|all
  cortexagent models reload big|tiny|all    unload then load
  cortexagent daemon status        daemon health (alias of `models status` + more)
  cortexagent daemon start         fork the daemon to background
  cortexagent daemon stop          graceful shutdown via socket
  cortexagent daemon run            foreground (systemd ExecStart)
  cortexagent install              OS-aware install (systemd unit / service)
  cortexagent status               one-shot: daemon up? models? ports?

Design notes
------------
- ``run`` execs ``bin/cortexagent`` so the full session env (isolated config dir,
  memory injection, hooks, banner, VRAM lifecycle) stays in one proven place.
- ``models`` / ``daemon`` use ``lib.control.send_request`` → the daemon's control
  socket. If the daemon is down, ``models load`` can't run (it needs the daemon);
  ``daemon start`` brings it up.
- No Ollama, no hardcoded home paths — all via ``lib.config.CFG``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import control  # noqa: E402
from lib.config import CFG  # noqa: E402

# ── Colors (best-effort; degrade if not a tty) ───────────────────────────────
if sys.stderr.isatty():
    CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
        "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
else:
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""


def _err(msg: str) -> None:
    print(f"{RED}✗ {msg}{RST}", file=sys.stderr)


def _need_daemon() -> bool:
    """Refuse control commands if the daemon isn't up. Returns True if up."""
    if not control.daemon_present(timeout=2):
        _err("daemon not running — start it with `cortexagent daemon start`")
        return False
    return True


# ── models ────────────────────────────────────────────────────────────────────
def _models_status(prefetched: "dict | None" = None) -> int:
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
    big, tiny, prox = s["big"], s["tiny"], s["proxy"]
    print(f"{BOLD}CortexAgent models{RST}")
    print(f"  big  :{big['port']}  {'🟢 healthy' if big['healthy'] else '🔴 down'}  (running={big['running']})")
    print(f"  tiny :{tiny['port']}  {'🟢 healthy' if tiny['healthy'] else '🔴 down'}  (running={tiny['running']})")
    print(f"  proxy: {'🟢 up' if prox['running'] else '🔴 down'}")
    print(f"  sessions: {s['active_sessions']}  idle: {s['idle_sec'] or 0}s / {s['idle_unload_sec']}s")
    return 0


def _models_load(which: str) -> int:
    if not _need_daemon():
        return 1
    print(f"{CYAN}loading {which}…{RST}")
    try:
        r = control.send_request("load", which=which, timeout=300)
    except Exception as e:
        _err(f"load failed: {e}")
        return 1
    if r.get("ok"):
        print(f"{GREEN}✓ {which} loaded{RST}")
        return 0
    _err(f"load failed: {r}")
    return 1


def _models_unload(which: str) -> int:
    if not _need_daemon():
        return 1
    print(f"{YELLOW}unloading {which} (freeing VRAM)…{RST}")
    try:
        r = control.send_request("unload", which=which, timeout=30)
    except Exception as e:
        _err(f"unload failed: {e}")
        return 1
    if r.get("ok"):
        print(f"{GREEN}✓ {which} unloaded{RST}")
        return 0
    _err(f"unload failed: {r}")
    return 1


def _models_reload(which: str) -> int:
    if which == "all":
        seq = ["big", "tiny"]
    else:
        seq = [which]
    rc = 0
    for w in seq:
        if _models_unload(w) != 0:
            rc = 1
        if _models_load(w) != 0:
            rc = 1
    return rc


def _models_swap(model_path: str, ctx: int = 8192, ngl: int = 999) -> int:
    """Hot-swap an arbitrary model into the main slot via the daemon."""
    if not model_path:
        _err("swap requires a model path: cortexagent models swap /path/to/model.gguf")
        return 2
    if not _need_daemon():
        return 1
    p = Path(model_path).expanduser()
    if not p.exists():
        _err(f"model not found: {p}")
        return 1
    print(f"{CYAN}hot-swapping {p.name} into the main slot (:{CFG.big_model_port})…{RST}")
    try:
        r = control.send_request("swap", model=str(p), ctx=ctx, ngl=ngl, timeout=300)
    except Exception as e:
        _err(f"swap failed: {e}")
        return 1
    if r.get("ok"):
        print(f"{GREEN}✓ {p.name} loaded{RST}  (model={r.get('model')})")
        return 0
    _err(f"swap failed: {r}")
    return 1


def cmd_models(args) -> int:
    action = args.action
    which = args.which
    if action == "status":
        return _models_status()
    if action == "swap":
        # `which` holds the model path for the swap action.
        return _models_swap(which, ctx=args.ctx, ngl=args.ngl)
    if action == "load":
        # `--model PATH` turns a load into a hot-swap into the big slot.
        if getattr(args, "model", None):
            return _models_swap(args.model, ctx=args.ctx, ngl=args.ngl)
        return _models_load(which)
    if action == "unload":
        return _models_unload(which)
    if action == "reload":
        return _models_reload(which)
    _err(f"unknown models action: {action}")
    return 2


# ── daemon ───────────────────────────────────────────────────────────────────
def cmd_daemon(args) -> int:
    # Delegate to lib/daemon.py's own CLI (run/start/stop/status) — single
    # implementation, no duplication.
    action = args.action
    if action == "status":
        # Liveness via the same send_request("status") path as `models status`
        # — a successful reply IS the proof the daemon is up. The old
        # daemon_present(timeout=2) ping gate was flaky under load and
        # spuriously reported "not running" (smoke: cli routing).
        try:
            s = control.send_request("status", timeout=5)
        except Exception:
            s = None
        if not s or not s.get("ok"):
            print(f"{DIM}daemon not running{RST}  ({CFG.control_socket})")
            print(f"  start with: {BOLD}cortexagent daemon start{RST}")
            return 1
        return _models_status(s)
    return _run_module_main("lib.daemon", [action])


def _run_module_main(mod: str, argv: list) -> int:
    """Run a library module's __main__ in-process (preserves import side effects)."""
    import importlib
    m = importlib.import_module(mod)
    # Save/restore argv so the module's argparse sees the subcommand only.
    old = sys.argv
    sys.argv = [mod] + argv
    try:
        rc = m.main() if hasattr(m, "main") else 1
    finally:
        sys.argv = old
    return int(rc or 0)


# ── status (one-shot) ─────────────────────────────────────────────────────────
def cmd_status(args) -> int:
    if not control.daemon_present(timeout=2):
        print(f"{RED}● daemon down{RST}  socket: {CFG.control_socket}")
        print(f"  {DIM}start: cortexagent daemon start{RST}")
        return 1
    return _models_status()


# ── queue (prompt queue) ──────────────────────────────────────────────────────
def cmd_queue(args) -> int:
    """Manage the prompt queue (the default per-prompt agenda).

    The UserPromptSubmit hook enqueues every prompt automatically; this is the
    manual view/control surface.
    """
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


# ── tray (system-tray app) ────────────────────────────────────────────────────
def cmd_tray(args) -> int:
    """Run the system-tray app that owns the overseer.

    GUI (pystray + Pillow) if available, else headless keeper. The tray is a
    separate persistent process: closing the CLI does NOT kill the overseer;
    only quitting the tray does.
    """
    from lib import tray
    if getattr(args, "check", False):
        return tray.check()
    return tray.run(force_headless=getattr(args, "headless", False))


# ── doctor (settings drift repair) ────────────────────────────────────────────
def cmd_doctor(args) -> int:
    """Detect + repair Claude Code settings drift (re-assert CortexAgent customs)."""
    from lib import doctor
    checks = doctor.run(dry=args.dry_run, no_patch=args.no_patch)
    if args.json:
        import json as _json
        print(_json.dumps([{"name": c.name, "status": c.status, "detail": c.detail,
                            "ok": c.ok} for c in checks], indent=2))
    else:
        print(doctor._format(checks, dry=args.dry_run))
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0


# ── install ───────────────────────────────────────────────────────────────────
def cmd_install(args) -> int:
    """OS-aware install.

    Linux/macOS: delegates to install.sh (templates config, seeds memory,
    symlinks the CLI, installs the systemd user service on Linux).
    Windows: prints the manual Windows-Service steps (PowerShell stub — the
    bash installer doesn't run on Windows; a native installer is a later pass).
    """
    plat = os.uname().sysname if hasattr(os, "uname") else os.name
    if plat in ("Linux", "Darwin") or plat == "posix":
        installer = _REPO_ROOT / "install.sh"
        if not installer.exists():
            _err(f"installer not found: {installer}")
            return 1
        print(f"{CYAN}running {installer}…{RST}")
        return subprocess.call(["bash", str(installer), *args.install_args])
    # Windows / other — guide the user (native installer is a later pass).
    print(f"{YELLOW}Windows install (manual):{RST}")
    print(f"  1. Ensure Python 3.10+ and llama-server are on PATH.")
    print(f"  2. Copy {CFG.config_dir} templates into %APPDATA%\\cortexagent-config")
    print(f"  3. Register the daemon as a service:")
    print(f"     sc create cortexagent binPath= \"python {_REPO_ROOT}\\lib\\daemon.py run\"")
    print(f"  4. Symlink/alias: cortexagent -> python {_REPO_ROOT}\\engine\\cli.py")
    print(f"  ({DIM}a native Windows installer is a later pass{RST})")
    return 0


# ── run (default → bash launcher) ─────────────────────────────────────────────
def cmd_run(args) -> int:
    launcher = _REPO_ROOT / "bin" / "cortexagent"
    if not launcher.exists():
        _err(f"launcher not found: {launcher}")
        return 1
    pass_through = [a for a in args.run_args if a not in ("--list-models",)]
    # exec the bash launcher so it owns the full session lifecycle.
    return subprocess.call(["bash", str(launcher), *pass_through])


# ── argparse ─────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cortexagent",
        description="CortexAgent — local coding agent on llama.cpp (no cloud).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    # models
    mp = sub.add_parser(
        "models", help="manage model backends via the daemon (status/load/unload/reload/swap)")
    mp.add_argument("action", choices=["status", "load", "unload", "reload", "swap"])
    mp.add_argument("which", nargs="?", default="big",
                    help="which model (big|tiny|all) — or the model path for 'swap'")
    mp.add_argument("--model", dest="model", default=None,
                    help="load an arbitrary model into the big slot (hot-swap by type)")
    mp.add_argument("--ctx", type=int, default=8192, help="context size for a swapped model")
    mp.add_argument("--ngl", type=int, default=999, help="GPU layers for a swapped model")
    mp.set_defaults(func=cmd_models)

    # daemon
    dp = sub.add_parser("daemon", help="start/stop/status the persistent backend daemon")
    dp.add_argument("action", choices=["start", "stop", "status", "run"])
    dp.set_defaults(func=cmd_daemon)

    # status (one-shot)
    sp = sub.add_parser("status", help="one-shot daemon + model status")
    sp.set_defaults(func=cmd_status)

    # queue (prompt queue — the default per-prompt agenda)
    qp = sub.add_parser("queue", help="manage the prompt queue (list/clear/done/drop/context)")
    qp.add_argument("action", choices=["list", "clear", "done", "drop", "context"])
    qp.add_argument("item_id", nargs="?", default=None, help="item id for done/drop")
    qp.set_defaults(func=cmd_queue)

    # tray (system-tray app that owns the overseer — CLI close ≠ kill overseer)
    tp = sub.add_parser("tray", help="run the system-tray app (owns the overseer)")
    tp.add_argument("--headless", action="store_true",
                    help="force headless keeper mode (no GUI / no pystray needed)")
    tp.add_argument("--check", action="store_true", help="report tray deps + exit")
    tp.set_defaults(func=cmd_tray)

    # install
    ip = sub.add_parser("install", help="OS-aware install (systemd unit / service)")
    ip.add_argument("install_args", nargs=argparse.REMAINDER)
    ip.set_defaults(func=cmd_install)

    # doctor (settings drift repair)
    docp = sub.add_parser("doctor", help="detect + repair Claude Code settings drift")
    docp.add_argument("--dry-run", action="store_true", help="report only, no writes")
    docp.add_argument("--no-patch", action="store_true",
                     help="skip the claude binary banner/tips patch step")
    docp.add_argument("--json", action="store_true", help="machine-readable output")
    docp.set_defaults(func=cmd_doctor)

    # run (default)
    rp = sub.add_parser("run", help="run the agent (default; passes args to the launcher)")
    rp.add_argument("run_args", nargs=argparse.REMAINDER)
    rp.set_defaults(func=cmd_run)

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        # No subcommand → default to `run` with all remaining args (the agent
        # itself takes flags like -p, --model, etc.). Rebuild a run invocation.
        launcher = _REPO_ROOT / "bin" / "cortexagent"
        if not launcher.exists():
            _err(f"launcher not found: {launcher}")
            return 1
        return subprocess.call(["bash", str(launcher), *sys.argv[1:]])
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())