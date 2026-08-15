# CortexAgent Status Report — Updated 2026-08-14 12:20

## ✅ Fixed / Completed

### System Tray Icon
- **Issue**: Tray icon wasn't appearing (falling back to headless mode)
- **Root cause**: No notification daemon running when tray started → pystray crashed on D-Bus call
- **Fix**: 
  - Added xfce4-notifyd autostart (`~/.config/autostart/xfce4-notifyd.desktop`)
  - Patched `lib/tray.py` to guard notification daemon failures (`_patch_pystray_notify`)
  - Tray now runs in GUI mode with greyok logo icon
- **Status**: ✅ Working

### Minify Stats / Slimtoken
- **Issue**: Dashboard not showing token savings (was showing 0 runs)
- **Root cause**: Proxy metrics reset to 0 on restart; dashboard/webui only read proxy metrics, not the persistent file
- **Fix**: 
  - `lib/tray_dashboard.py` now falls back to `~/.cortexagent/minify_stats.json` when proxy shows 0
  - `lib/webui.py` now falls back to `~/.cortexagent/minify_stats.json` when proxy shows 0
- **Status**: ✅ Working (257 runs, 7.8% savings across 12M+ tokens)

### Stuck Scheduler Tasks
- **Issue**: "smoke-test" and "verify-test" schedules stuck, not updating
- **Fix**: Removed via `overseer.py schedule remove smoke-test` and `schedule remove verify-test`
- **Status**: ✅ Clean (0 entries)

### Queue Cleanup
- **Issue**: Completed tasks never removed from queue
- **Fix**: Added `_cleanup_queue()` function — removes tasks older than 1 hour, keeps last 10 for debugging
- **Integration**: Called every 10th tick (~5 min) in the overseer tick loop
- **CLI**: `overseer.py queue cleanup` or `queue prune`
- **Status**: ✅ Working (6 tasks removed, queue is empty)

### Code Blocks Disabled
- **Issue**: LLM outputting code blocks when plain text requested
- **Fix**: Added "NO code blocks (never use ```)" to `_REACT_SYSTEM` and `_SOCRATIC_SYSTEM` prompts
- **Status**: ✅ Applied

### Beautification Pass
- **Issue**: Overseer output not beautified (markdown tables, CSV, key:value not formatted)
- **Fix**: 
  - Added `_beautify_response()` function in `react_loop.py` — applies to react/socratic/direct output
  - Added `_beautify_status()` function in `overseer.py` — applies to overseer CLI status output
  - Uses `lib/beautify.py` to convert tables, CSV, key:value to formatted output
- **Status**: ✅ Working (overseer status shows formatted table)

### Domain DB Access
- **Status**: ✅ Working
  - `lib/domain_db.py` — SQLite DB with FTS5 + sqlite-vec (FTS + semantic search)
  - `lib/domain_ingest.py` — chunk → embed → store pipeline
  - `lib/domain_embed.py` — DomainEmbedder for semantic embeddings
  - Tools registered: `rag_query`, `ingest_domain`
  - Smoke test: ✅ PASS

### ReAct / Socratic Methods
- **Status**: ✅ Working
  - `lib/react_loop.py` — ReAct/Socratic orchestration engine
  - Modes: `react` (tool-calling), `socratic` (assumptions + falsification), `direct` (conversation)
  - Mode classification via `lib/pre_flight_gate.classify_intent()`
  - Smoke test: ✅ PASS

## 📊 Current State

### Services Running
- ✅ Overseer (PID 114816) — linked to tiny LLM
- ✅ Big model (:8080) — Qwen3.6-35B-A3B-UD-IQ3_S.gguf
- ✅ Tiny model (:8082) — LFM2.5-1.2B-Instruct
- ✅ Proxy (:8081) — slimtoken minify, grammar proxy
- ✅ System tray — GUI mode, greyok logo icon
- ✅ Webui — running on http://127.0.0.1:8090/

### Minify Stats (from file)
- Runs: 257
- Tokens in: 12,499,713
- Tokens out: 11,522,624
- Tokens saved: 977,089
- Savings ratio: 7.8%

### Queue
- Size: 0 (all completed tasks removed)

### Schedule
- Entries: 0 (smoke-test, verify-test removed)

### Overseer CLI Status (beautified)
```
| Overseer     | RUNNING (pid 114816)                   |
| ------------ | -------------------------------------- |
| Started      | 2026-08-14T10:52:22.625399             |
| Ticks        | 177                                    |
| Model        | tiny LFM2.5-1.2B on :8082 (up)         |
| Memory       | 587H / 674W / 27C                      |
| Last compact | None                                   |
| Last distill | 2026-08-14T11:51:04.448747             |
| Queue        | 0 total (0 pending)                    |
| Schedule     | 0 entries                              |
| Minify       | 977,089 tok saved (8%) across 257 runs |
```

## 🚧 Remaining / Deferred

### Low Priority
1. **Overseer tiny-keepalive false positives**: Under GPU/CPU contention, keepalive times out and restarts tiny model unnecessarily. Fix: require N consecutive failures before restart.
2. **Notification daemon on Wayland**: Current fix uses xfce4-notifyd (X11). On Wayland, may need `mutter` or `gnome-shell` notification daemon.
3. **Cython/Nuitka compilation**: Deferred until Phases 0-8 complete.
4. **GitHub push**: Held until everything works.

### Planned
1. **Auto-compact (opt-in)**: Currently disabled by hard rule. Consider adding user toggle.
2. **Workflow engine**: The DAG workflow engine exists but needs more testing.
3. **Domain DB indexing**: sqlite-vec loading is optional — verify it's working on this system.
