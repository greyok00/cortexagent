# Browser Console — Authoritative Reframing

> **READ FIRST.** This is the canonical purpose statement for
> `lib/browser_console.py`. If any future change to the overlay (or
> any mental model of it) contradicts this doc, **the doc wins**.

## What the program IS

The CortexAgent stack — `bin/cortexagent` + `lib/slimtoken`
(minify/compress) + `lib/cortexllm` (persistent memory: hot NDJSON
+ cold curated facts + SQLite + vector embeddings) + `lib/overseer`
(tiny watchdog model) + `lib/browser_control` (page-level CDP driver
for Brave :9222) + `lib/browser_console` (floating overlay) — exists
to give the user a **persistent, autonomous local agent that drives
their browser over time, with full memory of prior sessions**.

The agent is not a chatbot. It is a long-lived process that:

- remembers prior turns across days/weeks (cortexllm hot + cold + vector)
- keeps its context window under budget (slimtoken minify)
- watches itself (overseer — a tiny model that flags stalls / costs)
- has hands in the browser (browser_control — page-level CDP click/type/nav)
- reads files, runs shell commands, edits code, calls MCP servers

The user can leave it running for hours, come back, and it still
remembers what it was doing. That's the whole point.

## What the overlay IS

`lib/browser_console.py` is **a floating monitor + command injector**
that sits in front of the real `bin/cortexagent` subprocess. It is
NOT a chat UI. It is NOT a place where one-shot API calls live.

- The overlay embeds the real `bin/cortexagent` process (PTY + xterm
  emulator widget, OR external xterm via XEMBED if pyte can't be
  installed).
- Every byte the subprocess writes (banner, ticker, prompt, tool
  output, browser automation traces) is rendered in the overlay.
- The overlay's entry box writes keystrokes into the PTY — they
  arrive in the subprocess exactly as if the user typed them in a
  real terminal.
- All persistence (memory, slimtoken, browser_control wiring) stays
  inside `bin/cortexagent` — the overlay doesn't bypass it.

## What the overlay is NOT

- **NOT** a chat UI that calls the proxy once per message and shows
  the model's `content` string. That's a one-shot, it has no memory,
  no browser access, no persistence — and it's a lie to call that
  "the CLI".
- **NOT** a place to summarize or reframe what the agent did. The
  user wants to SEE the real agent output, not a paraphrase.
- **NOT** an alternative entry point. It is the same entry point,
  with a window in front of it.

## Why this matters

If the overlay replaces the agent subprocess with one-shot proxy
calls, the entire cortexllm + slimtoken + browser_control stack
becomes a layer cake with no cake. The user loses:

- cross-session memory (cortexllm)
- context-budget enforcement (slimtoken)
- browser automation (browser_control)
- watchdog (overseer)

The user sees a one-shot answer and the rest of the system sits
idle. That's broken and unacceptable.

## Implementation contract

Any future edit to `lib/browser_console.py` must satisfy:

1. **Subprocess lives**: a `bin/cortexagent` PTY is forked on
   overlay open and killed on overlay close. No standalone proxy
   calls.
2. **PTY bytes → overlay**: a reader thread drains the PTY fd into a
   real terminal emulator (pyte if available, else external xterm
   XEMBED). The overlay shows the subprocess output, byte-for-byte.
3. **Entry box → PTY**: keystrokes go to the PTY. Pressing Enter
   sends `\n`. Ctrl+C sends `\x03`. Arrow keys send escape
   sequences. The subprocess handles its own line editing.
4. **No proxy shortcuts**: `_run_cortexagent_via_proxy()` and any
   one-shot API callers MUST be removed. The only allowed path from
   user-typed prompt to model output is through the embedded
   subprocess.
5. **Quick-action buttons → PTY**: even the small browser buttons
   (refresh, snapshot, list tabs) write their command into the PTY
   and let the agent run them — never import `browser_control`
   directly from the overlay.

## Persistence

If you ever forget this reframing, re-read this file. It lives at
`docs/BROWSER_CONSOLE_REFRAMING.md` and is referenced from
`CLAUDE.md` and `MEMORY.md`.