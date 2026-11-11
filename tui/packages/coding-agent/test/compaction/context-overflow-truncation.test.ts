import type { AgentMessage } from "@cortexagent/agent-core";
import { describe, expect, it } from "vitest";
import { chunkTextForWindow, estimateTokens, findCutPoint } from "../../src/core/compaction/compaction.ts";
import type { SessionEntry } from "../../src/core/session-manager.ts";

describe("Context overflow truncation", () => {
	it("should estimate tokens for a user message with text content", () => {
		const msg: AgentMessage = {
			role: "user",
			content: "Hello, world!",
			timestamp: new Date(),
			id: "test-1",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should estimate tokens for an assistant message with text content", () => {
		const msg: AgentMessage = {
			role: "assistant",
			content: [
				{ type: "text", text: "This is a long response with lots of detail about the topic being discussed." },
			],
			timestamp: new Date(),
			id: "test-2",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should estimate tokens for a custom (system) message", () => {
		const msg: AgentMessage = {
			role: "custom",
			content: "You are a helpful assistant.",
			timestamp: new Date(),
			id: "test-3",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should estimate tokens for a toolResult message", () => {
		const msg: AgentMessage = {
			role: "toolResult",
			content: '{"result": "success"}',
			timestamp: new Date(),
			id: "test-4",
			toolCallId: "tool-1",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should produce larger token estimates for larger messages", () => {
		const shortMsg: AgentMessage = {
			role: "user",
			content: "Hi",
			timestamp: new Date(),
			id: "test-5",
		};
		const longMsg: AgentMessage = {
			role: "user",
			content: "This is a very long message that contains a lot of text. ".repeat(100),
			timestamp: new Date(),
			id: "test-6",
		};
		const shortTokens = estimateTokens(shortMsg);
		const longTokens = estimateTokens(longMsg);
		expect(longTokens).toBeGreaterThan(shortTokens * 5); // Should be much larger
	});

	it("should estimate tokens for messages with thinking blocks", () => {
		const msg: AgentMessage = {
			role: "assistant",
			content: [
				{ type: "thinking", thinking: "Let me think about this...", source: "generated" },
				{ type: "text", text: "After thinking, I conclude..." },
			],
			timestamp: new Date(),
			id: "test-7",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should handle messages with image content", () => {
		const msg: AgentMessage = {
			role: "user",
			content: [
				{ type: "image", source: { type: "base64", media_type: "image/png", data: "base64data" } },
				{ type: "text", text: "What is in this image?" },
			],
			timestamp: new Date(),
			id: "test-8",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThan(0);
	});

	it("should handle empty messages", () => {
		const msg: AgentMessage = {
			role: "user",
			content: "",
			timestamp: new Date(),
			id: "test-9",
		};
		const tokens = estimateTokens(msg);
		expect(tokens).toBeGreaterThanOrEqual(0);
	});
});

function makeMessageEntry(index: number, content: string): SessionEntry {
	return {
		type: "message",
		id: `e${index}`,
		parentId: index === 0 ? null : `e${index - 1}`,
		timestamp: new Date().toISOString(),
		message: {
			role: "user",
			content,
			timestamp: new Date(),
			id: `m-${index}`,
		},
	};
}

describe("Chunked summarization (no truncation, 2026-10-11)", () => {
	it("never truncates: chunk union equals the original text", () => {
		const text = ["alpha beta gamma", "[Tool result]: x".repeat(200)].join("\n\n");
		const chunks = chunkTextForWindow(text, 300);
		expect(chunks.length).toBeGreaterThan(1);
		for (const chunk of chunks) expect(chunk.length).toBeLessThanOrEqual(300);
		expect(chunks.join("")).toBe(text);
	});

	it("returns one chunk for text within the window", () => {
		expect(chunkTextForWindow("hello", 300)).toEqual(["hello"]);
	});

	it("never produces empty chunks on pathological boundaries", () => {
		// Dense separator pattern: boundary search must still advance.
		const text = "\n\n\n".repeat(1000) + "end";
		const chunks = chunkTextForWindow(text, 50);
		expect(chunks.join("")).toBe(text);
		expect(chunks.every((c) => c.length > 0)).toBe(true);
	});
});

describe("findCutPoint must summarize oversized entries, not keep them", () => {
	it("cuts past a single entry larger than the whole keep budget when a later cut point exists", () => {
		const entries: SessionEntry[] = [
			makeMessageEntry(0, "old work"),
			makeMessageEntry(1, "G".repeat(4000)), // ~1000 estimated tokens, keepRecent 50
			makeMessageEntry(2, "final question"),
		];
		const cut = findCutPoint(entries, 0, entries.length, 50);
		expect(cut.firstKeptEntryIndex).toBe(2);
	});

	it("cuts at the oversized entry when it is the last cut point (legacy fallback)", () => {
		const entries: SessionEntry[] = [makeMessageEntry(0, "old work"), makeMessageEntry(1, "G".repeat(4000))];
		const cut = findCutPoint(entries, 0, entries.length, 50);
		expect(cut.firstKeptEntryIndex).toBe(1);
	});
});
