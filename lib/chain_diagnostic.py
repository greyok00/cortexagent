#!/usr/bin/env python3
"""chain_diagnostic.py — Full diagnostic of the entire CortexAgent request chain.

Traces a request from user input → proxy → model → output, showing where
minification, token tracking, and beautification happen (or don't).

Usage:
  python3 lib/chain_diagnostic.py          # full diagnostic
  python3 lib/chain_diagnostic.py trace    # detailed trace for a test request
"""
import json
import sys
import os
import time
from pathlib import Path
from typing import Dict, List, Any

# ── Chain Overview ──────────────────────────────────────────────────────────
print("=" * 70)
print("CortexAgent Request Chain Diagnostic")
print("=" * 70)
print()

# ── 1. Component Health ────────────────────────────────────────────────────
print("1. COMPONENT HEALTH")
print("-" * 70)
import socket
components = {
    "Proxy (minify)": ("127.0.0.1", 8081),
    "Big model (llama-server)": ("127.0.0.1", 8080),
    "Tiny model (llama-server)": ("127.0.0.1", 8082),
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

# ── 2. Minification Pipeline ───────────────────────────────────────────────
print("\n2. MINIFICATION PIPELINE")
print("-" * 70)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from lib.grammar_proxy import _MINIFY_OK, _MINIFY_BACKEND, _MINIFY_CFG, _get_minify_snapshot
    print(f"  Minification backend:   {_MINIFY_BACKEND}")
    print(f"  Minification enabled:   {_MINIFY_OK}")
    print(f"  Config stages:          {_MINIFY_CFG.enabled_stages}")
    print(f"  Token budget:           {_MINIFY_CFG.token_budget}")
    print(f"  Chunked minify:         {sys.modules['lib.grammar_proxy']._MINIFY_CHUNKED}")
    print(f"  Response minify:        {sys.modules['lib.grammar_proxy']._MINIFY_RESPONSE}")
    
    snap = _get_minify_snapshot()
    print(f"\n  Lifetime stats:")
    print(f"    Total runs:           {snap.get('runs', 0)}")
    print(f"    Tokens in:            {snap.get('tokens_in', 0):,}")
    print(f"    Tokens out:           {snap.get('tokens_out', 0):,}")
    print(f"    Tokens saved:         {snap.get('tokens_saved', 0):,}")
    print(f"    Savings ratio:        {snap.get('ratio_pct', 0):.1f}%")
except Exception as e:
    print(f"  ❌ Error: {e}")

# ── 3. Tiny Model Path (Overseer) ──────────────────────────────────────────
print("\n3. TINY MODEL PATH (OVERSEER)")
print("-" * 70)
try:
    from lib import tiny_llm
    print(f"  Model path:     {tiny_llm._BASE}")
    print(f"  Port:           {tiny_llm._PORT}")
    print(f"  Max tokens:     {tiny_llm._MAX_TOKENS}")
    print(f"  Is healthy:     {tiny_llm._is_healthy()}")
    # Test a query
    start = time.time()
    result = tiny_llm._is_healthy()
    elapsed = time.time() - start
    print(f"  Health check:   took {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ Error: {e}")

# ── 4. Beautification Pipeline ─────────────────────────────────────────────
print("\n4. BEAUTIFICATION PIPELINE")
print("-" * 70)
try:
    from lib.beautify import beautify, beautify_html
    
    # Test with various inputs
    tests = [
        ("Table", "| a | b |\n|---|---|\n| 1 | 2 |"),
        ("CSV", "name,score\nalice,10\nbob,20"),
        ("KV", "host: 10.0.0.5\nport: 8080"),
        ("Bar chart", "requests: 100\nerrors: 25"),
        ("Prose", "The investigation is complete. No issues found."),
    ]
    print(f"  Test cases:")
    for name, text in tests:
        result = beautify(text)
        changed = "CHANGED" if result != text else "UNCHANGED"
        print(f"    {name:15s} {changed}")
        if changed == "CHANGED":
            print(f"      → {result[:80]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# ── 5. React Loop ──────────────────────────────────────────────────────────
print("\n5. REACT LOOP")
print("-" * 70)
try:
    from lib.react_loop import classify_mode, _REACT_SYSTEM, _SOCRATIC_SYSTEM
    tests = [
        "What is 2+2?",
        "Investigate the security posture of this server",
        "Write a business plan for a coffee shop",
        "Help me with my homework",
    ]
    print(f"  Mode classification:")
    for text in tests:
        mode = classify_mode(text)
        print(f"    '{text[:40]:40s}' → {mode}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# ── 6. Overseer CLI ────────────────────────────────────────────────────────
print("\n6. OVERSEER CLI")
print("-" * 70)
try:
    from lib import overseer
    status = overseer._status()
    print(f"  Overseer status:")
    print(f"    Running:            {overseer._is_running() is not None}")
    print(f"    Queue size:         {len(overseer.queue_list())}")
    print(f"    Schedule entries:   {len(overseer.schedule_list())}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# ── 7. WebUI ───────────────────────────────────────────────────────────────
print("\n7. WEBUI")
print("-" * 70)
try:
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:8090/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            print(f"  WebUI: RUNNING on :8090")
            print(f"    Model:          {data.get('model', 'unknown')}")
            print(f"    Profile:        {data.get('profile', 'unknown')}")
            print(f"    Minify runs:    {data.get('minify', {}).get('runs', 0)}")
    except Exception as e:
        print(f"  ❌ WebUI: NOT RUNNING — {e}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
