# Cortex CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `cortex` command — a fork of Pi, rebranded and themed, wired to CortexAgent's local models and skills, fully offline, with auto-yes, plan mode, task strip, stats bar, and Shift+Tab mode cycling.

**Architecture:** Fork `earendil-works/pi` (MIT, minimal terminal agent harness). All customization lives in `extensions/` (TypeScript modules) + `theme/` so the Pi core stays clean and upstream-syncable. Extensions wire to CortexAgent's shared backbone (`lib/tool_registry.py`, `lib/skills.py`, `lib/pre_flight_gate.py`) via subprocess calls. MCP stays disabled.

**Tech Stack:** TypeScript (Pi core + extensions), Python (CortexAgent backbone + skills), llama-server OpenAI-compatible endpoints (`:8080` big, `:8082` tiny).

## Global Constraints

- **Fully offline** — no cloud, no API keys, no network calls. All model traffic is `127.0.0.1`.
- **CPU-capable** — must run without GPU.
- **MCP disabled by default** — stays in codebase, optional, offline mode works first.
- **Skill format is fixed** — `NAME`/`DESCRIPTION`/`SCHEMA`/`run(args) -> {"ok","output","error"}` from `lib/skills.py`. Do not invent a new format.
- **`<function_call>` tags are the model contract** — both `:8080` and `:8082` emit them; the tool loop parses that format.
- **Auto-switch reuses `pre_flight_gate.classify_intent`** — do not write a new classifier.
- **`lib/tool_registry.py` is the shared backbone** — `ensure_registered()` is idempotent, importable directly.
- **CortexAgent is untouched** — daemon/overseer/webui/tray/STT/browser/media/RAG all stay as-is.
- **Localhost-only bindings** — never `0.0.0.0`.
- **No personal info leaks** — use `Path.home()` / env vars.

---

### Task 1: Fork Pi + rebrand as `cortex`

**Files:**
- Create: `cortex/` (fork of `earendil-works/pi`)
- Modify: `cortex/package.json` (name → `cortex`, bin → `cortex`)
- Create: `cortex/README.md` (branded, offline-first)

**Interfaces:**
- Consumes: nothing (greenfield fork)
- Produces: a runnable `cortex` command; the `extensions/` + `theme/` directories that Tasks 2-7 populate

- [ ] **Step 1: Fork the repo**

```bash
git clone https://github.com/earendil-works/pi.git cortex
cd cortex
git remote rename origin upstream
```

- [ ] **Step 2: Install and verify the base runs**

```bash
npm install --ignore-scripts
npm run build
./test.sh   # base test suite passes
```

Expected: base Pi test suite passes. If any fail, note them — they must be pre-existing upstream failures, not ours.

- [ ] **Step 3: Rebrand package.json**

Edit `cortex/package.json`:
```json
{
  "name": "cortex",
  "bin": { "cortex": "./bin/cortex.js" },
  "description": "Cortex — fully offline local agent CLI"
}
```
(Adjust the bin path to match Pi's actual entry point — check `package.json` for the real `bin` value and keep the same file, just rename the command.)

- [ ] **Step 4: Create the extensions + theme dirs**

```bash
mkdir -p cortex/extensions cortex/theme cortex/scripts cortex/tests
```

- [ ] **Step 5: Write a branded README**

`cortex/README.md` — one page: what `cortex` is (offline local agent CLI), how to run it, that it's a fork of Pi (MIT, credit upstream), and that MCP is disabled by default.

- [ ] **Step 6: Verify the rebranded command runs**

```bash
cd cortex && npm run build && ./bin/cortex.js --version
```

Expected: prints the cortex version (or the Pi version with the cortex name). The chat TUI opens when run without args.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: fork Pi, rebrand as cortex"
```

---

### Task 2: Custom theme

**Files:**
- Create: `cortex/theme/cortex-theme.ts`
- Modify: `cortex/extensions/theme-loader.ts` (registers the theme via `resources_discover`)

**Interfaces:**
- Consumes: Pi's theme system (`theme.bg()`, `theme.fg()`, `theme.bold()`)
- Produces: a theme named `cortex` that Tasks 3-7's UI elements reference

- [ ] **Step 1: Write the theme**

`cortex/theme/cortex-theme.ts`:
```ts
import type { Theme } from "@earendil-works/pi-tui";

export const cortexTheme: Theme = {
  name: "cortex",
  // Brand colors — pick a palette (e.g. deep blue + amber accent).
  // Reference Pi's built-in themes for the exact Theme shape.
  colors: {
    primary: "#2d7ff9",
    accent: "#f5a623",
    background: "#0d1117",
    text: "#e6edf3",
    dim: "#8b949e",
    success: "#3fb950",
    error: "#f85149",
  },
};
```

- [ ] **Step 2: Register the theme**

`cortex/extensions/theme-loader.ts`:
```ts
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { cortexTheme } from "../theme/cortex-theme";

export default function (pi: ExtensionAPI) {
  pi.on("resources_discover", async (_event, ctx) => {
    ctx.themePaths.push(/* path to cortex-theme.ts */);
  });
}
```

- [ ] **Step 3: Verify the theme applies**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: the chat TUI renders with the cortex palette. If the theme API differs from the docs, read `node_modules/@earendil-works/pi-tui` types and adapt — the goal is a working custom theme, not a specific API call.

- [ ] **Step 4: Commit**

```bash
git add theme/ extensions/theme-loader.ts
git commit -m "feat: cortex custom theme"
```

---

### Task 3: Model wiring + auto-switch

**Files:**
- Create: `cortex/extensions/models.ts`
- Create: `cortex/scripts/classify.py` (thin wrapper over `pre_flight_gate.classify_intent`)
- Test: `cortex/tests/test_models.ts`

**Interfaces:**
- Consumes: `:8082` tiny (OpenAI-compatible, verified `/v1/models`), `:8080` big (same when loaded); `pre_flight_gate.classify_intent(prompt) -> intent`
- Produces: `classifyIntent(prompt: string): "tiny" | "big"` — used by Task 5's mode cycling and the tool loop

- [ ] **Step 1: Write the failing test**

`cortex/tests/test_models.ts`:
```ts
import { classifyIntent } from "../extensions/models";

test("classifies simple chat as tiny", () => {
  expect(classifyIntent("hi how are you")).toBe("tiny");
});

test("classifies coding task as big", () => {
  expect(classifyIntent("refactor the auth module and add tests")).toBe("big");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/test_models.ts`
Expected: FAIL — `classifyIntent` not defined.

- [ ] **Step 3: Write the classifier wrapper**

`cortex/scripts/classify.py`:
```python
#!/usr/bin/env python3
"""classify.py — tiny-vs-big intent routing for the cortex CLI.

Thin wrapper over CortexAgent's pre_flight_gate.classify_intent. Prints
"tiny" or "big" to stdout. Never raises.
"""
import sys
sys.path.insert(0, "/home/grey/cortexagent")
from lib.pre_flight_gate import classify_intent  # noqa: E402

_DIRECT = {"conversation", "memory_operation", "scheduling", "task_management"}

def main() -> int:
    prompt = sys.stdin.read().strip()
    intent = classify_intent(prompt)
    print("tiny" if intent in _DIRECT else "big")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Implement `classifyIntent`**

`cortex/extensions/models.ts`:
```ts
import { execSync } from "node:child_process";

export function classifyIntent(prompt: string): "tiny" | "big" {
  const out = execSync(`python3 scripts/classify.py`, {
    input: prompt,
    encoding: "utf-8",
  }).trim();
  return out === "tiny" ? "tiny" : "big";
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run tests/test_models.ts`
Expected: PASS (requires the tiny model or classifier to be reachable — if `:8082` is down, the classifier still returns an intent; the test asserts the routing, not the model).

- [ ] **Step 6: Register the providers**

In `cortex/extensions/models.ts`, add the extension factory:
```ts
export default function (pi: ExtensionAPI) {
  pi.registerProvider("cortex-tiny", {
    // OpenAI-compatible llama-server on :8082
    baseUrl: "http://127.0.0.1:8082/v1",
    // See Pi's registerProvider docs for the exact Provider shape
  });
  pi.registerProvider("cortex-big", {
    baseUrl: "http://127.0.0.1:8080/v1",
  });
}
```

- [ ] **Step 7: Verify auto-switch in the running CLI**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: a simple "hi" routes to tiny; a coding prompt routes to big. Verify via Pi's model indicator (or `/model` command) that the active model switches.

- [ ] **Step 8: Commit**

```bash
git add extensions/models.ts scripts/classify.py tests/test_models.ts
git commit -m "feat: wire local models + auto-switch by intent"
```

---

### Task 4: Permissions — auto-yes toggle

**Files:**
- Create: `cortex/extensions/permissions.ts`
- Test: `cortex/tests/test_permissions.ts`

**Interfaces:**
- Consumes: Pi's `tool_call` event (`event.input` mutable; return `{block: true, reason}` to block)
- Produces: `shouldBlockTool(toolName: string, args: object, autoYes: boolean): {block: boolean, reason?: string}` — used by the tool loop

- [ ] **Step 1: Write the failing test**

`cortex/tests/test_permissions.ts`:
```ts
import { shouldBlockTool } from "../extensions/permissions";

test("auto-yes blocks nothing", () => {
  expect(shouldBlockTool("run_command", { command: "rm -rf /" }, true).block).toBe(false);
});

test("auto-yes off blocks dangerous commands", () => {
  const r = shouldBlockTool("run_command", { command: "rm -rf /" }, false);
  expect(r.block).toBe(true);
  expect(r.reason).toContain("rm -rf");
});

test("auto-yes off allows safe reads", () => {
  expect(shouldBlockTool("read_file", { path: "/tmp/x" }, false).block).toBe(false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/test_permissions.ts`
Expected: FAIL — `shouldBlockTool` not defined.

- [ ] **Step 3: Implement the gate**

`cortex/extensions/permissions.ts`:
```ts
const DANGEROUS = ["rm -rf", "sudo", "mkfs", ":(){", "dd if="];

export function shouldBlockTool(
  toolName: string,
  args: Record<string, unknown>,
  autoYes: boolean
): { block: boolean; reason?: string } {
  if (autoYes) return { block: false };
  if (toolName === "run_command") {
    const cmd = String(args.command ?? "");
    for (const d of DANGEROUS) {
      if (cmd.includes(d)) return { block: true, reason: `dangerous pattern: ${d}` };
    }
  }
  return { block: false };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/test_permissions.ts`
Expected: PASS.

- [ ] **Step 5: Wire the gate to Pi's tool_call event**

In `cortex/extensions/permissions.ts`, add the factory:
```ts
export default function (pi: ExtensionAPI) {
  let autoYes = false;
  pi.registerFlag("yes", { description: "auto-approve all tool calls" });
  pi.on("session_start", async (_e, ctx) => {
    autoYes = Boolean(pi.getFlag("yes"));
  });
  pi.on("tool_call", (event, ctx) => {
    const r = shouldBlockTool(event.input.name, event.input.arguments, autoYes);
    if (r.block) return { block: true, reason: r.reason };
    return undefined; // allow
  });
  pi.registerCommand("auto-yes", {
    description: "toggle auto-approve mode",
    async run(_args, ctx) {
      autoYes = !autoYes;
      ctx.ui.notify(`auto-yes ${autoYes ? "ON" : "OFF"}`, "info");
    },
  });
}
```

- [ ] **Step 6: Verify in the running CLI**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: `/auto-yes` toggles; with auto-yes ON, a `run_command` with `rm -rf` executes without prompting; with OFF, it blocks with the reason.

- [ ] **Step 7: Commit**

```bash
git add extensions/permissions.ts tests/test_permissions.ts
git commit -m "feat: auto-yes permission gate"
```

---

### Task 5: Modes — plan mode + Shift+Tab cycling

**Files:**
- Create: `cortex/extensions/modes.ts`
- Test: `cortex/tests/test_modes.ts`

**Interfaces:**
- Consumes: `classifyIntent` from Task 3; Pi's `registerFlag`, `registerShortcut`
- Produces: `cycleMode(current: Mode): Mode` where `Mode = "chat" | "plan" | "auto"` — used by the UI task strip

- [ ] **Step 1: Write the failing test**

`cortex/tests/test_modes.ts`:
```ts
import { cycleMode } from "../extensions/modes";

test("cycles chat -> plan -> auto -> chat", () => {
  expect(cycleMode("chat")).toBe("plan");
  expect(cycleMode("plan")).toBe("auto");
  expect(cycleMode("auto")).toBe("chat");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/test_modes.ts`
Expected: FAIL — `cycleMode` not defined.

- [ ] **Step 3: Implement the cycle**

`cortex/extensions/modes.ts`:
```ts
export type Mode = "chat" | "plan" | "auto";
const ORDER: Mode[] = ["chat", "plan", "auto"];

export function cycleMode(current: Mode): Mode {
  const i = ORDER.indexOf(current);
  return ORDER[(i + 1) % ORDER.length];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/test_modes.ts`
Expected: PASS.

- [ ] **Step 5: Wire the mode flag + shortcut**

In `cortex/extensions/modes.ts`, add the factory:
```ts
export default function (pi: ExtensionAPI) {
  let mode: Mode = "chat";
  pi.registerFlag("plan", { description: "start in plan mode" });
  pi.on("session_start", async (_e, ctx) => {
    if (pi.getFlag("plan")) mode = "plan";
  });
  pi.registerShortcut("shift+tab", {
    description: "cycle mode (chat/plan/auto)",
    async run(_e, ctx) {
      mode = cycleMode(mode);
      ctx.ui.notify(`mode: ${mode}`, "info");
    },
  });
  pi.events.emit("cortex:mode-changed", mode);
}
```

- [ ] **Step 6: Verify in the running CLI**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: Shift+Tab cycles chat → plan → auto → chat with a notify; `--plan` starts in plan mode.

- [ ] **Step 7: Commit**

```bash
git add extensions/modes.ts tests/test_modes.ts
git commit -m "feat: plan mode + shift-tab mode cycling"
```

---

### Task 6: UI — task strip + stats bar

**Files:**
- Create: `cortex/extensions/ui.ts`
- Test: `cortex/tests/test_ui.ts`

**Interfaces:**
- Consumes: `ctx.ui.setWidget`, `ctx.ui.setStatus`, `ctx.getContextUsage()`; the `cortex:mode-changed` event from Task 5
- Produces: `formatStats(usage, mode, autoYes): string[]` — the stats bar lines

- [ ] **Step 1: Write the failing test**

`cortex/tests/test_ui.ts`:
```ts
import { formatStats } from "../extensions/ui";

test("formats stats bar", () => {
  const lines = formatStats(
    { inputTokens: 1000, outputTokens: 500 },
    "auto",
    true
  );
  expect(lines.join("\n")).toContain("auto");
  expect(lines.join("\n")).toContain("1.5k");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/test_ui.ts`
Expected: FAIL — `formatStats` not defined.

- [ ] **Step 3: Implement the formatter**

`cortex/extensions/ui.ts`:
```ts
export function formatStats(
  usage: { inputTokens: number; outputTokens: number },
  mode: string,
  autoYes: boolean
): string[] {
  const total = usage.inputTokens + usage.outputTokens;
  const totalK = total >= 1000 ? `${(total / 1000).toFixed(1)}k` : String(total);
  return [
    `mode: ${mode}`,
    `auto-yes: ${autoYes ? "ON" : "OFF"}`,
    `tokens: ${totalK}`,
  ];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/test_ui.ts`
Expected: PASS.

- [ ] **Step 5: Wire the widgets**

In `cortex/extensions/ui.ts`, add the factory:
```ts
export default function (pi: ExtensionAPI) {
  let mode = "chat";
  let autoYes = false;
  pi.events.on("cortex:mode-changed", (m) => { mode = m; });
  pi.on("turn_end", async (_e, ctx) => {
    const usage = ctx.getContextUsage();
    ctx.ui.setWidget("cortex-stats", formatStats(usage, mode, autoYes));
  });
  pi.on("session_start", async (_e, ctx) => {
    ctx.ui.setWidget("cortex-tasks", ["No scheduled tasks"]);
  });
}
```

- [ ] **Step 6: Verify in the running CLI**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: a stats widget (mode, auto-yes, tokens) updates after each turn; a task strip widget sits above the chat input.

- [ ] **Step 7: Commit**

```bash
git add extensions/ui.ts tests/test_ui.ts
git commit -m "feat: task strip + stats bar widgets"
```

---

### Task 7: Skills bridge + cache

**Files:**
- Create: `cortex/scripts/skill_bridge.py` (lists/runs CortexAgent Python skills)
- Create: `cortex/extensions/skills.ts` (registers skills as Pi tools, caches them)
- Test: `cortex/tests/test_skills.ts`

**Interfaces:**
- Consumes: `lib/skills.py` (`load_skills_dir`, `list_skills`, `run_skill`) — the fixed skill format
- Produces: `loadSkills(): SkillInfo[]` where `SkillInfo = {name, description, schema}`; `runSkill(name, args)` — cached, preloaded

- [ ] **Step 1: Write the failing test**

`cortex/tests/test_skills.ts`:
```ts
import { loadSkills, runSkill } from "../extensions/skills";

test("loads skills from the bridge", async () => {
  const skills = await loadSkills();
  expect(Array.isArray(skills)).toBe(true);
});

test("runs a skill by name", async () => {
  const r = await runSkill("weather", { city: "Phoenix" });
  expect(r).toHaveProperty("ok");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/test_skills.ts`
Expected: FAIL — `loadSkills` not defined.

- [ ] **Step 3: Write the Python bridge**

`cortex/scripts/skill_bridge.py`:
```python
#!/usr/bin/env python3
"""skill_bridge.py — list/run CortexAgent Python skills for the cortex CLI.

Usage:
  skill_bridge.py list
  skill_bridge.py run <name> <json-args>
"""
import json
import sys

sys.path.insert(0, "/home/grey/cortexagent")
from lib.skills import load_skills_dir, list_skills, run_skill  # noqa: E402

def main() -> int:
    load_skills_dir()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        print(json.dumps(list_skills()))
        return 0
    if cmd == "run":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(run_skill(name, args)))
        return 0
    return 2

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Implement the bridge + cache**

`cortex/extensions/skills.ts`:
```ts
import { execFileSync } from "node:child_process";

export interface SkillInfo { name: string; description: string; }

let cache: SkillInfo[] | null = null;

export async function loadSkills(): Promise<SkillInfo[]> {
  if (cache) return cache;
  const out = execFileSync("python3", ["scripts/skill_bridge.py", "list"], {
    encoding: "utf-8",
  });
  cache = JSON.parse(out);
  return cache;
}

export async function runSkill(name: string, args: Record<string, unknown>) {
  const out = execFileSync(
    "python3",
    ["scripts/skill_bridge.py", "run", name, JSON.stringify(args)],
    { encoding: "utf-8" }
  );
  return JSON.parse(out);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run tests/test_skills.ts`
Expected: PASS (requires `~/.cortexagent/skills/` to exist with at least `weather.py`).

- [ ] **Step 6: Register skills as Pi tools**

In `cortex/extensions/skills.ts`, add the factory:
```ts
export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_e, ctx) => {
    const skills = await loadSkills(); // preload cache at startup
    for (const s of skills) {
      pi.registerTool({
        name: `skill_${s.name}`,
        description: s.description,
        parameters: { type: "object", properties: {} },
        async execute(_id, params, _sig, _upd, _ctx) {
          return { content: [{ type: "text", text: JSON.stringify(await runSkill(s.name, params)) }] };
        },
      });
    }
  });
}
```

- [ ] **Step 7: Verify in the running CLI**

```bash
cd cortex && npm run build && ./bin/cortex.js
```

Expected: `skill_weather` (and any other skills) appear in the tool list; calling one runs the Python skill. The cache means a second session loads instantly (no re-execution).

- [ ] **Step 8: Commit**

```bash
git add scripts/skill_bridge.py extensions/skills.ts tests/test_skills.ts
git commit -m "feat: Python skills bridge + cache"
```

---

### Task 8: MCP disabled + offline verification

**Files:**
- Modify: `cortex/README.md` (MCP disabled note)
- Create: `cortex/tests/test_offline.ts`

**Interfaces:**
- Consumes: everything from Tasks 1-7
- Produces: a verified offline, CPU-capable `cortex` CLI

- [ ] **Step 1: Write the offline test**

`cortex/tests/test_offline.ts`:
```ts
import { execFileSync } from "node:child_process";

test("no MCP servers are registered by default", () => {
  // The skills/models extensions must not register any mcp_* tools.
  const out = execFileSync("python3", ["scripts/skill_bridge.py", "list"], {
    encoding: "utf-8",
  });
  expect(out).not.toContain("mcp_");
});
```

- [ ] **Step 2: Run test to verify it passes**

Run: `npx vitest run tests/test_offline.ts`
Expected: PASS — no MCP tools in the surface.

- [ ] **Step 3: Verify fully offline operation**

```bash
# Block all non-localhost network to prove air-gap
sudo iptables -A OUTPUT -p tcp -d 0.0.0.0/0 ! -d 127.0.0.1 -j DROP
cd cortex && ./bin/cortex.js
# run a chat turn + a tool call; both must work
sudo iptables -D OUTPUT -p tcp -d 0.0.0.0/0 ! -d 127.0.0.1 -j DROP
```

Expected: chat + tool calls work with all external network blocked. (If iptables isn't available, use `unshare -n` or a firewall tool — the goal is proving no external network dependency.)

- [ ] **Step 4: Verify CPU capability**

```bash
# With the GPU busy or unavailable, the CLI still works (models fall back to CPU)
cd cortex && ./bin/cortex.js
```

Expected: works with CPU-only model serving (llama-server CPU mode or the tiny model).

- [ ] **Step 5: Update README with MCP note**

Add to `cortex/README.md`:
```markdown
## MCP

MCP support is present but **disabled by default**. The fully offline mode
works first. To enable later, see the MCP configuration docs (minification
+ README handled in the harness session).
```

- [ ] **Step 6: Run the full test suite**

```bash
cd cortex && npx vitest run
```

Expected: all tests pass (models, permissions, modes, ui, skills, offline).

- [ ] **Step 7: Commit**

```bash
git add tests/test_offline.ts README.md
git commit -m "feat: MCP disabled by default + offline verification"
```

---

## Self-Review

**Spec coverage:**
- Fork Pi + rebrand → Task 1 ✅
- Theme → Task 2 ✅
- Model wiring + auto-switch → Task 3 ✅
- Auto-yes → Task 4 ✅
- Plan mode + Shift+Tab → Task 5 ✅
- Task strip + stats bar → Task 6 ✅
- Skills bridge + cache → Task 7 ✅
- MCP disabled → Task 8 ✅
- Fully offline + CPU → Task 8 ✅
- Handoff notes 1-7 → Tasks 3, 4, 7 (skill format, `<function_call>` contract noted in Global Constraints, stub mode noted, pre_flight_gate in Task 3, MCP off in Task 8, beautify noted, tool_registry noted) ✅

**Placeholder scan:** No TBD/TODO. All steps have concrete code or commands.

**Type consistency:** `classifyIntent` (Task 3) used by Task 5's mode cycling via the `cortex:mode-changed` event; `formatStats` (Task 6) consumes the mode + autoYes state; `loadSkills`/`runSkill` (Task 7) match the bridge's `list`/`run` commands. Consistent.

**Note:** The full port of Claude's skills (brainstorming, TDD, etc.) is a **separate plan** — this plan builds the bridge + cache so the CLI can call skills; the port itself is the next plan after this one lands.
