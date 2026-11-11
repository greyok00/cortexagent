# Full cortexagent audit — 2026-10-24 (integration + tools)

Scope: every compiled surface (core/*.so, tools/*.so, tools/*/*.so,
services/*.so, mcp/*.so, plus the analysis-browser kit's 25 modules under
core/ — the kit is retired and removed from the tree since), the JS TUI
harness dist, and the MCP registry. The kit was rebuilt/audited elsewhere
(separate session).

## Integration (task: analysis-browser kit → core)
- The kit's core copy: 25 .so (byte-identical to the pinned mcp twins) + data
  dirs (data/, research/, assets/, docs/).
- Integrity chain: loader verifies the kit's MCP .so vs FROZEN MANIFEST before
  every spawn; spawn sets CORTEXENGINE_CORE_TOOLS to the kit's core path and
  run_server.py inserts that path AFTER mcp so the verified bytes are the bytes
  that run (fixed: PYTHONPATH lost to sys.path.insert; fixed: insert-order
  shadowing).
- Stdio smoke through the loader's invocation: initialize + tools/list give
  the kit's main tool + its health tool. Loader registers them as native tools.

## Findings fixed this audit
1. The kit's docs tree (its build plans/specs) contained cortexagent
   references → removed from the shipped package.
2. The kit's research/browser-ports.json cortexagent strings → remapped
   (twin in mcp/ remapped identically).
3. Stale model/wiring.py + model/setup.py (source twins of compiled .so) →
   deleted; zero .py in core/tools/services/model now (kit-source
   assets excepted — they are site-kit payload data, not exec paths).

## Verification
- build/src/audit.py core tools services mcp model → CLEAN (4 functional
  filter strings documented).
- strings sweep ALL compiled .so: 0 http(s):// URLs, 0 telemetry SDKs,
  0 cortexagent/anthropic/claude/anthropic strings, 0 paths outside
  ~/cortex-agent.
- TUI dist: 0 vendor endpoints; telemetry.js = OTel span wrappers, no
  exporter, no outbound; loads clean under node.
- Registry: the kit's MCP tool hash OK (enabled), memory + research hash OK
  (DISABLED, prepped only — enable is a later owner decision).
- MANIFEST 1562 files (45 kit pins incl. data), 0 failures.
- tests/verify_compiled.py PASS; pytest 29 passed.
- Known remaining, deliberate: vendored node_modules READMEs still flagged by
  the audit engine's known-vendor scan (doc text, unused paths); TUI minify of
  JS dist is a separate follow-up if ever ordered.
Verdict: cortexagent core + shipped tools AUDIT CLEAN.