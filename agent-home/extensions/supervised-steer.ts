// supervised-steer.ts — 2026-11-09 owner order: supervise the session
// "from start to finish; if it breaks, have it learn how to get past it
// automatically... keep it going so it doesn't stop."
// Channel: an external supervision process appends one JSON line per steer
// to state/supervision/steer.jsonl. This extension polls that file and
// queues each message as real steering into the LIVE session. Only lines
// newer than the extension's start survive (history never replays).
import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

export default function supervisedSteer(pi: ExtensionAPI): void {
	const PATH = path.join(os.homedir(), "cortex-agent", "state", "supervision", "steer.jsonl");
	let offset = 0;
	try {
		offset = fs.existsSync(PATH) ? fs.statSync(PATH).size : 0;
	} catch {
		offset = 0;
	}

	const pump = () => {
		let data = "";
		try {
			const size = fs.statSync(PATH).size;
			// 2026-11-09 fix: rotation/truncation resyncs to EOF. The old
			// offset=0 replayed the ENTIRE file as new steers after any
			// rewrite (the heal.py backup-then-truncate purge is exactly
			// that event) — a mass [supervisor] flood into one turn.
			if (size < offset) offset = size; // rotated/truncated — resync, never replay
			if (size <= offset) return;
			const fd = fs.openSync(PATH, "r");
			const buf = Buffer.alloc(size - offset);
			fs.readSync(fd, buf, 0, buf.length, offset);
			fs.closeSync(fd);
			offset = size;
			data = buf.toString("utf8");
		} catch {
			return;
		}
		for (const line of data.split("\n")) {
			if (!line.trim()) continue;
			try {
				const rec = JSON.parse(line);
				const msg = String(rec.msg || "").trim();
				if (!msg) continue;
				pi.sendUserMessage(`[supervisor] ${msg}`, { deliverAs: "steer" });
			} catch {
				// partial line — next pump re-reads from the new offset; fine
			}
		}
	};

	// 2026-11-10 owner-reported bug fix: the polling interval kept the
	// event loop alive after --print answered (process hung until killed).
	// unref() lets the interval poll for the whole interactive session
	// while never being the thing that blocks a clean exit.
	setInterval(pump, 1500).unref();
}
