# Harness Session Handoff Report — for the cortex CLI session

**Date:** 2026-08-13
**From:** the harness session (full tool surface + stub-mode minification + MCP trimming)
**To:** the cortex CLI session (fork Pi → `cortex`, offline, skills cache)

## What this session built

The full harness tool surface for CortexAgent + the minification that makes it
fit the tiny overseer's 2,048-token context. **Nothing in the daemon / overseer /
webui / tray / STT / browser / media / RAG was touched.** The cortex CLI spec's
"out of scope" item — *"MCP minification + readme (other session)"* — is DONE.

## Commits (this session, on master)

| Commit | What |
|--------|------|
| `7118891` | Text-based tool-call fallback — `_parse_text_tool_calls` in `lib/tiny_llm.py` |
| `18c67a9` | `<function_call>` tag format + format-teaching system prompt |
| `6050cbf` | MCP client — `lib/mcp_client.py` (persistent stdio, `mcp_<server>_<tool>`) |
| `4205943` | Browser tools — 9 `brave_*` tools in `lib/browser_tools.py` |
| `82afae2` | Skills system — `lib/skills.py` (loads `~/.cortexagent/skills/`) |
| `ae7afca` | Beautify pass — `lib/beautify.py` (tables + ASCII bar charts) |
| `1744af2` | Harness wiring — `lib/harness_tools.py` `ensure_registered()` + priority ordering |
| `5b9dd89` | Changelog row 36 + design spec `2026-08-13-full-harness-design.md` |
| `f42220d` | **Stub-mode minification** — `list_tools(stub=True)` + backend schema resolution |
| `75fce5b` | README: "MCP servers (optional — off by default)" section |

## Key files the cortex CLI session should know

| File | What it exposes |
|------|-----------------|
| `lib/tool_registry.py` | `register_tool(name, schema, handler, priority)`, `list_tools(limit, stub)`, `get_schema(name)`, `execute_tool(name, args)` — the "indexed database" |
| `lib/skills.py` | Skill format: `NAME` / `DESCRIPTION` / `SCHEMA` / `run(args) -> {"ok","output","error"}`. Loads from `~/.cortexagent/skills/`. **Reuse this exact format for the cortex CLI's `skills.ts` bridge.** |
| `lib/tiny_llm.py` | `_parse_text_tool_calls` — parses text-JSON, ReAct, and `<function_call>` tags into tool_calls. **The models emit `<function_call>` tags — the cortex CLI's tool loop should parse this format.** |
| `lib/react_loop.py` | `STUB_MODE` (default on), `MAX_TOOLS=16`, `classify_mode` (direct/socratic/react) |
| `lib/pre_flight_gate.py` | `classify_intent(prompt)` — the intent classifier the cortex CLI spec plans to reuse for tiny-vs-big auto-switch |
| `lib/beautify.py` | `beautify(text)` — output → tables/charts. Reusable for the cortex CLI's output formatting. |
| `lib/mcp_client.py` | MCP client — **disabled by default** (`CORTEXAGENT_MCP_SERVERS` unset → zero MCP tools load) |

## The minification (the important finding)

The full tool schemas of every MCP server total **~30,000 tokens** — far beyond
the tiny overseer's 2,048 context. Stub mode fixes it:

| Surface | Full schemas | Stub mode | Reduction |
|---------|-------------|-----------|-----------|
| 168-tool MCP surface | ~30,091 tok | ~5,916 tok | **80%** |
| 16-tool default surface | ~1,023 tok | ~377 tok | **64%** |

**How it works:** the model sees only each tool's **name + one-line description**
(~35 tokens vs ~180 full). `execute_tool` resolves the full schema on the
backend — missing required args come back as `missing required args: <params>`
and the model retries; integer/number/string types are coerced. The registry is
the indexed database; the stub is the variable name. This is the user's "tiny
call that calls the large call" idea.

**Env knobs (all documented in README):**
- `CORTEXAGENT_MCP_SERVERS` — comma-separated allowlist; unset = no MCP tools
- `CORTEXAGENT_MAX_TOOLS` — default `16`, cap on the tool surface
- `CORTEXAGENT_TOOL_STUBS` — default `1` (stub mode on); `0` disables
- `CORTEXAGENT_HARNESS_TOOLS` — default `1`; `0` disables browser/skills/MCP

## MCP state (aligned with the cortex CLI spec)

- **MCP is disabled by default** — `CORTEXAGENT_MCP_SERVERS` unset → zero MCP
  tools load. Fully offline / air-gapped works.
- The config stays as the option: `~/.mcp.json` (6 servers: cortexllm, firecrawl,
  magicui, ibkr, alpaca, notebooklm) + `~/.cortexagent/config/lazy_mcp_servers.json`
  (wp-studio). Flip the env var on and they load.
- **slimtoken MCP entry REMOVED** from `~/.mcp.json` — redundant, slimtoken is
  built into the grammar proxy. No local code does MCP calls (verified).
- Fixed 3 broken server entries while in there: `quant-trader` (phantom npm
  package, removed — `ibkr-mcp` covers it), `alpaca` → `alpaca-mcp` (real
  package), `wp-studio` → `wordpress-mcp` (real package).

## Handoff notes for the cortex CLI build

1. **Skill format is already defined** — `NAME`/`DESCRIPTION`/`SCHEMA`/`run(args)`
   in `lib/skills.py`. The cortex CLI's `skills.ts` bridge should call these
   Python modules directly (or via a small shim) — don't invent a new format.
2. **The `<function_call>` tag format is the model contract** — both `:8080` and
   `:8082` are taught to emit it. The cortex CLI's tool loop should parse it
   (Pi's tool loop + `_parse_text_tool_calls` logic).
3. **Stub mode is available for the cortex CLI too** — `list_tools(stub=True)`
   keeps the tool surface tiny; `execute_tool` resolves schemas on the backend.
4. **Intent classifier to reuse** — `pre_flight_gate.classify_intent` for the
   tiny-vs-big auto-switch (the spec already plans this).
5. **MCP stays off** — the cortex CLI should not enable MCP by default. The
   minification + README are done, so enabling later is safe.
6. **Beautify is reusable** — `lib/beautify.py` for output formatting in the
   cortex CLI.
7. **The tool registry is the shared backbone** — if the cortex CLI wants the
   same tools (core + browser + skills), it can import `lib/tool_registry.py`
   directly; `ensure_registered()` is idempotent.

## Verification

- `lib/tool_registry.py --smoke` — PASS (incl. stub tests)
- `lib/react_loop.py --smoke` — PASS (stub mode)
- `tests/run_smoke.py --area harness` — **6/6 PASS** (mcp_client, browser_tools,
  skills, beautify, wiring, stub mode)
- Full gate: 57 ran / 4 FAIL — pre-existing environmental baseline (pii, models,
  proxy, promptqueue), no new failures
