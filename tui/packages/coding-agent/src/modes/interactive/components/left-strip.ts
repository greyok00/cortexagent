// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// LEFT STRIP — collapsible brown sidebar on the left edge of the TUI.
//
// Collapsed: thin vertical brown strip (STRIP_COLLAPSED_W). Shows just the
// toggle arrow `▸`.
//
// Expanded: full-width sidebar (STRIP_EXPANDED_W) with 5 stacked sections,
// mirroring the status-bar boxes so the strip and the bar agree:
//   Topic · Sub-agents (roster + who's running) · Memory (topics) ·
//   Services (messenger / security rows) · API Health.
//
// 2026-10-13 (owner: "I want the researchers and sub-agents to actually show
// up"): the Sub-agents section now reads the roster from THIS agent dir
// and marks each agent that has a live task running (scheduler events) or an
// active tool-call in the newest transcript. The Memory recall section shows
// cold-memory TOPICS (domain names, latest first) per the 2026-08-20 owner
// feedback that raw counts are useless; the old external-family store path
// is gone (this agent reads ITS OWN store).
//
// The strip animates between collapsed and expanded by interpolating its
// width over STRIP_ANIM_MS (~250ms). The chat's left edge moves with the
// strip, but the chat's text content does NOT re-wrap. User feedback
// 2026-08-20: "don't make the text move, it's gonna hurt the eyes."
//
// Toggling: call toggle() from any input handler (the TUI has no native
// click API). Use isExpanded() to query the current state.
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Component, truncateToWidth, visibleWidth } from "@cortexagent/tui";
import { theme } from "../theme/theme.ts";

// 2026-10-14 (local port): store paths follow the CORTEXAGENT_* env set by the
// launcher; defaults stay the local agent's own dirs.
const STATE_DIR = process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent");
const SCHEDULER_EVENTS = path.join(STATE_DIR, "scheduler", "tasks.events.jsonl");
const PANEL_STATUS_DIR = process.env.CORTEXAGENT_STATUS_DIR ?? path.join(STATE_DIR, "panel-status");
const COLD_DIR = path.join(process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory"), "cold");
const HOT_DIR = path.join(process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory"), "hot");
// The roster lives in THIS agent's dir (CORTEX_CODING_AGENT_DIR).
const AGENT_DIR = process.env.CORTEX_CODING_AGENT_DIR ?? path.join(os.homedir(), ".cortex", "agent");
const USER_AGENTS_DIR = path.join(AGENT_DIR, "agents");
const SESSIONS_DIR = path.join(AGENT_DIR, "sessions");

// ── Widths ───────────────────────────────────────────────────────────────────
// 2026-08-20 user feedback: "the arrow is not there, I don't know where it
// would be, but it should be there." Bumped STRIP_COLLAPSED_W from 3 to 5
// so the `▸ ▎` collapsed arrow + accent bar are unmistakable on dark themes,
// and the toggle is clickable without hunting for a single cell.
export const STRIP_COLLAPSED_W = 5; // visible glyph columns
export const STRIP_EXPANDED_W = 22; // bumped with collapse-w so the
// expanded sections don't crowd
export const STRIP_ANIM_MS = 250; // deployment ease

// ── Data sources (read-only) ────────────────────────────────────────────────

interface ColdMem {
	id: string;
	summary: string;
	ts: number;
}

// ── Active sub-agents: live tasks + newest-transcript tool calls ───────────
// Same two sources the 🤖 rows in status-panels.ts use, so the strip and the
// status bar can never disagree about who is running.

/** Live scheduler tasks (queued/running), by title. */
function readLiveTaskTitles(): { title: string; state: string }[] {
	try {
		if (!fs.existsSync(SCHEDULER_EVENTS)) return [];
		const lines = fs.readFileSync(SCHEDULER_EVENTS, "utf8").split("\n");
		const lastState = new Map<string, { type: string; title: string }>();
		for (let i = lines.length - 1; i >= 0; i--) {
			const raw = lines[i].trim();
			if (!raw) continue;
			try {
				const ev = JSON.parse(raw);
				const id = String(ev.task_id ?? "");
				if (!id || lastState.has(id)) continue;
				lastState.set(id, {
					type: String(ev.type ?? ""),
					title: String(ev.data?.title ?? ""),
				});
			} catch {
				/* ignore */
			}
		}
		const out: { title: string; state: string }[] = [];
		for (const v of lastState.values()) {
			if (v.type === "running" || v.type === "start" || v.type === "queue" || v.type === "queued") {
				out.push({ title: v.title, state: v.type === "running" || v.type === "start" ? "running" : "queued" });
			}
		}
		return out;
	} catch {
		return [];
	}
}

/** Names seen in the newest session transcript's most recent tool calls.
 * mcp_messenger_* / mcp_research_* / mcp_workers_* map to the roster words. */
function readRecentToolNames(): string[] {
	try {
		let bestDir: string | null = null;
		let bestM = -1;
		for (const e of fs.readdirSync(SESSIONS_DIR, { withFileTypes: true })) {
			if (!e.isDirectory()) continue;
			try {
				const m = fs.statSync(path.join(SESSIONS_DIR, e.name)).mtimeMs;
				if (m > bestM) {
					bestM = m;
					bestDir = e.name;
				}
			} catch {
				/* ignore */
			}
		}
		if (!bestDir) return [];
		const dir = path.join(SESSIONS_DIR, bestDir);
		let bestFile: string | null = null;
		bestM = -1;
		for (const f of fs.readdirSync(dir)) {
			if (!f.endsWith(".jsonl")) continue;
			try {
				const st = fs.statSync(path.join(dir, f));
				if (st.mtimeMs > bestM) {
					bestM = st.mtimeMs;
					bestFile = f;
				}
			} catch {
				/* ignore */
			}
		}
		if (!bestFile) return [];
		const lines = fs.readFileSync(path.join(dir, bestFile), "utf8").split("\n");
		const seq: string[] = [];
		for (let i = lines.length - 1; i >= 0 && seq.length < 8; i--) {
			const raw = lines[i].trim();
			if (!raw || !raw.includes("toolCall")) continue;
			try {
				const e = JSON.parse(raw);
				const content = (e.message ?? e)?.content;
				if (!Array.isArray(content)) continue;
				for (const c of content) {
					if (c?.type === "toolCall" && typeof c.name === "string" && c.name) seq.push(c.name);
				}
			} catch {
				/* ignore */
			}
		}
		return seq;
	} catch {
		return [];
	}
}

// ── Section renderers (expanded only) ────────────────────────────────────────

function sectionHeader(title: string, w: number): string {
	const inner = w - 4;
	const label = `▸ ${title}`;
	const truncated = truncateToWidth(label, inner, "…", false);
	const pad = " ".repeat(Math.max(0, inner - visibleWidth(truncated)));
	return `${theme.fg("dim", "┌─ ")}${truncated}${pad}${theme.fg("dim", " ─┐")}`;
}

function sectionLine(text: string, w: number): string {
	const inner = w - 4;
	const t = truncateToWidth(text, inner, "…", false);
	const pad = " ".repeat(Math.max(0, inner - visibleWidth(t)));
	return `${theme.fg("dim", "│ ")}${t}${pad}${theme.fg("dim", " │")}`;
}

function sectionFooter(w: number): string {
	return `${theme.fg("dim", "└─")}${"─".repeat(w - 4)}${theme.fg("dim", "─┘")}`;
}

// ── Component ────────────────────────────────────────────────────────────────

export class LeftStripComponent implements Component {
	private _expanded = false;
	private _animWidth: number = STRIP_COLLAPSED_W;
	private _animTarget: number = STRIP_COLLAPSED_W;
	private _animStart = 0;
	private _lastRenderAt = 0;
	private readonly onChange: () => void;

	constructor(onChange: () => void) {
		this.onChange = onChange;
	}

	dispose(): void {
		// No persistent timers — the animation tick is driven by onTick.
	}

	invalidate(): void {
		// Data is re-read on every render, but we want to throttle to avoid
		// hammering the scheduler events file. 1Hz is fast enough for the
		// animation to look smooth (250ms ease) and still surfaces fresh
		// tabs / tasks.
	}

	// ── Public API ──────────────────────────────────────────────────────────
	isExpanded(): boolean {
		return this._expanded;
	}

	toggle(): void {
		this._expanded = !this._expanded;
		this._animTarget = this._expanded ? STRIP_EXPANDED_W : STRIP_COLLAPSED_W;
		this._animStart = Date.now();
		this.onChange();
	}

	/** Width the layout should currently allocate for this strip. Animates
	 * toward the target. Always returns at least STRIP_COLLAPSED_W so even
	 * mid-animation the strip is visible. */
	getWidth(): number {
		const now = Date.now();
		// 60Hz tick — requestRender() is called from the timer.
		if (this._animWidth !== this._animTarget) {
			const dt = now - this._animStart;
			const t = Math.min(1, dt / STRIP_ANIM_MS);
			// Ease-out cubic for a smooth pull-out.
			const eased = 1 - (1 - t) ** 3;
			const from = this._expanded ? STRIP_COLLAPSED_W : STRIP_EXPANDED_W;
			this._animWidth = Math.round(from + (this._animTarget - from) * eased);
		}
		return Math.max(STRIP_COLLAPSED_W, this._animWidth);
	}

	/** Called by the host every render tick so the animation advances. */
	tick(): void {
		const w = this.getWidth();
		if (w !== this._animWidth) {
			this._animWidth = w;
			this.onChange();
		}
	}

	// ── Render ──────────────────────────────────────────────────────────────
	render(maxWidth: number): string[] {
		const w = Math.max(STRIP_COLLAPSED_W, Math.min(STRIP_EXPANDED_W, maxWidth));
		if (w <= STRIP_COLLAPSED_W) {
			// Collapsed: arrow + accent bar so the toggle is unmistakable.
			// 2026-08-20 user feedback: "the arrow is not there" — single
			// amber `▸` on dark bg was getting lost. Now it's `▸ ▎` so the
			// hit area is visible at a glance.
			const arrow = theme.fg("accent", "▸");
			const bar = theme.fg("accent", "│");
			return [`${arrow}${bar}`, bar, bar, bar, bar];
		}
		return this.renderExpanded(w);
	}

	private renderExpanded(w: number): string[] {
		const lines: string[] = [];
		// Top: collapse arrow (now wider so the toggle reads clearly)
		lines.push(`${theme.fg("accent", "◂")} ${theme.fg("accent", "▎")} ${theme.fg("dim", "CORTEX")}`);
		lines.push(theme.fg("dim", "─".repeat(w - 1)));

		// 1. Topic (replaces Active Task — user feedback 2026-08-20:
		// "Tasks is redundant, go ahead and just remove that". Now this
		// slot shows the brainstorming-style context: keywords from the
		// latest user prompt + matched cold-memory domain.)
		lines.push(" ");
		lines.push(sectionHeader("Topic", w));
		const topic = readTopicForStrip();
		if (topic) {
			for (const t of topic.split(" · ")) {
				lines.push(sectionLine(`${theme.fg("accent", "◇")} ${t}`, w));
			}
		} else {
			lines.push(sectionLine(theme.fg("muted", "(no topic yet)"), w));
		}
		lines.push(sectionFooter(w));

		// 2. Sub-agents (real roster + live activity; owner 2026-10-13:
		// "the researchers and sub-agents should actually show up" — a
		// running subagent gets ▶, an idle one keeps its plain name).
		lines.push(" ");
		lines.push(sectionHeader("Sub-agents", w));
		const roster = readSubAgents();
		if (roster.length === 0) {
			lines.push(sectionLine(theme.fg("muted", "(no agents defined)"), w));
		} else {
			const live = readSubAgentActivity(roster.map((a) => a.name));
			for (const a of roster.slice(0, 5)) {
				const running = live.has(a.name);
				const glyph = running ? theme.fg("accent", "▶") : theme.fg("accent", "🤖");
				const name = running ? theme.fg("accent", a.name) : theme.fg("muted", a.name);
				lines.push(sectionLine(`${glyph} ${name}`, w));
			}
		}
		lines.push(sectionFooter(w));

		// 3. Memory recall — cold-memory TOPICS (domain names, newest write
		// first). Owner feedback 2026-08-20: raw counts are useless, show
		// topics; 2026-10-14 (local port): read THIS agent's store, not the legacy cortexllm path.
		lines.push(" ");
		lines.push(sectionHeader("Memory", w));
		const mem = readColdTopics();
		if (mem.length === 0) {
			lines.push(sectionLine(theme.fg("muted", "(no topics yet)"), w));
		} else {
			for (const m of mem.slice(0, 4)) {
				lines.push(sectionLine(`${theme.fg("accent", "◇")} ${m}`, w));
			}
		}
		lines.push(sectionFooter(w));

		// 4. Services — the same messenger/security rows the ☁️ box renders,
		// compressed to one line each so the strip mirrors the status bar.
		lines.push(" ");
		lines.push(sectionHeader("Services", w));
		for (const [key, icon] of [
			["messenger", "M"],
			["secops", "🛡"],
		] as const) {
			try {
				const d = JSON.parse(fs.readFileSync(path.join(PANEL_STATUS_DIR, `${key}.json`), "utf8"));
				const l1 = String(d.lines?.[0] ?? "no data").slice(0, 40);
				lines.push(sectionLine(`${theme.fg("success", icon)} ${theme.fg("muted", l1)}`, w));
			} catch {
				lines.push(sectionLine(`${theme.fg("muted", icon)} ${theme.fg("muted", "no data")}`, w));
			}
		}
		lines.push(sectionFooter(w));

		// 5. API Health — lanes per the hard-baked 2026-09-21 port map;
		// the old big/:8080 + proxy/:8081 rows died with the grammar proxy.
		lines.push(" ");
		lines.push(sectionHeader("API Health", w));
		lines.push(sectionLine(theme.fg("success", "● ollama :11600"), w));
		lines.push(sectionLine(theme.fg("success", "● lane :11598→11599"), w));
		lines.push(sectionFooter(w));

		return lines;
	}
}

// ── Strip data readers ──────────────────────────────────────────────────────

/** Roster from the fork agent dir's agents/*.md (frontmatter name/description). */
function readSubAgents(): { name: string; desc: string }[] {
	try {
		const out: { name: string; desc: string }[] = [];
		for (const e of fs.readdirSync(USER_AGENTS_DIR, { withFileTypes: true })) {
			if (!e.name.endsWith(".md") || !(e.isFile() || e.isSymbolicLink())) continue;
			const content = fs.readFileSync(path.join(USER_AGENTS_DIR, e.name), "utf8");
			const m = content.match(/^name:\s*(.+)$/m);
			const d = content.match(/^description:\s*(.+)$/m);
			// Duty-skill files without frontmatter still belong to the roster —
			// fall back to the filename so messenger/monitoring/security show.
			const name = m ? m[1].trim() : e.name.replace(/\.md$/, "");
			out.push({ name, desc: (d?.[1] ?? "").trim() || name });
		}
		return out;
	} catch {
		return [];
	}
}

/** Which roster names are active right now: live scheduler tasks whose
 * title contains the agent name, plus recent transcript toolCalls mapped to
 * roster words (mcp_messenger_* → "messenger"). */
function readSubAgentActivity(rosterNames: string[]): Set<string> {
	const active = new Set<string>();
	const liveTasks = readLiveTaskTitles();
	for (const t of liveTasks) {
		for (const name of rosterNames) {
			if (t.title.toLowerCase().includes(name.toLowerCase())) active.add(name);
		}
	}
	for (const call of readRecentToolNames()) {
		if (call.startsWith("mcp_messenger_") && rosterNames.includes("messenger")) active.add("messenger");
		if (call.startsWith("mcp_secops_") && rosterNames.includes("security")) active.add("security");
		if (call.startsWith("mcp_research_") && rosterNames.includes("deep-research")) active.add("deep-research");
	}
	return active;
}

/** Cold-memory topics: the store's own domain names, latest write first. */
function readColdTopics(): string[] {
	try {
		if (!fs.existsSync(COLD_DIR)) return [];
		const out: { name: string; ts: number }[] = [];
		for (const f of fs.readdirSync(COLD_DIR)) {
			if (!f.endsWith(".md")) continue;
			try {
				out.push({ name: f.replace(/\.md$/, ""), ts: fs.statSync(path.join(COLD_DIR, f)).mtimeMs });
			} catch {
				/* ignore */
			}
		}
		out.sort((a, b) => b.ts - a.ts);
		return out.slice(0, 4).map((x) => x.name);
	} catch {
		return [];
	}
}

// Topic for the left strip — keywords from the latest user prompt. Mirrors
// status-panels.ts extractTopic() so the strip + status bar agree.
const STOPWORDS = new Set(
	"the a an and or but if then else for to of in on at by with from as is are was were be been being do does did have has had this that these those it its what which who whom whose when where why how not no so too very just about into over under again further then once here there all any both each few more most other some such only own same than can will should now your you our their they them we us me my".split(
		" ",
	),
);

// 2026-10-14 (local port): hot rows are written by the memory daemon
// (lib/memory_daemon.py → hot/<platform>.jsonl). Pick the most-recently-touched
// hot file, the same file the daemon writes — never a hardcoded filename.
function readTopicForStrip(): string {
	try {
		if (!fs.existsSync(HOT_DIR)) return "";
		let hotFile: string | null = null;
		let bestM = -1;
		for (const f of fs.readdirSync(HOT_DIR)) {
			if (!f.endsWith(".jsonl")) continue;
			const p = path.join(HOT_DIR, f);
			try {
				const st = fs.statSync(p);
				if (st.size > 0 && st.mtimeMs > bestM) {
					bestM = st.mtimeMs;
					hotFile = p;
				}
			} catch {
				/* ignore */
			}
		}
		if (!hotFile) return "";
		const lines = fs.readFileSync(hotFile, "utf8").split("\n");
		for (let i = lines.length - 1; i >= 0; i--) {
			const line = lines[i].trim();
			if (!line) continue;
			try {
				const e = JSON.parse(line);
				// 2026-09-19: the pipeline occasionally writes the schema
				// inverted (role=<text>, content="user"). Accept both.
				let role = String(e.role ?? "");
				let content = String(e.content ?? "");
				if (role !== "user" && (content === "user" || content === "assistant" || content === "system")) {
					[role, content] = [content, role];
				}
				if (role !== "user") continue;
				if (/^smoke[-_]?\d/i.test(content.trim())) continue;
				const words = content
					.toLowerCase()
					.split(/[^a-z0-9]+/)
					.filter((w) => w.length >= 5 && !STOPWORDS.has(w));
				if (!words.length) continue;
				const ranked = words.sort((a, b) => b.length - a.length);
				return ranked.slice(0, 2).join(" · ");
			} catch {}
		}
	} catch {
		/* no hot store */
	}
	return "";
}