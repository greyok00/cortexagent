# CortexAgent — module reference (read on demand)

Rules + memory live in `config/CLAUDE.md`. All modules stdlib-only; verify with `python3 lib/<name>.py smoke`.

- `profiles.py` — per-profile dirs under `~/.cortexagent/profiles/<n>/{state,memory,workspace,sandboxes,logs}`.
- `loop_guard.py` — detects repeated failures/retries; state in `profiles/<n>/state/loop_guard.json`.
- `anti_hallucination.py` — verifies CLI/path/service before use; config `config/verification.json`.
- `pre_flight_gate.py` — pre-LLM checks (empty/budget/iter-cap/memory); informational.
- `post_response_verifier.py` — scans output for secrets/PII/API keys, JSON/code validity.
- `context_pruner.py` — token-budget RAG + summarization over warm/cold data.
- `dom_pruner.py` — strips script/style/nav/footer/aria/data attrs from HTML.
- `cold_distiller.py` — warm→cold fact extraction.
- `heartbeat_service.py` — session health (msg count, size, status).
- `overseer.py` — heartbeat + tiny keepalive + the **single** inlined task queue + scheduler (#32; `orchestrator.py`/`scheduler.py`/`dispatcher.py` were deleted as zero-importer dead code).
- `webui.py` — HTTP UI on `127.0.0.1:8090`.
- `firecrawl_proxy.py` — lazy 1-tool Firecrawl MCP wrapper.
- `playwright_brave_mcp.py` — Brave CDP tools: `brave_status`, `brave_navigate`, `brave_fetch`, `brave_click`, `brave_type`, `brave_evaluate`, `brave_snapshot`.
- `humanize.py`, `reliability.py` — timing, retry/circuit-breaker.

Mutating ops only when user asks.
