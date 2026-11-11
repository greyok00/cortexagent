// visual-chat.ts — 2026-11-09 owner order: beautify chat for a visual
// learner — tables/side-by-side data as box tables, numbers as inline
// bar/line charts, emoji status markers, all inside normal markdown so the
// TUI renders them natively.
// Mechanism: markdown transformer rewrites fenced blocks BEFORE the TUI's
// renderer sees them:
//   ```chart                     ```spark
//   label 42                     t1 3.2  t2 4.1 ...
//   label2 17
//   ```
// → pre-rendered bar chart with ╭─┬─╮ box glyphs + ▁▂▃▅▆▇█ blocks.
// Also maps checklist/section markers to emoji (✅ ⬜ 🔵 ⚠️) and pads
// pipe tables with aligned columns when the source table is ragged.
import type { ExtensionAPI } from "@cortexagent/coding-agent";

const BLOCKS = "▁▂▃▄▅▆▇█";


// 2026-11-10 owner bug fix: emoji markers broke box-table alignment — cell
// padding used .length (emoji count 1 but RENDER as 2 columns). All table
// padding now goes through this display-width helper (emoji, CJK and
// east-asian-wide chars count as 2; combining marks 0).
function dispWidth(s: string): number {
	let w = 0;
	for (const ch of s) {
		const cp = ch.codePointAt(0) ?? 0;
		if (cp >= 0x1f000 || (cp >= 0x2190 && cp <= 0x2bff) ||
			(cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0xac00 && cp <= 0xd7a3)) {
			w += 2;
		} else if (cp >= 0x0300 && cp <= 0x036f) {
			// combining mark: zero width
		} else {
			w += 1;
		}
	}
	return w;
}
function padDisp(s: string, w: number): string {
	const pad = w - dispWidth(s);
	return s + (pad > 0 ? " ".repeat(pad) : "");
}

function spark(values: number[]): string {
	if (!values.length) return "";
	const max = Math.max(...values), min = Math.min(...values);
	const span = max - min || 1;
	return [...values].map(v => BLOCKS[Math.min(7, Math.floor(((v - min) / span) * 7.99))]).join("");
}

function barChart(source: string): string {
	const rows: { label: string; value: number }[] = [];
	for (const raw of source.split("\n")) {
		const m = raw.match(/^\s*(.+?)\s*[|:=]\s*(-?[\d.,]+)\s*$/);
		if (m) {
			const v = Number.parseFloat(m[2].replace(",", "."));
			if (Number.isFinite(v)) rows.push({ label: m[1].trim(), value: v });
		}
	}
	if (rows.length < 2) return null as unknown as string;
	const max = Math.max(...rows.map(r => Math.abs(r.value)), 1e-9);
	const LABEL_W = Math.max(...rows.map(r => r.label.length), 4);
	const BAR_W = 24;
	const lines: string[] = [];
	for (const r of rows) {
		const w = Math.max(1, Math.round((Math.abs(r.value) / max) * BAR_W));
		const bar = "█".repeat(w) + "░".repeat(BAR_W - w);
		const val = String(Math.round(r.value * 100) / 100);
		lines.push(`${r.label.padEnd(LABEL_W)} │${bar}│ ${val}`);
	}
	lines.push(`${" ".repeat(LABEL_W)} └${"─".repeat(BAR_W)}┘`);
	return lines.join("\n");
}

function lineChart(source: string): string {
	const values: number[] = [];
	for (const raw of source.split(/[\s,;]+/)) {
		const v = Number.parseFloat(raw);
		if (Number.isFinite(v)) values.push(v);
	}
	if (values.length < 3) return null as unknown as string;
	return `${spark(values)}  (${values.length} points, ${Math.min(...values)}–${Math.max(...values)})`;
}

const EMOJI_MAP: Array<[RegExp, string]> = [
	[/^(\s*)-\s\[x\]\s/i, "$1✅ "],
	[/^(\s*)-\s\[\s\]\s/, "$1⬜ "],
	[/^(\s*)-\s\[~\]\s/, "$1🔄 "],
	[/^(\s*)-\s\[!\]\s/i, "$1⚠️  "],
	[/^(\s*)(PASS|OK|DONE)\b\s*[:\-]/i, "$1✅ $2: "],
	[/^(\s*)(FAIL|ERROR|BROKEN)\b\s*[:\-]/i, "$1❌ $2: "],
	[/^(\s*)(WARN|WARNING|SKIP|PENDING)\b\s*[:\-]/i, "$1⚠️  $2: "],
	[/^(\s*)(RUN|BUILD|START|TESTING)\b\s*[:\-]/i, "$1🔵 $2: "],
];


// 2026-11-10 owner: the ui framework now lives INSIDE the session chat —
// laser-purple keywords/inline-code against the greyscale UI, violet table
// borders, chart bars in the brain ramp. Constants match
// assets/framework/tokens-v2.css (obsidian) + splash.py's violet RAMP.
const LASER = "\x1b[38;5;213m";   // laser purple — keywords, bold
const SOFT  = "\x1b[38;5;141m";   // inline code / skill names
const LINE  = "\x1b[38;5;60m";    // table borders, axis lines
const OFF   = "\x1b[0m";


// 2026-11-10 (owner: "beautified by default", emoji outlines fixed): markdown
// pipe tables now auto-render as aligned box tables BEFORE the TUI sees them,
// with emoji-aware cell widths (dispWidth), violet header/ borders (framework
// tokens) — beautify is the default, not opt-in.
const V_HEADER = "\x1b[38;5;213m";
const V_BORDER = "\x1b[38;5;60m";
const V_OFF = "\x1b[0m";

function boxFromPipeTable(block: string): string | null {
	const raw = block.split("\n").filter((l) => l.trim().startsWith("|"));
	if (raw.length < 2) return null;
	const parse = (l: string) =>
		l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
	const header = parse(raw[0]);
	const isSep = (l: string) => /^\|\s*[-:|\s]+\|\s*$/.test(l);
	const bodyRows = raw.slice(1).filter((l) => !isSep(l));
	if (!bodyRows.length) return null;
	const all = [header, ...bodyRows.map(parse)];
	const cols = Math.max(...all.map((r) => r.length));
	const widths: number[] = [];
	for (let c = 0; c < cols; c++) {
		widths[c] = Math.max(...all.map((r) => dispWidth(r[c] ?? "")), 3);
	}
	const edge = (l: string, m: string, r: string) => V_BORDER + l + m.join("") + r + V_OFF;
	const sep = edge.call(null, "├", header.map(() => "─".repeat(widths[0])), "┤");
	void sep;
	const rule = header
		.map((_, c) => "─".repeat(widths[c] + 2))
		.join(V_BORDER + "┼" + V_OFF);
	const row = (cells: string[], isHead: boolean) =>
		"│ " +
		header
			.slice(0, cols)
			.map((_, c) => {
				const v = padDisp(cells[c] ?? "", widths[c]);
				return isHead ? V_HEADER + v + V_OFF : v;
			})
			.join(" │ ") +
		" │";
	const top = edge.call(null, "┌", header.map(() => "─".repeat(widths[0] + 1)), "┐");
	void top;
	const border = V_BORDER + "┌" + rule + "┐" + V_OFF;
	const bottom = V_BORDER + "└" + rule + "┘" + V_OFF;
	const out = [border, row(header, true), border.replace("┌", "├").replace("┐", "┤")];
	for (const r of bodyRows.map(parse)) out.push(row(r, false));
	out.push(bottom);
	return out.join("\n");
}

function beautifyTables(part: string): string {
	// apply to consecutive pipe-table blocks outside code fences
	const lines = part.split("\n");
	let i = 0;
	const out: string[] = [];
	while (i < lines.length) {
		const l = lines[i];
		if (l.trim().startsWith("|") && i + 1 < lines.length && /^\|\s*[-:|\s]+\|\s*$/.test(lines[i + 1].trim())) {
			let j = i + 2;
			while (j < lines.length && lines[j].trim().startsWith("|")) j++;
			const box = boxFromPipeTable(lines.slice(i, j).join("\n"));
			if (box) {
				out.push(box);
				i = j;
				continue;
			}
		}
		out.push(l);
		i++;
	}
	return out.join("\n");
}

function purpleAccents(part: string): string {
	// table borders + separators (box rows) go deep violet
	if (part.includes("|") && part.includes("--")) {
		part = part.replace(/^[-|\s]+$/gm, (r) => LINE + r + OFF);
	}
	// bold = laser purple keywords
	part = part.replace(/\*\*([^*]+)\*\*/g, `${LASER}$1${OFF}`);
	// skill mentions and ticked names = soft purple
	part = part.replace(/\b([a-z][a-z0-9-]+\.md)\b/g, `${SOFT}$1${OFF}`);
	return part;
}

export default function visualChat(pi: ExtensionAPI): void {
	pi.registerMarkdownTransformer((markdown, ctx) => {
		if (ctx.messageType !== "assistant") return markdown;
		// fenced chart/spark blocks
		let out = markdown.replace(
			/```(chart|spark|sparkline)\n([\s\S]*?)```/g,
			(_m, kind: string, body: string) => {
				let rendered: string | undefined;
				if (kind === "chart") rendered = barChart(body) ?? undefined;
				else rendered = lineChart(body) ?? undefined;
				return rendered == null ? _m : "```\n" + rendered + "\n```";
			},
		);
		// emoji markers line-wise (skip code fences)
		const parts = out.split(/(```[\s\S]*?```|`[^`]*`)/g);
		out = parts
			.map((part, i) => {
				if (i % 2 === 1) return part;
				return part
					.split("\n")
					.map((line) => {
						for (const [re, sub] of EMOJI_MAP) {
							if (re.test(line)) return line.replace(re, sub);
						}
						return line;
					})
					.join("\n");
			})
			.join("");
		return out;
	});
}
