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

from lib import control  # noqa: E402
from lib.config import CFG  # noqa: E402


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
    big, prox = s["big"], s["proxy"]
    print(f"{BOLD}CortexAgent models{RST}")
    print(f"  big  :{big['port']}  {'🟢 healthy' if big['healthy'] else '🔴 down'}  (running={big['running']})")
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
        seq = ["big"]
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

        return _models_swap(which, ctx=args.ctx, ngl=args.ngl)
    if action == "load":

        if getattr(args, "model", None):
            return _models_swap(args.model, ctx=args.ctx, ngl=args.ngl)
        return _models_load(which)
    if action == "unload":
        return _models_unload(which)
    if action == "reload":
        return _models_reload(which)
    _err(f"unknown models action: {action}")
    return 2



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
        return _models_status(s)
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
    return _models_status()



def cmd_minify(args) -> int:

    import json
    try:
        p = Path.home() / ".cortexagent" / "minify_stats.json"
        if not p.exists():
            print("Minify: no data yet (proxy hasn't served a minified request)")
            return 0
        snap = json.loads(p.read_text() or "{}")
    except Exception as e:
        _err(f"minify: failed to read snapshot: {e}")
        return 1
    if not isinstance(snap, dict) or not snap:
        print("Minify: snapshot empty")
        return 0
    runs = int(snap.get("runs", 0) or 0)
    tin = int(snap.get("tokens_in", 0) or 0)
    tout = int(snap.get("tokens_out", 0) or 0)
    saved = int(snap.get("tokens_saved", 0) or 0)
    ratio = float(snap.get("ratio_pct", 0.0) or 0.0)
    last_pct = float(snap.get("last_saved_pct", 0.0) or 0.0)
    print(f"  Minify: {runs} run(s)")
    print(f"    tokens in:    {tin:,}")
    print(f"    tokens out:   {tout:,}")
    print(f"    tokens saved: {saved:,}  ({ratio:.1f}%)")
    print(f"    last run:     {last_pct:.1f}% saved")
    history = snap.get("history_60s") or []
    if history:

        n_buckets = 12
        bucket_size = max(1, len(history) // n_buckets)
        buckets = []
        for i in range(0, len(history), bucket_size):
            chunk = history[i:i + bucket_size]
            if not chunk:
                continue
            buckets.append(sum(v for _, v in chunk) / len(chunk))
        bars = "▁▂▃▄▅▆▇█"
        spark = "".join(
            bars[min(len(bars) - 1, int((b or 0) / 12.5))]
            for b in buckets
        )
        print(f"    60s trend:    {spark}")
    return 0


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



def cmd_tray(args) -> int:

    from lib import tray
    if getattr(args, "check", False):
        return tray.check()
    return tray.run(force_headless=getattr(args, "headless", False))



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
    print(f"  1. Ensure Python 3.10+ and llama-server are on PATH.")
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
    pass_through = [a for a in args.run_args if a not in ("--list-models",)]

    return subprocess.call(["bash", str(launcher), *pass_through])



def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cortexagent",
        description="CortexAgent — local coding agent on llama.cpp (no cloud).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")


    mp = sub.add_parser(
        "models", help="manage model backends via the daemon (status/load/unload/reload/swap)")
    mp.add_argument("action", choices=["status", "load", "unload", "reload", "swap"])
    mp.add_argument("which", nargs="?", default="big",
                    help="which model (big|all) — or the model path for 'swap'")
    mp.add_argument("--model", dest="model", default=None,
                    help="load an arbitrary model into the big slot (hot-swap by type)")
    mp.add_argument("--ctx", type=int, default=8192, help="context size for a swapped model")
    mp.add_argument("--ngl", type=int, default=999, help="GPU layers for a swapped model")
    mp.set_defaults(func=cmd_models)


    dp = sub.add_parser("daemon", help="start/stop/status the persistent backend daemon")
    dp.add_argument("action", choices=["start", "stop", "status", "run"])
    dp.set_defaults(func=cmd_daemon)


    sp = sub.add_parser("status", help="one-shot daemon + model status")
    sp.set_defaults(func=cmd_status)


    qp = sub.add_parser("queue", help="manage the prompt queue (list/clear/done/drop/context)")
    qp.add_argument("action", choices=["list", "clear", "done", "drop", "context"])
    qp.add_argument("item_id", nargs="?", default=None, help="item id for done/drop")
    qp.set_defaults(func=cmd_queue)


    mp2 = sub.add_parser("minify", help="proxy minify stats (savings, runs, history)")
    mp2.add_argument("action", nargs="?", default="status",
                     choices=["status"], help="what to show (default: status)")
    mp2.set_defaults(func=cmd_minify)


    tp = sub.add_parser("tray", help="run the system-tray app (owns the overseer)")
    tp.add_argument("--headless", action="store_true",
                    help="force headless keeper mode (no GUI / no pystray needed)")
    tp.add_argument("--check", action="store_true", help="report tray deps + exit")
    tp.set_defaults(func=cmd_tray)


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


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):


        launcher = _REPO_ROOT / "bin" / "cortexagent"
        if not launcher.exists():
            _err(f"launcher not found: {launcher}")
            return 1
        return subprocess.call(["bash", str(launcher), *sys.argv[1:]])
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())