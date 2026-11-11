#!/usr/bin/env python3
"""patchright_headless.py - THE launcher for a greysearch task-slot browser.

One process = ONE patchright-launched STEALTH Chromium, headless, with a
persistent per-slot profile, exposing a CDP HTTP endpoint on the slot port so
every driver in this session (MCP, bridge, fallback lane) attaches to the
same browser via connect_over_cdp. The parent (browser_ports.ensure) starts
this detached and probes the port until /json/version answers; this process
stays alive for the life of the browser - nothing here ever closes it.

Default headless (standing browser rule); --headful exists ONLY as an
explicit opt-in for sites that hard-fail headless.

CAPTCHA SOLVER, NOW LOCAL: the launcher loads NOTHING at launch time - no
third-party solve addon rides the chromium argv, and the retired loader and
key-seed surface is gone from this module entirely; the vendored extension
assets are purged from the repository too, which is what closed the
2026-11-05 audit finding. Solving is local and lives in captcha_solve.py (the rung ladder:
an already-resident model, a vendored CPU classifier, a gpu rung only when
explicitly allowed) behind the ONE knob, GREYSEARCH_CAPTCHA_SOLVER. The
detached launch path (browser_ports.ensure) forwards GREYSEARCH_* env vars
to this launcher so the knob resolves in the same process that launches
chromium, and the ready line answers with captcha_solver=local when the
knob allows solving (captcha_solve.solver_enabled) or off when the knob is
switched off. The WAIT behavior feeding that solver lives in
browser_session (GREYSEARCH_CAPTCHA_WAIT_S, GREYSEARCH_CAPTCHA_POLL_S):
launching the launcher never loops; the bounded wait does.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--headful", action="store_true",
                    help="explicit opt-in; default is headless")
    a = ap.parse_args()
    try:
        from patchright.sync_api import sync_playwright
    except Exception as e:
        print(f"patchright unavailable: {e}", file=sys.stderr)
        return 2

    profile = Path(a.profile).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    argv = [
        f"--remote-debugging-port={a.port}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--no-pings",
        "--disable-crash-reporter",
        "--disable-component-update",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-domain-reliability",
        "--disable-features=OptimizationHints,MediaRouter,Translate,OptimizationGuideFetchingForDesktop",
    ]
    pw = sync_playwright().start()
    launch_opts = dict(
        user_data_dir=str(profile),
        headless=not a.headful,
        viewport={"width": 1400, "height": 1000},
        java_script_enabled=True,
        locale="en-US",
        timezone_id="America/Phoenix",
        args=argv,
    )
    import captcha_solve as _cs
    solver = "local" if _cs.solver_enabled() else "off"
    try:
        pw.chromium.launch_persistent_context(channel="chromium",
                                              **launch_opts)
    except Exception:
        try:
            pw.chromium.launch_persistent_context(
                **{**launch_opts,
                   "args": launch_opts["args"] + ["--headless=new"]})
        except Exception as e:
            print(f"launch failed: {e}", file=sys.stderr)
            return 3

    print(f"greysearch slot browser ready: port={a.port} "
          f"profile={profile} headless={not a.headful} "
          f"captcha_solver={solver}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0

if __name__ == "__main__":
    sys.exit(main())