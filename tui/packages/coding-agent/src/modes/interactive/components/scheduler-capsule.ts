import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Component, truncateToWidth, visibleWidth } from "@cortexagent/tui";
import { theme } from "../theme/theme.ts";

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SCHEDULER CAPSULE
// Compact, borderless, color-rich status capsule rendered ABOVE the input box.
// Reads the scheduler store (~/.cortexagent/scheduler/tasks.json + executions)
// and shows at most 4 tasks, width-safe, with a one-line health header.
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const GLYPH = {
	active: "●",
	paused: "◌",
	running: "↻",
	success: "✓",
	failed: "✕",
	invalid: "!",
	waiting: "◷",
	accent: "◈",
	arrow: "↳",
	bar: "│",
};

interface SchedulerTask {
	id: string;
	title: string;
	kind: string;
	trigger: string;
	schedule: string;
	nextRunAt?: string;
	enabled: boolean;
	ephemeral: boolean;
	visible: boolean;
	/** Authoritative scheduler state: scheduled/queued/running/completed/failed/interrupted. */
	state: string;
	status: "running" | "active" | "paused" | "manual";
	lastResult?: "success" | "failed";
}

interface SchedulerState {
	tasks: SchedulerTask[];
	active: number;
	paused: number;
	running: number;
	manual: number;
	ok: boolean;
	error?: string;
}

// ── Cron normalization ──────────────────────────────────────────────────────
// Strip outer ()[]{} → commas→spaces → collapse whitespace → validate 5 fields.
function normalizeCron(raw: string | undefined): string | null {
	if (!raw) return null;
	let s = raw.trim();
	s = s.replace(/^[([{]+/, "").replace(/[)\]}]+$/, "");
	s = s.replace(/,/g, " ").replace(/\s+/g, " ").trim();
	const fields = s.split(" ");
	if (fields.length !== 5) return null;
	for (const f of fields) {
		if (!/^[0-9*/,-]+$/.test(f)) return null;
	}
	return s;
}

function humanizeCron(cron: string): string {
	const [min, hour, dom, mon, dow] = cron.split(" ");
	if (cron === "* * * * *") return "every minute";
	if (min === "0" && hour === "*" && dom === "*" && mon === "*" && dow === "*") return "hourly";
	if (min === "0" && hour !== "*" && dom === "*" && mon === "*" && dow === "*") return `daily ${hour}:00`;
	if (min === "0" && hour !== "*" && dom === "*" && mon === "*" && dow === "1-5") return `weekdays ${hour}:00`;
	return `cron ${cron}`;
}

// ── Relative time ("next 17h", "last 2m") ───────────────────────────────────
function relTime(iso: string | undefined, now: number): string | undefined {
	if (!iso) return undefined;
	const t = Date.parse(iso);
	if (Number.isNaN(t)) return undefined;
	const diffSec = Math.round((t - now) / 1000);
	const abs = Math.abs(diffSec);
	const unit = abs < 60 ? "s" : abs < 3600 ? "m" : abs < 86400 ? "h" : "d";
	const val =
		abs < 60
			? abs
			: abs < 3600
				? Math.round(abs / 60)
				: abs < 86400
					? Math.round(abs / 3600)
					: Math.round(abs / 86400);
	return diffSec >= 0 ? `next ${val}${unit}` : `last ${val}${unit}`;
}

// ── Store reading (cached, TTL ~1s) ─────────────────────────────────────────
// 2026-10-14 (local port): path follows CORTEXAGENT_STATE_DIR; default stays ~/.cortexagent.
const SCHEDULER_DIR = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "scheduler");
const TASKS_FILE = path.join(SCHEDULER_DIR, "tasks.json");
const EXEC_FILE = path.join(SCHEDULER_DIR, "executions.jsonl");
const CACHE_TTL = 1000;

let _cache: { at: number; state: SchedulerState } | undefined;

function readSchedulerState(): SchedulerState {
	const now = Date.now();
	if (_cache && now - _cache.at < CACHE_TTL) return _cache.state;

	let tasks: SchedulerTask[] = [];
	let ok = true;
	let error: string | undefined;

	try {
		const raw = fs.readFileSync(TASKS_FILE, "utf8");
		const obj = JSON.parse(raw) as Record<string, any>;
		const tasksById = new Map<string, SchedulerTask>();

		for (const rec of Object.values(obj)) {
			if (!rec || typeof rec !== "object") continue;
			// 2026-10-13 (owner): canceled/archived tasks are dead — a canceled
			// probe ruled the capsule forever. They do not get task rows.
			const recState = (rec as { state?: string }).state ?? "";
			if (recState === "canceled" || recState === "cancelled" || recState === "archived") continue;
			const id = rec.id;
			if (!id) continue;
			// dedup by stable id
			if (tasksById.has(id)) continue;
			const enabled = rec.enabled !== false;
			const trigger = rec.trigger || "manual";
			const cron = normalizeCron(rec.schedule_value);
			// Authoritative status comes from the task's `state` field, which the
			// overseer updates on dispatch (queued) and on completion (completed/
			// failed). Fall back to trigger/enabled for the resting state.
			const state = rec.state || "scheduled";
			const status: SchedulerTask["status"] = !enabled
				? "paused"
				: state === "queued" || state === "running"
					? "running"
					: trigger === "manual"
						? "manual"
						: "active";
			const lastResult: SchedulerTask["lastResult"] =
				state === "completed" ? "success" : state === "failed" || state === "interrupted" ? "failed" : undefined;
			tasksById.set(id, {
				id,
				title: rec.title || id,
				kind: rec.kind || "user",
				trigger,
				schedule: cron ?? rec.schedule_value ?? "",
				nextRunAt: rec.next_run_at,
				enabled,
				ephemeral: rec.ephemeral === true,
				visible: rec.visible !== false,
				state,
				status,
				lastResult,
			});
		}

		// Merge latest execution status (running / success / failed)
		try {
			const lines = fs.readFileSync(EXEC_FILE, "utf8").trim().split("\n");
			const lastByTask = new Map<string, { status: string; result: any }>();
			for (const line of lines) {
				if (!line.trim()) continue;
				try {
					const e = JSON.parse(line);
					if (e?.task_id) lastByTask.set(e.task_id, { status: e.status, result: e.result });
				} catch {
					/* skip malformed */
				}
			}
			for (const t of tasksById.values()) {
				const ex = lastByTask.get(t.id);
				if (!ex) continue;
				// The task `state` field is authoritative (overseer-synced). A
				// "pending" receipt with no queued/running state is stale (e.g. a
				// run_now that was never dispatched) — don't show it as running.
				if (t.state === "queued" || t.state === "running") {
					t.status = "running";
					continue;
				}
				// Only fill lastResult from receipts when the state didn't already
				// provide a terminal outcome (legacy tasks with no state sync).
				if (!t.lastResult && (ex.status === "completed" || ex.status === "success")) {
					t.lastResult = "success";
				} else if (!t.lastResult && (ex.status === "failed" || ex.status === "error")) {
					t.lastResult = "failed";
				}
			}
		} catch {
			/* executions optional */
		}

		tasks = Array.from(tasksById.values());
	} catch (e) {
		ok = false;
		error = e instanceof Error ? e.message : String(e);
	}

	// Sort: running → active → paused → manual; then next-run; then name
	const rank = (t: SchedulerTask) =>
		t.status === "running" ? 0 : t.status === "active" ? 1 : t.status === "paused" ? 2 : 3;
	tasks.sort((a, b) => {
		const r = rank(a) - rank(b);
		if (r !== 0) return r;
		const na = a.nextRunAt ? Date.parse(a.nextRunAt) : Infinity;
		const nb = b.nextRunAt ? Date.parse(b.nextRunAt) : Infinity;
		if (na !== nb) return na - nb;
		return a.title.localeCompare(b.title);
	});

	const state: SchedulerState = {
		tasks,
		active: tasks.filter((t) => t.status === "active").length,
		paused: tasks.filter((t) => t.status === "paused").length,
		running: tasks.filter((t) => t.status === "running").length,
		manual: tasks.filter((t) => t.status === "manual").length,
		ok,
		error,
	};
	_cache = { at: now, state };
	return state;
}

// ── Task fragment: ● name  schedule · detail ────────────────────────────────
function taskFragment(t: SchedulerTask, now: number, width: number): string {
	const glyph =
		t.status === "running"
			? theme.fg("warning", GLYPH.running)
			: t.status === "paused"
				? theme.fg("dim", GLYPH.paused)
				: t.status === "manual"
					? theme.fg("accent", GLYPH.active)
					: theme.fg("success", GLYPH.active);

	const nameColor: "success" | "text" | "dim" =
		t.status === "running" ? "text" : t.status === "paused" ? "dim" : "success";
	const name = theme.fg(nameColor, t.title);

	// schedule + detail
	const parts: string[] = [];
	if (t.trigger === "manual") {
		parts.push(theme.fg("dim", "manual"));
	} else if (t.schedule) {
		const cron = normalizeCron(t.schedule);
		if (cron) {
			parts.push(theme.fg("dim", humanizeCron(cron)));
		} else {
			parts.push(theme.fg("error", "invalid schedule"));
		}
	}

	// detail: next / last / running duration
	if (t.status === "running") {
		parts.push(theme.fg("warning", "running"));
	} else if (t.lastResult === "success") {
		parts.push(`${theme.fg("success", GLYPH.success)} ${relTime(t.nextRunAt, now) ?? ""}`.trim());
	} else if (t.lastResult === "failed") {
		parts.push(theme.fg("error", `${GLYPH.failed} failed`));
	} else if (t.nextRunAt) {
		const rel = relTime(t.nextRunAt, now);
		if (rel) parts.push(theme.fg("dim", rel));
	}

	const body = `${glyph} ${name}${parts.length ? "  " + parts.join("  ") : ""}`;
	return truncateToWidth(body, width, "…");
}

// ── Header: ◷ TASKS │ ● healthy · 3 active · 2 paused ─────────────────────
function buildHeader(state: SchedulerState): string {
	const title = theme.bold(theme.fg("accent", `${GLYPH.waiting} TASKS`));
	let health: string;
	if (!state.ok) {
		health = theme.fg("error", `${GLYPH.failed} offline · l logs`);
	} else if (state.tasks.length === 0) {
		health = theme.fg("dim", "no tasks");
	} else {
		const bits: string[] = [];
		bits.push(theme.fg("success", `${GLYPH.active} healthy`));
		if (state.active > 0) bits.push(theme.fg("text", `${state.active} active`));
		if (state.paused > 0) bits.push(theme.fg("dim", `${state.paused} paused`));
		if (state.running > 0) bits.push(theme.fg("warning", `${state.running} running`));
		health = bits.join(" · ");
	}
	return `${title} ${theme.fg("dim", GLYPH.bar)} ${health}`;
}

/**
 * Scheduler capsule — compact, borderless, at most 3 rows (header + 1-2 task rows).
 * Renders nothing when there are no tasks to show.
 */
export class SchedulerCapsuleComponent implements Component {
	private _cached?: { lines: string[]; width: number; at: number };

	invalidate(): void {
		this._cached = undefined;
	}

	render(width: number): string[] {
		const now = Date.now();
		if (this._cached && this._cached.width === width && now - this._cached.at < CACHE_TTL) {
			return this._cached.lines;
		}

		const state = readSchedulerState();
		// Only render if there are tasks to show
		if (!state.ok || state.tasks.length === 0) {
			this._cached = { lines: [], width, at: now };
			return [];
		}

		const panelWidth = Math.max(30, Math.min(72, width - 2));
		const lines: string[] = [];

		// Header
		lines.push(`  ${buildHeader(state)}`);

		// Task rows
		const visible = state.tasks.slice(0, 4);
		const more = state.tasks.length - visible.length;

		if (width >= 60) {
			// two fragments per row
			const fragW = Math.floor((panelWidth - 2) / 2);
			for (let i = 0; i < visible.length; i += 2) {
				const left = taskFragment(visible[i], now, fragW);
				const right = i + 1 < visible.length ? taskFragment(visible[i + 1], now, fragW) : "";
				const row = `  ${GLYPH.arrow} ${left}${right ? "  " + right : ""}`;
				lines.push(truncateToWidth(row, panelWidth + 2, "…"));
			}
		} else if (width >= 45) {
			// one fragment per row
			for (const t of visible) {
				lines.push(`  ${GLYPH.arrow} ${taskFragment(t, now, panelWidth - 2)}`);
			}
		} else {
			// compact: name + schedule only
			for (const t of visible.slice(0, 2)) {
				const glyph =
					t.status === "running"
						? theme.fg("warning", GLYPH.running)
						: t.status === "paused"
							? theme.fg("dim", GLYPH.paused)
							: theme.fg("success", GLYPH.active);
				const name = theme.fg(t.status === "paused" ? "dim" : "success", t.title);
				const sched = t.trigger === "manual" ? "manual" : humanizeCron(normalizeCron(t.schedule) ?? t.schedule);
				lines.push(`  ${GLYPH.arrow} ${glyph} ${name} · ${theme.fg("dim", sched)}`);
			}
		}

		// +N more suffix
		if (more > 0) {
			lines.push(`  ${GLYPH.arrow} ${theme.fg("dim", `+${more} more`)}`);
		}

		this._cached = { lines, width, at: now };
		return lines;
	}
}
