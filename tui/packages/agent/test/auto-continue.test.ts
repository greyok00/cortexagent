import { afterEach, describe, expect, it } from "vitest";
import {
	assistantText,
	autoContinueMax,
	buildAutoContinueNudge,
	isUnfinishedAnnouncement,
} from "../src/auto-continue.ts";

describe("autoContinueMax", () => {
	afterEach(() => {
		delete process.env.CORTEXAGENT_AUTO_CONTINUE_MAX;
	});

	it("defaults to 2 nudges per run", () => {
		expect(autoContinueMax()).toBe(2);
	});

	it("honours the env override, including 0 to disable", () => {
		process.env.CORTEXAGENT_AUTO_CONTINUE_MAX = "0";
		expect(autoContinueMax()).toBe(0);
		process.env.CORTEXAGENT_AUTO_CONTINUE_MAX = "5";
		expect(autoContinueMax()).toBe(5);
	});

	it("falls back to the default on nonsense input", () => {
		process.env.CORTEXAGENT_AUTO_CONTINUE_MAX = "many";
		expect(autoContinueMax()).toBe(2);
		process.env.CORTEXAGENT_AUTO_CONTINUE_MAX = "-3";
		expect(autoContinueMax()).toBe(2);
	});
});

describe("isUnfinishedAnnouncement", () => {
	it("catches the exact announcements that stalled runs on 2026-09-27", () => {
		// Verbatim from the session transcripts — each of these ended a run
		// with no tool call, which is the failure the owner reported.
		expect(
			isUnfinishedAnnouncement(
				"Wolf's down — no route to host. Your SMB connection to 192.168.0.61 isn't working. " +
					"Wolf may be off or disconnected. I'll retry and start the hotspot once it's back up.",
			),
		).toBe(true);
		expect(
			isUnfinishedAnnouncement(
				"I'm doing it. The SMB connection works — I can see Wolf's files. The issue is that " +
					"`run wsl.exe` isn't working on Wolf, but I can control it directly. " +
					"I'm going to pair Wolf and Parrot now.",
			),
		).toBe(true);
		expect(isUnfinishedAnnouncement("Let me check the status:")).toBe(true);
		expect(isUnfinishedAnnouncement("Now I'll list the interfaces on Wolf.")).toBe(true);
	});

	it("does not fire on a finished report", () => {
		expect(isUnfinishedAnnouncement("RAG is fully operational. Indexed docs: 118,305. That's it.")).toBe(false);
		expect(isUnfinishedAnnouncement("The fix is working. 9,516 runs, 75.5% saved. Nothing else to do.")).toBe(false);
		expect(isUnfinishedAnnouncement("Done — I'll leave the service as it was.")).toBe(false);
	});

	it("does not fire when the model hands the decision back to the user", () => {
		expect(isUnfinishedAnnouncement("Let me know if you want me to proceed")).toBe(false);
		expect(isUnfinishedAnnouncement("Should I restart the daemon now?")).toBe(false);
		expect(isUnfinishedAnnouncement("I can check that next — would you like me to?")).toBe(false);
	});

	it("ignores empty and non-string content", () => {
		expect(isUnfinishedAnnouncement("")).toBe(false);
		expect(isUnfinishedAnnouncement("   \n  ")).toBe(false);
		expect(isUnfinishedAnnouncement(undefined)).toBe(false);
		expect(isUnfinishedAnnouncement(null)).toBe(false);
	});

	it("only weights the tail of a long message", () => {
		const long = `${"Earlier context about the task. ".repeat(40)}Everything is verified and complete.`;
		expect(isUnfinishedAnnouncement(long)).toBe(false);
	});
});

describe("assistantText", () => {
	it("collects only visible text parts", () => {
		expect(
			assistantText([
				{ type: "thinking", text: "secret reasoning" },
				{ type: "text", text: "I'll check that." },
				{ type: "toolCall", text: "ignored" },
			]),
		).toBe("I'll check that.");
	});

	it("returns empty string for missing content", () => {
		expect(assistantText(undefined)).toBe("");
		expect(assistantText([])).toBe("");
	});
});

describe("buildAutoContinueNudge", () => {
	it("names the attempt count and the two acceptable answers", () => {
		const nudge = buildAutoContinueNudge(1, 2);
		expect(nudge).toContain("auto-continue 1/2");
		expect(nudge).toContain("tool call");
		expect(nudge).toContain("finished");
	});
});
