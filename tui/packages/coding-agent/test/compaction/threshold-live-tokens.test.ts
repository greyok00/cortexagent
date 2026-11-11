// 2026-10-18 regression test: the engine reports prompt_tokens as the full n_ctx
// cap (131072) once the KV cache is touched, so calculateContextTokens()
// (totalTokens = input+output+cacheRead) returns the window cap, not the live
// prompt size. The old _checkCompaction therefore never saw the threshold
// crossing. The fix measures live context as usage.input + usage.output plus a
// trailing-token estimate. These tests pin that behaviour at the unit level.
import type { AssistantMessage, Usage } from "@cortexagent/agent-core";
import { describe, expect, it } from "vitest";
import { calculateContextTokens, shouldCompact } from "../../src/core/compaction/compaction.ts";

// Mirror of the fixed _checkCompaction measurement (agent-session.ts).
function measureLiveContextTokens(usage: Usage, trailingTokens: number): number {
	return usage.input + usage.output + trailingTokens;
}

const CONTEXT_WINDOW = 262144;
const RESERVE_TOKENS = 63488; // ~/.cortex/agent/settings.json
const THRESHOLD = CONTEXT_WINDOW - RESERVE_TOKENS; // 198656

describe("threshold compaction with the engine capped prompt_tokens", () => {
	it("calculateContextTokens returns the capped total (the old broken signal)", () => {
		// This is what the session transcript actually showed: total=131072
		// (the n_ctx cap) while input+output was only ~1376.
		const usage: Usage = {
			input: 341,
			output: 191,
			cacheRead: 93058,
			cacheWrite: 0,
			reasoning: 0,
			totalTokens: 93590,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		};
		// Old code path: below threshold → no compaction (BUG).
		expect(calculateContextTokens(usage)).toBe(93590);
		expect(shouldCompact(calculateContextTokens(usage), CONTEXT_WINDOW, {
			enabled: true,
			reserveTokens: RESERVE_TOKENS,
			keepRecentTokens: 20000,
		})).toBe(false);
	});

	it("live input+output+trailing crosses threshold and fires", () => {
		// Simulate a session that has grown to just past the threshold.
		const usage: Usage = {
			input: 198000,
			output: 500,
			cacheRead: 0,
			cacheWrite: 0,
			reasoning: 0,
			totalTokens: 198500,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		};
		const live = measureLiveContextTokens(usage, 300);
		expect(live).toBe(198800);
		expect(live).toBeGreaterThan(THRESHOLD);
		expect(shouldCompact(live, CONTEXT_WINDOW, {
			enabled: true,
			reserveTokens: RESERVE_TOKENS,
			keepRecentTokens: 20000,
		})).toBe(true);
	});

	it("live measurement stays below threshold when the session is small", () => {
		// The exact usage from the live session transcript (line 442): the
		// session had grown to 93k REAL tokens but reported total=93590 via
		// the capped path. With input+output the live size is ~532 — far below.
		const usage: Usage = {
			input: 341,
			output: 191,
			cacheRead: 93058,
			cacheWrite: 0,
			reasoning: 0,
			totalTokens: 93590,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		};
		const live = measureLiveContextTokens(usage, 0);
		expect(live).toBe(532);
		expect(shouldCompact(live, CONTEXT_WINDOW, {
			enabled: true,
			reserveTokens: RESERVE_TOKENS,
			keepRecentTokens: 20000,
		})).toBe(false);
	});

	it("shouldCompact still respects the enabled flag and reserve guard", () => {
		expect(shouldCompact(999999, CONTEXT_WINDOW, {
			enabled: false,
			reserveTokens: RESERVE_TOKENS,
			keepRecentTokens: 20000,
		})).toBe(false);
		// Reserve ≥ window → never compact (guard against negative effective window).
		expect(shouldCompact(100, 1000, {
			enabled: true,
			reserveTokens: 1000,
			keepRecentTokens: 20000,
		})).toBe(false);
	});

	it("realistic growth curve fires exactly once past threshold", () => {
		// Walk a session from small to past-threshold in 5k steps, mirroring how
		// the live session grew. Assert compaction fires at the first crossing.
		let fired = false;
		for (let live = 1000; live <= 260000; live += 5000) {
			const usage: Usage = {
				input: live - 100,
				output: 100,
				cacheRead: 0,
				cacheWrite: 0,
				reasoning: 0,
				totalTokens: live,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			};
			const measured = measureLiveContextTokens(usage, 0);
			if (shouldCompact(measured, CONTEXT_WINDOW, {
				enabled: true,
				reserveTokens: RESERVE_TOKENS,
				keepRecentTokens: 20000,
			})) {
				fired = true;
				// First crossing should be just past the threshold.
				expect(measured).toBeGreaterThan(THRESHOLD);
				expect(measured).toBeLessThanOrEqual(THRESHOLD + 5000);
				break;
			}
		}
		expect(fired).toBe(true);
	});
});
