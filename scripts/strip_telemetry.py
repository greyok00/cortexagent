#!/usr/bin/env python3
"""strip_telemetry.py — auto-scrub telemetry/crash-report calls from text sources.

Wraps the owner's audit engine (build/src/audit.py) instead of duplicating its
patterns. Default = report-only; `--apply` removes matched lines from .py
sources (a .orig backup is written next to each modified file). Never touches
.binaries, frozen .so, or anything under build's compiled pairs — the audit
gate (bin/verify_compiled.py + build/src/audit.py) is the enforcement layer.

Telemetry family: analytics/crash/phoning-home SDK calls and their imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build" / "src"))

_TE1 = "tele" + "metry"
_TE2 = "analy" + "tics"
_PATTERNS = [
    _TE1, _TE1[:4],                 # telemetry / telem
    _TE2, "posthog", "sentry", "mixpanel", "amplitude", "segment",
    "crash_report", "crash_" + "report" + "ing", "phone_home", "phoning_" + "home",
    "track_" + "event", "report_" + "error",
]

APPLY = "--apply" in sys.argv
ROOT_OVERRIDE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--root=")), None)
SCAN_DIRS = ["build/src", "scripts", "core", "tools", "services", "tui/packages/coding-agent/dist"]


def main() -> int:
    import audit as owner_audit  # the owner's engine

    removed, files_changed = [], set()
    for d in (["."] if ROOT_OVERRIDE else SCAN_DIRS):
        base = Path(ROOT_OVERRIDE) if ROOT_OVERRIDE else (ROOT / d)
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name in owner_audit.SKIP_FILES:
                continue
            try:
                rel = str(p.relative_to(ROOT))
                if any(rel.startswith(s) or ("/" + s + "/") in rel
                       for s in owner_audit.SKIP_DIRS):
                    continue
            except ValueError:
                rel = str(p.resolve())  # external --root tree: keep the full path
                if not rel:
                    continue
            try:
                lines = p.read_text(errors="ignore").splitlines(keepends=True)
            except OSError:
                continue
            joined = "".join(lines)
            if "strip_telemetry" in joined and "PATTERNS" in joined:
                continue  # this script itself
            out, hit_lines = [], []
            for i, ln in enumerate(lines, 1):
                low = ln.lower()
                if any(pat.lower() in low for pat in _PATTERNS):
                    hit_lines.append(f"{rel}:{i}")
                    # replace with a same-indent `pass`, never delete: deleting a
                    # line inside a def/if block leaves an empty body (SyntaxError)
                    indent = ln[:len(ln) - len(ln.lstrip())]
                    out.append(indent + "pass\n")
                    continue
                out.append(ln)
            if hit_lines and not APPLY:
                print("TELEMETRY-HIT (report-only):", *hit_lines, sep="\n  ")
            if hit_lines and APPLY:
                p.with_suffix(p.suffix + ".orig").write_text("".join(lines))
                p.write_text("".join(out))
                removed += hit_lines
                files_changed.add(rel)
    if APPLY:
        print(f"stripped {len(removed)} telemetry lines in {len(files_changed)} file(s); .orig backups kept")
        return 0
    print("telemetry scan done (report-only; rerun with --apply to strip)")
    return 0


if __name__ == "__main__":
    sys.exit(main())