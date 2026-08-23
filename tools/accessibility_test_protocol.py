#!/usr/bin/env python3
"""
CortexAgent accessibility test protocol — runnable conductor.

Hand this to a test conductor (or run it yourself alongside an assistive-tech
user). It walks a REAL screen-reader / keyboard-only / low-vision user through
the core CortexAgent task on a chosen surface, times each step, and collects
pass/fail + notes into a report.

It does NOT replace scanners (axe / Lighthouse / WAVE) — it fills the gap scanners
miss. Per docs/cross_platform_ux.md §2.5, scanners catch only ~30-50% of real AT
failures and almost none of the interaction problems (focus flow, announcement
ordering, gesture conflicts). Use BOTH.

Baseline (must hold):
  - run on every surface, with 3-5 distinct real AT/impaired profiles
  - include at least one NOVICE AT user (fresh to the tool)
  - record time-on-task vs a sighted baseline; a large gap = accessibility tax
  - re-run when a NEW panel ships (each panel gets its own pass)

The script supports the sighted-baseline comparison: run once with --baseline
(a sighted/mouse user), then run AT passes; each AT step is compared to the
baseline and flagged as an "accessibility tax" when it exceeds --tax-ratio.

Usage:
  python3 tools/accessibility_test_protocol.py --list
  python3 tools/accessibility_test_protocol.py --surface web --baseline --tester sighted
  python3 tools/accessibility_test_protocol.py --surface web --at NVDA --tester A
  python3 tools/accessibility_test_protocol.py --surface desktop --at Narrator --tester B --novice
  python3 tools/accessibility_test_protocol.py --surface tui --at Orca --tester C --timeout 120
  python3 tools/accessibility_test_protocol.py --surface mobile --at VoiceOver --tester D

Options:
  --surface tui|desktop|web|mobile   surface under test (required)
  --at NAME                          assistive tech (screen reader / magnifier / keyboard / ...)
  --tester NAME                      tester/user id (e.g. A, B, "sarah")
  --novice                           flag: user is new to assistive tech
  --baseline                         record a sighted/mouse baseline (reference times)
  --tax-ratio FLOAT                  AT time / baseline time that flags a tax (default 2.0)
  --timeout SECS                     per-step hard timeout (default 120s; a yield here = tax)
  --out DIR                         report directory (default ./accessibility-reports)
  --list                            print the per-surface step lists and exit

Exit code: 0 if no FAIL/TIMEOUT steps, 1 otherwise (for CI gating).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

SURFACES = ("tui", "desktop", "web", "mobile")

# Core task model: compose -> send -> read result -> recall from memory.
# Wording is per-surface so the conductor reads a task the user can act on.
STEPS = {
    "tui": [
        ("compose", "Compose", "Open the app and compose a prompt in the input bar."),
        ("send", "Send", "Send the prompt and get a model/result response."),
        ("read-result", "Read result", "Read the response back aloud, correctly."),
        ("recall", "Recall memory", "Open the Memory panel and locate a previously saved item."),
        ("interrupt", "Interrupt", "While a command is running, interrupt/cancel it."),
        ("scheduler", "Scheduler", "Open the Scheduler panel and read the next scheduled run."),
        ("theme", "Theme", "Switch color theme; confirm no status is conveyed by color alone."),
    ],
    "desktop": [
        ("compose", "Compose", "Tab to the input field and compose a prompt."),
        ("send", "Send", "Send it (Enter or the send control) and get a response."),
        ("read-result", "Read result", "Read the response back aloud, correctly."),
        ("recall", "Recall", "Open the Memory panel and recall a saved item."),
        ("interrupt", "Interrupt", "Interrupt a running command with the keyboard."),
        ("scheduler", "Scheduler", "Open the Scheduler panel and read the next run."),
        ("handedness", "Handedness", "Toggle the handedness mirror and confirm the layout flips."),
    ],
    "web": [
        ("compose", "Compose", "Land on the page, move focus to the input, compose a prompt."),
        ("send", "Send", "Send it and get a response (a live region announces arrival)."),
        ("read-result", "Read result", "Read the streamed result back aloud, correctly."),
        ("recall", "Recall", "Open the Memory drawer and recall a saved item."),
        ("interrupt", "Interrupt", "Interrupt/cancel a running command without the mouse."),
        ("keyboard", "Keyboard-only", "Complete the whole flow using only the keyboard (no pointer)."),
        ("zoom", "Zoom", "Zoom to 200% and complete compose+send without horizontal scroll."),
    ],
    "mobile": [
        ("compose", "Compose", "Get focus to the input field and compose a prompt."),
        ("send", "Send", "Send it and get a response (thumb-reachable action)."),
        ("read-result", "Read result", "Read the response back aloud with the screen reader."),
        ("recall", "Recall", "Open the Memory panel (bottom sheet/tab) and recall a saved item."),
        ("interrupt", "Interrupt", "Interrupt a running command with the OS gesture/control."),
        ("handedness", "Handedness", "Switch to left-hand mode and confirm the send is reachable."),
        ("dynamic-type", "Dynamic type", "Increase system font size and confirm nothing is cut off."),
    ],
}

# AT-relevant hints the conductor reads aloud to frame each trial.
HINTS = {
    "read-result": "Output is live/streamed; the reader must keep up, not flood.",
    "interrupt": "Cancel must be discoverable by keyboard/AT, not only a corner button.",
    "theme": "State must never be conveyed by color alone — pair icon + text.",
    "handedness": "Mirror must flip the layout; send stays reachable for the other hand.",
    "zoom": "No horizontal scroll; layout must not break at 200%.",
}

RESULT_CHOICES = {"p": "pass", "f": "fail", "s": "skip", "x": "timeout"}


def _timed_step(sid, label, instruction, timeout):
    """Run one timed trial: Start -> user acts -> Stop -> score. Returns a record."""
    print("\n" + "=" * 72)
    print(f"  [{sid}] {label}")
    print(f"  TASK: {instruction}")
    hint = HINTS.get(sid)
    if hint:
        print(f"  AT-RELEVANCE: {hint}")
    if timeout:
        print(f"  HARD TIMEOUT: {timeout}s (a yield here still counts as a tax)")

    input("\n  Press Enter to START timing -> ")
    t0 = time.perf_counter()
    print("  ...user performing task... (press Enter when finished)")
    input()
    elapsed = round(time.perf_counter() - t0, 1)

    while True:
        r = input("  Result? p=pass f=fail s=skip x=timeout q=quit -> ").strip().lower()
        if r == "q":
            return None
        if r in RESULT_CHOICES:
            break
        print("  (choose one of: p f s x q)")
    note = input("  Note (optional): ").strip()
    return {"step": sid, "label": label, "elapsed": elapsed,
            "result": RESULT_CHOICES[r], "note": note}


def _report_path(out, surface, at, tester):
    safe = "".join(c if c.isalnum() else "_" for c in f"{surface}_{at}_{tester}") or "report"
    return os.path.join(out, safe)


def _baseline_path(out, surface):
    return os.path.join(out, f"{surface}_baseline.json")


def _load_baseline(out, surface):
    p = _baseline_path(out, surface)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def _save_baseline(out, surface, records):
    os.makedirs(out, exist_ok=True)
    with open(_baseline_path(out, surface), "w") as f:
        json.dump({r["step"]: r["elapsed"] for r in records}, f, indent=2)


def _render_markdown(report, stats, tax):
    lines = [
        "# CortexAgent Accessibility Test Report",
        "",
        f"- **Surface:** {report['surface']}",
        f"- **Assistive tech:** {report['at']}",
        f"- **Tester:** {report['tester']}{'  *(NOVICE)*' if report['novice'] else ''}",
        f"- **Date:** {report['date']}",
        "",
        "## Summary",
        f"- Steps run: {stats['total']}",
        f"- Passed: {stats['pass']}  Failed: {stats['fail']}  Skipped: {stats['skip']}  "
        f"Timed out: {stats['timeout']}",
        f"- Pass rate: {stats['rate']:.0%}",
    ]
    if report["baseline"]:
        lines += ["", "> This run recorded the **sighted/mouse baseline** (reference times)."]
    elif tax is not None:
        lines.append(f"- Accessibility tax: {len(tax)} step(s) >= {report['tax_ratio']}x baseline")
    lines += ["", "## Per-step results", "",
              "| Step | Result | Time (s) | vs baseline | Note |",
              "|------|--------|----------|-------------|------|"]
    for r in report["steps"]:
        vs = ""
        if r.get("tax_ratio") is not None:
            vs = f"{r['tax_ratio']}x" + ("  ⚠" if r["tax_ratio"] >= report["tax_ratio"] else "")
        lines.append(f"| {r['label']} | {r['result']} | {r['elapsed']} | {vs} | {r['note'] or ''} |")
    if tax:
        lines += ["", "## Accessibility tax (flagged)", ""]
        for label, ratio in tax:
            lines.append(f"- **{label}** — {ratio:.1f}x baseline. Investigate: is the extra time "
                         f"inherent to the task, or a fixable barrier?")
    if report["novice"]:
        lines.append("\n> This was a novice AT user — this is the on-boarding pass.")
    lines += ["", "_Generated by tools/accessibility_test_protocol.py_", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", choices=SURFACES, help="surface under test")
    ap.add_argument("--at", help="assistive tech used")
    ap.add_argument("--tester", default="tester", help="tester/user id")
    ap.add_argument("--novice", action="store_true", help="novice AT user flag")
    ap.add_argument("--baseline", action="store_true",
                    help="record a sighted/mouse baseline (reference times for tax comparison)")
    ap.add_argument("--tax-ratio", type=float, default=2.0,
                    help="AT time / baseline time that flags an accessibility tax (default 2.0)")
    ap.add_argument("--timeout", type=int, default=120, help="per-step hard timeout (s)")
    ap.add_argument("--out", default="accessibility-reports", help="report directory")
    ap.add_argument("--list", action="store_true", help="print step lists and exit")
    args = ap.parse_args()

    if args.list:
        for s in SURFACES:
            print(f"\n## {s}")
            for i, (sid, label, ins) in enumerate(STEPS[s], 1):
                print(f"  {i}. [{sid}] {label}\n      {ins}")
        return 0

    if not args.surface:
        ap.error("--surface is required unless --list")

    records = []
    for sid, label, ins in STEPS[args.surface]:
        try:
            rec = _timed_step(sid, label, ins, args.timeout)
        except EOFError:  # conductor closed the terminal mid-session
            print("\n  / input ended - finalizing with the steps completed so far")
            break
        if rec is None:  # conductor quit
            break
        records.append(rec)

    # Baseline handling + accessibility-tax comparison.
    tax = None
    if args.baseline:
        _save_baseline(args.out, args.surface, records)
        print(f"  Baseline saved: {_baseline_path(args.out, args.surface)}")
    else:
        baseline = _load_baseline(args.out, args.surface)
        if baseline:
            tax = []
            for r in records:
                b = baseline.get(r["step"])
                if b and b > 0:
                    ratio = r["elapsed"] / b
                    r["tax_ratio"] = round(ratio, 2)
                    if ratio >= args.tax_ratio:
                        tax.append((r["label"], ratio))
        else:
            print("  (no baseline found for this surface - run once with --baseline to enable "
                  "accessibility-tax comparison)")

    results = [r["result"] for r in records]
    stats = {
        "total": len(records),
        "pass": results.count("pass"),
        "fail": results.count("fail"),
        "skip": results.count("skip"),
        "timeout": results.count("timeout"),
    }
    stats["rate"] = stats["pass"] / stats["total"] if stats["total"] else 0.0

    report = {
        "surface": args.surface, "at": args.at, "tester": args.tester,
        "novice": args.novice, "baseline": args.baseline, "tax_ratio": args.tax_ratio,
        "date": datetime.now().isoformat(timespec="seconds"),
        "steps": records,
    }

    os.makedirs(args.out, exist_ok=True)
    path = _report_path(args.out, args.surface, args.at, args.tester)
    with open(path + ".md", "w") as f:
        f.write(_render_markdown(report, stats, tax))
    with open(path + ".json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 72)
    print(f"  PASS {stats['pass']}/{stats['total']}  |  FAIL {stats['fail']}  |  "
          f"SKIP {stats['skip']}  |  TIMEOUT {stats['timeout']}  |  rate {stats['rate']:.0%}")
    if tax:
        print(f"  ACCESSIBILITY TAX: {len(tax)} step(s) >= {args.tax_ratio}x baseline")
        for label, ratio in tax:
            print(f"    - {label}: {ratio:.1f}x")
    print(f"  Report: {path}.md  (+ .json)")
    if stats["fail"] or stats["timeout"]:
        print("  WARN: failures present — fix before shipping the panel (docs §2.5).")
    return 0 if (stats["fail"] == 0 and stats["timeout"] == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
