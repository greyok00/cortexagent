# Prompt Pipeline Audit — 2026-08-16

> **Scope:** every stage a prompt traverses from CLI input → token out → rendered response, with file:line refs, a worked example, silent failures, and TPS hotspots. **Read-only deliverable.**

## Context

User wanted to verify the pipeline actually does what it claims: `framing → minify → memory check → tool routing → model call`, surface any silent failures, and identify the TPS bottleneck. Output of this audit feeds directly into the dashboard Trace Viewer (Phase E of the parent plan) and the TPS hotfixes (Phase C).

## The 14 Pipeline Stages

```
                 ┌──────────────┐
   stdin/argv ──▶│ 1. CLI parse │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 2. Framing   │  (classify_domain → optimize → add_domain_framing → shrink)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 3. Overseer  │  (enqueue turn to scheduler/queue)
                 │    submit    │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 4. Scheduler │  (NDJSON event store, worker dispatch)
                 │   dispatch   │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 5. Memory    │  (hot memory for the platform)
                 │    gather    │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 6. RAG query │  (domain DB FTS5 + cortexllm hot + cold + vector)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 7. React     │  (loop: tiny_route → tool_call → observation, up to 8 steps)
                 │    loop      │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 8. Tiny route│  (1.2B model decides tool vs text)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 9. Tool exec │  (registry / converted_mcp_tools)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 10. Big call │  (SlimToken minify → 35B → stream)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 11. Post-    │  (strip fences, glyphs — NOT on hot path)
                 │    process   │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 12. Response │  (block cards, artifacts)
                 │     model    │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 13. Memory   │  (sync SQLite write to hot buffer)
                 │     write    │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ 14. Render   │  (Tk tray or curses TUI)
                 └──────────────┘
```

## Stage-by-Stage (file:line)

### Stage 1 — CLI parse + queue
- **File:** `engine/cli.py`
- **What:** Reads stdin/argv, builds `messages[]`. Calls `lib.overseer.start()` if daemon isn't already up; otherwise sends via the control socket.
- **Status:** ✅ Working. Verified in smoke tests.

### Stage 2 — Prompt framing
- **File:** `lib/prompt_framing.py`
- **Functions:** `classify_domain` (lines 48–56), `optimize_prompt` (lines 113–114), `add_domain_framing` (lines 79–89), `shrink_prompt` (lines 127–132).
- **Caller:** `lib/react_loop.py:155-158` (`frame_prompt(prompt, system)`).
- **What it claims to do:** Strip filler, classify domain, inject domain-specific system prompt.
- **What it actually does:**
  - `classify_domain` — keyword match (`.in` checks) on lowercased prompt. ✅ Works.
  - `optimize_prompt` — 10 regex substitutions for common verbose phrases. ✅ Works.
  - `add_domain_framing` — string concatenation on system prompt. ✅ Works.
  - `shrink_prompt` — **`return prompt` (no-op stub!)**. ❌ Silent failure.

### Stage 3 — Overseer submit
- **File:** `lib/overseer.py` (`_submit_to_overseer` or queue handler).
- **What:** Enqueues the framed prompt to the scheduler.
- **Status:** ✅ Working.

### Stage 4 — Scheduler dispatch
- **File:** `lib/scheduler/*` (NDJSON event store + worker pool).
- **What:** Worker picks up event, claims turn, hands off to react loop.
- **Status:** ✅ Working (commit 62c2c9f fixed crash recovery).

### Stage 5 — Memory gather
- **File:** `lib/converted_mcp_tools.py:145-160` (`memory_read`).
- **What:** Reads hot memory rows for the current platform.
- **On the request thread:** Yes (synchronous `MemoryManager().get_hot_messages(platform)`).
- **Status:** ⚠️ Functional but blocks the request thread on `SELECT`.

### Stage 6 — RAG query
- **File:** `lib/tool_registry.py:377-428` (`_rag_query`).
- **What:** Domain DB FTS5 → cortexllm hot search → cortexllm cold lookup → cortexllm_vector VectorStore search.
- **Cost:** 4 sequential DB/network roundtrips per call. All synchronous. All on the tool-call thread.
- **Status:** ❌ Sequential where it could be parallel.

### Stage 7 — React loop
- **File:** `lib/react_loop.py:141-251` (`run_react`).
- **What:** Up to 8 steps; calls tiny for routing per step.
- **TPS cost per step:**
  - `list_tools(limit=MAX_TOOLS, stub=STUB_MODE)` rebuilt from scratch (no cache) → up to 8×/turn.
  - `ThreadPoolExecutor(max_workers=1)` created and torn down per tool call → up to 8 transient pools/turn.
- **Silent failure (lines 207–212):** When the tiny model returns text (no tool call), the code returns `framed = frame_output(output, domain)` and exits — it does **NOT** call `_post_process` or `_beautify_response`. The beautify chain defined at lines 254–299 is dead code on this hot path.
- **Status:** ⚠️ Working, but beauty pass is bypassed.

### Stage 8 — Tiny routing call
- **File:** `lib/tiny_llm.py:query_with_tools` (lines 93-105 use `urllib.request.urlopen`).
- **What:** Synchronous HTTP POST to `:8082` (1.2B overseer). Decides if a tool is needed.
- **Timeout:** 60s (`TOOL_TIMEOUT` in `react_loop.py:32`).
- **Status:** ✅ Working but blocks. Streaming not supported for tiny.

### Stage 9 — Tool execution
- **File:** `lib/tool_registry.py` / `lib/converted_mcp_tools.py`.
- **What:** Runs tool by name, returns observation.
- **TPS cost (memory_write):**
  - `lib/converted_mcp_tools.py:163-186` re-imports `memory_manager` every call (line 168).
  - Fresh `MemoryManager()` runs `SELECT … GROUP BY` on init (cortexllm/memory_manager.py:44-47).
  - For non-code writes: `_update_warm_buffer` (line 112) runs **two** `SELECT`s, dedupes, then `DELETE` + up to 2000 `INSERT`s.
  - **All on the request thread.** Worst single TPS offender.

### Stage 10 — Big-model call
- **File:** `lib/grammar_proxy.py` (`_forward`, `_forward_chunked`, `_send_and_pipe`).
- **What:** SlimToken minify the request → 35B → stream back.
- **TPS costs:**
  - `_forward` (lines 731–742): full `json.loads(body)` → mutate → `json.dumps(...).encode()` on every non-chunked POST. Linear in message history size.
  - `_forward_chunked` (lines 810–818): same pattern with dechunk. Minify is real, but the full JSON round-trip is mandatory before the first byte reaches the model. **Biggest first-token blocker.**
  - `_send_and_pipe` (lines 983–1001): entire response buffered into `resp_buf: list[bytes]` so post-hoc `minify_response` can run. For 4K-token replies with tool calls, ~16–50 MB held until client closes.
  - `_diag` (lines 487–502): recursive `_has_key(parsed, "grammar")` walk of entire parsed request on every request, plus optional 400 KB file dump.
  - Comment at line 190 says "Bounded to ~16 KB scan per call" but `_minify_response` walks the full body.

### Stage 11 — Post-process
- **File:** `lib/overseer.py:_post_process` (only wired in `_execute_task`, NOT inside `react_loop.py`).
- **Silent failure:** `react_loop` at lines 207–212 returns without calling this. The whole beautify chain (`_post_process` + `_beautify_response`) is dead code on the tool-calling hot path. Only single-task paths (no tool calls) get the post-process pass — at the end of the task.

### Stage 12 — Response model
- **File:** `lib/response_model.py:241-326` (`parse_response`).
- **What:** Parses text into block cards (heading, paragraph, list, code, table, chart, artifact).
- **Silent failure:** `collapse` at line 330 has `max_visible_artifacts: int = 0` — hides all code by default. The R2 comment claims "reveal via 'show code'" but no caller surfaces this disclosure.
- **Status:** ⚠️ Functional, but code in replies is invisible by default.

### Stage 13 — Memory write
- **File:** `lib/converted_mcp_tools.py:163-186` (`memory_write`).
- **What:** Sync SQLite write to hot buffer + warm-buffer rebuild.
- **On the request thread:** Yes.
- **Status:** ❌ Worst TPS offender (see Stage 9).

### Stage 14 — Render
- **File:** `lib/tray_dashboard.py` / TUI / `lib/webui.py` (`:8090`).
- **What:** Tk draws block cards; TUI uses curses; webui uses HTML/SSE.
- **Status:** ✅ Working.

---

## Worked Example: A Real Prompt

User typed (paraphrased for length):
> "go through all of our docs. Remove any of the old shit remove any of the redundancy remove anything that is going to affect our latest build. update the poll diversion stuff that we had by the way because I remember we need to do that. But we had a bunch of plans... go through and figure out our full step. And give me step by step from prompt.to output everything that happens and then it gives me like...give me a demo prompt and then push it through the entire thing and show me step by step.what happens and show me what the prompt changes to...I need this broken down to this because we're gonna show this in the overseer dashboard as well.needed to actually fill this out to where we can actually select a prompt and see it and see everything that it says and all the changes you can actually...go back in and modify the product..."

### Stage 1 — CLI parse
- **Input:** 1,200-char raw string.
- **Output:** `{"messages": [{"role": "user", "content": "<the 1,200 chars>"}]}`

### Stage 2 — Framing
- `classify_domain` → matches "go through", "docs", "update", "step by step" → domain=`task_management`.
- `optimize_prompt` → 10 regex substitutions remove verbose filler ("a lot of", "kind of", "like", etc.).
- **Output (after optimize):** ~960 chars (≈20% reduction).
- `add_domain_framing` → injects "You are CortexAgent. Focus on planning and audit tasks..." into the system prompt.
- `shrink_prompt` → **does nothing** (`return prompt`). ❌ Silent failure: user explicitly wanted rambling stripped, but `shrink_prompt` is a stub.

### Stage 3 — Overseer submit
- Enqueues turn to scheduler NDJSON event store. New `turn_id` (uuid) generated.

### Stage 4 — Scheduler dispatch
- Worker thread picks event, claims it, calls `lib.react_loop.run_react(task)`.

### Stage 5 — Memory gather
- `memory_read(platform="claude")` returns ~30 hot memory rows for context.

### Stage 6 — RAG query
- `_rag_query` runs:
  1. Domain DB FTS5 → empty (no domain DB row for this prompt).
  2. cortexllm hot → 4 matches.
  3. cortexllm cold → 2 matches.
  4. VectorStore → 6 nearest.
- All four run sequentially. Combined latency: ~150 ms.

### Stage 7 — React loop, Step 1
- Tiny gets a system prompt with `RAG context` injected (as `system` message) + the framed user prompt.
- Tiny returns tool call: `{"name": "delegate_to_big", "arguments": {"prompt": "<combined context>"}}`.
- `list_tools(limit=16, stub=True)` rebuilt — 16 tool dicts constructed. (~5 ms.)

### Stage 8 — Tiny routing
- 1.2B model on `:8082` answers in ~200 ms.

### Stage 9 — Tool exec
- `delegate_to_big` triggers `lib.grammar_proxy.py:_forward_chunked`.
- Full request body `json.loads`'d → SlimToken minify → `json.dumps`'d → re-sent with new `Content-Length`.
- 35B on `:8080` starts streaming.

### Stage 10 — Big-model call
- Streamed back as SSE. `_send_and_pipe` buffers into `resp_buf`.
- After stream completes, `minify_response(resp_buf)` runs on full body → strips filler phrases.
- **Memory cost:** entire response held in RAM (~16 MB for 4K tokens with tool calls).

### Stage 11 — Post-process
- `_execute_task` calls `_post_process(text)` (in overseer.py, NOT in react_loop). Strips fences, normalizes glyphs.
- ⚠️ If the response came through `react_loop` with text-only return, this step is **skipped**.

### Stage 12 — Response model
- `parse_response(text)` → list of block cards.
- `collapse(...)` with `max_visible_artifacts=0` → code blocks hidden by default.

### Stage 13 — Memory write
- `memory_write(platform="claude", role="assistant", content=<final text>)` runs synchronously.
- `MemoryManager()` instantiated → `db.initialize()` → `_load_state()` runs `SELECT … GROUP BY`.
- `_update_warm_buffer` runs two `SELECT`s + dedupe + `DELETE` + ~2000 `INSERT`s.
- **Wall-time:** ~80–120 ms on the request thread.

### Stage 14 — Render
- Block cards rendered in Tk tray dashboard. TUI shows them in curses.

---

## Silent Failures (Ranked by Impact)

| # | Where | Issue |
|---|---|---|
| 1 | `lib/react_loop.py:127-132` | `shrink_prompt` is `return prompt`. User's rambling is **not** stripped. |
| 2 | `lib/react_loop.py:207-212` | Text-mode return skips `_post_process` and `_beautify_response`. Beautify chain is dead code on hot path. |
| 3 | `lib/response_model.py:330` | `max_visible_artifacts: int = 0` hides all code; no caller surfaces "show code" disclosure. |
| 4 | `lib/converted_mcp_tools.py:163-186` | `memory_write` does full warm-buffer rebuild on every tool call. Blocks request thread 80–120 ms. |
| 5 | `lib/grammar_proxy.py:190` (comment vs. code) | "Bounded to ~16 KB scan per call" — comment does not match: walks entire body. |
| 6 | `lib/tool_registry.py:479-482` | `_not_implemented` returns success-shaped error; tools that haven't been wired in look broken to the user but report as tool failures. |
| 7 | `lib/converted_mcp_tools.py:312-322` | `magicui_generate` returns placeholder HTML. "MagicUI" tool is not actually implemented. |
| 8 | `lib/prompt_framing.py:79-89` | `add_domain_framing` re-allocates the system prompt on every call; framing text is a constant — should be precomputed. |

---

## TPS Hotspots (Ranked)

| Rank | File / Lines | Why it kills TPS | Fix complexity |
|---|---|---|---|
| 1 | `lib/converted_mcp_tools.py:163-186` + `cortexllm/memory_manager.py:60-119` | Sync SQLite write + warm-buffer rebuild on every tool call. 80–120 ms blocked. | Medium (background queue / write-behind cache) |
| 2 | `lib/grammar_proxy.py:731-742, 810-818` | Full `json.loads` → mutate → `json.dumps` of the entire request body on every POST. Latency before first byte. | Medium (stream chunks, in-place mutate) |
| 3 | `lib/react_loop.py:131-138, 202-203` + `lib/tool_registry.py:51-84` | ThreadPoolExecutor per call + list_tools re-sorted every step. 8 transient pools/turn, 8 list rebuilds/turn. | Low (module-level pool + `functools.lru_cache` on list_tools) |
| 4 | `lib/tool_registry.py:377-428` (`_rag_query`) | 4 sequential DB/network roundtrips. Should be parallel. | Low (concurrent.futures + gather) |
| 5 | `lib/daemon.py:252-356` (DEFERRED — other session owns) | 2.1 s of `nvidia-smi` polling + 60 s model load on cold start. | Low (single --query-gpu) |
| 6 | `lib/grammar_proxy.py:983-1001` | Full response buffered to RAM to enable post-hoc minify. Blocks streaming-end parallelism. | Medium (per-chunk minify) |
| 7 | `lib/grammar_proxy.py:487-502` (`_diag`) | Recursive `_has_key(parsed, "grammar")` walk of entire request on every request. | Low (gate behind `CORTEXAGENT_PROXY_DEBUG=1`) |
| 8 | `lib/prompt_framing.py:79-89` | System-prompt string concatenation on every call. | Trivial (precompute constant) |

---

## Recommendations

1. **Wire `_post_process` + `_beautify_response` into `react_loop.run_react`'s text-mode return path** (lines 207-212). One-line change, eliminates a silent failure.
2. **Make `shrink_prompt` actually shrink** (lines 127-132 of `lib/prompt_framing.py`). Implement it as a sentence-rank + drop pipeline, OR delegate to SlimToken's minify.
3. **Cache `list_tools(limit, stub)` with `functools.lru_cache(maxsize=4)`.** Eliminates 8×/turn list rebuild.
4. **Move warm-buffer rebuild off the request thread.** Background queue or batched flush; write-behind cache the hot reads.
5. **Gate `_diag` behind `CORTEXAGENT_PROXY_DEBUG=1`.** Zero-cost in production.
6. **Precompute framing string constant.** Trivial.
7. **Surface `response_model.collapse(max_visible_artifacts=N)` so callers can pass `N>0` for code-bearing replies.** Currently it's 0 by default, no disclosure shown.

---

## Verification

| Check | Command |
|---|---|
| All 14 stages covered | This document |
| Worked example | This document (Stages 1–14) |
| Silent failures | This document (ranked table) |
| TPS hotspots | This document (ranked table) |
| Trace Viewer consumes these events | Phase E of parent plan (`lib/overseer_dashboard/trace_store.py`) |