# MCP/tool hardening pipeline — gate record (2026-10-24)

Owner order: all tools enter cortexagent ONLY through the pipeline ("it must work").
The analysis-browser kit (now retired and removed) stayed a SEPARATE MCP server
(roll-in ordered, then reversed — core/ tree was never authoritative).

## Pipeline (scripts/convert_mcp_to_so.py)
fetch/copy → minify+decomment (refuses unparseable) → strip_telemetry --apply →
strip_external_links --apply (STRICT allowlist in ingest mode: every URL that is
not localhost/private is commented out — unknown domains are guilty) → Cython
multi-module compile (annotation_typing off) → registry entry DISABLED ->
MANIFEST sha256 → enable only after hash verify. Refusal of any stage leaves
ZERO residue (no half-minified tree, no stale .so).

## Defects found and fixed in this session
1. strips were SILENT NO-OPS on ingested trees — UnboundLocalError on the
   --root path, swallowed by capture_output (fixture: posthog/sentry survived).
2. strip by deletion inside a def → empty body SyntaxError; now same-indent
   `pass`.
3. endpoint strip was known-vendor regex → unknown collector domains passed;
   ingest mode is now allowlist-only.
4. _fetch kept source folder name vs pipeline name (mis-compile/refuse).
5. __main__.py entry (Cython can't compile it); entry rule is now <name>.py.

## Proof (fixture E2E, dirty server: telemetry SDKs + unknown collector + unknown AI endpoint + unparseable file)
- unparseable extra file → REFUSED, zero residue.
- full run → converted; .so strings contain ZERO urls beyond none, ZERO
  telemetry SDK names; posthog/sentry/collector/AI endpoints absent.
- registered DISABLED, sha256 db2ffc5c…f8d1; fixture removed after proof.

## Shipped-set leak sweep (mcp/*.so, all 25 analysis-browser kit modules)
`strings` scan: 0 http(s):// strings of any kind; 0 telemetry SDK names.

## Gate results
- build/src/audit.py engine: strips + audit share ENDPOINTS/banned-word law.
- verify_compiled.py: PASS. pytest: 29 passed. MANIFEST: 1503 files, hash policy
  by-size for >64 MB vendored libs (by design).

## Known remaining surface (task backlog, not this task)
audit.py fail-list noise: dist/deb copies, vendored node_modules openai/anthropic
READMEs + SDK libs, tui harness telemetry.js, MANIFEST self-strings. Real
hardening of the TUI harness telemetry path is its own task.