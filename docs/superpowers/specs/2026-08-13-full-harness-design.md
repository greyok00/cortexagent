# CortexAgent Full Harness — MCP Client + Browser Tools + Skills + Beautification

**Date:** 2026-08-13
**Status:** Design (approved by user direction — all four pieces selected)

## Goal

Extend CortexAgent into a full agent harness on par with opencode/openclaw. The
overseer react loop becomes the general agent loop: it can call tools from MCP
servers, browser automation, and skills; its output passes through a
beautification pass that renders tables and charts. Everything is modularized
into skills and MCP servers (like slimtoken and cortexllm).

## Architecture

**Overseer = the agent loop** (existing react/socratic/direct loop in
`lib/react_loop.py`). It loads the big model, proxies through it, runs the
react/socratic/realism framing passes, calls RAG/tools/memory, and minifies
input/output. The new pieces feed tools into this loop and beautify its output:

| Component | File | Role |
|---|---|---|
| MCP client | `lib/mcp_client.py` | Connect to MCP servers (stdio), register their tools as `mcp_<server>_<tool>` |
| Browser tools | `lib/browser_tools.py` | Register the 9 `brave_*` tools directly (wrap `browser_control`, no MCP round-trip) |
| Skills | `lib/skills.py` | Skills registry + directory loader; each skill registers as `skill_<name>` |
| Beautification | `lib/beautify.py` | Post-process overseer output into markdown tables + ASCII/HTML charts |
| Wiring | `lib/harness_tools.py` | Idempotent `ensure_registered()` — registers browser + skills + MCP tools once |

## Components

### 1. `lib/mcp_client.py` — MCP client

- `load_servers()` — read `~/.mcp.json` (standard `mcpServers` format) + `~/.cortexagent/config/lazy_mcp_servers.json` (list format). Env override: `CORTEXAGENT_MCP_CONFIG`, `CORTEXAGENT_MCP_SERVERS` (comma-separated allowlist).
- `register_mcp_tools()` — for each server, list tools (spawn once), register each as `mcp_<server>_<tool>` in the tool registry. Returns count.
- `_call_server_tool(server, name, args)` — spawn, call, shutdown; returns `{"ok", "output", "error"}`.
- Uses the `mcp` library (`ClientSession`, `stdio_client`) with a **persistent background event loop** + per-server session cache (no per-call spawn churn — the react loop may call a tool several times).
- **Failure-tolerant:** a server that fails to init is skipped with a stderr note, never fatal to the loop.

### 2. `lib/browser_tools.py` — Playwright/browser tools

- `register_browser_tools()` — registers `brave_status`, `brave_tabs`, `brave_navigate`, `brave_fetch`, `brave_click`, `brave_type`, `brave_evaluate`, `brave_snapshot`, `brave_fill_send`.
- Wraps `lib/browser_control` functions directly (same schemas as `playwright_brave_mcp.py`'s `TOOLS`).
- Direct function calls — no MCP server process needed.

### 3. `lib/skills.py` — Skills system

- `register_skill(name, description, schema, run)` — add a skill at runtime.
- `load_skills_dir(path)` — load skill modules from a directory (default `~/.cortexagent/skills/`). Each module exposes `NAME`, `DESCRIPTION`, `SCHEMA`, `run(args) -> {"ok", "output", "error"}`.
- `register_skill_tools()` — register each loaded skill as `skill_<name>` in the tool registry.

### 4. `lib/beautify.py` — Beautification pass

- `beautify(text)` — post-process overseer output:
  - Normalize markdown tables (align columns, fix pipes).
  - Convert CSV/TSV blocks to markdown tables.
  - Convert `key: value` blocks to tables.
  - Render simple numeric series as ASCII bar charts.
- `beautify_html(text)` — HTML/SVG variant for the webui.
- Pure functions — no server, no side effects.

### 5. `lib/harness_tools.py` — Wiring

- `ensure_registered()` — idempotent; registers browser + skills + MCP tools once (module-level flag).
- Called from `react_loop.run_react` before `list_tools()` so the loop sees the full tool surface.
- `CORTEXAGENT_HARNESS_TOOLS` env (default `1`) to disable.

## Testing

- Each module has a `--smoke` self-test.
- `beautify` + `skills` + `browser_tools` registration are pure/offline (no server).
- `mcp_client` tested against a fake stdio MCP server (inline test server) — no external deps.
- Browser tools: graceful skip if Brave CDP unreachable.
- Smoke gate: new areas appended to `tests/run_smoke.py` (append-only constraint honored).

## Constraints

- Shared files append-only: `tests/run_smoke.py`, changelog.
- No STT files touched (`lib/stt.py` READ/IMPORT ONLY).
- Localhost-only bindings (nothing on 0.0.0.0).
- Lazy + failure-tolerant: optional servers must never break the react loop.
- Explicit-file-list commits only; no `git add -A`.
