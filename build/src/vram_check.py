#!/usr/bin/env python3
"""VRAM interlock (hardened build, owner order 2026-10-24; budget regime 2026-11-05).

Owner order 2026-11-05: "force 10 GB VRAM and rest RAM until these other
sessions are done." While the other sessions hold the card, cortexagent
COEXISTS: it boots when the GPU has at least CORTEXENGINE_MIN_FREE_MB
(default 10240) free, and the qwen36moe profile's expert split keeps the
model inside that budget (enforced again at boot end by
server._enforce_vram_cap). The old any-holder-is-a-refusal rule is gone:
with the card shared, refusing every boot because a protected-family lane
holds memory is the wrong policy, and evictions are gone with it
(server.py now defaults CORTEXENGINE_EVICT=off).

Exit codes: 0 = enough free VRAM (boot may proceed), 1 = under budget.
"""
from __future__ import annotations

import os
import subprocess
import sys

# memory below this is driver/desktop residue, not a competing model
_IGNORE_MB = 1024
# 2026-10-25 owner: the sibling fork runs side by side with cortexagent. Processes whose
# cmdline matches a protected path are siblings, not competitors.
# GA-17 (2026-11-03): this keep-list MUST equal the reaper's in build/src/
# server.py. One list, inlined identically, overridable via the same env name.
# (The reaper is off by default since 2026-11-05; the lists still match.)
_KEEP = [p for p in os.environ.get(
    "CORTEXENGINE_KEEP_VRAM",
    ":".join((os.path.expanduser("~/dystopia"),
              os.path.expanduser("~/.skeleton-key"),
              os.path.expanduser("~/.cortex-agent"),
              os.path.expanduser("~/cortex-agent"))).split(":"))
    if p]
_DISPLAY = ("Xorg", "Xwayland", "gnome-shell", "cinnamon", "mate",
            "kwin", "weston", "displaylink")


def _query(args: list[str]) -> str:
    try:
        return subprocess.run(["nvidia-smi", *args],
                              capture_output=True, text=True, timeout=10).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def held_by() -> list[tuple[int, str, int]]:
    """Return [(pid, name, used_mb)] of other GPU compute processes."""
    rows = []
    for line in _query(["--query-compute-apps=pid,process_name,used_memory",
                        "--format=csv,noheader,nounits"]).strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        pid, name, mb = int(parts[0]), parts[1], int(parts[2])
        if mb < _IGNORE_MB:
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace")
        except OSError:
            cmd = name
        if any(w in cmd or w in name for w in _DISPLAY):
            continue  # display stack is not a competing model (GA-17 symmetry)
        if any(k in cmd or k in name for k in _KEEP):
            continue  # protected sibling — coexist, never refuse
        rows.append((pid, name, mb))
    return rows


def free_mb() -> int:
    """Free VRAM on device 0, or -1 when nvidia-smi cannot answer."""
    out = _query(["--query-gpu=memory.used,memory.total",
                  "--format=csv,noheader,nounits"]).strip()
    first = out.splitlines()[0] if out else ""
    parts = [p.strip() for p in first.split(",")]
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[1]) - int(parts[0])
    return -1


def main() -> int:
    # Default budget comes from the active profile's min_free_mb key
    # (2026-11-05 end state: 15360). CORTEXENGINE_MIN_FREE_MB overrides for a
    # launch beside the other sessions without editing code.
    try:
        from server import _P as _profile
    except Exception:
        _profile = {}
    budget = int(os.environ.get("CORTEXENGINE_MIN_FREE_MB",
                                str(_profile.get("min_free_mb", 10240))))
    free = free_mb()
    if free >= 0 and free < budget:
        print(f"VRAM under budget: {free} MiB free, need {budget} MiB "
              f"(CORTEXENGINE_MIN_FREE_MB) - refusing boot")
        for pid, name, mb in held_by():
            print(f"  holder: pid {pid} ({name}) using {mb} MiB")
        return 1
    if free >= 0:
        print(f"VRAM clear for coexistence: {free} MiB free "
              f"(budget {budget} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
