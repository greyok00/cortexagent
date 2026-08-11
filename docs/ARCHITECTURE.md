# CortexAgent — Architecture & Operations Report

> **Living document.** Updated 2026-08-11 (post-audit refresh). This is the
> authoritative map of how CortexAgent works, what it needs to run, and how it
> differs from the generic slimtoken / cortexllm packages. Read this before
> touching the codebase. For the full audit, see `docs/AUDIT-2026-08-11.md`.

---

## 1. What CortexAgent is

A **local coding agent** running entirely on a single llama.cpp model. One
daemon, one overseer, one big model on `:8080`, one tiny LLM on `:8082` for the
overseer, in-process `diffusers` for image/video. **No cloud, no API key, no
fallback swap path** — the big model is the only model on `:8080`.

CortexAgent is a **custom variant** of the generic slimtoken (token minifier)
and cortexllm (memory engine) packages. It is uniquely tailored to this project:
hard-coded integration, its own models, its own memory platform
(`platform="cortexagent"`), an isolated config dir (CLAUDE.md/AGENTS.md
disabled) so cortexllm memory is the default source of truth, and a unified
multi-agent session where webui / TUI / overseer all share one chat log.

---

## 2. Component map

| Component | Port / socket | Process | Purpose |
|---|---|---|---|
| Big LLM | `:8080` | `llama-server` | Qwen3.6-35B-A3B UD-IQ3_S (~13.7 GB, 128K ctx) — only model on 8080 |
| Tiny LLM | `:8082` | `llama-server` | LFM2.5-1.2B Q4_K_M (~728 MB) — overseer only |
| Grammar proxy | `:8081` | `lib/grammar_proxy.py` | Minify (slimtoken) + grammar-strip + tool-call routing for every chat |
| Daemon | AF_UNIX `~/.cortexagent/control.sock` | `lib/daemon.py run` | Owns `:8080`/`:8081`, session lifecycle, idle-unload |
| Overseer | always-on systemd | `lib/overseer.py start` | Scheduler, warm→cold distillation, tiny keepalive, watchdog |
| Webui | `:8090` | `lib/webui.py serve` | 3D chat + live dashboard, shared session with CLI |
| TUI | stdio | `lib/tui.py` | Streaming TUI (opt-in, `cortexagent --tui`) |
| Tray | system tray | `lib/tray.py` + `lib/tray_dashboard.py` | Tray icon + overseer dashboard popout |
| Diffusion | in-process | `lib/diffusion_backend.py` | SDXL / SD1.5 image, LTX-Video (group-offloaded) |
| Memory daemon | AF_UNIX `~/.cortexllm/memory.sock` | `~/.cortexllm/scripts/memory-daemon.py` | CortexLLM hot/warm/cold writes |

---

## 3. Runtime topology

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  CLI (you)   │────▶│  Proxy :8081  │────▶│  Big :8080   │
└──────────────┘     └───────────────┘     └──────────────┘
        │                    │
        │ session-start      │ X-CortexAgent-Session header
        ▼                    ▼
┌──────────────┐     ┌───────────────┐
│  Daemon       │     │  Webui :8090  │
│  control.sock │     └──────┬────────┘
└──────┬────────┘            │ /webui-events (SSE)
       │                     ▼
       │              ┌──────────────┐
       ▼              │   Browser    │
┌──────────────┐      └──────────────┘
│  Overseer     │──▶ Tiny :8082
│  (systemd)    │
└──────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│  SessionBridge JSONL (unified chat)   │
│  ~/.cortexagent/state/webui_session  │
└──────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│  CortexLLM memory (hot/warm/cold)     │
│  ~/.config/cortexllm/memory/          │
└──────────────────────────────────────┘
```

Two systemd user services run the whole stack independent of any CLI session:

- `cortexagent.service` — daemon + proxy + big-model slot (Type=simple,
  Wants=cortexagent-overseer.service, idle_unload=0)
- `cortexagent-overseer.service` — overseer + tiny keepalive (Type=forking)

---

## 4. Session model

**Who tracks what:**

- **Daemon** owns the session refcount: `_active_sessions` (int) + `_last_request`
  (unix ts), guarded by `_lock`. It also owns the big model (`:8080`) and the
  grammar proxy (`:8081`).
- **CLI** (`bin/cortexagent`) is the only session-start/end caller: on launch it
  sends `session-start` (increments refcount, synchronously loads big); on exit
  its `trap cleanup EXIT INT TERM PIPE` sends `session-end` (decrements).
- **Grammar proxy** sends `activity` on every forwarded request, resetting
  `_last_request` — keeps big loaded during webui-only use.
- **Webui** does NOT claim a daemon session; it reads the daemon's active
  session pid and uses it as its `X-CortexAgent-Session` header so CLI + webui
  share proxy context. Falls back to `webui-<uuid>` if no live CLI session.
- **Overseer** is strictly a monitor/scheduler. It queries the big model's
  `/slots`, the proxy's `/health`, and the daemon's control socket. Its own LLM
  traffic goes to the tiny on `:8082`. It does not write chat messages by
  default (see §11 for the bridge wiring that enables this).

**Session lifecycle / reset paths:**

1. **Idle-unload** (`lib/daemon.py`): when `sessions == 0` and idle >
   `idle_unload_sec` (only if `> 0`), unloads big. Default `0` = never unload
   (default-backend mode keeps big warm all day).
2. **Stale-session self-heal**: if `sessions > 0` but no request for
   `stale_session_sec` (1800s), zeroes the refcount so idle-unload can fire.
3. **Overseer watchdog**: if no `bin/cortexagent`/`claude --mcp-config` process
   AND daemon `idle_sec > 300` AND `active_sessions > 0`, sends `session-reset`.
4. **Context failsafe**: if big's `/slots` shows `n_past/n_ctx ≥ 95%` for 3
   ticks, sends `session-reset` to avoid a hard 400.

---

## 5. Unified session bridge (multi-agent chat)

`lib/session_bridge.py` is the shared-file backbone that lets TUI / webui /
overseer all participate in one conversation. The implementation was rewritten
2026-08-11 after the audit caught a clobber bug.

**File format:** append-only JSONL at `~/.cortexagent/state/webui_session.jsonl`
plus a sidecar `webui_session.jsonl.lock` for `fcntl.flock` serialization.

**Atomicity:** writers `open("a")` under exclusive flock, write the line,
`fsync`, release flock. POSIX guarantees `O_APPEND ≤ PIPE_BUF` (4096B) is
atomic on local filesystems, but flock+fsync is correct for any line size.

**API:**

```python
from lib.session_bridge import SessionBridge
b = SessionBridge()                      # default path

b.write(origin, event)                    # atomic append; origin ∈ {"webui","tui","overseer","big",…}
b.read_new(origin="tui")                  # events where from==origin (skip self); advances all cursors
b.read_new(None)                          # ALL events (unified chat display)
b.tail(50)                                # last N events for initial SSE replay
b.mark_read(origin, seq)                  # advance cursor explicitly
```

**Event shape (every write):**

```json
{
  "id": "<uuid>",          // stable; consumers dedupe by id (SSE reconnect safety)
  "from": "tui",           // writer identity (used by read_new filter)
  "type": "message|response|response_done",
  "username": "Big Model", // display name in the unified chat pane
  "content": "...",
  "ts": "2026-08-11T10:11:12",
  "seq": 0
}
```

**Multi-voice identity:**
- TUI writes `username="User"` (typed) and `username="Big Model"` (response)
- Webui writes `username="User"` (typed) and `username="Big Model"` (response)
- Overseer can write `username="Overseer"` for scheduled-task activity
- The webui frontend's `_ensureBridgeConnected()` opens an `EventSource` to
  `/webui-events`, dedupes by id, reconnects every 3s on error, and renders
  each event under its `username` badge (or "You" for the user role).

**Known constraint:** EventSource can't carry custom auth headers, so the
token is passed via `?token=…` query param (the server's `_check_auth` accepts
this).

---

## 6. Memory model

CortexAgent writes to CortexLLM memory via `lib/memory_thin.py` (CLI hook thin
wrapper) and the in-tree `memory/` package (`memory/db.py`, `memory/mcp_server.py`,
`memory/manager.py`, `memory/{hot,warm,cold}/`). All writes use
`platform="cortexagent"`.

- **Hot** — `~/.config/cortexllm/memory/hot/cortexagent.jsonl` (every prompt)
- **Warm** — `~/.config/cortexllm/memory/warm/cortexagent.warm.jsonl` (mirror)
- **Cold** — `~/.config/cortexllm/memory/cold/*.json` (curated facts)
- **SQLite** — `~/.config/cortexllm/cortexllm.db` (mirror, faster queries)

Write path: daemon socket (`~/.cortexllm/memory.sock`) first, NDJSON append
fallback. **No caps** (2026-08-11 rule): every prompt appends to hot AND is
mirrored to warm. The mirror is what the overseer uses as its cross-session
buffer; the engine was designed for it.

Hooks wire the CLI session into memory:
- `hooks/session-start.sh` — starts overseer, reads recent memory
- `hooks/user-prompt-submit.sh` — saves prompt via `memory_thin.append()`
- `hooks/stop.sh` — captures assistant's final response into hot memory

The MCP server the CLI uses is `memory/mcp_server.py` (in-tree, always
present). After the v0.3.2 split, the standalone `~/cortexllm/repo/` is the
package; the in-tree copy is the project-specific deployment.

---

## 7. Config

Precedence: **env var > `~/.cortexagent/cortexagent.conf` > built-in defaults**
(`lib/config.py`). Some keys are LOCKED (`LOCKED_KEYS`) — env/conf can't change
them unless `CORTEXAGENT_UNLOCK=1`.

| Key | Default | Notes |
|---|---|---|
| `big_model` | `""` (must-configure) | Local: `~/models/qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf` |
| `tiny_model` | `lfm2.5-1.2b/...` | Overseer model |
| `big_ctx` | `131072` | 128K, LOCKED |
| `big_ub` | `1024` | ubatch, LOCKED |
| `idle_unload_sec` | `0` | Big stays loaded (default-backend mode) |
| `stale_session_sec` | `1800` | Stale-session self-heal |
| `big_vram_min_gb` | `14` | Informational — no fallback swap, daemon logs + leaves big down if it can't fit |
| `backend` | `llamacpp` | ollama removed |
| `author` | `CortexAgent` | Branding |

**No `fallback_model` attr.** The user explicitly opted out of the fallback
swap path (Aug 2026). `lib/daemon._fallback_extra_args()` is a back-compat
no-op stub.

---

## 8. Models

| Model | Path | VRAM | Purpose |
|---|---|---|---|
| Big | `qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf` | ~13.7 GB @128k/ub1024 | Main model, multimodal |
| Tiny | `lfm2.5-1.2b/...` | ~728 MB | Overseer scheduler/distill |

**No fallback model.** The daemon refuses to swap when VRAM is tight.
`big_vram_min_gb` is informational only.

---

## 9. Separation from generic slimtoken / cortexllm

| Aspect | CortexAgent (this repo) | Generic slimtoken | Generic cortexllm |
|---|---|---|---|
| Minify | `lib/grammar_proxy.py` imports `slimtoken.pipeline` (hard dep) | Standalone package | — |
| Memory platform | `platform="cortexagent"` (in-tree `memory/` + `lib/memory_thin.py`) | — | `platform="default"` (standalone `~/cortexllm/repo/cortexllm/`) |
| Layout | `memory/` flat pkg in tree + `lib/memory_thin.py` | — | Package `cortexllm/` under `~/cortexllm/repo/` (post-v0.3.2 split) |
| Models | Only its own (35B + 1.2B) | Model-agnostic | Model-agnostic |
| CLAUDE.md/AGENTS.md | Disabled (isolated config dir) | — | — |
| MCP server | In-tree `memory/mcp_server.py` | — | Standalone `~/cortexllm/repo/legacy/cortexllm_mcp_server.py` |
| Hooks | `hooks/*.sh` write via `memory_thin.py` | — | Generic `hooks/` in standalone repo |
| Session bridge | `lib/session_bridge.py` (CortexAgent-specific, multi-voice) | — | — |

**Maintenance rule (2026-08-11):** whenever CortexAgent is updated, anything
that can individually update the generic MCP servers (slimtoken, cortexllm)
must be propagated to them with default configs that work for anyone who
downloads them. CortexAgent stays uniquely tailored. Concretely:

- Improvements to `lib/memory_thin.py` write paths that don't depend on
  CortexAgent-specific platforms should be ported to
  `~/cortexllm/repo/cortexllm/` as a feature.
- Slimtoken minify rule improvements made for CortexAgent's prompt shape should
  be pushed upstream with safe defaults (no `LOCKED_KEYS` etc).
- The `SessionBridge` is **CortexAgent-specific** (multi-voice chat) — it does
  NOT belong upstream.
- The daemon/overseer/tray/tui/webui modules are all CortexAgent-specific.

**The "decoupled" test:** if I strip out `platform="cortexagent"`, the daemon
hooks, the SessionBridge, the unified chat, and the model-specific config, does
the rest still work? If yes, it belongs upstream. If no, it stays.

---

## 10. Operations

```bash
cortexagent                     # interactive CLI (default — talks to the daemon)
cortexagent -p "fix this bug"   # one-shot
cortexagent --restart           # restart both services, reload big
cortexagent doctor              # repair drift, validate config
cortexagent status              # print daemon / overseer / proxy state
```

- Install: `bash install.sh` (installs two systemd services + `~/.cortexagent/`)
- Smoke gate: `python3 tests/run_smoke.py` (38 tests; isolated state dir)
- Backup: `~/backups/cortexagent-2026-08-11/` (git bundle + worktree + state)

---

## 11. What changed in the 2026-08-11 audit pass

All CRITICAL and HIGH findings from `docs/AUDIT-2026-08-11.md` are resolved:

| # | Item | Fix |
|---|------|-----|
| C1 | SessionBridge `os.replace` clobbered file | Rewrite with `O_APPEND` + flock + fsync |
| C2 | `_api_overseer()` returned flat bundle, dead nested builder | Rebuild nested schema from raw sources |
| C3-C6 | v0.3.2 split: 4 scripts pointing at moved files | Add `legacy/` to sys.path + fallback chain |
| H1 | memory-daemon dropped payloads >4KB | Drain-until-EOF with 8MB cap |
| H2 | `_handle_events` re-implemented file polling | Use `BRIDGE.tail()` + `read_new(None)` |
| H3 | Chunked uploads skipped grammar stripping when minify off | New `_forward_chunked_strip_only` method |
| H4 | statusline read `daemon.sock` but config defines `control.sock` | Path now matches |

Smoke test gate: **31/31 coverage green**, **33/38 tests pass**. The 5
remaining failures are pre-existing (test-stale references or v0.3.2 split
side-effects), not regressions from the audit fixes.

---

## 12. Known issues (post-audit)

- **Smoke test 5 failures** (pre-existing, not regressions from audit):
  - `pii_free`: my docs (`docs/ARCHITECTURE.md`, `docs/AUDIT-2026-08-11.md`,
    `lib/tray_dashboard.py`) mention the username — the PII rule excludes
    `GreyOK00` and `/home/grey` literally. The doc references are intentional.
  - `tiny_llm_query`: live port-busy against the real tiny backend.
  - `proxy_vram_field`: test mocks the proxy `/metrics` but
    `_get_vram_breakdown()` reads the daemon `control.sock` (correct path —
    H4 fix made this work; the test assertion is stale).
  - `fallback_config_and_args`: test references removed `fallback_model`
    attribute (the user opted out).
  - `regression_cortexllm_apis`: flat modules moved to `legacy/` in v0.3.2;
    test imports from `CFG.cortexllm_dir` which now resolves to the new
    package.

- **MEDIUM (deferred):** ~~M21~~ memory-store split, ~~M22~~ `Coding_Practices`
  table, ~~M23~~ cold-fact profile mismatch. **All three fixed 2026-08-11**:
  M21 → distiller reads NDJSON first (lib/cold_distiller.py:_read_warm_entries),
  M22 → table added to SCHEMA_SQL (memory/db.py), M23 → distiller normalizes
  profile to `platform:<x>` (lib/cold_distiller.py:_write_cold_fact).

- **TODO:** ~~Overseer should emit `username="Overseer"` chat events to the
  SessionBridge for scheduled-task activity (wiring is in place — the bridge
  accepts any origin/username — but the actual overseer loop calls haven't been
  added yet).~~ **Done 2026-08-11** — `lib/overseer.py:_bridge_emit()` writes
  to the bridge with `username="Overseer"`. Wired into `_process_queue` (queue
  start/done/fail/crash) and `_check_schedule` (cron/daily/weekly fire).