#!/usr/bin/env python3
"""End-to-end request-chain diagnostic: probe each lane and print latency."""
import json
import sys
import time
from pathlib import Path

print("=" * 70)
print("CortexAgent Request Chain Diagnostic")
print("=" * 70)
print()

print("1. COMPONENT HEALTH")
print("-" * 70)
import socket
components = {
    "slimtoken cloud lane": ("127.0.0.1", 11435),
    "slimtoken local lane": ("127.0.0.1", 11436),
    "ollama backend": ("127.0.0.1", 11600),
}
for name, addr in components.items():
    try:
        s = socket.socket()
        s.settimeout(1)
        s.connect(addr)
        s.close()
        print(f"  ✅ {name:30s} RUNNING on :{addr[1]}")
    except Exception as e:
        print(f"  ❌ {name:30s} NOT RUNNING — {e}")

print("\n2. LANE METRICS (SLIMTOKEN :11436)")
print("-" * 70)
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:11436/metrics",
                                timeout=2) as resp:
        snap = json.loads(resp.read())
    print(f"    Total requests:       {snap.get('requests', 0)}")
    print(f"    Prompt tokens:        {snap.get('prompt_tokens', 0):,}")
    print(f"    Completion tokens:    {snap.get('completion_tokens', 0):,}")
    print(f"    Avg tok/s:            {snap.get('avg_tok_s', 0)}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n3. LLM PATH (OVERSEER)")
print("-" * 70)
try:
    from lib.overseer import _model_healthy
    print("  LLM lane:       slimtoken :11436 → ollama :11600")
    print(f"  Is healthy:     {_model_healthy()}")

    start = time.time()
    result = _model_healthy()
    elapsed = time.time() - start
    print(f"  Health check:   took {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n4. BEAUTIFICATION PIPELINE")
print("-" * 70)
try:
    from lib.beautify import beautify

    tests = [
        ("Table", "| a | b |\n|---|---|\n| 1 | 2 |"),
        ("CSV", "name,score\nalice,10\nbob,20"),
        ("KV", "host: 10.0.0.5\nport: 8080"),
        ("Bar chart", "requests: 100\nerrors: 25"),
        ("Prose", "The investigation is complete. No issues found."),
    ]
    print("  Test cases:")
    for name, text in tests:
        result = beautify(text)
        changed = "CHANGED" if result != text else "UNCHANGED"
        print(f"    {name:15s} {changed}")
        if changed == "CHANGED":
            print(f"      → {result[:80]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n5. REACT LOOP")
print("-" * 70)
try:
    from lib.react_loop import classify_mode
    tests = [
        "What is 2+2?",
        "Investigate the security posture of this server",
        "Write a business plan for a coffee shop",
        "Help me with my homework",
    ]
    print("  Mode classification:")
    for text in tests:
        mode = classify_mode(text)
        print(f"    '{text[:40]:40s}' → {mode}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n6. OVERSEER CLI")
print("-" * 70)
try:
    from lib import overseer
    status = overseer._status()
    print("  Overseer status:")
    print(f"    Running:            {overseer._is_running() is not None}")
    print(f"    Queue size:         {len(overseer.queue_list())}")
    print(f"    Schedule entries:   {len(overseer.schedule_list())}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
