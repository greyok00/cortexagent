import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Component, truncateToWidth, visibleWidth } from "@cortexagent/tui";
import { theme } from "../theme/theme.ts";
import {
	type FeedCompression,
	type FeedCompressor,
	type FeedState,
	feedAgeMs,
	feedState,
} from "./event-feed-client.ts";

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// STATUS BAR — compact 4-box bordered table under the chat window.
//
//   ┌─ ⚡ Compression ───────┐ ┌─ 🧠 Memory ──────────┐ ┌─ 📅 Tasks ──────────────┐
//   │ ⠋ 42% saved · 4 runs    │ │ +2 recent            │ │ ◷ dip-screen-sweep      │
//   │ 25.1k in → 14.5k out     │ │ topic: web-dap       │ │ ◷ swing-research-cycle  │
//   └─────────────────────────┘ └──────────────────────┘ └ next 22m · 4 done ──────┘
//   ┌─ ☁️ Services ────────────────────────────────┐ │ 🤖 messenger·reply ×1  │
//   │ M Messenger — 0 texts · 0 emails waiting     │ │ 🤖 bash ×3             │
//   │ 🛡 Security Operations — no threats today    │ └─────────────────────────┘
//   └──────────────────────────────────────────────┘
//
// 2026-10-13 (owner): the old ☁️ Cloud Management box is GONE — not a cloud
// fork subsystem, not rendered, not hidden-but-listed. Memory stays in the
// top row beside compression; the tall Tasks box also carries 🤖 helper rows
// (the agent's most recent tool calls) so sub-agents/researchers/workers
// actually show up as they run; Services shows ONLY the two live helpers
// (messenger + security) with what they actually did and what to run next.
//
// Data comes from the event feed first (CORTEXAGENT_STATE_DIR/state/event_feed.sock,
// via event-feed-client.ts) and falls back to the files on disk when the daemon
// isn't serving. The feed is the live view; the files are the record.
//   - Compression : feed → CORTEXAGENT_STATE_DIR/minify_stats.json
//   - Memory      : feed tiers → CORTEXAGENT_MEMORY_DIR/{cold,hot}/
//   - Tasks       : feed → CORTEXAGENT_STATE_DIR/scheduler/tasks.json
//   - Topic       : latest user prompt in hot memory, keywords matched to cold domains
//   - Services    : CORTEXAGENT_STATE_DIR/panel-status/{messenger,secops}.json
//                   (daemon runs each helper with --write-status every 60s)
//   - 🤖 rows     : newest session transcript in CORTEX_CODING_AGENT_DIR/sessions
//
// A 500ms timer cycles a spinner char in the compression panel; the TUI's
// incremental renderer redraws only that one line in place, so the animation
// never spams the scrollback.
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const HOME = os.homedir();
// Store paths follow the CORTEXAGENT_* env set by the launcher; default stays ~/.cortex-agent.
const SCHEDULER_FILE = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "scheduler", "tasks.json");
// Real activity source: events.jsonl is the append-only history of every
// task created/started/done/failed. tasks.json is the snapshot — it
// empties out as soon as everything finishes, so reading it alone makes
// the Tasks panel look dead. Merge the two so scheduled-but-not-yet-run
// tasks are visible.
const SCHEDULER_EVENTS = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "scheduler", "tasks.events.jsonl");
// Execution receipts (append-only): one {task_id, status, started_at} line per
// scheduler run. The tall Tasks box reads the LAST receipt per task so a task
// that just ran keeps its ✓ instead of snapping back to plain "scheduled".
const SCHEDULER_EXEC_FILE = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "scheduler", "executions.jsonl");
// Three writers have produced compression numbers, and the panel used to read
// only the first of them: slimtoken's own state file. When slimtoken restarted
// it began writing the other two, so the single hardcoded path made the panel
// show older numbers than existed on disk — "the compression never calculates
// or shows ... it's basically putting in hard numbers instead" (owner report
// 2026-09-27). Read whichever file was written most recently, and carry its age
// so a frozen figure is labelled instead of passing as live.
const TOKEN_FILE = path.join(HOME, ".local", "state", "slimtoken", "stats.json");
// Store paths follow the CORTEXAGENT_* env set by the launcher; default stays ~/.cortex-agent.
const TOKEN_FILE_LEGACY = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "minify_stats.json");
const TOKEN_FILE_TRACKER = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "token_tracker.json");
/** Older than this and the numbers describe a run that has already ended. */
const COMPRESSION_LIVE_WINDOW_MS = 10 * 60 * 1000;
// 2026-10-14 (local port): the local agent reads ITS OWN store — env override first.
const COLD_DIR = path.join(process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory"), "cold");
const HOT_DIR = path.join(process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory"), "hot");

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

// ── Sanitize: strip URLs, JSON braces/quotes, control chars, collapse space ─
function sanitize(text: string): string {
	return text
		.replace(/https?:\/\/\S+/g, "[link]")
		.replace(/[{}[\]"\\]/g, " ")
		.replace(/[\r\n\t]+/g, " ")
		.replace(/\s+/g, " ")
		.trim();
}

function formatNum(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
	return String(n);
}

// ── Data readers ────────────────────────────────────────────────────────────

interface SchedulerTask {
	id?: string;
	title?: string;
	state?: string;
	status?: string;
	next_run_at?: string | null;
}

/**
 * The scheduler's task list as the feed reports it.
 *
 * `null` means "the feed isn't serving" — an empty array is a real answer and
 * must not be confused with it, or a live feed with zero tasks would fall back
 * to the file and resurrect stale rows.
 */
function schedulerTasksFromFeed(s: FeedState["scheduling"]): SchedulerTask[] | null {
	if (!s || !Array.isArray(s.tasks)) return null;
	return s.tasks.map((t) => ({ title: t.title, state: t.state, next_run_at: t.next_run_at ?? null }));
}

function readScheduler(): { tasks: SchedulerTask[]; ok: boolean; missing: boolean } {
	// Live feed first: one source, updated as the scheduler changes. The file is
	// the fallback for when the daemon isn't running.
	const feedTasks = schedulerTasksFromFeed(feedState().scheduling);
	if (feedTasks) return { tasks: feedTasks, ok: true, missing: false };
	// Distinguish "file doesn't exist" (no scheduler → "no scheduler")
	// from "file exists but empty {}" (scheduler is up, just idle →
	// "✓ idle"). User feedback 2026-08-20: empty tasks.json should NOT
	// render as "no scheduler"; the scheduler is clearly there.
	//
	// 2026-08-21: tasks.json is a FLAT DICT keyed by task-id (the
	// scheduler writes entries as {id: {title, state, ...}}), not the
	// {tasks: [...]} envelope the old reader assumed. The mismatch
	// made `data.tasks` always empty → panel permanently showed "no
	// active jobs" even when the scheduler had dozens of queued/running
	// tasks. Accept BOTH shapes (array envelope OR flat dict).
	try {
		if (!fs.existsSync(SCHEDULER_FILE)) return { tasks: [], ok: false, missing: true };
		const data = JSON.parse(fs.readFileSync(SCHEDULER_FILE, "utf8"));
		let tasks: SchedulerTask[];
		if (Array.isArray(data.tasks)) {
			tasks = data.tasks;
		} else if (data && typeof data === "object" && !Array.isArray(data)) {
			// Flat dict {id: {title, state, ...}} — values are the tasks.
			tasks = Object.values(data) as SchedulerTask[];
		} else {
			tasks = [];
		}
		return { tasks, ok: true, missing: false };
	} catch {
		return { tasks: [], ok: false, missing: false };
	}
}

/** All tasks ever touched, derived from the append-only event log.
 *
 * Merges the snapshot (state.json / tasks.json — current authoritative state)
 * with the events log so scheduled-but-not-yet-running tasks are still
 * visible. Returns a list of {id, title, state, ts}. Out-of-order events are
 * resolved by last-write-wins on `task_id`. Falls back to the snapshot alone
 * when the event log is missing.
 */
function readLiveActivity(): { id: string; title: string; state: string; ts: string }[] {
	const byId = new Map<string, { id: string; title: string; state: string; ts: string }>();
	// Latest known per id from the snapshot.
	// 2026-08-21: tasks.json may be a flat dict keyed by id, not the
	// {tasks: [...]} envelope. Accept BOTH.
	try {
		if (fs.existsSync(SCHEDULER_FILE)) {
			const data = JSON.parse(fs.readFileSync(SCHEDULER_FILE, "utf8"));
			const snapshot: any[] = Array.isArray(data.tasks)
				? data.tasks
				: data && typeof data === "object" && !Array.isArray(data)
					? Object.values(data)
					: [];
			for (const t of snapshot) {
				const id = String(t.id ?? "");
				if (!id) continue;
				byId.set(id, {
					id,
					title: String(t.title ?? "(untitled)"),
					state: String(t.state ?? t.status ?? "scheduled"),
					ts: String(t.next_run_at ?? t.last_run_at ?? t.updated_at ?? ""),
				});
			}
		}
	} catch {
		/* ignore */
	}
	// Events overwrite state by ts ordering (last-write-wins per task_id).
	try {
		if (fs.existsSync(SCHEDULER_EVENTS)) {
			const lines = fs.readFileSync(SCHEDULER_EVENTS, "utf8").split("\n");
			for (const raw of lines) {
				const line = raw.trim();
				if (!line) continue;
				let ev: any;
				try {
					ev = JSON.parse(line);
				} catch {
					continue;
				}
				const id = String(ev.task_id ?? "");
				if (!id) continue;
				const ts = String(ev.timestamp ?? "");
				const cur = byId.get(id);
				// If we already have a newer event for this id, skip.
				if (cur && cur.ts && ts && cur.ts >= ts) continue;
				// Map event type → state. Unknown types preserve current state.
				let state = cur?.state ?? "scheduled";
				if (ev.type === "create") state = "scheduled";
				else if (ev.type === "queue" || ev.type === "queued") state = "queued";
				else if (ev.type === "start" || ev.type === "running") state = "running";
				else if (ev.type === "done" || ev.type === "succeeded") state = "succeeded";
				else if (ev.type === "fail" || ev.type === "failed") state = "failed";
				else if (ev.type === "cancel") state = "cancelled";
				byId.set(id, {
					id,
					title: String(ev.data?.title ?? cur?.title ?? "(untitled)"),
					state,
					ts,
				});
			}
		}
	} catch {
		/* ignore */
	}
	// Filter out terminal states so the panel surfaces what's actually live.
	// User feedback 2026-08-20: "STILL HAS THE FUCKING SCHEDULED TASK LIST IN
	// THE MAIN TEXT" — seeded tasks with state="scheduled" but no actual
	// queue/run event are still "scheduled" but not actionable. Only show
	// tasks that have actually fired (queued or running). Seeded/manual tasks
	// with no event-driven state stay invisible until they move.
	const live = ["queued", "running"];
	const out = Array.from(byId.values()).filter((t) => live.includes(t.state));
	// Sort: running first, then queued, then scheduled; tie-break by ts.
	const order = (s: string) => (s === "running" ? 0 : s === "queued" ? 1 : 2);
	out.sort((a, b) => {
		const o = order(a.state) - order(b.state);
		if (o !== 0) return o;
		return (a.ts || "").localeCompare(b.ts || "");
	});
	return out;
}

/** Count of `done` / `succeeded` events in the last hour. Used so the
 * Idle panel can say "5 done recently" instead of looking dead forever. */
function countRecentCompleted(): number {
	let n = 0;
	const cutoff = Date.now() - 60 * 60 * 1000;
	try {
		if (!fs.existsSync(SCHEDULER_EVENTS)) return 0;
		for (const raw of fs.readFileSync(SCHEDULER_EVENTS, "utf8").split("\n")) {
			const line = raw.trim();
			if (!line) continue;
			let ev: any;
			try {
				ev = JSON.parse(line);
			} catch {
				continue;
			}
			if (ev.type !== "done" && ev.type !== "succeeded") continue;
			const ts = Date.parse(String(ev.timestamp ?? ""));
			if (Number.isFinite(ts) && ts >= cutoff) n++;
		}
	} catch {
		/* ignore */
	}
	return n;
}

interface CompressionStats {
	runs: number;
	tokensIn: number;
	tokensOut: number;
	saved: number;
	ratio: number;
	ok: boolean;
	/** Milliseconds since the numbers were written, or null when unknown. */
	ageMs: number | null;
	/** Which file the numbers came from. */
	source: string | null;
	/** True when the numbers are recent enough to describe current traffic. */
	live: boolean;
	/** Live state of the compressor itself, when the feed reports it. */
	compressor?: FeedCompressor | null;
}

/** The most recently written of the compression ledgers. */
function newestCompressionFile(): { file: string; label: string; mtimeMs: number } | null {
	let best: { file: string; label: string; mtimeMs: number } | null = null;
	for (const [label, file] of [
		["token_tracker", TOKEN_FILE_TRACKER],
		["slimtoken", TOKEN_FILE],
		["slimtoken (legacy)", TOKEN_FILE_LEGACY],
	] as const) {
		try {
			const st = fs.statSync(file);
			if (!st.isFile() || st.size === 0) continue;
			if (!best || st.mtimeMs > best.mtimeMs) best = { file, label, mtimeMs: st.mtimeMs };
		} catch {
			/* missing or unreadable — try the next one */
		}
	}
	return best;
}

/**
 * The feed's compression section as panel stats.
 *
 * Age is recomputed from the ledger's own `last_run_ts` rather than the feed's
 * `age_s`/`live` fields: those were true when the daemon built the snapshot, and
 * a snapshot is sent only once per connection, so trusting them would label a
 * five-day-old figure as current — the exact fault being fixed here.
 */
function compressionFromFeed(c: FeedCompression | null): CompressionStats | null {
	if (!c || typeof c.runs !== "number") return null;
	const ageMs = feedAgeMs(c.last_run_ts);
	return {
		runs: c.runs,
		tokensIn: c.tokens_in ?? 0,
		tokensOut: c.tokens_out ?? 0,
		saved: c.tokens_saved ?? 0,
		ratio: c.ratio_pct ?? 0,
		ok: true,
		ageMs,
		source: `feed · ${c.source ?? "?"}`,
		live: ageMs !== null && ageMs < COMPRESSION_LIVE_WINDOW_MS,
		compressor: c.compressor ?? null,
	};
}

/**
 * How old the numbers are: the ledger's own `last_run_ts`, and only if that is
 * missing, the file's mtime.
 *
 * The mtime was the old answer and it lied by design — `token_tracker.json` is
 * rewritten on every agent restart, so its mtime is minutes old while the runs
 * it totals are five days old. `last_run_ts` is the writer's own word.
 */
function ledgerAgeMs(t: { last_run_ts?: number | string } | null, mtimeMs: number): number | null {
	const fromLedger = feedAgeMs(t?.last_run_ts ?? null);
	if (fromLedger !== null) return fromLedger;
	return mtimeMs > 0 ? Math.max(0, Date.now() - mtimeMs) : null;
}

function readSlimToken(): CompressionStats {
	// Live feed first: it carries the same ledgers plus the writer's own
	// timestamps, and it cannot be shadowed by a stale file left on disk.
	const fromFeed = compressionFromFeed(feedState().compression);
	if (fromFeed) return fromFeed;
	const missing: CompressionStats = {
		runs: 0,
		tokensIn: 0,
		tokensOut: 0,
		saved: 0,
		ratio: 0,
		ok: false,
		ageMs: null,
		source: null,
		live: false,
	};
	try {
		const pick = newestCompressionFile();
		if (!pick) return missing;
		const d = JSON.parse(fs.readFileSync(pick.file, "utf8"));
		// minify_stats.json is flat; token_tracker.json wraps under `total`.
		const t = d.total ?? d;
		const ageMs = ledgerAgeMs(t, pick.mtimeMs);
		return {
			runs: t.runs ?? 0,
			tokensIn: t.tokens_in ?? 0,
			tokensOut: t.tokens_out ?? 0,
			saved: t.tokens_saved ?? 0,
			ratio: t.ratio_pct ?? 0,
			ok: true,
			ageMs,
			source: pick.label,
			live: ageMs !== null && ageMs < COMPRESSION_LIVE_WINDOW_MS,
		};
	} catch {
		return missing;
	}
}

/**
 * What the footer's ⚡ capsule should say — the panel's number, or an honest
 * "off".
 *
 * The footer used to read `~/.cortex-agent/minify_stats.json` on its own, a
 * different writer from the panel's, so one screen showed two compression
 * figures at once ("0.0%" beside "75.5%", owner report 2026-09-27). Both now
 * come from this one reader, and neither prints a percentage that no live
 * traffic backs — a figure that cannot move is the stub the owner rejected.
 * `null` means there is nothing to claim, so the capsule is omitted rather
 * than replaced by a guess.
 */
export function compressionCapsuleText(s: {
	ok: boolean;
	live: boolean;
	ratio: number;
}): { text: string; live: boolean } | null {
	if (!s.ok) return null;
	if (!s.live) return { text: "off", live: false };
	return { text: `${s.ratio.toFixed(1)}%`, live: true };
}

/** The capsule for whatever the ledgers (or the feed) say right now. */
export function compressionCapsule(): { text: string; live: boolean } | null {
	return compressionCapsuleText(readSlimToken());
}

/** "7h ago" / "12m ago" — short enough for the panel's second line. */
function formatAge(ms: number): string {
	const mins = Math.floor(ms / 60000);
	if (mins < 1) return "just now";
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

/**
 * The same idea, but past a day it names the date instead of counting.
 *
 * "5d ago" invites the reading that this is a slow trickle of recent work. A
 * total that stopped five days ago should look stopped, so say when it stopped.
 */
function formatLedgerAge(ms: number, now = Date.now()): string {
	if (ms < 24 * 3600_000) return formatAge(ms);
	const d = new Date(now - ms);
	const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
	return `${month} ${d.getDate()}`;
}

/**
 * Why a frozen counter is frozen.
 *
 * Four different situations produce the same non-moving number, and naming
 * which one it is is the difference between a status panel and a stub: the
 * compressor is gone, it is up but nothing is routed through it, it is up and
 * idle on a lane the agent does not use (the live 2026-09-27 case — traffic goes
 * to engine-server :11599 while slimtoken fronts ollama :11600), or it is in the
 * lane with every rewriting stage switched off, which is a pass-through and not
 * a fault (owner's staged ramp, 2026-09-27: the lane proxy starts gutted so it
 * cannot mangle data; a "not compressing" panel is then the truth, not a
 * breakage). With no probe at all the honest answer is that we don't know, not
 * that slimtoken is down: the panel used to call a missing probe "slimtoken not
 * running" while slimtoken was in fact running, which is a worse lie than a
 * stale number.
 */
function compressionReason(c: FeedCompressor | null | undefined): string {
	if (!c) return "no compressor data";
	if (!c.in_path) return "bypasses slimtoken";
	if (!c.running) return "slimtoken down";
	if (c.stages && c.stages.length === 0) return "passing through";
	return "no traffic through it";
}

/**
 * Line 2 of the compression panel, cut down to what the panel can actually show.
 *
 * Each panel is a third of the terminal, so the same sentence has ~22 cells at
 * 80 columns and ~35 at 120. A fixed wording does not truncate cleanly — it ends
 * mid-date ("… · last run Sep" cut to "… · last run Sep"), which reads as broken
 * text rather than as status (owner report 2026-09-27). The longest form that
 * fits wins, and the reason alone is the floor, so the line never ends in an
 * ellipsis.
 */
function compressionDetailLine(s: CompressionStats, contentW: number): string {
	const reason = compressionReason(s.compressor);
	const age = s.ageMs !== null ? formatLedgerAge(s.ageMs) : null;
	const forms = age ? [`${reason} · last run ${age}`, `${reason} · ${age}`, reason] : [reason];
	for (const form of forms) {
		if (visibleWidth(form) <= contentW) return form;
	}
	return forms[forms.length - 1]!;
}

/**
 * The two ⚡ Compression lines.
 *
 * Line 1 is a claim about now, so it carries a percentage only while traffic is
 * actually being compressed. A total frozen five days ago — 9,516 runs from a
 * proxy deleted 2026-09-22 — rendered as "76% saved" is the stub the owner
 * rejected (2026-09-27: "it's just stub text that never updates"): a ledger's
 * numbers are evidence of past runs, not status, and they belong on line 1 only
 * while they move. When they don't, line 1 says what is true of the compressor
 * now and line 2 carries the reason, sized to the panel.
 */
function compressionStatusLines(
	s: CompressionStats,
	spinner: string,
	changed: boolean,
	contentW = Number.POSITIVE_INFINITY,
): { l1: string; l2: string } {
	if (s.live) {
		return {
			l1: `${spinner} ${theme.fg("success", `${s.ratio.toFixed(0)}% saved${changed ? " ✓" : ""}`)} · ${s.runs} runs`,
			l2: `${formatNum(s.tokensIn)} in → ${formatNum(s.tokensOut)} out`,
		};
	}
	return {
		l1: `${spinner} ${theme.fg("warning", "not compressing")}`,
		l2: theme.fg("warning", compressionDetailLine(s, contentW)),
	};
}

/** Running work first, then queued, then failed, then scheduled. */
function schedulerTaskRank(state: string): number {
	if (ACTIVE_STATES.has(state) || state === "running") return 0;
	if (state === "queued") return 1;
	if (state === "failed") return 2;
	return 3;
}

/**
 * The 📅 Tasks rows: the scheduler's own tasks, most live first.
 *
 * These rows used to come from the dispatcher queue — a different subsystem,
 * and an empty one — so the scheduler's tasks were never listed and the box
 * read "queue empty" while the store held 17 of them (owner report 2026-09-27:
 * "the tasks scheduler doesn't show any tasks").
 */
function schedulerTaskLines(
	tasks: readonly SchedulerTask[],
	frame: number,
	max = 6,
): { lines: string[]; total: number } {
	// 2026-10-13 (owner): dead tasks (canceled/archived) never render — a
	// canceled probe task sat in the box forever and looked like a broken
	// list with one stuck row.
	const usable = tasks.filter(
		(t) =>
			String(t.title ?? "").trim() !== "" &&
			!DEAD_TASK_STATES.has(String(t.state ?? t.status ?? "scheduled")),
	);
	const sorted = [...usable].sort((a, b) => {
		const ra = schedulerTaskRank(String(a.state ?? a.status ?? "scheduled"));
		const rb = schedulerTaskRank(String(b.state ?? b.status ?? "scheduled"));
		if (ra !== rb) return ra - rb;
		return String(a.title ?? "").localeCompare(String(b.title ?? ""));
	});
	const lines: string[] = [];
	for (const t of sorted) {
		if (lines.length >= max) break;
		const state = String(t.state ?? t.status ?? "scheduled");
		const active = ACTIVE_STATES.has(state);
		const g = active ? SPINNER[frame % SPINNER.length]! : (STATE_GLYPH[state] ?? "·");
		const c = active ? "accent" : g === "!" || g === "⨯" ? "warning" : g === "✓" ? "success" : "muted";
		lines.push(`${theme.fg(c, g)} ${sanitize(t.title ?? "")}`);
	}
	if (sorted.length > lines.length) {
		lines.push(theme.fg("muted", `+${sorted.length - lines.length} more scheduled`));
	}
	return { lines, total: sorted.length };
}

function readMemoryCounts(): { recent: { cold: number; hot: number } } {
	let recentCold = 0;
	let recentHot = 0;
	// The feed's memory section is the store's own tally, and the only source
	// that still works if the memory dirs move.
	const feedMem = feedState().memory;
	// 24h ago — used to surface "is anything actually being written?".
	// User feedback 2026-08-20: "memory is playing right there, doesn't
	// even work, it doesn't capture any information, doesn't upload the
	// memory, doesn't update anything."  A blank store could mean either a
	// rich corpus or a dead system. Show the 24h write count so the user
	// can tell at a glance. 2026-10-13 (fork): count ROWS written in 24h,
	// not merely files touched — hot is one NDJSON per platform here, so a
	// single append would otherwise read as the same "recent" for days.
	const cutoff = Date.now() - 24 * 60 * 60 * 1000;
	const recentRows = (dir: string, ext: string): number => {
		let n = 0;
		try {
			if (!fs.existsSync(dir)) return 0;
			for (const f of fs.readdirSync(dir)) {
				if (!f.endsWith(ext)) continue;
				try {
					const st = fs.statSync(path.join(dir, f));
					if (st.mtimeMs < cutoff) continue;
					const buf = fs.readFileSync(path.join(dir, f), "utf8");
					let nl = 0;
					for (let i = buf.length - 1; i >= 0; i--) {
						if (buf[i] === "\n") nl++;
					}
					if (buf.length > 0 && !buf.endsWith("\n")) nl++;
					n += nl;
				} catch {
					/* ignore */
				}
			}
		} catch {
			/* ignore */
		}
		return n;
	};
	recentCold = recentRows(COLD_DIR, ".json");
	recentHot = recentRows(HOT_DIR, ".jsonl");
	// A zero recent count means "no file was written today". The feed knows
	// whether the memory layer wrote anything at all, so when it says the
	// last write is inside the window, report one instead of a bare "nothing"
	// (socket writes the disk scan missed, rotation, etc.).
	if (
		recentCold + recentHot === 0 &&
		((typeof feedMem?.tiers?.hot === "number" && feedMem.tiers.hot > 0) ||
			(typeof feedMem?.last_write_age_s === "number" && feedMem.last_write_age_s < 86_400))
	) {
		recentHot = 1;
	}
	return { recent: { cold: recentCold, hot: recentHot } };
}

/** Does the feed have a memory tier line to show? */
function feedTierLine(feedMem: FeedState["memory"]): string | null {
	// 2026-10-13 (owner: warm tier removed — hot + cold only; warm was a
	// session bridge that no longer exists). Counts are ROWS via the feed
	// tally, not files — hot is one NDJSON per platform in this fork.
	if (!feedMem?.tiers) return null;
	const { hot, cold } = feedMem.tiers as { hot?: number; cold?: number };
	if (typeof hot !== "number" || typeof cold !== "number") return null;
	return `${hot} hot · ${cold} cold`;
}

// ── Current topic: keywords from the latest user prompt, matched to cold domains ─
const STOPWORDS = new Set(
	"the a an and or but if then else for to of in on at by with from as is are was were be been being do does did have has had this that these those it its what which who whom whose when where why how not no so too very just about into over under again further then once here there all any both each few more most other some such only own same than can will should now your you our their they them we us me my".split(
		" ",
	),
);

function readColdCategoryNames(): Set<string> {
	const names = new Set<string>();
	try {
		if (!fs.existsSync(COLD_DIR)) return names;
		for (const f of fs.readdirSync(COLD_DIR)) {
			if (f.endsWith(".json")) names.add(f.replace(/\.json$/, "").toLowerCase());
		}
	} catch {
		/* ignore */
	}
	return names;
}

// Smoke / test markers that have polluted hot memory on this box
// (smoke-1787XXXXXX-XX, verify-* ids, etc). The previous code happily
// surfaced them as "topics" — useless noise. User feedback 2026-08-20.
const NOISE_PATTERNS = [
	/^smoke[-_]?\d/i,
	/^\d{6,}$/, // pure-numeric tokens (timestamps, pids, unix ts)
	/^verify[-_]?/i,
	/^test[-_]?/i,
	/^[a-f0-9]{8,}$/i, // hex hashes
];

function isNoise(word: string): boolean {
	return NOISE_PATTERNS.some((re) => re.test(word));
}

// 2026-10-14 (local port): hot rows are written by the memory daemon
// (lib/memory_daemon.py → hot/<platform>.jsonl). Never hardcode a single filename —
// pick the most-recently-touched hot file, the same file the daemon writes.
function latestHotFile(): string | null {
	try {
		if (!fs.existsSync(HOT_DIR)) return null;
		let best: string | null = null;
		let bestM = -1;
		for (const f of fs.readdirSync(HOT_DIR)) {
			if (!f.endsWith(".jsonl")) continue;
			const p = path.join(HOT_DIR, f);
			try {
				const st = fs.statSync(p);
				if (st.size <= 0) continue;
				if (st.mtimeMs > bestM) {
					bestM = st.mtimeMs;
					best = p;
				}
			} catch {
				/* ignore */
			}
		}
		return best;
	} catch {
		return null;
	}
}

// ── Messenger panel-status extras ──────────────────────────────────────
// The messenger writer folds its own state into line 2 of its payload
// ("Texting browser closed · run /messenger up ... · last 14:25"). The
// Services row already shows the summary; these two pull the SAME file's
// line 2 for (a) the HH:MM freshness stamp and (b) the browser status word —
// one reader, no second probe of the browser.
function latestMessengerLine2(): string {
	try {
		const d = JSON.parse(fs.readFileSync(path.join(MCP_STATUS_DIR, "messenger.json"), "utf8"));
		const lines = Array.isArray(d.lines) ? d.lines.map(String) : [];
		return lines[1] ?? "";
	} catch {
		return "";
	}
}

/** "5-min auto-check on · last 14:25" from the messenger payload's line 2. */
function latestMessengerStamp(): string | null {
	const l2 = latestMessengerLine2();
	if (!l2) return null;
	const m = /last (\d{1,2}:\d{2})/.exec(l2);
	const check = l2.includes("checked for replies every") || l2.includes("every 5 min");
	if (m && check) return `5-min auto-check on · last ${m[1]}`;
	if (m) return `auto-check · last ${m[1]}`;
	return null;
}

/** The browser status word from line 2: "live" | "closed" | null. */
function latestMessengerBrowser(): string | null {
	const l2 = latestMessengerLine2();
	if (!l2) return null;
	if (/browser closed/i.test(l2)) return "closed";
	const m = /browser live/i.exec(l2);
	if (m) return "live";
	return null;
}

// ── Last execution receipts per task (status + time) ───────────────────────
// executions.jsonl is append-only: {task_id, status, started_at...}. The
// LAST receipt per task answers "did the previous run work", which
// tasks.json alone loses (its state returns to "scheduled" as soon as the
// next slot is computed).
function readLastExecutions(): Map<string, { status: string; ts: string }> {
	const byId = new Map<string, { status: string; ts: string }>();
	try {
		if (!fs.existsSync(SCHEDULER_EXEC_FILE)) return byId;
		for (const raw of fs.readFileSync(SCHEDULER_EXEC_FILE, "utf8").split("\n")) {
			const line = raw.trim();
			if (!line) continue;
			try {
				const e = JSON.parse(line);
				const id = String(e.task_id ?? "");
				if (!id) continue;
				byId.set(id, { status: String(e.status ?? ""), ts: String(e.started_at ?? e.completed_at ?? "") });
			} catch {
				/* skip malformed */
			}
		}
	} catch {
		/* ignore */
	}
	return byId;
}

function extractTopic(): string {
	try {
		const hotFile = latestHotFile();
		if (!hotFile) return "";
		const lines = fs.readFileSync(hotFile, "utf8").split("\n");
		// Scan at most the last 50 user prompts so a buried real question
		// isn't masked by 30 minutes of smoke tests.
		const userLines: string[] = [];
		for (let i = lines.length - 1; i >= 0 && userLines.length < 50; i--) {
			const line = lines[i].trim();
			if (!line) continue;
			try {
				const e = JSON.parse(line);
				let role = String(e.role ?? "");
				let content = String(e.content ?? "");
				if (role !== "user" && (content === "user" || content === "assistant" || content === "system")) {
					[role, content] = [content, role];
				}
				if (role === "user") userLines.push(content);
			} catch {
				/* skip unparseable line */
			}
		}
		const cats = readColdCategoryNames();
		for (const content of userLines) {
			// Skip smoke-test-looking prompts outright so a single
			// genuine question buried in test traffic wins.
			if (/^smoke[-_]?\d/i.test(content.trim())) continue;
			const words = content
				.toLowerCase()
				.split(/[^a-z0-9]+/)
				.filter((w) => w.length >= 5 && !STOPWORDS.has(w) && !isNoise(w));
			if (!words.length) continue;
			// Rank: cold-domain matches first, then longer words.
			const ranked = words.sort((a, b) => {
				const aCat = cats.has(a) ? 1 : 0;
				const bCat = cats.has(b) ? 1 : 0;
				if (aCat !== bCat) return bCat - aCat;
				return b.length - a.length;
			});
			const top = ranked.slice(0, 2);
			if (top.length) return top.join(" · ");
		}
	} catch {
		/* no hot store */
	}
	return "";
}

// ── Box-drawing helpers ─────────────────────────────────────────────────────
// Width math is done in VISIBLE cells, not String.length. Both `title` (via
// theme.fg) and `content` (via theme.fg / truncateToWidth) carry ANSI escape
// sequences that inflate String.length without contributing display cells.
// padEnd/repeat against String.length under-fills the panel and breaks the
// borders when they're stacked side-by-side with panelBottom (which has no
// ANSI and therefore hits exactly w cells).
function panelTop(title: string, w: number, padAdjust = 0): string {
	// 2026-10-14: emoji-width drift (☁️ measures 2 in visibleWidth but renders
	// 1 cell on some terminals — and the TUI CRASHES on any over-width line)
	// killed the fork at startup. Rule: the dash run is COMPOSED BY COUNT from
	// the measured title width — never by measuring the composed border and
	// refilling a shortfall. The old refill appended "─" PAST the closing ┐
	// (the border measured one short only because padAdjust had shrunk it on
	// purpose), which put a literal stray dash in the seam between the
	// Services box and the Tasks column (owner 2026-10-14: "┐─ │").
	// padAdjust < 0 compensates the emoji's render-measure gap by carving
	// cells out of the DASH RUN only — corners and title never move.
	// padAdjust > 0 is clamped away: measuring wider than the box renders is
	// the over-width direction the renderer's width guard crashes on.
	const inner = w - 2;
	const t = ` ${title} `;
	const tVisible = Math.max(0, visibleWidth(t) + (padAdjust > 0 ? padAdjust : 0));
	if (tVisible >= inner) {
		return `┌${truncateToWidth(t, inner, "…", false)}┐`;
	}
	const dashes = Math.max(0, inner - tVisible + Math.min(0, padAdjust));
	return `┌${t}${"─".repeat(dashes)}┐`;
}

function panelRow(content: string, w: number, padAdjust = 0): string {
	const inner = w - 2;
	const c = truncateToWidth(content, inner, "…");
	// padAdjust < 0 trades one trailing pad cell for the emoji's render-measure
	// gap so the row's right border lands in the same cell as the box's top
	// border (measured stays ≤ w; clamped: content never gains cells).
	const pad = " ".repeat(Math.max(0, inner - visibleWidth(c) + Math.min(0, padAdjust)));
	return `│${c}${pad}│`;
}

function panelBottom(w: number, padAdjust = 0): string {
	// Same compose-by-count rule as panelTop, same padAdjust semantics: the
	// dash run comes straight from w — no measure-and-refill — so no "─" can
	// ever follow the ┘, and the Services bottom edge meets the Tasks column
	// exactly where its rows do.
	const dashes = Math.max(0, w - 2 + Math.min(0, padAdjust));
	return `└${"─".repeat(dashes)}┘`;
}

// Exported for unit testing the width-math invariants.

// ── Services box (owner order 2026-10-13: ☁️ Cloud Management is REMOVED) ──
// Only two rows render, both from CORTEXAGENT_STATE_DIR/panel-status/*.json —
// the payload each helper server writes via `--write-status` (the fork daemon
// runs that one-shot every 60s). The TUI is a pure renderer; nothing here
// spawns the comms browser or pokes the security stack.
const MCP_STATUS_DIR = process.env.CORTEXAGENT_STATUS_DIR
	?? path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "panel-status");
const MCP_STALE_MS = 5 * 60 * 1000;

interface HelperStatus {
	/** panel-status file stem: "messenger" or "secops" */
	key: string;
	summary: string;
	stale: boolean;
	latest?: string; // server-provided detail line (what it actually did)
}

function readHelperStatus(key: string): HelperStatus {
	try {
		const d = JSON.parse(fs.readFileSync(path.join(MCP_STATUS_DIR, `${key}.json`), "utf8"));
		const ts = Number(d.ts) || 0;
		const lines = Array.isArray(d.lines) ? d.lines.map(String) : [];
		return {
			key,
			summary: lines[0] ?? String(d.summary ?? "no data"),
			latest: lines[1],
			stale: Date.now() - ts > MCP_STALE_MS,
		};
	} catch {
		return { key, summary: "no data", stale: false };
	}
}

/** The ☁️ Services row payloads (2026-10-13 owner: say what it DOES and how
 * to act, sized to fit). Renderers pick the form that fits the width so
 * nothing ends in an ellipsis:
 *   M Messenger — 1 text waiting · 0 emails waiting · 0 sent today · browser closed (/messenger up)
 *   🛡 Security Operations — no threats today · protection on + the deep fact
 *     it rotated in this refresh (what it actually did), then the jobs line
 *     ("auto: responderd reacts to threats · fail2ban bans brute · ...").
 */
function servicePayloads(): {
	messenger: { icon: string; name: string; forms: string[]; stale: boolean };
	secops: { icon: string; name: string; forms: string[]; stale: boolean };
	footer: string;
} {
	const msg = readHelperStatus("messenger");
	const sec = readHelperStatus("secops");
	const stamp = latestMessengerStamp();
	const browser = latestMessengerBrowser();
	const nums = /(?:^|\s)(\d+ text[s]? waiting \u00b7 \d+ email[s]? waiting(?: \u00b7 \d+ sent today)?)/.exec(msg.summary)?.[1] ?? msg.summary;
	const jobs = (sec.latest && sec.latest.includes("auto:")) ? sec.latest : "";
	const deep = (sec.latest && !sec.latest.includes("auto:")) ? sec.latest : "";
	const secForms = [
		deep ? `${sec.summary} · ${deep}` : sec.summary,
		sec.summary,
	];
	if (jobs) secForms.unshift(jobs);
	// The browser line is the ACTION rows — it must survive narrow widths, so
	// it lives on the footer row instead of competing with the counts:
	//   browser closed · run /messenger up · last 15:01
	const browserCore = browser ? (browser === "closed" ? "browser closed · run /messenger up" : "browser live") : null;
	const footerForms = browserCore
		? stamp
			? [`${browserCore} · ${stamp}`, browserCore, stamp]
			: [browserCore]
		: stamp
			? [stamp]
			: ["checking every 5 min"];
	return {
		messenger: {
			icon: theme.fg(msg.stale ? "warning" : "success", "M"),
			name: "Messenger",
			// The 50-form rule: “1 text waiting · 0 emails waiting · 1 sent
			// today” and its summary twin are distinct forms here — when the
			// counts regex misses (payload without counts), the summary is
			// the only truthful line and dedup would hide it.
			forms: nums === msg.summary ? [nums] : [nums, msg.summary],
			stale: msg.stale,
		},
		secops: {
			icon: theme.fg(sec.stale ? "warning" : "success", "🛡"),
			name: "Security Operations",
			forms: secForms,
			stale: sec.stale,
		},
		footer: fitForm(footerForms, Number.POSITIVE_INFINITY, false),
	};
}

/** First service form that fits in `w` visible cells; the last form is the
 * floor so the line never ends in an ellipsis. Stale payloads render warning. */
function fitForm(forms: readonly string[], w: number, stale: boolean): string {
	for (const f of forms) {
		if (visibleWidth(f) <= w) return stale ? theme.fg("warning", f) : theme.fg("success", f);
	}
	// No form fits: truncate the SHORTEST form (still readable), never a long
	// one — truncating the longest form was how "… · last 15:02" lost the
	// time stamp first.
	const shortest = forms.reduce((a, b) => (visibleWidth(b) < visibleWidth(a) ? b : a));
	return stale ? theme.fg("warning", truncateToWidth(shortest, w, "…")) : theme.fg("success", truncateToWidth(shortest, w, "…"));
}

// ── 🤖 helper rows: what the agent is doing right now (newest transcript) ──
// Sub-agents, researchers and workers run as tool calls inside THIS session's
// transcript (agent/sessions/<cwd>/*.jsonl, updated live). The most recent
// toolCalls are the truthful picture of who is running — no extra probe, no
// queue, no guessing from task titles.
const TRANSCRIPTS_DIR = path.join(
	process.env.CORTEX_CODING_AGENT_DIR
		?? path.join(os.homedir(), ".cortex", "agent"),
	"sessions",
);

interface ToolCallRow {
	name: string;
	count: number;
}

function readRecentToolCalls(): ToolCallRow[] {
	try {
		// Newest transcript dir: the agent dir encodes the cwd as `--home-...`.
		let bestDir: string | null = null;
		let bestM = -1;
		for (const e of fs.readdirSync(TRANSCRIPTS_DIR, { withFileTypes: true })) {
			if (!e.isDirectory()) continue;
			try {
				const m = fs.statSync(path.join(TRANSCRIPTS_DIR, e.name)).mtimeMs;
				if (m > bestM) {
					bestM = m;
					bestDir = e.name;
				}
			} catch {
				/* ignore */
			}
		}
		if (!bestDir) return [];
		const dir = path.join(TRANSCRIPTS_DIR, bestDir);
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
		// Walk BACKWARD only — the newest entries win and a big session never
		// costs O(file). Stop after enough recent toolCalls.
		const seq: string[] = [];
		for (let i = lines.length - 1; i >= 0 && seq.length < 12; i--) {
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
				/* skip malformed */
			}
		}
		// Collapse to name + count, newest first.
		const out: ToolCallRow[] = [];
		for (const name of seq) {
			const hit = out.find((r) => r.name === name);
			if (hit) hit.count++;
			else out.push({ name, count: 1 });
		}
		return out;
	} catch {
		return [];
	}
}

/** Label a recent toolCall in owner vocabulary: mcp_messenger_* → the
 * researcher/worker doing messenger work, plain names stay plain. */
function helperLabel(name: string): { label: string; who: "messenger" | "research" | "worker" | "agent" } {
	if (name.startsWith("mcp_messenger_")) return { label: "messenger·reply", who: "messenger" };
	if (name.startsWith("mcp_research_")) return { label: "research·cycle", who: "research" };
	if (name.startsWith("mcp_workers_")) return { label: "workers·earn", who: "worker" };
	if (name.startsWith("mcp_secops_")) return { label: "security·check", who: "agent" };
	if (name.startsWith("spawn_subagent")) return { label: "subagent·spawn", who: "research" };
	if (name.startsWith("mcp_")) return { label: name.slice(4), who: "agent" };
	return { label: name, who: "agent" };
}

const HELPER_GLYPH: Record<string, string> = {
	messenger: "✉",
	research: "▶",
	worker: "$",
	agent: "🤖",
};

/** The agent's own core tool calls — not sub-agents. 🤖 rows are for the
 * helpers that run THROUGH those tools; the brain's own bash/read/edit calls
 * would only drown them (owner: "the main agent posing as a subagent"). */
const AGENT_OWN_TOOLS = new Set(["bash", "read", "edit", "write", "grep", "find", "ls"]);

/** Filter recent toolCalls down to true helper activity. A helper is an
 * MCP/harness tool call (messenger, research, workers, secops, spawn) or a
 * custom tool that is not one of the loop's own primitives. */
function helperRows(calls: readonly ToolCallRow[]): ToolCallRow[] {
	return calls.filter((c) => !AGENT_OWN_TOOLS.has(c.name));
}

// 2026-10-14 (local port): dispatcher rows removed from the Tasks box —
// it is not a panel subsystem; only scheduler rows render.
const ACTIVE_STATES = new Set(["running", "claimed", "ready", "optimizing"]);

const STATE_GLYPH: Record<string, string> = {
	running: "▶",
	claimed: "▶",
	ready: "▶",
	pending: "·",
	flagged: "!",
	done: "✓",
	blocked: "⨯",
	// Scheduler states (lib/scheduler/store.py): the 📅 Tasks box lists these,
	// so they need glyphs of their own.
	scheduled: "◷",
	queued: "◦",
	succeeded: "✓",
	failed: "!",
	cancelled: "⨯",
};

// Terminal-by-owner states: the scheduler keeps the records, but the fork
// UI must not list them (owner 2026-10-13: "canceled probe sat there
// forever — that's the only task"). Cancel/archive = gone from every view.
const DEAD_TASK_STATES = new Set(["canceled", "cancelled", "archived"]);

// ── Cloud-line deepening (owner directive 2026-10-13): secops and messenger
// rows come from their servers' --write-status payload (label/icon/lines).
// Extra context the servers carry (last scan, protection ages, browser
// readiness) is already folded into those lines by the servers themselves —
// the panel stays a pure renderer.

// ── When may the panel block join a frame? ──────────────────────────────────
// The panel block is the tallest thing in the dock, and in inline mode a frame
// that carries it but no session content is committed to SCROLLBACK at the top
// of the session — where it stays for the rest of the run, showing values that
// have since moved on (owner report 2026-09-27: a Cloud Management / Messenger
// box sitting above [Context]). So the signal is "the session view has been
// composed", not elapsed time: the [Context] pass waits on extensions, skills,
// themes and a local model warm-up, and that outran the old 2s stopwatch.
export const PANELS_FALLBACK_MS = 30_000;

/** Safety net: a view that never composes must still get its panels. */
export function panelsMayJoinFrame(
	state: { sessionViewComposed: boolean; fallbackAt: number },
	now: number = Date.now(),
): boolean {
	return state.sessionViewComposed || now >= state.fallbackAt;
}

// ── Component: compact 3-panel bordered status table ────────────────────────
// 2026-10-24 (owner): Tasks + Services panels REMOVED — none of them worked.
// The bar is now three equal-height boxes: ⚡ Compression · 🧠 Memory · 🔢 Tokens.
// Tokens is real data, not a stub: totals come from the caller's session
// (provider.getSessionStats — the usage the model itself reports per reply),
// and the realtime speed is derived from the engine's /metrics counters
// (llamacpp:tokens_predicted_total / _seconds_total, delta over the 500ms
// frame — a moving count of what the model is generating RIGHT NOW).
export interface StatusPanelSessionProvider {
	/** Session totals; undefined = no session yet, panel shows an honest 0. */
	getSessionStats?(): { tokens: { total: number; output: number; input: number } } | undefined;
}

export interface LaneMetrics {
	requests: number;
	promptTokens: number;
	completionTokens: number;
	avgTokS: number;
	epochMs: number;
}

export class StatusPanelsComponent implements Component {
	private frame = 0;
	private timer: NodeJS.Timeout | null = null;
	private lastDataHash = "";
	private flashTimer: NodeJS.Timeout | null = null;
	private readonly onTick?: () => void;
	private readonly sessionProvider?: StatusPanelSessionProvider;
	// 2026-10-24 (owner: "last run Oct 3 — cortexagent wasn't even in existence
	// then!"): the ledgers on disk are ghosts from pre-cortexagent runs. The
	// live truth is the slimtoken lane's own /metrics, polled here each tick
	// and cached for the synchronous render.
	private laneStats: LaneMetrics | null = null;
	private laneLastPoll = 0;
	private laneUrl = (process.env.CORTEXENGINE_LOCAL_BASE ?? "http://127.0.0.1:7081/v1").replace(/\/v1$/, "") + "/metrics";
	// Realtime speed: stream deltas (one delta ≈ one generated token) are
	// stamped on arrival; the tok/s line is the count of deltas in the last
	// second, recomputed every render. The "generating" state lingers 1.2s
	// after the last delta so brief stalls don't flicker to idle.
	private deltaTimestamps: number[] = [];
	private generatingUntil = 0;

	constructor(onTick?: () => void, sessionProvider?: StatusPanelSessionProvider) {
		this.onTick = onTick;
		this.sessionProvider = sessionProvider;
		this.timer = setInterval(() => {
			this.frame = (this.frame + 1) % SPINNER.length;
			void this.pollLane();
			this.onTick?.();
		}, 500);
	}

	private async pollLane(): Promise<void> {
		if (Date.now() - this.laneLastPoll < 2000 && this.laneLastPoll > 0) return;
		this.laneLastPoll = Date.now();
		try {
			const res = await fetch(this.laneUrl, { signal: AbortSignal.timeout(700) });
			if (!res.ok) return;
			const d = (await res.json()) as Record<string, unknown>;
			this.laneStats = {
				requests: Number(d.requests ?? 0),
				promptTokens: Number(d.prompt_tokens ?? 0),
				completionTokens: Number(d.completion_tokens ?? 0),
				avgTokS: Number(d.avg_tok_s ?? 0),
				epochMs: Date.now(),
			};
		} catch {
			this.laneStats = null;
		}
	}

	/** One streamed token landed. Called from the agent session's
	 * message_update (text_delta/thinking_delta) events by the owner mode. */
	onStreamDelta(): void {
		const now = Date.now();
		this.deltaTimestamps.push(now);
		this.generatingUntil = Math.max(this.generatingUntil, now + 1200);
	}

	/** Session-level generate/idle transition (agent_start / agent_end). */
	onGenerationState(active: boolean): void {
		if (active) {
			this.deltaTimestamps.length = 0;
			this.generatingUntil = Math.max(this.generatingUntil, Date.now() + 1200);
		} else {
			// End of turn: keep the last window visible for the 1.2s linger
			// handled by the expiry in the render, then it flips to idle.
		}
	}

	dispose(): void {
		if (this.timer) clearInterval(this.timer);
		this.timer = null;
	}

	invalidate(): void {
		// Data is re-read on every render; nothing to cache.
	}

	render(width: number): string[] {
		const gap = 1;
		const panelW = Math.max(14, Math.floor((width - gap * 2) / 3));
		const spinner = SPINNER[this.frame];

		// Panel 1: Compression — fed by the slimtoken lane's LIVE metrics.
		// 2026-10-24 (owner): the old on-disk ledgers stopped being written
		// during the cortexagent era and showed "last run Oct 3" ghosts from a
		// pre-cortexagent machine; the lane's /metrics is the only source that
		// reflects this session's actual traffic.
		const lane = this.laneStats;
		const laneFresh = lane !== null && Date.now() - lane.epochMs < 6000;
		// Detect data change → flash effect
		const dataHash = lane ? `${lane.requests}-${lane.promptTokens}-${lane.completionTokens}` : "lane-down";
		const changed = laneFresh && dataHash !== this.lastDataHash;
		this.lastDataHash = dataHash;
		if (changed) {
			if (this.flashTimer) clearTimeout(this.flashTimer);
			this.flashTimer = setTimeout(() => {
				this.flashTimer = null;
				this.onTick?.();
			}, 1200);
		}
		const compTitle = theme.fg("dim", "⚡ Compression");
		// panelW minus the two borders and the leading spinner cell — line 2 is
		// sized to this so it is never cut mid-date.
		const compL1 = laneFresh
			? `${spinner} ${theme.fg(changed ? "accent" : "success", `${lane!.requests} req served${changed ? " ✓" : ""}`)}`
			: `${spinner} ${theme.fg("warning", "lane down")}`;
		const compL2 = laneFresh
			? `${formatNum(lane!.promptTokens)} in → ${formatNum(lane!.completionTokens)} out${lane!.avgTokS > 0 ? ` · ${lane!.avgTokS.toFixed(1)} tok/s avg` : ""}`
			: theme.fg("muted", "no lane on :7081 — traffic goes direct");

		// Panel 2: Memory — recent additions + current topic. User feedback
		// 2026-08-20: "30 cold, 29 hot, that doesn't help at all. I don't
		// need to see those numbers. I want to see recent additions,
		// topics. That's it."
		// 2026-10-13 (fork): counts are ROWS, not files; no warm tier.
		const { recent } = readMemoryCounts();
		const topic = extractTopic();
		const memTitle = theme.fg("dim", "🧠 Memory");
		const last24 = recent.cold + recent.hot;
		const memL1 =
			last24 > 0 ? `${theme.fg("success", "+")}${last24} recent` : theme.fg("warning", "no recent writes");
		// Topic when there is one; otherwise the live tier counts from the feed, so
		// the line reports the store rather than an em dash (owner report
		// 2026-09-27: the panel's numbers never came from the feed).
		const memTiers = feedTierLine(feedState().memory);
		const memL2 = topic
			? `topic: ${theme.fg("accent", topic)}`
			: memTiers
				? theme.fg("muted", memTiers)
				: theme.fg("muted", "topic: —");

		// Panel 3: Tokens — the session's real usage plus the speed of the
		// model generating RIGHT NOW (owner spec 2026-10-24). Totals come
		// from the session provider (usage the model itself reports per
		// reply); speed is the delta of the engine's /metrics counters.
		const stats = this.sessionProvider?.getSessionStats?.();
		const totalTok = stats?.tokens.total ?? 0;
		const outTok = stats?.tokens.output ?? 0;
		const genTok = Math.max(0, totalTok - (stats?.tokens.input ?? 0) - outTok); // cache traffic
		const tokTitle = theme.fg("dim", "🔢 Tokens");
		const tokL1 =
			totalTok > 0
				? `${theme.fg("success", formatNum(totalTok))} tok session · ${formatNum(outTok)} out${genTok > outTok ? ` · ${formatNum(genTok)} cache` : ""}`
				: theme.fg("muted", "0 tok — session empty");
		const now = Date.now();
		while (this.deltaTimestamps.length > 0 && now - this.deltaTimestamps[0]! > 1000) {
			this.deltaTimestamps.shift();
		}
		const generating = this.generatingUntil > now;
		const tokL2 = generating
			? `${theme.fg("accent", SPINNER[this.frame % SPINNER.length]!)} ${theme.fg("accent", `${this.deltaTimestamps.length} tok/s`)}`
			: theme.fg("muted", "idle — not generating");

		// Assemble the grid (2026-10-24 owner redesign): three EQUAL-HEIGHT boxes
		// — the same 4-line height the old Compression/Memory boxes had. Tasks
		// and Services are gone entirely (owner: "none of them work").
		const rows: string[] = [];
		const w = panelW;
		const cell = (content: string, width: number, padAdjust = 0) => {
			const inner = width - 2;
			const c = truncateToWidth(content, inner, "…");
			const pad = " ".repeat(Math.max(0, inner - visibleWidth(c) + (padAdjust < 0 ? padAdjust : 0)));
			return `│${c}${pad}│`;
		};
		// 2026-10-14 (owner: "fix it where the frame lines up"): no padAdjust —
		// compose-by-count from panelTop/panelBottom keeps every box measured ==
		// rendered so the seams between the three boxes stay exact (over-render
		// trips the width guard that crashed the fork once already).
		rows.push(
			`${panelTop(compTitle, w)}${" ".repeat(gap)}${panelTop(memTitle, w)}${" ".repeat(gap)}${panelTop(tokTitle, w)}`,
		);
		rows.push(`${cell(compL1, w)}${" ".repeat(gap)}${cell(memL1, w)}${" ".repeat(gap)}${cell(tokL1, w)}`);
		rows.push(`${cell(compL2, w)}${" ".repeat(gap)}${cell(memL2, w)}${" ".repeat(gap)}${cell(tokL2, w)}`);
		rows.push(
			`${panelBottom(w)}${" ".repeat(gap)}${panelBottom(w)}${" ".repeat(gap)}${panelBottom(w)}`,
		);
		return rows;
	}
}

// ── Test surface ────────────────────────────────────────────────────────────
// Kept at the end of the module: a `const` referenced from here before its
// declaration is a temporal-dead-zone crash at import time, not a test failure.
export const __test = {
	panelTop,
	panelRow,
	panelBottom,
	formatAge,
	formatLedgerAge,
	compressionStatusLines,
	compressionReason,
	compressionCapsuleText,
	schedulerTaskLines,
	compressionFromFeed,
	schedulerTasksFromFeed,
	feedTierLine,
	ledgerAgeMs,
	panelsMayJoinFrame,
	PANELS_FALLBACK_MS,
	// 2026-10-13 (owner redesign): services rows + helper rows + receipts.
	servicePayloads,
	fitForm,
	readHelperStatus,
	helperLabel,
	readRecentToolCalls,
	readLastExecutions,
	latestMessengerStamp,
	latestMessengerBrowser,
};
