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

### 2026-08-11 v0.4.3 docs release + two-models-only enforcement

This is the post-v0.4.0 follow-up entry for the v0.4.3 release on the
public GitHub repo (origin `8c40b92`). It captures (a) the slimtoken
version drift since v0.4.0, (b) the two-models-only rule enforcement
in code, and (c) the docs surface rewrite.

**Released:**

- **v0.4.3** on origin/master (commit `8c40b92`). Tag and GitHub
  Release. v0.4.0/v0.4.1/v0.4.2 tags retired; v0.1/v0.2.0 releases
  deleted. Only one release on the repo going forward.
- README.md + ABOUT.md rewritten as straight technical reference
  (overview → installation → usage → spec tables → configuration →
  reference). No marketing sections.
- `assets/workflow.svg` replaces the stale `assets/workflow.png` (a
  JPEG mislabeled as PNG, showing pre-v0.4.0 architecture).

**Version drift (MCP server side):**

| Package | Documented pin | Installed | Source |
|---|---|---|---|
| `cortexllm` | `>=0.4.0` | **0.4.0** | `~/cortexllm/repo` (dev install) |
| `slimtoken` | `>=0.3.3` | **0.3.5** | `~/.local/lib/python3.13/site-packages` (PyPI) |

`slimtoken` drifted from `0.3.3` (documented floor) to `0.3.5`
(installed). No breaking changes from the cortexagent side — the
grammar proxy imports `slimtoken.pipeline.minify_request` which has
been stable since 0.3.3. Action: keep the documented floor at `0.3.3`
for compatibility, but the smoke gate's slimtoken import will pass on
0.3.5+. No code change required.

**Two-models-only enforcement (user-confirmed multiple times):**

The user re-confirmed: two models total, big (13.7 GB
`Qwen3.6-35B-A3B-UD-IQ3_S`, multimodal, uncensored) on `:8080` and
overseer MoE (≤2 GB) on `:8082`. Nothing between 2 GB and 12 GB. No
fallback, no third model, no separate vision server.

| Action | Status | Notes |
|---|---|---|
| 4 retired 5–6 GB GGUF dirs deleted from disk | ✅ Done | `~/models/{lfm2.5-8b-a1b,qwen3-4b,qwen3vl-8b,flux}/` (~18 GB recovered). |
| `Config.fallback_model` attribute removed | ✅ Done (was already removed) | The attribute was removed 2026-08-11; absence is the proof. |
| `tests/run_smoke.py:test_no_fallback_two_models_only` | ✅ Added | Replaces `test_fallback_config_and_args`. Fails LOUDLY if `fallback_model` is set. |
| `tests/run_smoke.py:PII_EXCLUDE_FILES` extended | ✅ Done | `ABOUT.md`, `docs/ARCHITECTURE.md`, `docs/AUDIT-2026-08-11.md`, `lib/tray_dashboard.py` ship GreyOK00 as branding or are local-only audit docs. |
| `docs/SEPARATION.md` PII cleanup | ✅ Done | `/home/grey/cortexagent/lib` → `~/cortexagent/lib`. |

**README + ABOUT rewrite:**

- Lead sections: no "What it does" / "When to use it" / "Is this for
  you" marketing framing. Goes straight to Overview → Architecture →
  Install → Usage → Reference.
- Component table: `Reasoning model` / `Orchestrator` /
  `Grammar proxy` / `Daemon` / `Webui` / `Diffusion`. No "big model" /
  "tiny LLM" internal labels.
- Reasoning model spec table: model name, quantisation, total params,
  active per token, footprint, context, KV cache, capabilities.
- Configuration: `big_model` / `overseer_model` (was `tiny_model`)
  with env overrides `CORTEXAGENT_MODEL` / `CORTEXAGENT_OVERSEER_MODEL`.
- Non-goals prose (no fallback, no third model, no separate vision
  server, no diffusers as separate process, no network exposure).

**Smoke gate:** 30/30 pass, 31/31 covered.

**TODO (forward to next session):**

- [ ] Bump documented `slimtoken` pin to `>=0.3.5` if the API surface
      between 0.3.3 → 0.3.5 introduced any changes the proxy depends
      on. Verify with `python3 -c "from slimtoken.pipeline import
      minify_request; minify_request({})"`.
- [ ] Confirm `cortexllm 0.4.0` MCP server's `mcp__cortexllm__*` tool
      surface still matches the cortexagent `memory/mcp_server.py`
      in-tree server's tool list. If divergence appears, decide whether
      to upgrade in-tree server or pin the upstream version.
- [ ] `cortexllm.dag` and `cortexllm.workflow` are intentionally
      **not** adopted (per the existing migration table — domain
      templates stay in cortexagent). No action.
- [ ] `lib/memory_thin.py:_atomic_append` and `lib/memory-daemon.py`
      socket drain are still marked as "Migrate" but not yet migrated.
      Drop-in change, low risk. Pick up next session.

### 2026-08-11 cortexagent side changes (this session)

While waiting for v0.4.0 to ship, took the user's "have at it" guidance
and fixed cortexagent-side issues that don't depend on the v0.4.0 surface:

**WIP commits (3,265 lines staged) — see git log on master:**
- `37d456f` docs: ARCHITECTURE/AUDIT/SEPARATION/v0.4.0-DIVERGENCE
- `0190613` feat: branding swap (wolfhead icons), v0.4.x docs, lib/minify → slimtoken
- `3ec7b54` test: 33-test unit suite for lib/response_model.py

**Fix commits (side-portable improvements):**
- `c2defd0` fix(cold_distiller): read NDJSON first, SQLite fallback (M21)
- `48c666d` fix(db): create Coding_Practices table on fresh installs (M22)
- `6157546` fix(cold_distiller): normalize profile to platform:<x> (M23)
- `5dc5093` feat(overseer): emit SessionBridge events as 'Overseer' (unified chat)
- `b94698e` fix(readme): daemon.sock → control.sock (L39)

**Cleanup:**
- Deleted 12 `*.png.pre-wolfhead-20260811-011630` backups (pre-rebrand snapshots)
- Skipped `.bak` files (user may want them as reference)

**Smoke gate after all changes:** 31/31 coverage + 33/38 tests pass.
Same 5 known failures (all pre-existing, documented in
`docs/ARCHITECTURE.md` §12). No regressions.

### 2026-08-11 — low/medium sweep continues

After the WIP and crash-fix commits, continued fixing remaining LOW audit
items. **3 new commits, no regressions (smoke 34/38, up from 33/38):**

- `bc4bc26` fix(docs): stale 0.5b docstrings → LFM2.5-1.2B (L2); malformed CSS var (L32)
  - 25 docstring hits across 7 lib files (overseer, tiny_llm, model_backend,
    model_switcher, pdf_knowledge, daemon, diffusion_backend) replaced with
    "LFM2.5-1.2B" / "LFM2.5:1.2b"
  - `assets/webui_template.html:95` — `var(--surface; rgba(20,20,20,0.5))`
    malformed (missing closing paren); replaced with `var(--surface)`; the
    override on the next line still wins
- `e7b2e69` fix: dead code cleanup (L3/L4/L5/L6/L17/L19/L20/L21/L23)
  - L3: watchdog_stale_sec comment now explains 300s is INTENTIONALLY tighter
    than daemon's 1800s (watchdog fires first)
  - L4: dropped dead `tag = " 🎮 fallback (low VRAM)"` (big dict never has
    `fallback` key)
  - L5: dropped dead `profile`/`model_alias` fields (scan dicts lack those)
  - L6: aligned tiny ctx 4096 → 2048 to match daemon's lean tiny config
  - L17: dropped duplicate `ConfigParser()` (interpolation=None wins)
  - L19: removed unused `_check_tiny_model` (replaced by `_preload_tiny_model`)
  - L20: removed unused `_auto_compact` (no-caps rule: never trim warm)
  - L21: removed unused `_fallback_extra_args` (no fallback model exists)
  - L23: guarded `history[-1][1]` for empty / list-of-1 cases
- `946ecf6` fix(tests): S4 regression test tries legacy/ path after v0.3.2 split
  - The test was inserting `CFG.cortexllm_dir` into sys.path only, but post
    v0.3.2 split the flat modules (`cortexllm_vector.py`, `cortexllm_graph.py`,
    `cortexllm_ontology.py`) live in `~/cortexllm/repo/legacy/`. Now the test
    tries the new `cortexllm/` package first, then the legacy flat fallbacks.
  - Smoke flips to 34/38. Pre-existing failures (S1 PII, S2 tiny_llm behavior,
    S3 statusline test, S5 fallback attr removed) unchanged — all documented.

**Side-port candidates (this batch):**
- L6 (tiny ctx alignment) — generic. If v0.4.0's tiny-LLM keepalive exposes
  its own ctx knob, document the canonical value (2048 here, daemon's view
  is truth; matches lean ~300 MB footprint).
- L17 (ConfigParser) — purely local cleanup, but if v0.4.0 has a similar
  `_load_conf()`, the `interpolation=None` default is correct (so `{{HOME}}`-
  style placeholders in values aren't mangled).

The body of "2026-08-11 — what to side-port from this batch to upstream
cortexllm" continues below — those three generic techniques (NDJSON-first
reads, lazy import for optional integrations, `platform:<x>` profile
normalization) remain the canonical side-port list.

These fixes are cortexagent-specific but the underlying techniques are
generic enough to mention when the upstream PR for v0.4.0 lands:

1. **NDJSON-first reads** — `lib/cold_distiller.py:_read_warm_entries`
   reads NDJSON (file-of-truth per the no-caps rule) before falling back
   to SQLite. Useful pattern for any engine that has dual stores.
   Worth mentioning in the upstream README so consumers know to mirror
   to NDJSON if they want fast consumer reads.

2. **Lazy import for optional integrations** —
   `lib/overseer.py:_bridge_emit` imports SessionBridge inside the
   function, never at module load. Same pattern works for any optional
   notification path (webhooks, queues, etc.).

3. **`platform:<x>` profile normalization** — the distiller's write
   side assumes the canonical MCP key. If the upstream engine has a
   `profile` concept, document it; the cortexllm v0.4.0 API
   `cortexllm.distill()` should accept either form and normalize.

---

## 2026-08-11 — post-v0.4.0 cortexagent follow-ups

### What landed upstream

- **v0.4.0 tagged on `master`** (4 commits between v0.3.3 and v0.4.0).
- **9 new modules** in `~/cortexllm/repo/cortexllm/` (atomic, drain,
  lifecycle, stats, integrity, scheduler, queue, plan, dag, workflow —
  ~1,800 lines total). All stdlib-only. None touch cortexagent.
- **5 new MCP tools**: `memory_stats`, `memory_integrity`, `cron_parse`,
  `workflow_run`, `workflow_status`.
- **76 cortexllm tests** (19 baseline + 17 Phase A + 22 Phase B + 18 Phase C).
  All green.
- **README rewrite** — new "Lifecycle & scheduling helpers" section.
- **No cortexagent imports / `platform="cortexagent"` defaults /
  `CORTEXAGENT_*` env names / `~/.cortexagent/` paths** in v0.4.0
  (confirmed by §10 of the brief).

### cortexagent required updates (blocking) — STATUS

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | `start-cortexllm-mcp.sh` fallback chain | ✅ Done (`b130297`) | First branch (flat `cortexllm_mcp_server.py` at repo root) was dead — moved in v0.3.2 split. New chain: `cortexllm/` package → `legacy/` → in-tree. PYTHONPATH updated to include the package dir so sub-imports resolve. |
| 2 | `_detect_cortexllm_dir` re-test | ✅ No change needed | Vendored path still `~/cortexllm/repo/cortexllm/` — same as before. 3-tier preference (env > repo > vendored) works. |
| 3 | CortexAgent smoke gate | ✅ Baseline 34/38 | Same 4 known failures (S1 PII, S2 tiny_llm behavior, S3 statusline test, S5 fallback-attr). No regressions. Coverage 31/31. |

### cortexagent optional migrations (deferred — do at leisure)

Per the brief §11, these are non-blocking. Status as of v0.4.0:

| cortexagent file | What | Decision |
|---|---|---|
| `lib/overseer.py:_get_memory_stats/_estimate_tokens` | swap to `cortexllm.stats` | Deferred — local copy works; brief confirms "same dict shape, plus estimated_tokens field". Migrate when convenient. |
| `lib/overseer.py:_check_db_integrity/_check_memory_writes` | swap to `cortexllm.integrity` | Deferred. |
| `lib/overseer.py:_cron_matches/schedule_*/_check_schedule` | swap to `cortexllm.scheduler` | Deferred — semantic mismatch risk. Cortexagent's cron is **calibrated for the daemon/overseer use case**; new module has a generic parser + aliases. Test both before swapping. |
| `lib/overseer.py:queue_*` | swap to `cortexllm.queue` | Deferred. |
| `lib/overseer.py:plan_*` | swap to `cortexllm.plan` | Deferred. |
| `lib/overseer.py:_is_running/_start/_stop` | swap to `cortexllm.lifecycle` | **Do not migrate.** cortexagent's `os.fork` + `os.setsid` is daemonization (full session leader), not single-instance lock. cortexllm's `SingleInstance(pidfile)` is a CM; its `daemonize()` is functionally equivalent but the integration with systemd Type=forking + the systemd `Restart=on-failure` loop and the SIGPIPE-safety redirects is non-trivial. Keep local. |
| `lib/memory_thin.py:_atomic_append` | swap to `cortexllm.atomic.atomic_append` | **Migrate.** Drop-in. |
| `lib/memory-daemon.py:_atomic_append_ndjson/socket drain` | swap to `cortexllm.atomic + drain` | **Migrate.** Drop-in. |
| `engine/dag.py` | delete, use `cortexllm.dag` | **Do not migrate.** Cortexagent's DAG is template-aware (deploy/pentest/malware-analysis step kinds). The generic `cortexllm.dag.DAGScheduler` has no domain knowledge. Keep local. |
| `engine/workflow.py` | delegate engine to `cortexllm.workflow` | **Keep local templates, can opt-in to engine shell.** Per the brief §3.2. |

### Recommended migration order (when convenient, not blocking)

1. **`lib/memory_thin.py:_atomic_append`** — 1 line. Do first.
2. **`lib/memory-daemon.py` socket drain** — 1 line. Do with #1.
3. **`lib/overseer.py:_get_memory_stats/_estimate_tokens`** — small, low-risk.
4. **`lib/overseer.py:_check_db_integrity`** — small, low-risk.
5. **`lib/overseer.py:queue_*/plan_*`** — easy wins if testable.
6. **`lib/overseer.py:schedule_*`** — needs care (semantic test).
7. `lifecycle`/`dag`/`workflow` — **leave local** (see notes above).

### Don't touch

- **`lib/daemon.py`** — daemon policy is CortexAgent-specific.
- **`lib/session_bridge.py`** — multi-voice UX, stays.
- **`memory/mcp_server.py` (in-tree)** — knows `platform="cortexagent"`.
- **systemd units, `install.sh`, `bin/cortexagent`** — CortexAgent-specific.
- **`engine/dag.py` + `engine/workflow.py`** — template-specific (see notes).
