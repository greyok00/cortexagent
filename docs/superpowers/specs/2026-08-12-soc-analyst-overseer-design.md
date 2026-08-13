# CortexAgent — SOC Analyst Overseer Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

Part of the SlimToken orchestration layer (see
`2026-08-12-slimtoken-orchestration-design.md`). This spec designs the
**24/7 threat-monitoring role**: the overseer becomes an active SOC analyst
that monitors the machine, consults domain-specific data (dfir), makes
security decisions (block / quarantine / kill / revoke), and learns from
review. It builds on step 2 (ReAct loop), step 3 (dfir domain DB), and
step 5 (overseer model swap).

---

## 1. Goal

The overseer model becomes a persistent SOC analyst:

1. **Monitors 24/7** — watches honeypot alerts, canary hits, process/network
   state, and system logs on the existing daemon tick loop.
2. **Consults domain data** — `rag_query(dfir)` for threat intel, IOCs,
   response playbooks, and past incidents before deciding.
3. **Makes decisions** — block / quarantine / kill / revoke / alert / ignore.
4. **Learns from review** — every review (✅ correct / ❌ false positive /
   🔀 wrong action) sharpens the dfir domain DB.
5. **Graduates to autonomy** — training mode first, per-action toggles, auto
   only when the hit rate is sound.

**User-confirmed (2026-08-12):** the overseer is the *active analyst* — it
consults domain-specific data and makes decisions like blocking attacks. The
big model (:8080) is the escalation path for deep analysis, not the primary
brain. Autonomy is **graduated**: training mode → per-action toggles → auto.

---

## 2. Architecture

```
24/7 watch (overseer 3B, always-on, ~2 GB on :8082)
   │  sources: honeypot · canary · process/network · syslog
   ▼
DETECT  →  anomaly spotted (rule hit, canary fire, new process, log pattern)
   ▼
CONSULT  →  rag_query(dfir) → threat intel · IOCs · playbooks · past incidents
   ▼
DECIDE  →  block / quarantine / kill / revoke / alert / ignore
   │
   ├── auto + confident  →  ACT (audit trail + undo)
   ├── training / low confidence  →  PROPOSE (alert + review)
   └── benign  →  log only
   ▼
LEARN  →  review feedback → dfir domain DB (incident memory)
```

- **Watch loop** = the existing overseer daemon tick (30s), extended with a
  `soc` scan step. No new daemon.
- **Brain** = the overseer model (:8082) + dfir domain DB (step 3). The
  overseer stays stateless; the dfir DB is its memory.
- **Escalation** = when the overseer's confidence is low but the signal is
  strong, it hands the investigation to the big model (:8080) for deep
  analysis, then acts on the result.

---

## 3. Autonomy model (graduated, per-action)

Config at `~/.cortexagent/soc_autonomy.json`:

```json
{
  "mode": "training",                    // training | live
  "actions": {
    "block_ip":        {"auto": false, "confidence": 0.8},
    "quarantine_file": {"auto": false, "confidence": 0.8},
    "kill_process":    {"auto": false, "confidence": 0.9},
    "revoke_token":    {"auto": false, "confidence": 0.8}
  }
}
```

| Mode | Behavior |
|---|---|
| **training** | Overseer detects → consults dfir → *proposes* action + reasoning + confidence. Never acts. Every proposal is reviewable. |
| **live** | Per-action: if `auto: true` and confidence ≥ threshold → act. Below threshold → propose. |

- **Graduation** — the user flips `block_ip.auto: true` when the training log
  shows a sound hit rate. Each action type graduates independently.
- **Confidence** — the overseer emits a 0–1 confidence with every decision.
  Thresholds are per-action (kill_process is higher — most destructive).
- **Audit trail** — every decision (proposed or acted) is appended to
  `~/.cortexagent/soc_audit.jsonl`: timestamp, source, signal, decision,
  confidence, action taken, undo command.
- **Undo** — every action has a recorded inverse (see §4).

---

## 4. Action tools (new registry entries, step 1)

| Tool | Action | Undo |
|---|---|---|
| `block_ip(ip, reason)` | nftables drop rule (via `nft` or `iptables`) | remove rule |
| `quarantine_file(path, reason)` | move to `~/.cortexagent/quarantine/` | move back |
| `kill_process(pid, reason)` | SIGTERM (SIGKILL only if confirmed) | restart if known |
| `revoke_token(token_id)` | invalidate a fired canary token | re-issue |

- Registered in `lib/tool_registry.py` (step 1) as **stubs** → filled in by
  this spec's implementation.
- All actions run through the audit trail + undo machinery (§3).
- `block_ip` is the highest-value action for the honeypot/canary use case —
  an attacker hitting a canary gets their IP dropped at the firewall.

---

## 5. Monitoring sources

| Source | Exists today | Feeds |
|---|---|---|
| Honeypot alerts (`canary_hits.jsonl`, `~/honeypot`) | ✅ | `block_ip` / `revoke_token` |
| Canary tokens (file access, web beacons) | ✅ | `revoke_token` / `quarantine_file` |
| Process snapshot (`ps` diff) | ⏳ new | `kill_process` |
| Network snapshot (`ss`/`lsof` diff) | ⏳ new | `block_ip` |
| System logs (auth, sudo, cron) | ⏳ new | alert / investigate |
| Overseer health events (`overseer_state.json`) | ✅ | context |

- **Phase 1 sources** (this spec): honeypot + canary + process/network
  snapshot. Syslog parsing is a later enhancement.
- **Snapshot diffing** — the watch loop takes a process/network snapshot each
  tick and diffs against the previous one. New/changed entries are the
  anomaly signal. Cheap, no new daemon.

---

## 6. dfir domain DB as the brain

The dfir domain DB (step 3) is the overseer's knowledge layer:

- **Seeded with**: threat intel, IOCs, response playbooks, past incidents,
  network baseline (known-good IPs/processes).
- **Consulted via**: `rag_query(dfir, query)` before every decision.
- **Learning loop**: every review writes back — "this pattern = real threat,
  action = block_ip" or "this pattern = false positive, ignore." The overseer's
  next `rag_query` retrieves the sharper knowledge.
- **Incident memory**: each confirmed incident is stored as a dfir document
  (source, signal, decision, action, outcome) so similar future signals
  retrieve the past response.

---

## 7. Overseer model

**Primary: Qwen2.5-3B-Instruct-abliterated Q4_K_M (~1.93 GB)** — the VRAM
ceiling, abliterated (no refusals — matches the uncensored big model).

| Model | File (Q4_K_M) | Est. VRAM | Fits 16 GB? |
|---|---|---|---|
| LFM2.5-1.2B (current) | 731 MB | ~0.95 GB | ✅ comfortable |
| Qwen2.5-1.5B-Instruct | ~1.0 GB | ~1.3 GB | ✅ comfortable |
| **Qwen2.5-3B-Instruct** | **1.93 GB** | **~2.3 GB** | ⚠️ needs big-model trim |
| Llama-3.2-3B-Instruct | 2.0 GB | ~2.5 GB | ❌ too big |
| Qwen3-4B | 2.5 GB | ~2.9 GB | ❌ too big |

**VRAM budget (measured from config, 2026-08-12):**
- Big model at `big_ub=1024`: ~14.1 GB
- Current tiny: ~0.95 GB
- Total: ~15.05 GB → ~0.95 GB margin on 16 GB

**To fit Qwen2.5-3B (~2.3 GB), trim the big model:**
- `big_ub` 1024 → 512 (saves ~0.4 GB; ub512 was the original tuned value)
- `big_ctx` 128k → 64k (saves ~0.3 GB; SOC escalation doesn't need 128k)
- Result: big ~13.4 GB + overseer ~2.3 GB = ~15.7 GB → ~0.3 GB margin

**Why Qwen2.5-3B-Instruct (abliterated):**
- Strongest reasoning in the 3B class (MMLU-Pro 32.4, MATH 65.9 vs
  Llama-3.2-3B's 24.0 / 48.0)
- Native tool calling (ChatML, works with llama.cpp :8082)
- 32k context — plenty for RAG + slimtoken compression
- **Abliterated** — no refusals, so it analyzes attack traffic / malware /
  suspicious processes without moralizing (matches the uncensored big model)
- ~1.93 GB Q4_K_M from `huihui-ai/Qwen2.5-3B-Instruct-abliterated` (Apache 2.0,
  FailSpy abliteration, most popular) — or the more aggressive
  `arzaan789/qwen2.5-3b-uncensored` (abliteration + LoRA + re-abliteration)

**Why not abliterate ourselves:** refusal-geometry research on Qwen2.5-3B
shows refusal is a 6.55-dimensional polyhedral cone (not a single direction)
with Ouroboros self-repair — single-direction abliteration fails; 3+
simultaneous ablations are needed. The pre-abliterated models already did that
work.

**Alternative: Qwen2.5-3B-Instruct_Function_Calling_xLAM (1.93 GB)** — a
tool-call specialist (fine-tuned on xLAM Function Calling 60K). Better tool-call
reliability, possibly weaker general reasoning. Evaluate both in training mode.

**Fallback if VRAM is too tight: Qwen2.5-1.5B-Instruct Q4_K_M (~1.0 GB)** —
fits without any big-model changes; smaller jump from the current 1.2B.

**Evaluation (training mode is the test):** the overseer's hit rate on real
honeypot/canary signals — right call, FP rate, FN rate, tool-call validity.
Swap the winner into `cortexagent.conf` (`overseer_model`).

### 7.1 Optimizing further — distillation from logged trajectories

The training mode (§3) logs every decision: signal → dfir context → decision →
action → outcome. After enough data, LoRA fine-tune the 3B base on those
trajectories → a custom overseer specialized for the user's threat landscape.

| Piece | Detail |
|---|---|
| Teacher | 35B big model (:8080) — generates deep analysis during escalation |
| Student | Qwen2.5-3B-Instruct (LoRA fine-tune) |
| Tool | Unsloth — LoRA on a 3B model fits 16GB, a few hours of training |
| Data | SOC trajectories from training mode (free, generated by the watch loop) |
| Result | merged GGUF → swapped into `cortexagent.conf` (`overseer_model`) |

- **No third model** — the fine-tune *replaces* the overseer, so the
  two-models-only rule holds.
- **This is the "distill from logged trajectories" item** that was Phase 2 in
  the master spec, pulled forward — it's the cheapest, most effective
  optimization available on this hardware.

**Nemotron-Flash-3B assessment** (the master prompt's "shrink and distill"
mention): Nemotron-Flash is a *latency-optimal SLM architecture* (NeurIPS
2025), not a distillation technique — the distillation half is Nemotron-H
miniPuzzle, which needs data-center compute (63B tokens in FP8). Flash-3B is
faster (1.3× lower latency, 6.4× higher throughput vs Qwen2.5-3B) but has
three blockers for this stack, verified 2026-08-12: **no tool calling** (the
official README's chat template is basic `User: ... Assistant:`; tool calling
exists only on the 30B Nemotrons — 3.5 Lightning, 3-Nano-30B), **no official
GGUF** (custom Mamba/DeltaNet kernels — llama.cpp support uncertain), and a
non-commercial license. **Verdict: not a drop-in; the LoRA path above is the
practical "optimize further."**

---

## 8. Alerting

| Channel | Where | For |
|---|---|---|
| Tray panel | Ollama Tray (CortexAgent panel) | proposals + high-confidence hits |
| Webui | RecordRelief security tab | full incident view + review UI |
| Desktop notification | `notify-send` | high-confidence hits only |

- **Review UI** — the webui security tab lists proposals with ✅ / ❌ / 🔀
  buttons. Each review writes to the dfir domain DB (learning loop).
- **No alert spam** — low-confidence / benign signals are logged, not alerted.

---

## 9. Safety

| Guard | Behavior |
|---|---|
| Training mode default | Overseer never acts until a toggle is flipped |
| Per-action confidence thresholds | kill_process highest (0.9) |
| Audit trail | every decision → `soc_audit.jsonl` |
| Undo | every action has a recorded inverse |
| Localhost-only | all bindings 127.0.0.1 (standing rule) |
| No PII | audit trail uses IPs/process names, not user data |
| Big model stays loaded | escalation path always available |

---

## 10. Testing

| Test | What it proves |
|---|---|
| Training-mode evaluation | Feed real honeypot/canary hits → overseer proposes → score hit rate |
| FP/FN tracking | False-positive and false-negative rates per action type |
| Tool-call validity | Overseer emits valid `tool_calls` (ReAct loop step 2) |
| Action tools | `block_ip` adds a real nftables rule; undo removes it |
| Audit trail | every decision logged with undo command |
| Graduation | flipping a toggle to `auto` makes it act at threshold |
| Smoke gate | `cortexagent doctor` + `tests/run_smoke.py` extended |

---

## 11. Out of scope (later)

- Syslog deep parsing (Phase 1 uses honeypot/canary/process/network only)
- Android accessibility (Phase 2)
- Full-scale distillation (Nemotron-H miniPuzzle style — needs data-center
  compute; the LoRA path in §7.1 is the hardware-feasible alternative)
- Automated response beyond the four action tools (e.g., network isolation)

---

## 12. Tracking

- This file = `docs/superpowers/specs/2026-08-12-soc-analyst-overseer-design.md`
- Master spec = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
