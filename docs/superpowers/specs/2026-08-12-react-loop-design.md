# CortexAgent — Step 2: ReAct/Socratic Loop Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

Part of the SlimToken orchestration layer (see
`2026-08-12-slimtoken-orchestration-design.md` for the roadmap + step 1).
This spec designs **step 2**: the orchestration engine that drives the
overseer model through a ReAct (Thought → Action → Observation) loop, with a
Socratic branch for ambiguous/investigative prompts.

---

## 1. Goal

Let the tiny overseer model (LFM2.5-1.2B, :8082) solve multi-step tasks by
calling tools from the step-1 registry, observing results, and iterating —
instead of a single one-shot `query_llm` call. Two modes:

- **ReAct** — straight Thought → Action → Observation for well-defined tasks
  (math, code, factual lookups, file ops, commands).
- **Socratic** — for ambiguous or investigative prompts (OSINT, security
  triage, legal/business analysis): surface hidden assumptions and ask
  "what would falsify this hypothesis?" *before* acting.

The loop is driven entirely by the tiny model on CPU. The big model (:8080)
is untouched. The loop publishes its steps to the existing `task_steps`
state so the tray/webui show live progress.

---

## 2. Architecture

```
Task queue (scheduler)
   │  task type "llm" → run_react(task)
   ▼
lib/react_loop.py  (the engine)
   │
   ├─ 1. classify_intent(task.prompt)          ← pre_flight_gate
   ├─ 2. pick mode: react | socratic | direct
   ├─ 3. build messages [system(mode), user]
   └─ 4. loop (max_steps=8):
         │  publish task_steps (current step)
         │  query_with_tools(messages, list_tools())   ← tiny :8082
         │     ├─ tool_calls? → execute_tool(name, args)  ← registry
         │     │                append results, continue
         │     └─ text?       → return final answer
         └─ max_steps hit → return partial + note
```

- **Queue** = what to do (unchanged). A queued `llm` task spawns a ReAct session.
- **Registry** = how to act (step 1). `list_tools()` + `execute_tool()`.
- **Loop** = how to think (this step).
- **State** = `task_steps` publishing (existing, reused).

---

## 3. Mode selection

`pre_flight_gate.classify_intent()` returns one of: `command_execution`,
`file_operation`, `information_retrieval`, `memory_operation`,
`task_management`, `conversation`, `scheduling`, `verification`, `ambiguous`,
`llm_required`.

| Intent | Mode | Behavior |
|---|---|---|
| `conversation` | **direct** | No loop — single tiny query, return answer |
| `command_execution`, `file_operation`, `information_retrieval`, `verification`, `llm_required` | **react** | Straight ReAct loop with tools |
| `ambiguous` | **socratic** | Clarify before acting |
| Investigative keywords (osint, security, triage, investigate, analyze, legal, business, "what would falsify") | **socratic** | Surface assumptions + falsification question before acting |
| `memory_operation`, `scheduling`, `task_management` | **direct tool** | Single tool call, no loop |

**Socratic trigger** = `is_ambiguous(prompt)` OR investigative keyword match.
The Socratic system prompt instructs the model to: (1) restate the goal,
(2) surface hidden assumptions, (3) ask "what would falsify this hypothesis?",
(4) only then call tools. The clarifying questions are returned to the user
as output — the loop does not act until the user answers (or the prompt is
re-submitted with the clarification).

---

## 4. Tool-call mechanics

### 4.1 Extend `lib/tiny_llm.py`

Add a tool-call-capable query alongside the existing `query()`:

```python
def query_with_tools(messages: list, tools: list,
                     max_tokens: int = 512, timeout: int = 60) -> dict:
    """Send full messages + tools to :8082. Returns:
    {"kind": "text", "content": str}  or
    {"kind": "tool_calls", "calls": [{"id", "name", "arguments": dict}]}
    """
```

- Sends `{"model": "tiny", "messages": messages, "tools": tools,
  "max_tokens": ..., "stream": False}` to `/v1/chat/completions`.
- Parses `choices[0].message.tool_calls` → normalized list.
- llama-server's chat template already renders `tools` (verified 2026-08-12),
  so no template changes needed.
- Returns `None` on server failure (caller handles).

### 4.2 Loop step

```
response = query_with_tools(messages, list_tools())
if response is None:            # tiny down → fail task, queue retries
    return {"ok": False, "error": "tiny model unavailable"}
if response["kind"] == "tool_calls":
    for call in response["calls"]:
        result = execute_tool(call["name"], call["arguments"])
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": result["output"] or result["error"]})
    continue
else:
    return {"ok": True, "output": response["content"]}
```

---

## 5. Loop guards

| Guard | Value | Why |
|---|---|---|
| `max_steps` | 8 (configurable) | Bounds the loop; a runaway ReAct session can't spin forever |
| Per-tool timeout | 60s | A hung tool (web fetch, subagent) can't freeze the loop |
| Malformed tool_calls | retry once with stricter framing | Model occasionally emits bad JSON; one retry, then fail |
| Tool failure | feed error back to model | Let the model recover (try another tool / rephrase) |
| `loop_guard.py` reuse | existing | Infinite-loop protection already in the codebase |
| Tiny server down | fail task, queue retries | Non-fatal — the queue marks it failed, next tick retries |

---

## 6. State publishing

Each loop step publishes to the existing two-layer state:

```
task_steps_publish(state, [
    {"id": 1, "label": "Thought: classify task",        "status": "done"},
    {"id": 2, "label": "Action: run_command(echo hi)",  "status": "done"},
    {"id": 3, "label": "Observation: 'hi'",             "status": "done"},
    {"id": 4, "label": "Thought: answer ready",         "status": "in_progress"},
], current=4)
```

The tray popout and webui already read `task_steps` verbatim — no consumer
changes needed. Labels stay short and human.

---

## 7. Integration with the queue

`lib/overseer.py:_execute_task` — task type `llm` now spawns a ReAct session
instead of a single `_query_tiny_llm` call:

```
task type "llm" → run_react({"prompt": ..., "system": ..., "max_steps": ...})
```

The queue's completed/failed bookkeeping is unchanged (`run_react` returns
`{"ok": bool, "output": str}`). Other task types (command, subagent, media)
keep their current paths — they become tools in step 1 and the loop can call
them, but the queue still dispatches them directly when queued.

---

## 8. Error handling

| Failure | Behavior |
|---|---|
| Tiny :8082 down | `run_react` returns `{"ok": False, "error": "tiny unavailable"}`; queue marks failed, retries next tick |
| Tool raises | `execute_tool` returns `{"ok": False, "error": ...}`; error fed back to model as observation |
| Malformed tool_calls | One retry with stricter framing, then fail |
| max_steps exceeded | Return partial answer + "reached step limit — rephrase or narrow the task" |
| Socratic clarification needed | Return the clarifying questions as output; no tools called until re-submitted |

---

## 9. Testing

| Test | What it proves |
|---|---|
| `lib/react_loop.py --smoke` | Runs a real ReAct task ("run `echo hello` and report the output") end-to-end with real tools |
| Socratic trigger | Ambiguous prompt ("fix it") → returns clarifying questions, no tools called |
| Tool-failure recovery | A tool that errors → model recovers with another tool/rephrase |
| max_steps cap | A task that never converges → partial answer + step-limit note |
| `query_with_tools` parse | Validates tool_calls parsing against a real :8082 response |
| Smoke gate | `cortexagent doctor` + `tests/run_smoke.py` extended with loop checks |

---

## 10. Files

| File | Change |
|---|---|
| `lib/react_loop.py` | NEW — the loop engine (`run_react`, mode selection, guards) |
| `lib/tiny_llm.py` | ADD `query_with_tools(messages, tools)` |
| `lib/overseer.py` | `_execute_task`: task type `llm` → `run_react` |
| `tests/run_smoke.py` | ADD loop checks |
| `docs/superpowers/specs/2026-08-10-daily-changelog.md` | ADD row |

---

## 11. Out of scope (later steps)

- Domain DBs + ingestion (step 3) — the loop can call `rag_query` (CortexLLM
  half, real in step 1) but the domain-DB backend lands in step 3.
- Adapters (step 4) — `describe_image`/`transcribe_audio`/`parse_document`
  are registered stubs; the loop can call them but they return
  "not implemented" until step 4.
- Android accessibility (Phase 2).

---

## 12. Tracking

- This file = `docs/superpowers/specs/2026-08-12-react-loop-design.md`
- Master spec = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
