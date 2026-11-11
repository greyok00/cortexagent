# cortexagent supervision plane (2026-11-09, owner order: supervise start to
# finish; loops/breaks auto-fixed; keep it trucking forever)

Components (all detached python processes; logs beside them):
- watch.py     — session watcher: detects identical toolCall streaks (x4),
                 bash refusals, length stops -> incidents.jsonl  [RUNNING]
- heal.py      — machine healer + steering brain every 20s:
                   :7090 down  -> wait for systemd self-heal, restart unit if 4 misses
                   :7091 down  -> restart cortexagent-lane.service
                   refusal storms -> targeted steer (cooldown-gated)
                 lessons.jsonl (per-key counts) + heel actions heal.jsonl
                   [RUNNING]
- steer.jsonl  — the live channel INTO the running session: written by
                 heal.py, consumed by extensions/supervised-steer.ts
                 (sendUserMessage deliverAs:"steer"). Lights up at next TUI
                 start (the extension auto-loads from the extensions dir).

Harness fixes already implemented in the build this session will pick up
on next TUI restart (dist rebuilt + manifest regenerated + gate green):
- agent-loop.ts: loop guards re-enabled (exact-match 4, args-streak 6,
  burst cap 6/message, guard-resumes 4) — trip = block offender + resume,
  never end the run.
- exec-gate.ts: refusals now TEACH the single-command form.

HARD SCOPE LAW (owner 2026-11-09 04:5x): greysearch (:11600 lane, cloud
ollama, its MCP, its sessions) is OFF-LIMITS — it runs all night in a
separate session. heal.py/watch.py only ever touch :7090, :7091, the two
cortexagent systemd units, and ~/.cortexagent session files. Never probe,
restart, renice, or observe anything on :11600/:11435/:11436/:11598/:11437
or the greysearch/knowledge MCP pairs of RUNNING windows (idle registry
spawns of LIVE windows are also untouchable — the orphan law).

Machine plane (always live): model watcher unit self-heals :7090,
lane unit restarts :7091, boot ladder handles VRAM, clamp floor 1024
prevents 1-token storms, compaction at 47.8k.
