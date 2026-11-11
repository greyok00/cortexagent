import { stripVTControlCharacters } from "node:util";
import { setKeybindings, visibleWidth } from "@cortexagent/tui";
import { beforeAll, beforeEach, describe, expect, test } from "vitest";
import { KeybindingsManager } from "../src/core/keybindings.ts";
import type {
	ModelChangeEntry,
	SessionEntry,
	SessionMessageEntry,
	SessionTreeNode,
} from "../src/core/session-manager.ts";
import { TreeSelectorComponent } from "../src/modes/interactive/components/tree-selector.ts";
import { initTheme } from "../src/modes/interactive/theme/theme.ts";

beforeAll(() => {
	initTheme("dark");
});

beforeEach(() => {
	setKeybindings(new KeybindingsManager());
});

function userMessage(id: string, parentId: string | null, content: string): SessionMessageEntry {
	return {
		type: "message",
		id,
		parentId,
		timestamp: new Date().toISOString(),
		message: { role: "user", content, timestamp: Date.now() },
	};
}

function assistantMessage(id: string, parentId: string | null, text: string): SessionMessageEntry {
	return {
		type: "message",
		id,
		parentId,
		timestamp: new Date().toISOString(),
		message: {
			role: "assistant",
			content: [{ type: "text", text }],
			api: "anthropic-messages",
			provider: "anthropic",
			model: "test-model-sonnet-4",
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			stopReason: "stop",
			timestamp: Date.now(),
		},
	};
}

function toolCallOnlyAssistant(id: string, parentId: string | null): SessionMessageEntry {
	return {
		type: "message",
		id,
		parentId,
		timestamp: new Date().toISOString(),
		message: {
			role: "assistant",
			content: [{ type: "toolCall", id: `tc-${id}`, name: "read", arguments: { path: "test.ts" } }],
			api: "anthropic-messages",
			provider: "anthropic",
			model: "test-model-sonnet-4",
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			stopReason: "toolUse",
			timestamp: Date.now(),
		},
	};
}

function modelChange(id: string, parentId: string | null): ModelChangeEntry {
	return {
		type: "model_change",
		id,
		parentId,
		timestamp: new Date().toISOString(),
		provider: "anthropic",
		modelId: "test-model-sonnet-4",
	};
}

function buildTree(entries: Array<SessionEntry>): SessionTreeNode[] {
	if (entries.length === 0) return [];

	const nodes: SessionTreeNode[] = entries.map((entry) => ({
		entry,
		children: [],
	}));

	const byId = new Map<string, SessionTreeNode>();
	for (const node of nodes) {
		byId.set(node.entry.id, node);
	}

	const roots: SessionTreeNode[] = [];
	for (const node of nodes) {
		if (node.entry.parentId === null) {
			roots.push(node);
		} else {
			const parent = byId.get(node.entry.parentId);
			if (parent) {
				parent.children.push(node);
			}
		}
	}
	return roots;
}

describe("TreeSelectorComponent", () => {
	describe("initial selection with metadata entries", () => {
		test("focuses nearest visible ancestor when currentLeafId is a model_change with sibling branch", () => {
			const entries = [
				userMessage("user-1", null, "hello"),
				assistantMessage("asst-1", "user-1", "hi"),
				userMessage("user-2", "asst-1", "active branch"), // Active branch
				modelChange("model-1", "user-2"), // Current leaf (metadata)
				userMessage("user-3", "asst-1", "sibling branch"), // Sibling branch
			];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"model-1", // currentLeafId is the model_change entry
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();

			expect(list.getSelectedNode()?.entry.id).toBe("user-2");
		});

		test("focuses nearest visible ancestor when currentLeafId is a thinking_level_change entry", () => {
			const entries = [
				userMessage("user-1", null, "hello"),
				assistantMessage("asst-1", "user-1", "hi"),
				userMessage("user-2", "asst-1", "active branch"),
				{
					type: "thinking_level_change" as const,
					id: "thinking-1",
					parentId: "user-2",
					timestamp: new Date().toISOString(),
					thinkingLevel: "high",
				},
				userMessage("user-3", "asst-1", "sibling branch"),
			];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"thinking-1",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");
		});
	});

	describe("filter switching with parent traversal", () => {
		test("switches to nearest visible user message when changing to user-only filter", () => {
			const entries = [
				userMessage("user-1", null, "hello"),
				assistantMessage("asst-1", "user-1", "hi"),
				userMessage("user-2", "asst-1", "active branch"),
				assistantMessage("asst-2", "user-2", "response"),
				userMessage("user-3", "asst-1", "sibling branch"),
			];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"asst-2",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			expect(list.getSelectedNode()?.entry.id).toBe("asst-2");

			selector.handleInput("\x15");

			expect(list.getSelectedNode()?.entry.id).toBe("user-2");
		});

		test("returns to nearest visible ancestor when switching back to default filter", () => {
			const entries = [
				userMessage("user-1", null, "hello"),
				assistantMessage("asst-1", "user-1", "hi"),
				userMessage("user-2", "asst-1", "active branch"),
				assistantMessage("asst-2", "user-2", "response"),
				userMessage("user-3", "asst-1", "sibling branch"),
			];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"asst-2",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			expect(list.getSelectedNode()?.entry.id).toBe("asst-2");

			selector.handleInput("\x15");
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");

			selector.handleInput("\x04");
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");
		});
	});

	describe("help", () => {
		test("renders semantic help rows without truncating narrow terminal controls", () => {
			const entries = [userMessage("user-1", null, "hello"), assistantMessage("asst-1", "user-1", "hi")];
			const tree = buildTree(entries);
			const selector = new TreeSelectorComponent(
				tree,
				"asst-1",
				24,
				() => {},
				() => {},
			);

			const plainLines = selector.render(30).map(stripVTControlCharacters);
			const plain = plainLines.join("\n");
			expect(plain).toContain("branch");
			expect(plain).toContain("copy");
			expect(plain).toContain("filters");
			expect(plain).toContain("cycle");
			expect(plain).toContain("label time");
			expect(plain).not.toContain("...");
			expect(plainLines.every((line) => visibleWidth(line) <= 30)).toBe(true);
		});
	});

	describe("copy", () => {
		// 2026-10-13 (owner order): copy arm disabled in CortexAgent-Cloud —
		// app.message.copy has empty keys, ctrl+x no longer copies.
		test("does nothing on ctrl+x (copy disabled)", () => {
			const message = `${"long message ".repeat(30)}\nsecond line`;
			const tree = buildTree([userMessage("user-1", null, "hello"), assistantMessage("asst-1", "user-1", message)]);
			const selector = new TreeSelectorComponent(
				tree,
				"asst-1",
				24,
				() => {},
				() => {},
			);
			let copied: string | undefined;
			selector.onCopy = (text) => {
				copied = text;
			};

			selector.handleInput("\x18");

			expect(copied).toBeUndefined();
		});
	});

	describe("label timestamps", () => {
		test("toggles label timestamps for labeled nodes", () => {
			const entries = [userMessage("user-1", null, "hello"), assistantMessage("asst-1", "user-1", "hi")];
			const tree = buildTree(entries);
			const labelDate = new Date(2026, 2, 28, 14, 32, 0);
			tree[0]!.label = "checkpoint";
			tree[0]!.labelTimestamp = labelDate.toISOString();

			const selector = new TreeSelectorComponent(
				tree,
				"asst-1",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			let render = list.render(200).join("\n");
			expect(render).toContain("[checkpoint]");
			expect(render).not.toContain("3/28 14:32");
			expect(render).not.toContain("[+label time]");

							(selector as any).treeList.showLabelTimestamps = true;

			render = list.render(200).join("\n");
			expect(render).toContain("3/28 14:32");
			expect(render).toContain("[+label time]");
		});
	});

	describe("empty filter preservation", () => {
		test("preserves selection when switching to empty labeled filter and back", () => {
			const entries = [
				userMessage("user-1", null, "hello"),
				assistantMessage("asst-1", "user-1", "hi"),
				userMessage("user-2", "asst-1", "bye"),
				assistantMessage("asst-2", "user-2", "goodbye"),
			];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"asst-2",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			expect(list.getSelectedNode()?.entry.id).toBe("asst-2");

			selector.handleInput("\x0c");

			expect(list.getSelectedNode()).toBeUndefined();

			selector.handleInput("\x04");

			expect(list.getSelectedNode()?.entry.id).toBe("asst-2");
		});

		test("preserves selection through multiple empty filter switches", () => {
			const entries = [userMessage("user-1", null, "hello"), assistantMessage("asst-1", "user-1", "hi")];
			const tree = buildTree(entries);

			const selector = new TreeSelectorComponent(
				tree,
				"asst-1",
				24,
				() => {},
				() => {},
			);

			const list = selector.getTreeList();
			expect(list.getSelectedNode()?.entry.id).toBe("asst-1");

			selector.handleInput("\x0c");
			expect(list.getSelectedNode()).toBeUndefined();

			selector.handleInput("\x0c");
			expect(list.getSelectedNode()?.entry.id).toBe("asst-1");

			selector.handleInput("\x0c");
			expect(list.getSelectedNode()).toBeUndefined();

			selector.handleInput("\x04");
			expect(list.getSelectedNode()?.entry.id).toBe("asst-1");
		});
	});

	describe("branch navigation and folding with ctrl+arrow keys", () => {
		const UP = "\x1b[A";
		const DOWN = "\x1b[B";
		const CTRL_LEFT = "\x1b[1;5D";
		const CTRL_RIGHT = "\x1b[1;5C";
		const ALT_LEFT = "\x1b[1;3D";
		const ALT_RIGHT = "\x1b[1;3C";

		function buildBranchingTree() {
			const entries: SessionEntry[] = [
				userMessage("user-1", null, "first message"),
				assistantMessage("asst-1", "user-1", "response 1"),
				userMessage("user-2", "asst-1", "second message"),
				assistantMessage("asst-2", "user-2", "response 2"),

				userMessage("user-3a", "asst-2", "branch A start"),
				assistantMessage("asst-3a", "user-3a", "branch A response"),
				userMessage("user-4a", "asst-3a", "branch A deep"),
				assistantMessage("asst-4a", "user-4a", "branch A leaf"),

				userMessage("user-3b", "asst-2", "branch B start"),
				assistantMessage("asst-3b", "user-3b", "branch B response"),
				userMessage("user-4b", "asst-3b", "branch B deep"),
			];
			return buildTree(entries);
		}

		test("ctrl+right unfolds a folded node, then does segment jump when unfolded", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3b");

			selector.handleInput(UP);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-3a");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-4a");
		});

		test("alt+left/right are aliases for fold and unfold navigation", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(ALT_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(ALT_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(ALT_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(ALT_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-4a");
		});

		test("folding root hides entire subtree, nested fold preserved on unfold", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3a");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3b");
		});

		test("fold and navigate on non-active branch", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			let found = false;
			for (let i = 0; i < 20; i++) {
				selector.handleInput(DOWN);
				if (list.getSelectedNode()?.entry.id === "user-3b") {
					found = true;
					break;
				}
			}
			expect(found).toBe(true);

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-4b");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3b");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3b");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");
		});

		test("fold and navigate with multiple roots", () => {
			const entries: SessionEntry[] = [
				userMessage("user-1", null, "first root"),
				assistantMessage("asst-1", "user-1", "response 1"),
				userMessage("user-2", null, "second root"),
				assistantMessage("asst-2", "user-2", "response 2"),
			];
			const tree = buildTree(entries);
			const selector = new TreeSelectorComponent(
				tree,
				"asst-1",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			expect(list.getSelectedNode()?.entry.id).toBe("asst-1");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");

			selector.handleInput(CTRL_RIGHT);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-2");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-2");
		});

		test("folding root hides descendants even when intermediate nodes are filtered out", () => {
			const entries: SessionEntry[] = [
				userMessage("user-1", null, "hello"),
				toolCallOnlyAssistant("tool-asst-1", "user-1"),
				userMessage("user-2", "tool-asst-1", "follow up"),
				assistantMessage("asst-2", "user-2", "response"),
			];
			const tree = buildTree(entries);
			const selector = new TreeSelectorComponent(
				tree,
				"asst-2",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(CTRL_LEFT);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-1");
		});

		test("search resets fold state", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(CTRL_LEFT);
			selector.handleInput(CTRL_LEFT);

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("user-3b");

			selector.handleInput("b");
			selector.handleInput("\x1b");

			let currentId = "";
			for (let i = 0; i < 20; i++) {
				selector.handleInput(DOWN);
				currentId = list.getSelectedNode()?.entry.id ?? "";
				if (currentId === "user-3a") break;
			}
			expect(currentId).toBe("user-3a");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-3a");
		});

		test("filter mode change resets fold state", () => {
			const tree = buildBranchingTree();
			const selector = new TreeSelectorComponent(
				tree,
				"asst-4a",
				24,
				() => {},
				() => {},
			);
			const list = selector.getTreeList();

			selector.handleInput(CTRL_LEFT);
			selector.handleInput(CTRL_LEFT);

			selector.handleInput("\x15");
			selector.handleInput("\x04");

			let currentId = "";
			for (let i = 0; i < 20; i++) {
				selector.handleInput(DOWN);
				currentId = list.getSelectedNode()?.entry.id ?? "";
				if (currentId === "user-3a") break;
			}
			expect(currentId).toBe("user-3a");

			selector.handleInput(DOWN);
			expect(list.getSelectedNode()?.entry.id).toBe("asst-3a");
		});
	});
});
