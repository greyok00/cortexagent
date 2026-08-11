# cortexllm v0.4.0 — CortexAgent divergence tracker

> **Live tracking document.** Updated 2026-08-11. Tracks what the other
> session is shipping in cortexllm v0.4.0 and what cortexagent needs to
> do after it ships. **Read this on next session resume** before touching
> any cortexagent file that touches memory.

---

## Quick reference

| Field | Value |
|---|---|
| Cortexllm version going from → to | `v0.3.3` → `v0.4.0` (major bump) |
| Branch / repo | `~/cortexllm/repo/` (master) |
| Other session's brief | `~/cortexllm/repo/MAJOR_UPDATE_BRIEF.md` §9 |
| Other session's plan | 9 modules, ~990 lines, stdlib-only, 4 phases |
| Other session won't touch | `~/cortexagent/` (their words: "I'll stay out of your tree entirely") |
| Cortexagent pin strategy | **Don't pin yet** — let v0.4.0 ship first |

---

## What the other session is shipping

### 9 new modules (all stdlib-only)

| Module | Source derived from | Notes |
|---|---|---|
| `cortexllm.stats` | `lib/overseer.py:_get_memory_stats` + `_estimate_tokens` | drop-in replacements, bytes/entries/per-platform/cold/est tokens |
| `cortexllm.integrity` | `lib/overseer.py:_check_db_integrity` + `_check_memory_writes` | NDJSON line-by-line validity, truncation detect |
| `cortexllm.scheduler` | `lib/overseer.py:_cron_matches` + `schedule_*` + `_check_schedule` (150 lines) | 5-field cron + aliases (`@hourly/daily/weekly/monthly`) |
| `cortexllm.queue` | `lib/overseer.py:queue_add/list/clear/remove` | persistent JSON task queue, tmp+rename writes |
| `cortexllm.plan` | `lib/overseer.py:plan_set/step/status/complete` | persistent numbered-step plan state |
| `cortexllm.dag` | `engine/dag.py` | near-verbatim port, already clean |
| `cortexllm.workflow` | `engine/workflow.py` (engine shell only) | generic engine, `Executor` protocol. **Templates stay in cortexagent** |
| `cortexllm.lifecycle` | `lib/overseer.py:_is_running/_start/_stop` | `SingleInstance(pidfile)` + `daemonize()` |
| `cortexllm.atomic` + `cortexllm.drain` | `lib/memory_thin.py:_atomic_append` + `~/.cortexllm/scripts/memory-daemon.py:handle_client` | public `atomic_append(path, line)` + `drain_lines(conn, max_bytes)` |

### Modules that stay in cortexagent (DO NOT propagate)

| CortexAgent file | Why it stays |
|---|---|
| `engine/workflow.py:_deploy_website_tasks` | template, not engine |
| `engine/workflow.py:_pentest_tasks` | template, not engine |
| `engine/workflow.py:_malware_analysis_tasks` | template, not engine |
| `engine/_run_shell_command` | hardened shell wrapper, user-customized |
| `lib/overseer.py` (rest) | 35B model glue, daemon protocol, watchdog → CortexAgent-specific |
| `lib/daemon.py` | 35B keepalive, no-fallback-swap policy |
| `lib/grammar_proxy.py` | wraps slimtoken + LOCKED_KEYS |
| `lib/session_bridge.py` | multi-voice UX |
| `lib/memory_thin.py` | thin CLI hook wrapper, can opt-in to new `cortexllm.atomic` but not required |
| `memory/mcp_server.py` (in-tree) | knows `platform="cortexagent"` |

### Phases (other session's commit cadence)

| Phase | Scope | Wall-time | Commit signal |
|---|---|---|---|
| A | atomic, drain, lifecycle, stats, integrity | ~30 min | small pure modules |
| B | scheduler, queue, plan | ~30 min | state + dispatch |
| C | dag, workflow | ~45 min | needs care |
| D | MCP tools, README, smoke, version bump, tag, push | ~30 min | `v0.4.0` in commit message |

Other session does all 4 phases in one pass without stopping. Watch
`~/cortexllm/repo/` master for `v0.4.0` commits.

---

## CortexAgent divergence — what we MUST do after v0.4.0 ships

### Required updates (blocking)

1. **Verify fallback chain in `cortexllm/start-cortexllm-mcp.sh`** — the
   script checks (in order) `~/cortexllm/repo/cortexllm_mcp_server.py`
   (flat legacy), `~/cortexllm/repo/legacy/cortexllm_mcp_server.py` (old
   legacy), `~/cortexllm/repo/cortexllm/mcp_server.py` (new package).
   After v0.4.0:
   - If new package's `mcp_server.py` is the canonical path, the new
     fallback chain should resolve to it.
   - If the new package DOES NOT re-export the old `cortexllm_mcp_server.py`
     flat module, the legacy fallback MUST stay (or we break older cortexagent
     installs).
   - **Action:** read the v0.4.0 `README.md` installation section, confirm
     the recommended path, verify the script's order.

2. **Re-test `lib/config.py:_detect_cortexllm_dir`** — vendored fallback
   paths may need adjustment if v0.4.0 renames/moves vendored modules.
   The 3-tier preference (env `CORTEXLLM_DIR` > `~/cortexllm/repo` > vendored)
   should still work since the new modules are in the same `cortexllm/`
   dir. **Action:** grep `_detect_cortexllm_dir` for the module list, no
   changes needed unless v0.4.0 changes the vendored shape.

3. **Run cortexagent smoke gate** — `python3 ~/cortexagent/tests/run_smoke.py`.
   Baseline: 31/31 coverage + ≥33/38 tests. The 5 known pre-existing
   failures (in `docs/ARCHITECTURE.md` §12) should NOT shift.

### Optional migrations (non-blocking, do at leisure)

- `lib/memory_thin.py:_atomic_append` → `from cortexllm.atomic import atomic_append`.
  One-line change. Same semantics. Switch when convenient.
- `lib/overseer.py:_get_memory_stats` → `from cortexllm.stats import memory_stats`.
  Same idea. Hold off until the new module's signature is verified.
- `lib/overseer.py:_check_db_integrity` + `_check_memory_writes` →
  `from cortexllm.integrity import check_ndjson`.
- `lib/overseer.py:queue_*` → `from cortexllm.queue import Queue`.
- `lib/overseer.py:plan_*` → `from cortexllm.plan import Plan`.
- `lib/overseer.py:_cron_matches` + `schedule_*` → `from cortexllm.scheduler import Schedule`.
- `engine/dag.py` → `from cortexllm.dag import DAG`. (Already clean, near-verbatim.)
- `engine/workflow.py` → `from cortexllm.workflow import Executor` + refactor templates.
  This is the biggest opt-in refactor. Not required.

### Don't touch

- **Anything in `lib/daemon.py`** — daemon policy is CortexAgent-specific.
- **`lib/session_bridge.py`** — multi-voice UX, stays.
- **`memory/mcp_server.py` (in-tree)** — knows `platform="cortexagent"`.
- **systemd units, `install.sh`, `bin/cortexagent`** — CortexAgent-specific.

---

## Test target after v0.4.0 lands

| Suite | Command | Expected | If fails |
|---|---|---|---|
| cortexllm unit | `python3 -m pytest ~/cortexllm/repo/tests/` | 49/49 (was 19/19) | Read fresh CHANGELOG; update CortexAgent imports if API changed |
| cortexllm smoke | `python3 -m cortexllm.smoke` | (new in v0.4.0) | New module integration check |
| cortexagent smoke | `python3 ~/cortexagent/tests/run_smoke.py` | 31/31 + ≥33/38 | 5 known failures should NOT shift; investigate new ones |
| cortexagent end-to-end bridge | inline `BRIDGE` SSE test | `bridge OK` | Re-check `lib/webui.py:_check_auth` parity with other session's MCP server |

---

## Communication protocol

- **My side (cortexagent):** this document. Append updates under §`cortexagent-divergence` below.
- **Other side (cortexllm):** `~/cortexllm/repo/MAJOR_UPDATE_BRIEF.md` §9 (their plan), §10 (what shipped), §11 (cortexagent follow-ups), §12 (smoke result).
- **Sync point:** when their §10 lands, glob for `v0.4.0` in the git log on `~/cortexllm/repo/`, then read §10/§11/§12 and execute the required updates above.

---

## cortexagent-divergence — running notes

### 2026-08-11 initial
- Brief received from other session. 9 modules, ~990 lines, 4 phases.
- Other session confirmed: won't touch cortexagent tree.
- Action: opened this tracker. No code changes yet. Waiting for v0.4.0 commits.

<!-- Append new dated entries below as the other session ships phases. -->
