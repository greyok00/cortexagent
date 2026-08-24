#!/usr/bin/env python3

import sys

CFG = "~/cortexagent/lib/config.py"
CONF = "~/.cortexagent/cortexagent.conf"

def patch(path, subs, label):
    with open(path) as f:
        src = f.read()
    orig = src
    for old, new in subs:
        if old not in src:
            print(f"  !! MISS in {label}: {old!r}")
            continue
        src = src.replace(old, new, 1)
    if src == orig:
        print(f"  no change: {label}")
        return
    with open(path, "w") as f:
        f.write(src)
    print(f"  patched: {label}")

print("config.py:")
patch(CFG, [
    ('"big_ub": 2048,', '"big_ub": 2560,'),
    ('"big_ub", "CORTEXAGENT_UB", "backend", "big_ub", 2048)',
     '"big_ub", "CORTEXAGENT_UB", "backend", "big_ub", 2560)'),
    ('"big_ub": ("CORTEXAGENT_UB", 2048),', '"big_ub": ("CORTEXAGENT_UB", 2560),'),
    ('"CORTEXAGENT_STT_VAD_THRESHOLD", "stt", "vad_threshold", 0.03)',
     '"CORTEXAGENT_STT_VAD_THRESHOLD", "stt", "vad_threshold", 0.05)'),
], "config.py")

print("conf:")
patch(CONF, [
    ('big_ub = 2048', 'big_ub = 2560'),
], "cortexagent.conf")

print("done")
