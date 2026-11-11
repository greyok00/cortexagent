import { describe, expect, it } from "vitest";
import {
	FEED_SOCKET,
	type FeedState,
	feedAgeMs,
	mergeFeedMessage,
	parseFeedBuffer,
} from "../src/modes/interactive/components/event-feed-client.ts";

function empty(): FeedState {
	return {
		connected: false,
		compression: null,
		routing: null,
		scheduling: null,
		memory: null,
		lastMessageAt: null,
	};
}

const SNAPSHOT = JSON.stringify({
	type: "snapshot",
	data: {
		compression: {
			runs: 9516,
			tokens_in: 919401718,
			ratio_pct: 75.5,
			last_run_ts: 1790093662.145819,
			source: "token_tracker",
		},
		routing: { route: "local", model: "cortexagent", router_mode: "auto" },
		scheduling: { task_count: 17, by_state: { scheduled: 10 }, tasks: [{ id: "a", title: "t", state: "scheduled" }] },
		memory: { tiers: { hot: 140, warm: 7, cold: 1 }, last_write_ts: 1, last_write_age_s: 10 },
	},
});

describe("parseFeedBuffer", () => {
	it("parses complete NDJSON lines and keeps the trailing partial", () => {
		const { messages, rest } = parseFeedBuffer('{"a":1}\n{"b":2}\n{"c":');
		expect(messages).toEqual([{ a: 1 }, { b: 2 }]);
		expect(rest).toBe('{"c":');
	});

	it("returns nothing and no rest for an empty buffer", () => {
		expect(parseFeedBuffer("")).toEqual({ messages: [], rest: "" });
	});

	it("skips a corrupt line instead of throwing", () => {
		const { messages } = parseFeedBuffer('not json\n{"ok":true}\n');
		expect(messages).toEqual([{ ok: true }]);
	});

	it("ignores blank lines", () => {
		expect(parseFeedBuffer("\n\n").messages).toEqual([]);
	});
});

describe("mergeFeedMessage", () => {
	it("fills every section from a snapshot", () => {
		const s = mergeFeedMessage(empty(), JSON.parse(SNAPSHOT));
		expect(s.compression?.runs).toBe(9516);
		expect(s.routing?.route).toBe("local");
		expect(s.scheduling?.task_count).toBe(17);
		expect(s.memory?.tiers.hot).toBe(140);
	});

	it("replaces only the named section on an event", () => {
		const base = mergeFeedMessage(empty(), JSON.parse(SNAPSHOT));
		const ev = {
			type: "event",
			event_type: "compression",
			data: { runs: 9517, ratio_pct: 76, last_run_ts: 1790094000 },
		};
		const s = mergeFeedMessage(base, ev);
		expect(s.compression?.runs).toBe(9517);
		// Untouched sections survive.
		expect(s.scheduling?.task_count).toBe(17);
		expect(s.memory?.tiers.hot).toBe(140);
	});

	it("carries the compressor probe through untouched", () => {
		// The panel decides whether to headline a ratio from this block, so it
		// must survive the merge verbatim (2026-09-27: the agent's lane :11599 is
		// not fronted by slimtoken, which is why the counter never moves).
		const snap = JSON.parse(SNAPSHOT);
		snap.data.compression.compressor = {
			running: true,
			ports: ["11435", "11436"],
			upstreams: ["http://127.0.0.1:11600"],
			lane: "http://127.0.0.1:11599",
			lane_port: "11599",
			in_path: false,
		};
		const s = mergeFeedMessage(empty(), snap);
		expect(s.compression?.compressor?.in_path).toBe(false);
		expect(s.compression?.compressor?.lane_port).toBe("11599");
		expect(s.compression?.compressor?.ports).toStrictEqual(["11435", "11436"]);
	});

	it("ignores unknown event types and malformed messages", () => {
		const base = mergeFeedMessage(empty(), JSON.parse(SNAPSHOT));
		expect(mergeFeedMessage(base, { type: "event", event_type: "telemetry", data: {} })).toBe(base);
		expect(mergeFeedMessage(base, null)).toBe(base);
		expect(mergeFeedMessage(base, "nope")).toBe(base);
		// A snapshot with no sections is a no-op on content (a fresh object is
		// fine — a partial snapshot must never blank a section that did arrive).
		expect(mergeFeedMessage(base, { type: "snapshot" })).toStrictEqual(base);
	});

	it("survives a chunk split mid-line across two reads", () => {
		const first = SNAPSHOT.slice(0, 40);
		const second = `${SNAPSHOT.slice(40)}\n`;
		const a = parseFeedBuffer(first);
		expect(a.messages).toHaveLength(0); // nothing complete yet
		const b = parseFeedBuffer(a.rest + second);
		expect(b.messages).toHaveLength(1);
		const s = mergeFeedMessage(empty(), b.messages[0]);
		expect(s.compression?.runs).toBe(9516);
	});
});

describe("feedAgeMs", () => {
	const now = 1_790_100_000_000;

	it("reads epoch seconds", () => {
		expect(feedAgeMs(1_790_099_940, now)).toBe(60_000);
	});

	it("reads epoch milliseconds", () => {
		expect(feedAgeMs(1_790_099_940_000, now)).toBe(60_000);
	});

	it("reads ISO strings, which the slimtoken ledgers use", () => {
		expect(feedAgeMs("2026-09-22T09:14:22.145Z", Date.parse("2026-09-22T09:15:22.145Z"))).toBe(60_000);
	});

	it("returns null for missing or unusable timestamps", () => {
		expect(feedAgeMs(null)).toBeNull();
		expect(feedAgeMs(undefined)).toBeNull();
		expect(feedAgeMs(0)).toBeNull();
		expect(feedAgeMs("not a date")).toBeNull();
	});

	it("never returns a negative age for a clock-skewed future stamp", () => {
		expect(feedAgeMs(1_790_100_600_000, now)).toBe(0);
	});
});

describe("socket path", () => {
	it("points at the daemon's socket", () => {
		// LOCAL (2026-10-13): FEED_SOCKET stays at ~/.cortexagent/state — the
		// local agent's own store. (Fork assertion about cortexagent-cloud
		// intentionally NOT ported — different agent dir by design.)
		expect(FEED_SOCKET.endsWith(".cortexagent/state/event_feed.sock")).toBe(true);
	});
});
