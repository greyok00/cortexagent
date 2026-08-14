#!/usr/bin/env python3
"""ASU Live Chat watcher — sends a canned message when an agent joins, and
keeps the chat session alive by typing "." on a random 1–1.5 hour cadence.

A consumer of lib/browser_control (the general Playwright + CDP :9222
browser engine). No raw CDP here — the engine holds the persistent
connection and exposes the shadow-DOM fill/send + text-read helpers.

Usage:
    python3 scripts/asu_chat_watcher.py            # foreground
    python3 scripts/asu_chat_watcher.py --once    # send canned msg if agent joined, then exit
    python3 scripts/asu_chat_watcher.py --status  # print current state, exit
    python3 scripts/asu_chat_watcher.py --test     # fill+verify+clear the real textarea (nothing sent)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from lib.browser_control import find_tab, page_text, fill_and_send, element_value, clear_element  # noqa: E402

CHAT_URL_PREFIX = "https://asu.my.site.com/chat"
FRAME_MARKER = "lwc.mode"
TEXTAREA_CLS = "embeddedMessagingInputFooterTextArea"

CANNED_MSG = (
    "I have unsub loans available but was never given Grad PLUS loans to select. "
    "I requested them in the FAFSA and got them over the summer semester. "
    "I have a credit report acceptance letter from April 26th for this year. "
    "Do I need to do anything to get offered them for the fall and spring semester?"
)
FOLLOWUP_MSG = (
    "If so, can you please tell me how to apply and then accept the loans? "
    "I also received a $300 crisis fund because I was in a car accident a week ago. "
    "It's deducting it from my unsub loans, however. Can you fix that? They said it was a grant."
)

# Messages sent in order once the agent joins.
MESSAGES = [CANNED_MSG, FOLLOWUP_MSG]
MSG_DELAY_SEC = 10  # gap between consecutive messages

KEEPALIVE_MIN_SEC = 60 * 60    # keep-alive floor: 1 hour
KEEPALIVE_MAX_SEC = 90 * 60    # keep-alive ceiling: 1.5 hours
POLL_SEC = 5                   # how often we check for agent-joined

# Join-send guards (2026-08-12): a mid-load frame reads as "agent joined"
# because the queue text paints AFTER the header — observed 15:54:50 firing
# a false join and failing the send. So:
JOIN_CONFIRM_POLLS = 3         # consecutive polls showing joined before sending
SEND_RETRIES = 3               # fill_and_send attempts per message
SEND_RETRY_GAP_SEC = 3         # gap between send attempts


def _next_keepalive_delay() -> float:
    """Random keep-alive delay in [1h, 1.5h]."""
    return random.uniform(KEEPALIVE_MIN_SEC, KEEPALIVE_MAX_SEC)
STATE_FILE = Path.home() / ".cortexagent" / "state" / "asu_chat_watcher.json"
LOG_FILE = Path.home() / ".cortexagent" / "logs" / "asu_chat_watcher.log"

QUEUE_MARKERS = ("queue position", "Your support specialist will be with you shortly")
AGENT_MARKERS = ("now chatting with", "you're now chatting with", "chatting with")
ENDED_MARKERS = ("conversation ended", "start a new one", "chat has ended", "session ended")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}
    # migrate old single-message schema -> sent_count
    if "sent_count" not in state:
        state["sent_count"] = 1 if state.get("sent") else 0
    state.setdefault("sent_at", None)
    state.setdefault("last_keepalive", None)
    return state


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def textarea_ready(page: str) -> bool:
    """True when the chat textarea has rendered. Mid-load frames have none —
    probing it (instead of assuming) prevents a send into a half-built page."""
    return element_value(page, iframe_marker=FRAME_MARKER,
                         tag="TEXTAREA", class_fragment=TEXTAREA_CLS) is not None


def send_with_retry(page: str, msg: str, retries: int = SEND_RETRIES,
                    gap: float = SEND_RETRY_GAP_SEC) -> bool:
    """Fill + Enter a message, riding out the page-load race. Returns True when
    the DOM-level send succeeded (i.e. fill + Enter dispatched)."""
    for attempt in range(1, retries + 1):
        if not textarea_ready(page):
            log(f"  textarea not ready (attempt {attempt}/{retries}) — waiting {gap}s")
            time.sleep(gap)
            continue
        if fill_and_send(page, msg, iframe_marker=FRAME_MARKER,
                         tag="TEXTAREA", class_fragment=TEXTAREA_CLS):
            return True
        log(f"  send attempt {attempt}/{retries} failed — retrying in {gap}s")
        time.sleep(gap)
    return False


def agent_joined(text: str) -> bool:
    """Agent has connected when the queue message is gone (or a chat greeting appears).

    Empty/unreadable text is NOT a signal — it means the read failed or the
    page is mid-load, not that the agent joined. Refuse to fire on it.
    """
    if not text or not text.strip():
        return False
    low = text.lower()
    if any(m in low for m in ENDED_MARKERS):
        return False  # session over — not an agent join
    if any(m in low for m in AGENT_MARKERS):
        return True
    return not any(m in low for m in QUEUE_MARKERS)


def run(once: bool = False) -> int:
    state = load_state()
    last_keepalive_ts = float(state.get("last_keepalive") or 0.0)

    # Next keep-alive: migrate from last_keepalive, or start fresh.
    next_keepalive_at = state.get("next_keepalive_at")
    if not next_keepalive_at:
        next_keepalive_at = (last_keepalive_ts + _next_keepalive_delay()
                             if last_keepalive_ts else time.time() + _next_keepalive_delay())
        state["next_keepalive_at"] = next_keepalive_at
        save_state(state)

    log(f"ASU chat watcher started (sent={state.get('sent_count', 0)}/{len(MESSAGES)}, "
        f"keepalive={KEEPALIVE_MIN_SEC // 60}-{KEEPALIVE_MAX_SEC // 60} min random)")
    for i, msg in enumerate(MESSAGES, 1):
        log(f"  message {i}: {msg[:60]}...")

    while True:
        page = find_tab(CHAT_URL_PREFIX)
        if page is None:
            log("  chat tab not found — retrying in 15s")
            time.sleep(15)
            continue

        text = page_text(page, iframe_marker=FRAME_MARKER)
        joined = agent_joined(text)

        # 1) Send messages in order once the agent connects. The join must be
        #    CONFIRMED across JOIN_CONFIRM_POLLS consecutive polls — a mid-load
        #    frame reads as "agent joined" (queue text paints after the header),
        #    which caused a false fire + failed send on 2026-08-12. The streak
        #    resets the moment a queue marker reappears.
        sent_count = state.get("sent_count", 0)
        if joined and sent_count < len(MESSAGES):
            streak = state.get("_join_streak", 0) + 1
            if streak < JOIN_CONFIRM_POLLS:
                state["_join_streak"] = streak
                save_state(state)
                log(f"  join signal x{streak}/{JOIN_CONFIRM_POLLS} — confirming")
            else:
                state["_join_streak"] = 0
                save_state(state)
                idx = sent_count
                msg = MESSAGES[idx]
                log(f"  AGENT JOINED — sending message {idx + 1}/{len(MESSAGES)}")
                if send_with_retry(page, msg):
                    state["sent_count"] = idx + 1
                    state["sent_at"] = datetime.now().isoformat()
                    save_state(state)
                    log(f"  ✅ message {idx + 1} sent")
                    if idx + 1 < len(MESSAGES):
                        time.sleep(MSG_DELAY_SEC)  # let the previous message land
                else:
                    log("  ⚠️ send failed after retries — will retry next poll")
        elif not joined and state.get("_join_streak"):
            state["_join_streak"] = 0
            save_state(state)

        # 2) Keep-alive: type "." on a random 1–1.5h cadence — runs from the
        #    start (during the queue wait too), so the session doesn't die.
        now = time.time()
        if now >= next_keepalive_at:
            log("  keep-alive: typing '.'")
            if fill_and_send(page, ".", iframe_marker=FRAME_MARKER,
                             tag="TEXTAREA", class_fragment=TEXTAREA_CLS):
                state["last_keepalive"] = now
                next_keepalive_at = now + _next_keepalive_delay()
                state["next_keepalive_at"] = next_keepalive_at
                save_state(state)
                last_keepalive_ts = now
                log(f"  ✅ keep-alive sent — next in {int(next_keepalive_at - now) // 60} min")
            else:
                log("  ⚠️ keep-alive failed — retrying next poll")

        if once:
            log("  --once done")
            return 0

        time.sleep(POLL_SEC)


def status() -> int:
    state = load_state()
    print(json.dumps(state, indent=2))
    return 0


def test() -> int:
    """Drive the real chat textarea: fill a visible marker, verify, clear.
    Nothing is sent (no Enter) — proves CDP + frame + shadow-DOM + fill work."""
    page = find_tab(CHAT_URL_PREFIX)
    if page is None:
        print("FAIL: chat tab not found")
        return 1

    marker = "OSINT-WATCHER-TEST-OK"
    ok = fill_and_send(page, marker, iframe_marker=FRAME_MARKER,
                       tag="TEXTAREA", class_fragment=TEXTAREA_CLS, submit=False)
    if not ok:
        print("FAIL: fill error")
        return 1
    print("PASS: textarea fill verified — you should see the marker in the chat box")

    val = element_value(page, iframe_marker=FRAME_MARKER,
                        tag="TEXTAREA", class_fragment=TEXTAREA_CLS)
    if val == marker:
        print("PASS: value read-back matches")
    else:
        print(f"FAIL: read-back mismatch: {val!r}")
        return 1

    if clear_element(page, iframe_marker=FRAME_MARKER,
                     tag="TEXTAREA", class_fragment=TEXTAREA_CLS):
        print("PASS: cleared, nothing sent to the queue")
    else:
        print("FAIL: clear failed")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ASU live chat watcher")
    ap.add_argument("--once", action="store_true", help="send canned msg if agent joined, then exit")
    ap.add_argument("--status", action="store_true", help="print state and exit")
    ap.add_argument("--test", action="store_true", help="fill+verify+clear the real textarea (nothing sent)")
    args = ap.parse_args()
    if args.test:
        return test()
    if args.status:
        return status()
    return run(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
