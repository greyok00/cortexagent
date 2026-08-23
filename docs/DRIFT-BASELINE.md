# CortexAgent Drift Baseline

> **The "default code file the system can check against everything" the user asked for.**

A reference baseline that catches silent regressions **between** sessions. Four artifacts
together form the drift fence:

| Artifact | What it asserts | File |
|----------|-----------------|------|
| **File-hash manifest** | Every `.py`/`.md`/`.json`/`.sh` SHA256 matches the baseline | `.superpowers/manifest/cortexagent.manifest.json` |
| **End-to-end smoke** | 8 layers (compile, import, module, CLI, live, hot-paths, socket, config) all pass | `tools/smoke_all.py` |
| **Feature catalog** | Every advertised feature (70 across 5 kinds) is reachable | `tools/feature_catalog.json` |
| **Doc-vs-code contract** | Every documented API exists in the source it claims | `tools/contract_test.py` |

## Why four?

Each catches a different class of regression:

| Class | What broke | Caught by |
|-------|-----------|-----------|
| Code modified off-baseline | Edit to `lib/overseer.py` slips in | **manifest** |
| `spans: []` fake-pass smokes | `--smoke` exits 0 with empty list | **smoke hot-paths** |
| Tool advertised but unreachable | `tool_registry.register_tool("foo")` removed but CLI still calls | **feature catalog** |
| Public API documented but deleted | `lib.foo()` removed; docs still reference it | **contract test** |

Any one of these alone is gappy. **All four together** close the gap.

## Usage

```bash
# One-shot full verification
bin/verify

# Or, individual layers
python3 tools/verify_manifest.py
python3 tools/contract_test.py
python3 tools/smoke_all.py --no-live     # omit --no-live for live endpoints
python3 tools/verify_feature_catalog.py

# Build/update the manifest after intentional changes
python3 tools/build_manifest.py
python3 tools/build_feature_catalog.py  # if you added a feature
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All green |
| 1 | Drift/miss in one or more layers |
| 2 | Catastrophic — manifest/catalog missing entirely |

## When to run

- **Before commit** (CI / pre-commit hook)
- **After session-end** (the `bin/verify` reports are the session-end checkpoint)
- **After ANY edit to `lib/`, `scripts/`, `bin/`, `cortex/`, `engine/`, `extension/`, `addons/`** — run `tools/build_manifest.py` first to capture the new baseline, then `bin/verify` to confirm green.
- **After adding a new feature** — update `tools/feature_catalog.json` and run `bin/verify`.

## What "drift" means here

It is **silent regression** in adjacent code — code that compiles, imports, and even
returns success codes, while no longer doing what it claims.

The canonical cases this baseline catches:
1. **Default-config drift** — `lib/config.py:382` sets `stt_device="cuda"` but a smoke
   asserts `"auto"` (the user's "stt is suspended" symptom).
2. **Empty-span smokes** — observability smoke prints OK while writing `spans: []`.
3. **Adrift endpoints** — `webui.py` removes `/api/tps` but the feature catalog still
   lists it as available.
4. **Cross-module drift** — `lib/daemon.py` renames the `swap` RPC; `bin/cortexagent`
   still calls `cmd == "swap"` and silently no-ops.

## Files in this baseline

```
bin/verify                              ← single-shot runner
tools/build_manifest.py                  ← generates the SHA256 baseline
tools/verify_manifest.py                 ← catches file-level drift
tools/smoke_all.py                       ← 8-layer in-process + endpoint check
tools/build_feature_catalog.py           ← scans CONVERTED_TOOLS, routes, RPCs
tools/verify_feature_catalog.py          ← asserts every feature is reachable
tools/contract_test.py                   ← docstring vs real symbols
.superpowers/manifest/cortexagent.manifest.json
tools/feature_catalog.json
docs/DRIFT-BASELINE.md                   ← this file
```

## Limitations

- The manifest only catches **file-content drift**, not **runtime drift** in a process
  that did not change (e.g. crash bugs without a code edit).
- The smoke harness verifies behavior **up to the rate of the local model**; an offline
  `:8080` will show `L5.live: down`.
- The feature catalog is **statically discovered** — it does not enumerate features
  the model itself invents via ReAct/Socratic loops.

## See also

- `AUDIT.md` — the 2026-08-17 deep audit (per-module table of every public entry point).
- `tools/contract_test.py:contract_test` — the doc-vs-code runner.
