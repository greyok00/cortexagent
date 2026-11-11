# cortexagent Acceptance Record — Phase 7

Live acceptance run on the compiled tree. Model: qwen3.8-27B Q4-era Q3_K_XL GGUF via
cortexagent's own the engine server (127.0.0.1:11811, CPU-only), mmproj vision projector
on CPU/RAM.

| Gate item | Result |
|---|---|
| Server boots on local GGUF, CPU resident, CPU/RAM mmproj | PASS |
| Splash: devils flanking GREYAGENT banner, MODEL/AUTHOR/PROMPT lines, controls line, prompt | PASS (headless + terminal render) |
| Tool registry: 31 registered tools across the 15 frozen surfaces | PASS |
| files write/read/edit/list live | PASS |
| search_files glob + grep live | PASS |
| shell bash exec + timeout | PASS |
| kali_bank query against cortexagent-owned assets/kali-commands.json | PASS |
| memory append / search, persists across process restart | PASS |
| scheduler add / list (Store-backed, version-tracked) | PASS |
| web_search live: SearXNG lanes + Patchright/Chromium scrape through greyresearcher clean/distill/relevance pipeline | PASS (real results returned, distilled) |
| parse_document, charts, vision, browser, system, spawn_subagent registered; browser+web share one Chromium session | PASS (registered; browser visual flows exercised in TUI session) |
| Model round-trip on compiled engine: direct chat + ReAct tool-use + memory + compression | PASS |
| slimtoken code mode: default mode is code, fenced code blocks pass byte-identical | PASS (tests/test_slimtoken_identity.py) |
| Strip/minify: zero comments, docstrings, shebangs, inline prompts (only model/system-prompt.txt) | PASS |
| Cython compile: zero .py in core/tools/services/model/ui/build/vendor/src; binary launcher bin/cortexagent | PASS |
| Phase 6 isolation audit | PASS (docs/audit-phase6.md) |

Notes:
- tests/ stays as the verification harness (pytest) re-runnable against the .so tree;
  everything inside core/tools/services/model/ui/build/vendor/src is binary-only.
- TPS during the live run: ~12.7 tok/s generation on the 27B.
- compression ratio 1.0 in these short conversations — code mode is lossless, exactly as
  specified; ratios drop only on long prose-heavy histories.

Verdict: ACCEPTANCE GATE PASSED. cortexagent is frozen at this state.
---

# Release prep addendum — 2026-10-24 evening

| Item | Result |
|---|---|
| Pipeline gate (convert_mcp_to_so.py) fixture-proven E2E | PASS (docs/pipeline-gate.md) |
| Analysis-browser kit integrated into frozen core (25 .so + data; kit since retired and removed) | PASS (docs/audit-2026-10-24-core.md) |
| Spawn integrity: verified bytes == bytes that run (CORTEXENGINE_CORE_TOOLS precedence) | PASS |
| memory.so + research.so: converted, smoketested (10 tools), hash-pinned, ENABLED | PASS |
| Full strings audit: 0 external URLs, 0 telemetry SDKs, 0 banned words, 0 path escapes | PASS |
| build/src/audit.py core+tools+services+mcp+model | CLEAN |
| Gates at release: verify_compiled PASS, pytest 29 passed, MANIFEST 1562 (0 fail) | PASS |
| Release artifact: dist/deb/cortexagent_0.7.5.1_amd64.deb (postinst runs verify_compiled) | BUILT |

Publishing: NOT pushed anywhere (git remote empty by design); .deb is the release
artifact. New tools are admitted ONLY through the pipeline (DISABLED -> hash ->
tool-matrix -> enable).
