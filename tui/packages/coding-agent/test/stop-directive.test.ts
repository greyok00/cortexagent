import { describe, expect, it } from "vitest";
import { isStopDirective } from "../src/core/stop-directive.ts";

describe("isStopDirective", () => {
	it("matches pure stop orders in any casing/punctuation", () => {
		expect(isStopDirective("STOP")).toBe(true);
		expect(isStopDirective("STOP NOW.")).toBe(true);
		expect(isStopDirective("stop it")).toBe(true);
		expect(isStopDirective("Stop That!")).toBe(true);
		expect(isStopDirective("halt")).toBe(true);
		expect(isStopDirective("abort")).toBe(true);
		expect(isStopDirective("cancel")).toBe(true);
		expect(isStopDirective("quit")).toBe(true);
		expect(isStopDirective("stop stop stop")).toBe(true);
		expect(isStopDirective("cancel that now please")).toBe(true);
		expect(isStopDirective("stop working")).toBe(true);
		expect(isStopDirective("stop doing that immediately")).toBe(true);
		expect(isStopDirective("stop everything")).toBe(true);
	});

	it("matches when wrapped in whitespace or backticks", () => {
		expect(isStopDirective("  STOP  ")).toBe(true);
		expect(isStopDirective('"stop now"')).toBe(true);
	});

	it("does not match normal task messages that merely contain a stop word", () => {
		expect(isStopDirective("STOP LOOKING FOR THE RADIOLOG SCRIPT NOW.")).toBe(false);
		expect(isStopDirective("stop the scan and list the results")).toBe(false);
		expect(isStopDirective("stop after 3 retries")).toBe(false);
		expect(isStopDirective("please stop the server, then restart it")).toBe(false);
	});

	it("matches when the FINAL sentence is a stop order, even in a mixed message", () => {
		// 2026-09-23 incident: "...WHAT DID I JUST SAY. STOP IT NOW" was queued
		// as steering and the run kept going. A trailing stop order is a stop.
		expect(isStopDirective("DO NOT EXTRACT OLD FILES LOOK AT THE TIMESTAMPS. STOP IT NOW")).toBe(true);
		expect(isStopDirective("delete the ssid list. stop.")).toBe(true);
		expect(isStopDirective("i said delete them\nSTOP NOW!")).toBe(true);
		expect(isStopDirective("you were told twice. halt immediately")).toBe(true);
	});

	it("still treats a stop word in the middle as steering, not abort", () => {
		expect(isStopDirective("STOP extracting and delete the files instead")).toBe(false);
		expect(isStopDirective("stop. now delete the files")).toBe(false);
		expect(isStopDirective("do not extract the ssid list i did not tell you to do that")).toBe(false);
	});

	it("does not match empty or unrelated input", () => {
		expect(isStopDirective("")).toBe(false);
		expect(isStopDirective("now connect to .68 instead")).toBe(false);
		expect(isStopDirective("continue")).toBe(false);
		expect(isStopDirective("stopped?")).toBe(false);
	});
});
