# Overseer: Per-Model Registry + Decisive VRAM Selection + Singleton Guard

**Date:** 2026-08-04
**Status:** Proposed (awaiting approval)
**Scope:** `lib/config.py`, `lib/daemon.py`, `bin/cortexagent`, `tests/run_smoke.py`, memory

## Problem

1. **Blocking bug:** LFM2.5-8B-A1B (the MoE fallback) loads with `fallback_ctx=8192`.
   Claude Code's first request is ~29 K tokens (system prompt + 30 tools) →
   `request (29040 tokens) exceeds the available context size (8192)`. The fallback
   is unusable. Symptom looked like "wrong model / empty VRAM" because the model
   loaded but rejected every request.
2. **No per-model settings:** Only `fallback_ctx` is per-fallback. Fallback args
   (`_fallback_extra_args`) reuse the big model's `fa/ctk/ctv/np/b/ub`. No per-model
   `ngl`, `alias`, or `vram_min_gb`. One size does not fit a Mamba-2 MoE + a 35 B
   transformer + a 0.5 B dense model.
3. **Big model rarely loaded / double-load risk:** A single 14 GB threshold on a
   16 GB card + max-of-3 probe. Conservative and not tied to each model's actual
   footprint, so the decision can be wrong → load → OOM → reload (wasting ~60 s).
4. **Daemon not guaranteed up:** The launcher *detects* the daemon but doesn't
   *start* it. If the systemd service is down → legacy `DAEMON_MODE=0` starts its
   own servers, bypassing the overseer's VRAM-aware decision logic and risking
   duplicate model servers.
5. **Orphaned sessions:** A crash strands a `session-start` (+1) with no matching
   `session-end` (−1). The idle watcher refuses to unload while
   `active_sessions > 0`, so VRAM never frees.
6. **Claude Code logo (cosmetic):** no built-in suppression flag; deferred.

## Measured facts (2026-08-04, this 16 GB GPU)

| Model | ctx | -ngl | extra | VRAM (model only) | Notes |
|-------|-----|------|-------|-------------------|-------|
| Big Qwen3.6-35B IQ3_S | 131072 | 999 | --kv-unified | **~14.6 GB** | Fits only when GPU idle; OOM'd at 256k |
| Fallback LFM2.5-8B-A1B Q4_K_M | 65536 | 999 | (none, Mamba) | **~6.4 GB** | +412 MiB vs 8k (Mamba = constant state) |
| Tiny qwen2.5-0.5b | 4096 | 999 | (none) | ~0.6 GB | always-on overseer sidecar |

Mamba-2 recurrent state is O(1) in sequence length → 8× context costs ~0.4 GB.

## Design

### §1 Model Registry (`lib/config.py`)

A `ModelCfg` dataclass + a `MODEL_REGISTRY` dict. Each model owns: `ctx`,
`ngl`, `alias`, `fa`, `ctk`, `ctv`, `b`, `ub`, `extra_args`, `vram_min_gb`,
`kv_offload`.

```python
@dataclass
class ModelCfg:
    ctx: int
    ngl: int
    alias: str
    fa: str = "on"
    ctk: str = "q4_0"
    ctv: str = "q4_0"
    np: int = 1
    b: int = 2048
    ub: int = 2048
    extra_args: list = field(default_factory=list)
    vram_min_gb: int = 0          # hard VRAM requirement; 0 = always fits
    kv_offload: int = 1

MODEL_REGISTRY = {
    "big":      ModelCfg(ctx=131072, ngl=999, alias="cortexagent",
                        extra_args=["--kv-unified"], vram_min_gb=14),
    "fallback": ModelCfg(ctx=65536,  ngl=999, alias="cortexagent",
                        extra_args=[],                vram_min_gb=7),
    "tiny":     ModelCfg(ctx=4096,   ngl=999, alias="cortexagent-tiny",
                        extra_args=[],                vram_min_gb=0),
}
```

- LFM2.5 gets **ctx=65536** (64K). Mamba → cheap; measured 6.4 GB.
- Big gets **ctx=131072** (128K, down from 256K). Smaller KV → fits on the 16 GB
  card when GPU idle (measured 14.6 GB). 256K OOM'd.
- `vram_min_gb` is the **hard requirement** per model (the decisive selector key).
- **Backward compat:** existing flat fields (`big_ctx`, `fallback_ctx`,
  `big_vram_min_gb`, `big_fa`, …) become property getters that read from the
  registry, so env vars (`CORTEXAGENT_FALLBACK_CTX`, …) and conf
  (`[backend] fallback_ctx`, …) still override. Registry defaults are the
  baseline; conf/env layer on top.

### §2 Decisive model selection (`lib/daemon.py` `_load_session_model`)

Replaces max-of-3 + single threshold with **one probe, one decision, one load**:

1. Probe free VRAM **once** (keep max-of-3 to reject sub-second glitches; the max
   is *the* reading).
2. Scan `big → fallback` in registry order; pick the **first** whose
   `vram_min_gb ≤ free_gb`. (Tiny is always available on :8082 regardless.)
3. **Force the decision:**
   - If chosen model already up + healthy → no-op (no reload).
   - If a *different* model is up → `_swap_big` **once** (stops old → frees VRAM
     → loads new).
   - No try-big-then-OOM-retry. If the chosen model fails to load → log + fall to
     the next smaller **once** (exception path, not the default).
4. Because `vram_min_gb` is the model's *measured* footprint + margin, the
   decision is correct the first time → no double load.

Selection table on this 16 GB card (baseline ~1.6 GB used = system + tiny):

| Free VRAM | Choice | Result |
|-----------|--------|--------|
| ≥14 GB (GPU idle) | big @128k | uses ~15.2 GB total, 0.8 spare |
| 7–14 GB (browser/game) | fallback @64k | uses ~7 GB total, ~9 spare |
| <7 GB (heavy load) | tiny only (:8082) | big slot stays unloaded |

### §3 Daemon singleton guard (`bin/cortexagent`)

Before the `DAEMON_MODE` detection:

```bash
if ! python3 "$REPO_ROOT/lib/control.py" 2>/dev/null | grep -q True; then
    systemctl --user start cortexagent 2>/dev/null \
      || (nohup python3 "$REPO_ROOT/lib/daemon.py" run >/dev/null 2>&1 &)
    # wait for the control socket to answer (≤60 s)
    for i in $(seq 1 60); do
        python3 "$REPO_ROOT/lib/control.py" 2>/dev/null | grep -q True && break
        sleep 1
    done
fi
DAEMON_MODE=1   # always — overseer owns models; legacy path retired
```

- Guarantees exactly one daemon: up → reuse; down → start via systemd (or direct
  fallback) → wait for ready.
- **Retire `DAEMON_MODE=0`:** the launcher no longer starts its own model
  servers; the overseer always decides. Removes duplicate-server risk and the
  VRAM-logic bypass. The legacy `_cortexagent_kill_stale` / in-band server starts
  are removed.

### §3b Overseer control commands (`bin/cortexagent` + `lib/daemon.py`)

A `cortexagent --restart` command that reboots the daemon so it picks up an
updated `~/.cortexagent/cortexagent.conf` / env vars. **Why a full restart, not
a hot swap:** `config.py`'s `CFG` is a module-level singleton instantiated at
import. The control socket's `load`/`swap` handlers reuse the already-loaded
`CFG`, so they cannot pick up conf edits. Only a process restart re-imports
`config.py` → re-reads the conf → applies new registry overrides. So
`--restart` = **stop → start → wait-ready**.

**Two services, names confusingly similar:**

| systemd service | Runs | Owns |
|-----------------|------|------|
| `cortexagent` | `lib/daemon.py run` | big/fallback (:8080) + proxy (:8081) + control socket — the VRAM decision-maker |
| `cortexagent-overseer` | `lib/overseer.py start` | the 0.5b tiny (:8082) + keepalive scheduler |

CLI (early-exit flags in `bin/cortexagent`, parsed **before** the §3 singleton
guard so the guard doesn't short-circuit them). Each takes an optional `--all`
to also bounce the `cortexagent-overseer` tiny sidecar:

| Flag | Action |
|------|--------|
| `cortexagent --restart` | restart `cortexagent` only (stop → start → wait ready → status) |
| `cortexagent --restart --all` | also `systemctl restart cortexagent-overseer` (tiny) |
| `cortexagent --stop` | stop `cortexagent` only (socket `shutdown` + wait exit); frees big/fallback VRAM |
| `cortexagent --stop --all` | also stop `cortexagent-overseer` (tiny) |
| `cortexagent --start` | start `cortexagent` only (§3 logic: systemctl → direct fork → wait ready) |
| `cortexagent --start --all` | also start `cortexagent-overseer` (tiny) |
| `cortexagent --status` | print both services' status (decision-maker via socket; overseer via `systemctl is-active`) |

All delegate to `lib/daemon.py`'s CLI (`bin/cortexagent` does
`exec python3 lib/daemon.py <cmd> [--all]`). Default = decision-maker only, so
the tiny keeps running and :8082 doesn't blip. `--all` is for the rare case you
changed tiny-side settings (tiny model path / ctx).

`_restart()` logic (method-agnostic — works whether systemd or direct-fork
started the daemon):

1. **Detect management** *before* stopping: `systemctl --user is-active
   cortexagent --quiet` → if active, systemd owns it; else direct-fork owns it.
2. **Stop** via `_stop()` (sends socket `shutdown`, waits ≤15 s for exit, clears
   pid file). Method-agnostic — the socket works regardless of how it started.
   If `--all`: `systemctl --user stop cortexagent-overseer` (tiny is
   systemd-only — no direct-fork fallback; it's the always-on autostart service).
3. **Start** via the same method detected in step 1:
   - systemd → `systemctl --user start cortexagent` (re-reads the unit file, so
     unit-level env edits also apply).
   - direct → `_start_bg()` (os.fork; inherits shell env, re-imports config.py).
   If `--all`: `systemctl --user start cortexagent-overseer`.
4. **Wait ready** ≤60 s: poll `control.daemon_present()` once/s (and, with
   `--all`, wait for :8082 healthy).
5. **Print status** via `_status()` (both services when `--all`).

**Scope of restart:** only the `cortexagent` daemon (the proxy + big/fallback
selection logic + control socket). The `cortexagent-overseer` tiny sidecar
(:8082) is **not** restarted — it has no config-driven decisions and restarting
it just blips :8082 for no benefit. The tiny stays up across `--restart`.

### §4 Orphaned-session self-healing (`lib/daemon.py`)

The idle watcher / status handler treats `proxy.running == false` as "no real
session." On each idle poll, if `active_sessions > 0` **and** the proxy is not
running **and** no activity for >60 s → auto-decrement down to 0. Crash-stranded
sessions no longer pin VRAM forever. (This is "option A" from the prior session.)

### §5 `.md` audit (light)

Audit all auto-loaded `.md` for the local agent and trim bloat. **Already small**
(measured): `config/CLAUDE.md` ≈ 646 tok, `AGENT.md` ≈ 200, `MODELS.md` ≈ 973
(~1.8 K total). The 29 K overhead is tools + system prompt + MCP, not `.md`. So
this is a light pass (tighten wording, drop redundancy), **not** the main lever
— the 64 K ctx is. MCP config (`config/mcp.json`) and agent defs are also
audited for unused tools that inflate context.

### §6 Banner (Claude logo) — deferred

No clean suppression exists (no flag, no settings key; `hideLogo` is an internal
React prop; block chars overlap other UI). **Deferred** from this round. A pty
filter spike can follow if desired.

## EXCLUDE (must NOT change)

- `lib/banner.py` (CortexAgent's own banner).
- `lib/model_backend.py` `LlamaServer.start()` cmd construction (already takes
  `extra_args`).
- Grammar proxy, control-socket protocol, MCP config schema, statusline.
- Big model path; tiny model path.
- `cortexagent-overseer` systemd unit file / `lib/overseer.py` source — only
  their *lifecycle* (start/stop/restart) is driven via `systemctl` under `--all`;
  their code and unit definitions are not edited.

## Definition of Done

| # | Check | Verification |
|---|-------|-------------|
| 1 | LFM2.5 loads with ctx=65536 | `n_ctx_slot = 65536` in server log |
| 2 | Claude Code's 29 K-token request accepted | no "exceeds context size" error |
| 3 | GPU idle → big @128k loads | status `fallback:false` when ≥14 GB free; VRAM ~15.2 GB |
| 4 | GPU busy → fallback @64k loads + works | status `fallback:true`; request succeeds |
| 5 | One daemon across multiple launches | two `cortexagent` invocations → one daemon pid |
| 6 | Orphaned session self-clears | kill session mid-run → VRAM frees within ~65 s |
| 7 | Smoke gate passes | `tests/run_smoke.py` updated; ≥28/28 PASS |
| 8 | `--restart` picks up new conf | edit `fallback_ctx` in conf → `cortexagent --restart` → new ctx in server log |
| 9 | `--restart` (default) keeps tiny up | :8082 healthy before and after `--restart` |
| 10 | `--stop` frees VRAM | `--stop` → big/fallback VRAM freed; tiny :8082 still healthy |
| 11 | `--restart --all` bounces tiny | :8082 down briefly then healthy again; both services active |
| 12 | `--status` shows both services | decision-maker + overseer lines both present |

## Commit & memory

Local-only commit (user convention): registry + decisive selection + singleton +
self-healing + .md audit + smoke updates. Update memory file
`cortexagent-fallback-lfm2-5-8b-a1b.md` (registry, 64 K ctx, decisive selection,
measured footprints). Run `save-context.py`.

## Files touched

- `lib/config.py` — `ModelCfg`, `MODEL_REGISTRY`, compat getters.
- `lib/daemon.py` — `_load_session_model` (decisive), `_big_extra_args` /
  `_fallback_extra_args` (read from registry), orphan self-healing, idle watcher;
  `_restart()`/`_stop()`/`_start()`/`_status()` with optional `--all` (also drive
  `cortexagent-overseer` via `systemctl`); wire `restart` into `main()` CLI.
- `bin/cortexagent` — singleton guard, retire `DAEMON_MODE=0`, `--restart`/
  `--stop`/`--start`/`--status` early-exit flags with `--all` modifier
  (delegate to `lib/daemon.py <cmd> [--all]`).
- `tests/run_smoke.py` — registry test, decisive-selection test.
- `config/CLAUDE.md`, `config/AGENT.md`, `config/MODELS.md` — light trim.
- Memory: `cortexagent-fallback-lfm2-5-8b-a1b.md`.