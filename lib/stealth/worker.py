#!/usr/bin/env python3
"""CortexAgent stealth browser worker.

Replaces the old `lib/browser_control.py` (Brave + page-level CDP) with a
Patchright + Chrome-channel stack that:

  * Patches CDP Runtime.enable leak at the binary level (anti-bot bypass)
  * Uses an isolated persistent profile (~/.config/chrome-stealth-profile/)
  * Spins up on demand via `google-chrome --remote-debugging-port=9223`
  * Lets multiple sub-agents share tabs through one persistent context
  * Applies the cortexagent/stealth init script (fingerprint spoof)
  * Adds anti-throttling flags so background tabs don't get suspended

This is intentionally separate from the main TUI / daemon so the user can
run an all-night clickworker / scraper on it without affecting the chat
session.

NOTE: as of 2026-08-28 the integration into CortexAgent's TUI/MCP is NOT
done yet — the user paused that work. Keep this file standalone and
expose only the simple `run / connect / shutdown` surface until the
integration lands.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

USER_DATA_DIR = Path.home() / ".config" / "chrome-stealth-profile"
CHROME_BIN = os.environ.get("CORTEX_STEALTH_CHROME", "/usr/bin/google-chrome")
CDP_PORT = int(os.environ.get("CORTEX_STEALTH_CDP_PORT", "9224"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

STEALTH_FLAGS = [
    # Anti-detection / automation flag stripping
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    # Background performance: keep tabs processing at full speed even when
    # the window is occluded or in the background
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    # Xvfb-friendly
    "--no-sandbox",
]

# Stealth init-script sources
from lib.stealth.seed import profile_seed  # noqa: E402
from lib.stealth.profiles import derive_profile  # noqa: E402
from lib.stealth.init_script import build_init_script  # noqa: E402


def _is_chrome_running() -> bool:
    try:
        out = subprocess.check_output(
            ["curl", "-s", "--max-time", "2", f"{CDP_URL}/json/version"],
            stderr=subprocess.DEVNULL,
        )
        return b"Browser" in out
    except Exception:
        return False


def ensure_xvfb(display: str = ":99") -> bool:
    """Start Xvfb on the given display if not already running.

    Returns True if a usable X server is up on `display` after the call.
    Chrome on Linux needs an X display even when launched with --headless=new
    if the user wants WebGL / canvas rendering to work without GPU.

    Cheap to call repeatedly — the lockfile check is the gate.
    """
    lockfile = Path(f"/tmp/.X{display.lstrip(':')}-lock")
    if lockfile.exists():
        return True
    if not shutil.which("Xvfb"):
        print(f"[stealth] Xvfb not installed; skipping virtual display on {display}",
              file=sys.stderr, flush=True)
        return False
    subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1080x24",
         "-nolisten", "tcp", "-dpi", "96"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(20):
        if lockfile.exists():
            return True
        time.sleep(0.25)
    print(f"[stealth] Xvfb failed to start on {display} within 5s",
          file=sys.stderr, flush=True)
    return False


def start_chrome(display: str = ":99",
                 user_data_dir: Optional[Path] = None,
                 port: int = CDP_PORT,
                 background: bool = True,
                 extra_args: Optional[list[str]] = None) -> subprocess.Popen:
    """Spawn a fresh Chrome with the stealth flags + debug port open."""
    ensure_xvfb(display)
    if _is_chrome_running():
        print(f"🟢 stealth chrome already on :{port}", flush=True)
        # Find and return the existing process
        ps = subprocess.run(["pgrep", "-af", "google-chrome"],
                            capture_output=True, text=True)
        # Caller doesn't need the Popen — they just want confirmation
        return subprocess.Popen(["true"])

    profile = user_data_dir or USER_DATA_DIR
    profile.mkdir(parents=True, exist_ok=True)

    cmd = [
        CHROME_BIN,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        *STEALTH_FLAGS,
        *(extra_args or []),
        "about:blank",
    ]
    env = os.environ.copy()
    env["DISPLAY"] = display
    print(f"🚀 launching stealth chrome: {' '.join(cmd)}", flush=True)

    if background:
        proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    else:
        proc = subprocess.run(cmd, env=env, check=False)
        proc = subprocess.Popen(["true"])
    # Wait for CDP to come up
    for _ in range(40):
        if _is_chrome_running():
            print(f"✅ stealth chrome CDP ready on :{port}", flush=True)
            return proc
        time.sleep(0.25)
    raise RuntimeError(f"stealth chrome did not open CDP on :{port} within 10s")


def stop_chrome() -> bool:
    """Stop the chrome instance started by start_chrome()."""
    killed = False
    for sig in ("TERM", "KILL"):
        r = subprocess.run(["pkill", f"-{sig}", "-f", "google-chrome.*--remote-debugging-port"],
                           capture_output=True)
        if r.returncode == 0:
            killed = True
        time.sleep(1)
        if not _is_chrome_running():
            return True
    return not _is_chrome_running()


# ---------------------------------------------------------------------------
# Patchright / Playwright worker — runs asyncio
# ---------------------------------------------------------------------------


async def connect(cdp_url: str = CDP_URL, headless: bool = True) -> Any:
    """Connect Patchright (Playwright drop-in) to the running Chrome.

    Patchright patches the CDP Runtime.enable leak at the binary level,
    so anti-bot detectors (Cloudflare / DataDome / Kasada / etc.) can't
    see automation. Falls back to plain Playwright if Patchright isn't
    installed — the user should run `pip install patchright` (already
    done as of 2026-08-28).
    """
    try:
        from patchright.async_api import async_playwright  # type: ignore
        _lib = "patchright"
    except Exception:
        from playwright.async_api import async_playwright  # type: ignore
        _lib = "playwright"

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(cdp_url)
    contexts = browser.contexts
    if not contexts:
        ctx = await browser.new_context()
    else:
        ctx = contexts[0]
    print(f"[stealth] connected via {_lib} on {cdp_url}", flush=True)
    return pw, browser, ctx


async def get_or_create_tab(ctx, task_id: str, headless: bool = True):
    page = await ctx.new_page()
    page.set_default_timeout(45_000)
    # Inject the stealth init script before any page script runs
    seed = profile_seed(task_id)
    profile = derive_profile(seed=seed)
    js = build_init_script(profile)
    try:
        await page.add_init_script(js)
    except Exception as e:
        print(f"[stealth] init-script injection failed: {e}", flush=True)
    return page


async def fetch(url: str, cdp_url: str = CDP_URL) -> Dict[str, Any]:
    """Convenience: open url in a new tab, return title + text + html."""
    pw, browser, ctx = await connect(cdp_url)
    try:
        page = await get_or_create_tab(ctx, task_id=url)
        await page.goto(url, wait_until="domcontentloaded")
        return {
            "url": page.url,
            "title": await page.title(),
            "text": await page.evaluate("() => document.body.innerText"),
        }
    finally:
        await pw.stop()


# ---------------------------------------------------------------------------
# CLI helpers — useful from the worker prompts (S2 pixel theme etc.)
# ---------------------------------------------------------------------------

def cli_start() -> int:
    start_chrome()
    return 0 if _is_chrome_running() else 1


def cli_stop() -> int:
    return 0 if stop_chrome() else 1


def cli_status() -> int:
    if _is_chrome_running():
        print(f"� stealth chrome CDP up on {CDP_URL}")
        return 0
    print(f"🔴 stealth chrome CDP down ({CDP_URL})")
    return 1


def cli_fetch(url: str) -> int:
    out = asyncio.run(fetch(url))
    print(f"title: {out['title']}")
    print(f"url:   {out['url']}")
    print("---")
    print((out["text"] or "")[:4000])
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "start":
        return cli_start()
    if args[0] == "stop":
        return cli_stop()
    if args[0] == "status":
        return cli_status()
    if args[0] == "fetch" and len(args) >= 2:
        return cli_fetch(args[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
