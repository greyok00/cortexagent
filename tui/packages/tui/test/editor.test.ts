import assert from "node:assert";
import { describe, it } from "node:test";
import { stripVTControlCharacters } from "node:util";
import { type AutocompleteProvider, CombinedAutocompleteProvider } from "../src/autocomplete.ts";
import { Editor, wordWrapLine } from "../src/components/editor.ts";
import type { TUI } from "../src/tui.ts";
import { TuiMainScreen } from "../src/tui-main-screen.ts";
import { visibleWidth } from "../src/utils.ts";
import { defaultEditorTheme } from "./test-themes.ts";
import { VirtualTerminal } from "./virtual-terminal.ts";

function createTestTUI(cols = 80, rows = 24): TUI {
	return new TuiMainScreen(new VirtualTerminal(cols, rows));
}

function applyCompletion(
	lines: string[],
	cursorLine: number,
	cursorCol: number,
	item: { value: string },
	prefix: string,
): { lines: string[]; cursorLine: number; cursorCol: number } {
	const line = lines[cursorLine] || "";
	const before = line.slice(0, cursorCol - prefix.length);
	const after = line.slice(cursorCol);
	const newLines = [...lines];
	newLines[cursorLine] = before + item.value + after;
	return {
		lines: newLines,
		cursorLine,
		cursorCol: cursorCol - prefix.length + item.value.length,
	};
}

async function flushAutocomplete(): Promise<void> {
	await Promise.resolve();
	await new Promise((resolve) => setImmediate(resolve));
}

describe("Editor component", () => {
	describe("Prompt history navigation", () => {
		it("does nothing on Up arrow when history is empty", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[A");

			assert.strictEqual(editor.getText(), "");
		});

		it("shows most recent history entry on Up arrow when editor is empty", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first prompt");
			editor.addToHistory("second prompt");

			editor.handleInput("\x1b[A");

			assert.strictEqual(editor.getText(), "second prompt");
		});

		it("cycles through history entries on repeated Up arrow", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first");
			editor.addToHistory("second");
			editor.addToHistory("third");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "third");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "first");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "first");
		});

		it("jumps to start before entering history from a non-empty draft", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("prompt");
			editor.setText("draft");
			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "draft");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "prompt");

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "draft");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("navigates forward through history with Down arrow", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first");
			editor.addToHistory("second");
			editor.addToHistory("third");
			editor.setText("draft");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "third");

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "draft");
		});

		it("exits history mode when typing a character", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("old prompt");

			editor.handleInput("\x1b[A");
			editor.handleInput("x");

			assert.strictEqual(editor.getText(), "xold prompt");
		});

		it("exits history mode on setText", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first");
			editor.addToHistory("second");

			editor.handleInput("\x1b[A");
			editor.setText("");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "second");
		});

		it("does not add empty strings to history", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("");
			editor.addToHistory("   ");
			editor.addToHistory("valid");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "valid");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "valid");
		});

		it("does not add consecutive duplicates to history", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("same");
			editor.addToHistory("same");
			editor.addToHistory("same");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "same");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "same");
		});

		it("allows non-consecutive duplicates in history", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first");
			editor.addToHistory("second");
			editor.addToHistory("first");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "first");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "first");
		});

		it("uses cursor movement instead of history when editor has content", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("history item");
			editor.setText("line1\nline2");

			editor.handleInput("\x1b[A");

			editor.handleInput("X");

			assert.strictEqual(editor.getText(), "line1X\nline2");
		});

		it("limits history to 100 entries", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			for (let i = 0; i < 105; i++) {
				editor.addToHistory(`prompt ${i}`);
			}

			for (let i = 0; i < 100; i++) {
				editor.handleInput("\x1b[A");
			}

			assert.strictEqual(editor.getText(), "prompt 5");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "prompt 5");
		});

		it("places cursor at start after browsing history upward", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("older entry");
			editor.addToHistory("line1\nline2\nline3");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "older entry");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("places cursor at end after browsing history downward", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("older entry");
			editor.addToHistory("line1\nline2\nline3");
			editor.addToHistory("newer entry");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 5 });

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "newer entry");
		});

		it("allows opposite-direction cursor movement within multi-line history entry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("line1\nline2\nline3");

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});
	});

	describe("public state accessors", () => {
		it("returns cursor position", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("a");
			editor.handleInput("b");
			editor.handleInput("c");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x1b[D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 2 });
		});

		it("returns lines as a defensive copy", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.setText("a\nb");

			const lines = editor.getLines();
			assert.deepStrictEqual(lines, ["a", "b"]);

			lines[0] = "mutated";
			assert.deepStrictEqual(editor.getLines(), ["a", "b"]);
		});
	});

	describe("Backslash+Enter newline workaround", () => {
		it("inserts backslash immediately (no buffering)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\\");

			assert.strictEqual(editor.getText(), "\\");
		});

		it("converts standalone backslash to newline on Enter", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\\");
			editor.handleInput("\r");

			assert.strictEqual(editor.getText(), "\n");
		});

		it("inserts backslash normally when followed by other characters", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\\");
			editor.handleInput("x");

			assert.strictEqual(editor.getText(), "\\x");
		});

		it("does not trigger newline when backslash is not immediately before cursor", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = false;

			editor.onSubmit = () => {
				submitted = true;
			};

			editor.handleInput("\\");
			editor.handleInput("x");
			editor.handleInput("\r");

			assert.strictEqual(submitted, true);
		});

		it("only removes one backslash when multiple are present", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\\");
			editor.handleInput("\\");
			editor.handleInput("\\");
			assert.strictEqual(editor.getText(), "\\\\\\");

			editor.handleInput("\r");

			assert.strictEqual(editor.getText(), "\\\\\n");
		});
	});

	describe("Kitty CSI-u handling", () => {
		it("ignores printable CSI-u sequences with unsupported modifiers", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[99;9u");

			assert.strictEqual(editor.getText(), "");
		});

		it("inserts shifted CSI-u letters as text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[69;2u");

			assert.strictEqual(editor.getText(), "E");
		});

		it("inserts shifted xterm modifyOtherKeys letters as text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[27;2;69~");

			assert.strictEqual(editor.getText(), "E");
		});
	});

	describe("Unicode text editing behavior", () => {
		it("inserts mixed ASCII, umlauts, and emojis as literal text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("H");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("ä");
			editor.handleInput("ö");
			editor.handleInput("ü");
			editor.handleInput(" ");
			editor.handleInput("😀");

			const text = editor.getText();
			assert.strictEqual(text, "Hello äöü 😀");
		});

		it("deletes single-code-unit unicode characters (umlauts) with Backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("ä");
			editor.handleInput("ö");
			editor.handleInput("ü");

			editor.handleInput("\x7f");

			const text = editor.getText();
			assert.strictEqual(text, "äö");
		});

		it("deletes multi-code-unit emojis with single Backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("😀");
			editor.handleInput("👍");

			editor.handleInput("\x7f");

			const text = editor.getText();
			assert.strictEqual(text, "😀");
		});

		it("inserts characters at the correct position after cursor movement over umlauts", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("ä");
			editor.handleInput("ö");
			editor.handleInput("ü");

			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");

			editor.handleInput("x");

			const text = editor.getText();
			assert.strictEqual(text, "äxöü");
		});

		it("moves cursor across multi-code-unit emojis with single arrow key", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("😀");
			editor.handleInput("👍");
			editor.handleInput("🎉");

			editor.handleInput("\x1b[D");

			editor.handleInput("\x1b[D");

			editor.handleInput("x");

			const text = editor.getText();
			assert.strictEqual(text, "😀x👍🎉");
		});

		it("preserves umlauts across line breaks", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("ä");
			editor.handleInput("ö");
			editor.handleInput("ü");
			editor.handleInput("\n");
			editor.handleInput("Ä");
			editor.handleInput("Ö");
			editor.handleInput("Ü");

			const text = editor.getText();
			assert.strictEqual(text, "äöü\nÄÖÜ");
		});

		it("replaces the entire document with unicode text via setText (paste simulation)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("Hällö Wörld! 😀 äöüÄÖÜß");

			const text = editor.getText();
			assert.strictEqual(text, "Hällö Wörld! 😀 äöüÄÖÜß");
		});

		it("moves cursor to document start on Ctrl+A and inserts at the beginning", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("a");
			editor.handleInput("b");
			editor.handleInput("\x01");
			editor.handleInput("x");

			const text = editor.getText();
			assert.strictEqual(text, "xab");
		});

		it("deletes words correctly with Ctrl+W and Alt+Backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("foo bar baz");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo bar ");

			editor.setText("foo bar   ");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo ");

			editor.setText("foo bar...");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo bar");

			editor.setText("foo.bar");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo.");

			editor.setText("foo:bar");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo:");

			editor.setText("line one\nline two");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "line one\nline ");

			editor.setText("line one\n");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "line one");

			editor.setText("foo 😀😀 bar");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo 😀😀 ");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo ");

			editor.setText("foo bar");
			editor.handleInput("\x1b\x7f");
			assert.strictEqual(editor.getText(), "foo ");
		});

		it("navigates words correctly with Ctrl+Left/Right", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("foo bar... baz");

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 14 });

			editor.setText("   foo bar");
			editor.handleInput("\x01");
			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });

			editor.setText("foo.bar baz");
			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });
			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });
			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x01");
			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });
			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });
			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });
		});

		it("stops at fullwidth Chinese punctuation (issue #4972)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("你好，世界");

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 2 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 2 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });
		});

		it("handles mixed CJK and ASCII word movement", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello你好，world世界");

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 13 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 13 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 15 });
		});
	});

	describe("Scroll indicators", () => {
		it("keeps truncated scroll indicators within width and preserves their color (issue #6962)", () => {
			const width = 10;
			const borderColor = (text: string) => `\x1b[35m${text}\x1b[39m`;
			const editor = new Editor(createTestTUI(width), { ...defaultEditorTheme, borderColor });
			editor.setText(Array.from({ length: 20 }, (_, index) => `line ${index}`).join("\n"));

			editor.render(width);
			for (let index = 0; index < 10; index++) editor.handleInput("\x1b[A");

			const lines = editor.render(width);
			const topBorder = lines[0]!;
			const bottomBorder = lines.at(-1)!;

			assert.match(stripVTControlCharacters(topBorder), /^─── ↑/);
			assert.match(stripVTControlCharacters(bottomBorder), /^─── ↓/);
			assert.strictEqual(topBorder, borderColor(stripVTControlCharacters(topBorder)));
			assert.strictEqual(bottomBorder, borderColor(stripVTControlCharacters(bottomBorder)));
			for (const line of lines) {
				assert.strictEqual(visibleWidth(line), width, `line exceeds width ${width}: ${JSON.stringify(line)}`);
			}
		});
	});

	describe("Grapheme-aware text wrapping", () => {
		it("wraps lines correctly when text contains wide emojis", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 20;

			editor.setText("Hello ✅ World");
			const lines = editor.render(width);

			for (let i = 1; i < lines.length - 1; i++) {
				const lineWidth = visibleWidth(lines[i]!);
				assert.strictEqual(lineWidth, width, `Line ${i} has width ${lineWidth}, expected ${width}`);
			}
		});

		it("wraps long text with emojis at correct positions", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 10;

			editor.setText("✅✅✅✅✅✅");
			const lines = editor.render(width);

			for (let i = 1; i < lines.length - 1; i++) {
				const lineWidth = visibleWidth(lines[i]!);
				assert.strictEqual(lineWidth, width, `Line ${i} has width ${lineWidth}, expected ${width}`);
			}
		});

		it("renders isolated Thai and Lao AM clusters without width drift", () => {
			for (const text of ["ำabc", "ຳabc"]) {
				const editor = new Editor(createTestTUI(), defaultEditorTheme);
				const width = 8;
				editor.setText(text);

				for (const line of editor.render(width)) {
					assert.strictEqual(visibleWidth(line), width, `line width drift for ${JSON.stringify(text)}: ${line}`);
				}
			}
		});

		it("wraps CJK characters correctly (each is 2 columns wide)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 10 + 1;

			editor.setText("日本語テスト");
			const lines = editor.render(width);

			for (let i = 1; i < lines.length - 1; i++) {
				const lineWidth = visibleWidth(lines[i]!);
				assert.strictEqual(lineWidth, width, `Line ${i} has width ${lineWidth}, expected ${width}`);
			}

			const contentLines = lines.slice(1, -1).map((l) => stripVTControlCharacters(l).trim());
			assert.strictEqual(contentLines.length, 2);
			assert.strictEqual(contentLines[0], "日本語テス");
			assert.strictEqual(contentLines[1], "ト");
		});

		it("handles mixed ASCII and wide characters in wrapping", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 15 + 1;

			editor.setText("Test ✅ OK 日本");
			const lines = editor.render(width);

			const contentLines = lines.slice(1, -1);
			assert.strictEqual(contentLines.length, 1);

			const lineWidth = visibleWidth(contentLines[0]!);
			assert.strictEqual(lineWidth, width);
		});

		it("renders cursor correctly on wide characters", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 20;

			editor.setText("A✅B");

			const lines = editor.render(width);

			const contentLine = lines[1]!;
			assert.ok(contentLine.includes("\x1b[7m"), "Should have reverse video cursor");

			assert.strictEqual(visibleWidth(contentLine), width);
		});

		it("does not exceed terminal width with emoji at wrap boundary", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 11;

			editor.setText("0123456789✅");
			const lines = editor.render(width);

			for (let i = 1; i < lines.length - 1; i++) {
				const lineWidth = visibleWidth(lines[i]!);
				assert.ok(lineWidth <= width, `Line ${i} has width ${lineWidth}, exceeds max ${width}`);
			}
		});

		it("shows cursor at end of line before wrap, wraps on next char", () => {
			const width = 10;
			for (const paddingX of [0, 1]) {
				const editor = new Editor(createTestTUI(width + paddingX), defaultEditorTheme, { paddingX });

				for (const ch of "aaaaaaaaa") editor.handleInput(ch);
				let lines = editor.render(width + paddingX);
				let contentLines = lines.slice(1, -1);
				assert.strictEqual(contentLines.length, 1, "Should be 1 content line before wrap");
				assert.ok(contentLines[0]!.endsWith("\x1b[7m \x1b[0m"), "Cursor should be at end of line");

				editor.handleInput("a");
				lines = editor.render(width + paddingX);
				contentLines = lines.slice(1, -1);
				assert.strictEqual(contentLines.length, 2, "Should wrap to 2 content lines");
			}
		});
	});

	describe("Word wrapping", () => {
		it("wraps at word boundaries instead of mid-word", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 40;

			editor.setText("Hello world this is a test of word wrapping functionality");
			const lines = editor.render(width);

			const contentLines = lines.slice(1, -1).map((l) => stripVTControlCharacters(l).trim());

			assert.ok(!contentLines[0]!.endsWith("-"), "Line should not end with hyphen (mid-word break)");

			for (const line of contentLines) {
				const lastChar = line.trimEnd().slice(-1);
				assert.ok(lastChar === "" || /[\w.,!?;:]/.test(lastChar), `Line ends unexpectedly with: "${lastChar}"`);
			}
		});

		it("does not start lines with leading whitespace after word wrap", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 20;

			editor.setText("Word1 Word2 Word3 Word4 Word5 Word6");
			const lines = editor.render(width);

			const contentLines = lines.slice(1, -1);

			for (let i = 0; i < contentLines.length; i++) {
				const line = stripVTControlCharacters(contentLines[i]!);
				const trimmedStart = line.trimStart();

				if (trimmedStart.length > 0) {
					assert.ok(!/^\s+\S/.test(line.trimEnd()), `Line ${i} starts with unexpected whitespace before content`);
				}
			}
		});

		it("breaks long words (URLs) at character level", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 30;

			editor.setText("Check https://example.com/very/long/path/that/exceeds/width here");
			const lines = editor.render(width);

			for (let i = 1; i < lines.length - 1; i++) {
				const lineWidth = visibleWidth(lines[i]!);
				assert.strictEqual(lineWidth, width, `Line ${i} has width ${lineWidth}, expected ${width}`);
			}
		});

		it("preserves multiple spaces within words on same line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 50;

			editor.setText("Word1   Word2    Word3");
			const lines = editor.render(width);

			const contentLine = stripVTControlCharacters(lines[1]!).trim();

			assert.ok(contentLine.includes("Word1   Word2"), "Multiple spaces should be preserved");
		});

		it("handles empty string", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 40;

			editor.setText("");
			const lines = editor.render(width);

			assert.strictEqual(lines.length, 3);
		});

		it("handles single word that fits exactly", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const width = 10 + 1;

			editor.setText("1234567890");
			const lines = editor.render(width);

			assert.strictEqual(lines.length, 3);
			const contentLine = stripVTControlCharacters(lines[1]!);
			assert.ok(contentLine.includes("1234567890"), "Content should contain the word");
		});

		it("wraps word to next line when it ends exactly at terminal width", () => {
			const chunks = wordWrapLine("hello world test", 11);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "hello ");
			assert.strictEqual(chunks[1]!.text, "world test");
		});

		it("keeps whitespace at terminal width boundary on same line", () => {
			const chunks = wordWrapLine("hello world test", 12);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "hello world ");
			assert.strictEqual(chunks[1]!.text, "test");
		});

		it("handles unbreakable word filling width exactly followed by space", () => {
			const chunks = wordWrapLine("aaaaaaaaaaaa aaaa", 12);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "aaaaaaaaaaaa");
			assert.strictEqual(chunks[1]!.text, " aaaa");
		});

		it("wraps word to next line when it fits width but not remaining space", () => {
			const chunks = wordWrapLine("      aaaaaaaaaaaa", 12);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "      ");
			assert.strictEqual(chunks[1]!.text, "aaaaaaaaaaaa");
		});

		it("keeps word with multi-space and following word together when they fit", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,    consectetur", 30);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,    consectetur");
		});

		it("keeps word with multi-space and following word when they fill width exactly", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,              consectetur", 30);

			assert.strictEqual(chunks.length, 2);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,              consectetur");
		});

		it("splits when word plus multi-space plus word exceeds width", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,               consectetur", 30);

			assert.strictEqual(chunks.length, 3);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,               ");
			assert.strictEqual(chunks[2]!.text, "consectetur");
		});

		it("breaks long whitespace at line boundary", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,                         consectetur", 30);

			assert.strictEqual(chunks.length, 3);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,                         ");
			assert.strictEqual(chunks[2]!.text, "consectetur");
		});

		it("breaks long whitespace at line boundary 2", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,                          consectetur", 30);

			assert.strictEqual(chunks.length, 3);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,                         ");
			assert.strictEqual(chunks[2]!.text, " consectetur");
		});

		it("breaks whitespace spanning full lines", () => {
			const chunks = wordWrapLine("Lorem ipsum dolor sit amet,                                     consectetur", 30);

			assert.strictEqual(chunks.length, 3);
			assert.strictEqual(chunks[0]!.text, "Lorem ipsum dolor sit ");
			assert.strictEqual(chunks[1]!.text, "amet,                         ");
			assert.strictEqual(chunks[2]!.text, "            consectetur");
		});

		it("force-breaks when wide char after word boundary wrap still overflows", () => {
			const line = ` ${"a".repeat(186)}你`;
			const chunks = wordWrapLine(line, 187);

			for (const chunk of chunks) {
				assert.ok(
					visibleWidth(chunk.text) <= 187,
					`chunk "${chunk.text.slice(0, 20)}..." has visible width ${visibleWidth(chunk.text)}, expected <= 187`,
				);
			}

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});

		it("splits oversized atomic segment across multiple chunks", () => {
			const marker = "[paste #1 +20 lines]";
			const line = `A${marker}B`;
			const segments: Intl.SegmentData[] = [
				{ segment: "A", index: 0, input: line },
				{ segment: marker, index: 1, input: line },
				{ segment: "B", index: 1 + marker.length, input: line },
			];

			const chunks = wordWrapLine(line, 10, segments);

			for (const chunk of chunks) {
				assert.ok(
					visibleWidth(chunk.text) <= 10,
					`chunk "${chunk.text}" has visible width ${visibleWidth(chunk.text)}, expected <= 10`,
				);
			}

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});

		it("splits oversized atomic segment at start of line", () => {
			const marker = "[paste #1 +20 lines]";
			const line = `${marker}B`;
			const segments: Intl.SegmentData[] = [
				{ segment: marker, index: 0, input: line },
				{ segment: "B", index: marker.length, input: line },
			];

			const chunks = wordWrapLine(line, 10, segments);

			for (const chunk of chunks) {
				assert.ok(visibleWidth(chunk.text) <= 10);
			}

			assert.strictEqual(chunks[chunks.length - 1]!.text.includes("B"), true);

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});

		it("splits oversized atomic segment at end of line", () => {
			const marker = "[paste #1 +20 lines]";
			const line = `A${marker}`;
			const segments: Intl.SegmentData[] = [
				{ segment: "A", index: 0, input: line },
				{ segment: marker, index: 1, input: line },
			];

			const chunks = wordWrapLine(line, 10, segments);

			for (const chunk of chunks) {
				assert.ok(visibleWidth(chunk.text) <= 10);
			}
			assert.strictEqual(chunks[0]!.text, "A");

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});

		it("splits consecutive oversized atomic segments", () => {
			const m1 = "[paste #1 +20 lines]";
			const m2 = "[paste #2 +30 lines]";
			const line = `${m1}${m2}`;
			const segments: Intl.SegmentData[] = [
				{ segment: m1, index: 0, input: line },
				{ segment: m2, index: m1.length, input: line },
			];

			const chunks = wordWrapLine(line, 10, segments);

			for (const chunk of chunks) {
				assert.ok(
					visibleWidth(chunk.text) <= 10,
					`chunk "${chunk.text}" has visible width ${visibleWidth(chunk.text)}, expected <= 10`,
				);
			}

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});

		it("wraps normally after oversized atomic segment", () => {
			const marker = "[paste #1 +20 lines]";
			const line = `${marker} hello world`;
			const segments: Intl.SegmentData[] = [
				{ segment: marker, index: 0, input: line },
				{ segment: " ", index: marker.length, input: line },
				{ segment: "h", index: marker.length + 1, input: line },
				{ segment: "e", index: marker.length + 2, input: line },
				{ segment: "l", index: marker.length + 3, input: line },
				{ segment: "l", index: marker.length + 4, input: line },
				{ segment: "o", index: marker.length + 5, input: line },
				{ segment: " ", index: marker.length + 6, input: line },
				{ segment: "w", index: marker.length + 7, input: line },
				{ segment: "o", index: marker.length + 8, input: line },
				{ segment: "r", index: marker.length + 9, input: line },
				{ segment: "l", index: marker.length + 10, input: line },
				{ segment: "d", index: marker.length + 11, input: line },
			];

			const chunks = wordWrapLine(line, 10, segments);

			for (const chunk of chunks) {
				assert.ok(
					visibleWidth(chunk.text) <= 10,
					`chunk "${chunk.text}" has visible width ${visibleWidth(chunk.text)}, expected <= 10`,
				);
			}

			assert.strictEqual(chunks[chunks.length - 1]!.text, "world");

			const reconstructed = chunks.map((c) => line.slice(c.startIndex, c.endIndex)).join("");
			assert.strictEqual(reconstructed, line);
		});
	});

	describe("Kill ring", () => {
		it("Ctrl+W saves deleted text to kill ring and Ctrl+Y yanks it", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("foo bar baz");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo bar ");

			editor.handleInput("\x01");
			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "bazfoo bar ");
		});

		it("Ctrl+U saves deleted text to kill ring", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");

			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "world");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("Ctrl+K saves deleted text to kill ring", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			editor.handleInput("\x0b");

			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("Ctrl+Y does nothing when kill ring is empty", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("test");
			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "test");
		});

		it("Alt+Y cycles through kill ring after Ctrl+Y", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("first");
			editor.handleInput("\x17");
			editor.setText("second");
			editor.handleInput("\x17");
			editor.setText("third");
			editor.handleInput("\x17");

			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "third");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "first");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "third");
		});

		it("Alt+Y does nothing if not preceded by yank", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("test");
			editor.handleInput("\x17");
			editor.setText("other");

			editor.handleInput("x");
			assert.strictEqual(editor.getText(), "otherx");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "otherx");
		});

		it("Alt+Y does nothing if kill ring has ≤1 entry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("only");
			editor.handleInput("\x17");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "only");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "only");
		});

		it("consecutive Ctrl+W accumulates into one kill ring entry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("one two three");
			editor.handleInput("\x17");
			editor.handleInput("\x17");
			editor.handleInput("\x17");

			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "one two three");
		});

		it("Ctrl+U accumulates multiline deletes including newlines", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("line1\nline2\nline3");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "line1\nline2\n");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "line1\nline2");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "line1\n");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "line1");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
		});

		it("backward deletions prepend, forward deletions append during accumulation", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("prefix|suffix");

			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x0b");
			editor.handleInput("\x0b");
			assert.strictEqual(editor.getText(), "prefix");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "prefix|suffix");
		});

		it("non-delete actions break kill accumulation", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("foo bar baz");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo bar ");

			editor.handleInput("x");
			assert.strictEqual(editor.getText(), "foo bar x");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "foo bar ");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "foo bar x");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "foo bar baz");
		});

		it("non-yank actions break Alt+Y chain", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("first");
			editor.handleInput("\x17");
			editor.setText("second");
			editor.handleInput("\x17");
			editor.setText("");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("x");
			assert.strictEqual(editor.getText(), "secondx");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "secondx");
		});

		it("kill ring rotation persists after cycling", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("first");
			editor.handleInput("\x17");
			editor.setText("second");
			editor.handleInput("\x17");
			editor.setText("third");
			editor.handleInput("\x17");
			editor.setText("");

			editor.handleInput("\x19");
			editor.handleInput("\x1by");

			assert.strictEqual(editor.getText(), "second");

			editor.handleInput("x");
			editor.setText("");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "second");
		});

		it("consecutive deletions across lines coalesce into one entry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1\n2\n3");
			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "1\n2\n");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "1\n2");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "1\n");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "1");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "1\n2\n3");
		});

		it("Ctrl+K at line end deletes newline and coalesces", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("");
			editor.handleInput("a");
			editor.handleInput("b");
			editor.handleInput("\n");
			editor.handleInput("c");
			editor.handleInput("d");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x05");

			editor.handleInput("\x0b");
			assert.strictEqual(editor.getText(), "abcd");

			editor.handleInput("\x0b");
			assert.strictEqual(editor.getText(), "ab");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "ab\ncd");
		});

		it("handles yank in middle of text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("word");
			editor.handleInput("\x17");
			editor.setText("hello world");

			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello wordworld");
		});

		it("handles yank-pop in middle of text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("FIRST");
			editor.handleInput("\x17");
			editor.setText("SECOND");
			editor.handleInput("\x17");

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello SECONDworld");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "hello FIRSTworld");
		});

		it("multiline yank and yank-pop in middle of text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("SINGLE");
			editor.handleInput("\x17");

			editor.setText("A\nB");
			editor.handleInput("\x15");
			editor.handleInput("\x15");
			editor.handleInput("\x15");

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello A\nBworld");

			editor.handleInput("\x1by");
			assert.strictEqual(editor.getText(), "hello SINGLEworld");
		});

		it("Alt+D deletes word forward and saves to kill ring", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world test");
			editor.handleInput("\x01");

			editor.handleInput("\x1bd");
			assert.strictEqual(editor.getText(), " world test");

			editor.handleInput("\x1bd");
			assert.strictEqual(editor.getText(), " test");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello world test");
		});

		it("Alt+D at end of line deletes newline", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("line1\nline2");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x05");

			editor.handleInput("\x1bd");
			assert.strictEqual(editor.getText(), "line1line2");

			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "line1\nline2");
		});
	});

	describe("Undo", () => {
		it("does nothing when undo stack is empty", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("coalesces consecutive word characters into one undo unit", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("undoes spaces one at a time", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput(" ");
			assert.strictEqual(editor.getText(), "hello  ");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello ");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("undoes newlines and signals next word to capture state", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput("\n");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "hello\nworld");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello\n");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("undoes backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput("\x7f");
			assert.strictEqual(editor.getText(), "hell");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");
		});

		it("undoes forward delete", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[3~");
			assert.strictEqual(editor.getText(), "hllo");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");
		});

		it("undoes Ctrl+W (delete word backward)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "hello ");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("undoes Ctrl+K (delete to line end)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x0b");
			assert.strictEqual(editor.getText(), "hello ");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("|");
			assert.strictEqual(editor.getText(), "hello |world");
		});

		it("undoes Ctrl+U (delete to line start)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x15");
			assert.strictEqual(editor.getText(), "world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("undoes yank", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("\x17");
			editor.handleInput("\x19");
			assert.strictEqual(editor.getText(), "hello ");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("undoes single-line paste atomically", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[200~beep boop\x1b[201~");
			assert.strictEqual(editor.getText(), "hellobeep boop world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("|");
			assert.strictEqual(editor.getText(), "hello| world");
		});

		it("does not trigger autocomplete during single-line paste", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let suggestionCalls = 0;

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async () => {
					suggestionCalls += 1;
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);
			editor.handleInput("\x1b[200~look at @node_modules/react/index.js please\x1b[201~");

			assert.strictEqual(editor.getText(), "look at @node_modules/react/index.js please");
			assert.strictEqual(suggestionCalls, 0);
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("decodes CSI-u Ctrl+letter sequences inside bracketed paste (tmux popup)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("\x1b[200~line1\x1b[106;5uline2\x1b[106;5uline3\x1b[201~");
			assert.strictEqual(editor.getText(), "line1\nline2\nline3");
		});

		it("undoes multi-line paste atomically", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[200~line1\nline2\nline3\x1b[201~");
			assert.strictEqual(editor.getText(), "helloline1\nline2\nline3 world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("|");
			assert.strictEqual(editor.getText(), "hello| world");
		});

		it("undoes insertTextAtCursor atomically", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");

			editor.insertTextAtCursor("/tmp/image.png");
			assert.strictEqual(editor.getText(), "hello/tmp/image.png world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("|");
			assert.strictEqual(editor.getText(), "hello| world");
		});

		it("insertTextAtCursor handles multiline text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");

			editor.insertTextAtCursor("line1\nline2\nline3");
			assert.strictEqual(editor.getText(), "helloline1\nline2\nline3 world");

			const cursor = editor.getCursor();
			assert.strictEqual(cursor.line, 2);
			assert.strictEqual(cursor.col, 5);

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("insertTextAtCursor normalizes CRLF and CR line endings", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("");

			editor.insertTextAtCursor("a\r\nb\r\nc");
			assert.strictEqual(editor.getText(), "a\nb\nc");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");

			editor.insertTextAtCursor("x\ry\rz");
			assert.strictEqual(editor.getText(), "x\ny\nz");
		});

		it("undoes setText to empty string", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "hello world");

			editor.setText("");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");
		});

		it("clears undo stack on submit", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = "";
			editor.onSubmit = (text) => {
				submitted = text;
			};

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput("\r");

			assert.strictEqual(submitted, "hello");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");
		});

		it("exits history browsing mode on undo", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("hello");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "world");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "hello");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "world");
		});

		it("undo restores to pre-history state even after multiple history navigations", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.addToHistory("first");
			editor.addToHistory("second");
			editor.addToHistory("third");

			editor.handleInput("c");
			editor.handleInput("u");
			editor.handleInput("r");
			editor.handleInput("r");
			editor.handleInput("e");
			editor.handleInput("n");
			editor.handleInput("t");
			assert.strictEqual(editor.getText(), "current");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "third");
			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "second");
			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getText(), "first");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "current");
		});

		it("cursor movement starts new undo unit", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput(" ");
			editor.handleInput("w");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("l");
			editor.handleInput("d");
			assert.strictEqual(editor.getText(), "hello world");

			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[D");

			editor.handleInput("l");
			editor.handleInput("o");
			editor.handleInput("l");
			assert.strictEqual(editor.getText(), "hello lolworld");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello world");

			editor.handleInput("|");
			assert.strictEqual(editor.getText(), "hello |world");
		});

		it("no-op delete operations do not push undo snapshots", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.handleInput("h");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput("l");
			editor.handleInput("o");
			assert.strictEqual(editor.getText(), "hello");

			editor.handleInput("\x17");
			assert.strictEqual(editor.getText(), "");
			editor.handleInput("\x17");
			editor.handleInput("\x17");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "hello");
		});

		it("undoes autocomplete", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const prefix = text.slice(0, cursorCol);
					if (prefix === "di") {
						return {
							items: [{ value: "dist/", label: "dist/" }],
							prefix: "di",
						};
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("d");
			editor.handleInput("i");
			assert.strictEqual(editor.getText(), "di");

			editor.handleInput("\t");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "dist/");
			assert.strictEqual(editor.isShowingAutocomplete(), false);

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "di");
		});
	});

	describe("Autocomplete", () => {
		it("auto-applies single force-file suggestion without showing menu", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol, options) => {
					if (!options.force) {
						return null;
					}
					const text = lines[0] || "";
					const prefix = text.slice(0, cursorCol);
					if (prefix === "Work") {
						return {
							items: [{ value: "Workspace/", label: "Workspace/" }],
							prefix: "Work",
						};
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("W");
			editor.handleInput("o");
			editor.handleInput("r");
			editor.handleInput("k");
			assert.strictEqual(editor.getText(), "Work");

			editor.handleInput("\t");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "Workspace/");
			assert.strictEqual(editor.isShowingAutocomplete(), false);

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "Work");
		});

		it("shows menu when force-file has multiple suggestions", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol, options) => {
					if (!options.force) {
						return null;
					}
					const text = lines[0] || "";
					const prefix = text.slice(0, cursorCol);
					if (prefix === "src") {
						return {
							items: [
								{ value: "src/", label: "src/" },
								{ value: "src.txt", label: "src.txt" },
							],
							prefix: "src",
						};
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("s");
			editor.handleInput("r");
			editor.handleInput("c");
			assert.strictEqual(editor.getText(), "src");

			editor.handleInput("\t");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "src");
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\t");
			assert.strictEqual(editor.getText(), "src/");
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("keeps suggestions open when typing in force mode (Tab-triggered)", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const allFiles = [
				{ value: "readme.md", label: "readme.md" },
				{ value: "package.json", label: "package.json" },
				{ value: "src/", label: "src/" },
				{ value: "dist/", label: "dist/" },
			];

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol, options) => {
					const text = lines[0] || "";
					const prefix = text.slice(0, cursorCol);
					const shouldMatch = options.force || prefix.includes("/") || prefix.startsWith(".");
					if (!shouldMatch) {
						return null;
					}
					const filtered = allFiles.filter((f) => f.value.toLowerCase().startsWith(prefix.toLowerCase()));
					if (filtered.length > 0) {
						return { items: filtered, prefix };
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("\t");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("r");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "r");
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("e");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "re");
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\t");
			assert.strictEqual(editor.getText(), "readme.md");
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("debounces @ autocomplete while typing", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let suggestionCalls = 0;

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					suggestionCalls += 1;
					const text = (lines[0] || "").slice(0, cursorCol);
					return {
						items: [{ value: "@main.ts", label: "main.ts" }],
						prefix: text,
					};
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("@");
			editor.handleInput("m");
			editor.handleInput("a");
			editor.handleInput("i");

			assert.strictEqual(suggestionCalls, 0);
			assert.strictEqual(editor.isShowingAutocomplete(), false);

			await new Promise((resolve) => setTimeout(resolve, 50));
			await flushAutocomplete();

			assert.strictEqual(suggestionCalls, 1);
			assert.strictEqual(editor.isShowingAutocomplete(), true);
		});

		it("re-queries the autocomplete picker when the cursor moves back into the command name", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const before = (lines[0] || "").slice(0, cursorCol);
					if (!before.startsWith("/")) return null;

					if (before.includes(" ")) {
						return {
							items: [
								{ value: "repo", label: "repo" },
								{ value: "message", label: "message" },
								{ value: "help", label: "help" },
							],
							prefix: before.slice(before.indexOf(" ") + 1),
						};
					}

					return { items: [{ value: "cmd", label: "cmd" }], prefix: before };
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			for (const ch of "/cmd ") {
				editor.handleInput(ch);
				await flushAutocomplete();
			}
			assert.strictEqual(editor.getText(), "/cmd ");
			assert.strictEqual(editor.isShowingAutocomplete(), true);
			const atArg = editor
				.render(80)
				.map((l) => stripVTControlCharacters(l))
				.join("\n");
			assert.ok(atArg.includes("repo"), "argument menu should be visible at `/cmd `");

			editor.handleInput("\x1b[D");
			await flushAutocomplete();

			const afterMove = editor
				.render(80)
				.map((l) => stripVTControlCharacters(l))
				.join("\n");
			assert.ok(!afterMove.includes("repo"), "stale argument menu must not survive the cursor move");
			assert.ok(!afterMove.includes("message"), "stale argument menu must not survive the cursor move");
		});

		it("debounces # autocomplete while typing", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let suggestionCalls = 0;

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					suggestionCalls += 1;
					const text = (lines[0] || "").slice(0, cursorCol);
					return {
						items: [{ value: "#2983", label: "#2983" }],
						prefix: text,
					};
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("#");
			editor.handleInput("2");
			editor.handleInput("9");
			editor.handleInput("8");

			assert.strictEqual(suggestionCalls, 0);
			assert.strictEqual(editor.isShowingAutocomplete(), false);

			await new Promise((resolve) => setTimeout(resolve, 50));
			await flushAutocomplete();

			assert.strictEqual(suggestionCalls, 1);
			assert.strictEqual(editor.isShowingAutocomplete(), true);
		});

		it("debounces custom triggerCharacters autocomplete while typing", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let suggestionCalls = 0;

			editor.setAutocompleteProvider({
				triggerCharacters: ["$"],
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					suggestionCalls += 1;
					const prefix = (lines[0] || "").slice(0, cursorCol);
					return { items: [{ value: "$skill-name", label: "skill-name" }], prefix };
				},
				applyCompletion,
			});

			editor.handleInput("$");
			editor.handleInput("s");
			editor.handleInput("k");

			assert.strictEqual(suggestionCalls, 0);
			await new Promise((resolve) => setTimeout(resolve, 50));
			await flushAutocomplete();

			assert.strictEqual(suggestionCalls, 1);
			assert.strictEqual(editor.isShowingAutocomplete(), true);
		});

		it("resets custom triggerCharacters when provider changes", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let suggestionCalls = 0;

			editor.setAutocompleteProvider({
				triggerCharacters: ["$"],
				getSuggestions: async () => ({ items: [{ value: "$skill-name", label: "skill-name" }], prefix: "$" }),
				applyCompletion,
			});
			editor.setAutocompleteProvider({
				getSuggestions: async () => {
					suggestionCalls += 1;
					return { items: [{ value: "$skill-name", label: "skill-name" }], prefix: "$" };
				},
				applyCompletion,
			});

			editor.handleInput("$");
			editor.handleInput("s");
			await new Promise((resolve) => setTimeout(resolve, 50));
			await flushAutocomplete();

			assert.strictEqual(suggestionCalls, 0);
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("aborts active @ autocomplete when typing continues", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let aborts = 0;

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (_lines, _cursorLine, _cursorCol, options) => {
					return await new Promise((resolve) => {
						const timeout = setTimeout(() => {
							resolve({ items: [{ value: "@main.ts", label: "main.ts" }], prefix: "@main" });
						}, 500);
						options.signal.addEventListener(
							"abort",
							() => {
								aborts += 1;
								clearTimeout(timeout);
								resolve(null);
							},
							{ once: true },
						);
					});
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("@");
			editor.handleInput("m");
			editor.handleInput("a");
			editor.handleInput("i");
			await new Promise((resolve) => setTimeout(resolve, 250));
			editor.handleInput("n");
			await new Promise((resolve) => setTimeout(resolve, 50));

			assert.strictEqual(aborts, 1);
		});

		it("hides autocomplete when backspacing slash command to empty", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const prefix = text.slice(0, cursorCol);

					if (prefix.startsWith("/")) {
						const commands = [
							{ value: "/model", label: "model", description: "Change model" },
							{ value: "/help", label: "help", description: "Show help" },
						];
						const query = prefix.slice(1);
						const filtered = commands.filter((c) => c.value.startsWith(query));
						if (filtered.length > 0) {
							return { items: filtered, prefix };
						}
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "/");
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\x7f");
			await flushAutocomplete();
			assert.strictEqual(editor.getText(), "");
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("applies exact typed slash-argument value on Enter even when first item is highlighted", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const beforeCursor = text.slice(0, cursorCol);

					const argtestMatch = beforeCursor.match(/^\/argtest\s+(\S+)$/);
					if (argtestMatch) {
						const argumentText = argtestMatch[1]!;
						const allArguments = [
							{ value: "one", label: "one" },
							{ value: "two", label: "two" },
							{ value: "three", label: "three" },
						];

						const filtered = allArguments.filter((arg) => arg.value.startsWith(argumentText));
						if (filtered.length > 0) {
							return { items: filtered, prefix: argumentText };
						}
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			editor.handleInput("a");
			editor.handleInput("r");
			editor.handleInput("g");
			editor.handleInput("t");
			editor.handleInput("e");
			editor.handleInput("s");
			editor.handleInput("t");
			editor.handleInput(" ");
			editor.handleInput("t");
			editor.handleInput("w");
			editor.handleInput("o");

			assert.strictEqual(editor.getText(), "/argtest two");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\r");

			assert.strictEqual(editor.getText(), "/argtest two");
		});

		it("selects first prefix match on Enter when typed arg is not exact match", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const beforeCursor = text.slice(0, cursorCol);

					const argtestMatch = beforeCursor.match(/^\/argtest\s+(\S+)$/);
					if (argtestMatch) {
						const argumentText = argtestMatch[1]!;
						const allArguments = [
							{ value: "two", label: "two" },
							{ value: "three", label: "three" },
							{ value: "twelve", label: "twelve" },
						];

						const filtered = allArguments.filter((arg) => arg.value.startsWith(argumentText));
						if (filtered.length > 0) {
							return { items: filtered, prefix: argumentText };
						}
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			editor.handleInput("a");
			editor.handleInput("r");
			editor.handleInput("g");
			editor.handleInput("t");
			editor.handleInput("e");
			editor.handleInput("s");
			editor.handleInput("t");
			editor.handleInput(" ");
			editor.handleInput("t");

			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\r");
			assert.strictEqual(editor.getText(), "/argtest two");
		});

		it("highlights unique prefix match as user types (before full exact match)", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const beforeCursor = text.slice(0, cursorCol);

					const argtestMatch = beforeCursor.match(/^\/argtest\s+(\S+)$/);
					if (argtestMatch) {
						const argumentText = argtestMatch[1]!;

						const allArguments = [
							{ value: "one", label: "one" },
							{ value: "two", label: "two" },
							{ value: "three", label: "three" },
						];
						return { items: allArguments, prefix: argumentText };
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			editor.handleInput("a");
			editor.handleInput("r");
			editor.handleInput("g");
			editor.handleInput("t");
			editor.handleInput("e");
			editor.handleInput("s");
			editor.handleInput("t");
			editor.handleInput(" ");
			editor.handleInput("t");
			editor.handleInput("w");

			assert.strictEqual(editor.getText(), "/argtest tw");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\r");
			assert.strictEqual(editor.getText(), "/argtest two");
		});

		it("selects first prefix match when multiple items match", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const beforeCursor = text.slice(0, cursorCol);

					const argtestMatch = beforeCursor.match(/^\/argtest\s+(\S+)$/);
					if (argtestMatch) {
						const argumentText = argtestMatch[1]!;
						const allArguments = [
							{ value: "one", label: "one" },
							{ value: "two", label: "two" },
							{ value: "three", label: "three" },
						];
						return { items: allArguments, prefix: argumentText };
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			editor.handleInput("a");
			editor.handleInput("r");
			editor.handleInput("g");
			editor.handleInput("t");
			editor.handleInput("e");
			editor.handleInput("s");
			editor.handleInput("t");
			editor.handleInput(" ");
			editor.handleInput("t");

			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\r");
			assert.strictEqual(editor.getText(), "/argtest two");
		});

		it("works for built-in-style command argument completion path (model-like)", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const mockProvider: AutocompleteProvider = {
				getSuggestions: async (lines, _cursorLine, cursorCol) => {
					const text = lines[0] || "";
					const beforeCursor = text.slice(0, cursorCol);

					const modelMatch = beforeCursor.match(/^\/model\s+(\S+)$/);
					if (modelMatch) {
						const modelText = modelMatch[1]!;
						const allModels = [
							{ value: "gpt-4o", label: "gpt-4o" },
							{ value: "gpt-4o-mini", label: "gpt-4o-mini" },
							{ value: "claude-sonnet", label: "claude-sonnet" },
						];

						const filtered = allModels.filter((m) => m.value.startsWith(modelText));
						if (filtered.length > 0) {
							return { items: filtered, prefix: modelText };
						}
					}
					return null;
				},
				applyCompletion,
			};

			editor.setAutocompleteProvider(mockProvider);

			editor.handleInput("/");
			editor.handleInput("m");
			editor.handleInput("o");
			editor.handleInput("d");
			editor.handleInput("e");
			editor.handleInput("l");
			editor.handleInput(" ");
			editor.handleInput("g");
			editor.handleInput("p");
			editor.handleInput("t");
			editor.handleInput("-");
			editor.handleInput("4");
			editor.handleInput("o");
			editor.handleInput("-");
			editor.handleInput("m");
			editor.handleInput("i");
			editor.handleInput("n");
			editor.handleInput("i");

			assert.strictEqual(editor.getText(), "/model gpt-4o-mini");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\r");

			assert.strictEqual(editor.getText(), "/model gpt-4o-mini");
		});

		it("awaits async slash command argument completions", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const provider = new CombinedAutocompleteProvider(
				[
					{
						name: "load-skills",
						description: "Load skills",
						getArgumentCompletions: async (prefix) =>
							prefix.startsWith("s") ? [{ value: "skill-a", label: "skill-a" }] : null,
					},
				],
				process.cwd(),
			);
			editor.setAutocompleteProvider(provider);
			editor.setText("/load-skills ");

			editor.handleInput("s");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\t");
			assert.strictEqual(editor.getText(), "/load-skills skill-a");
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});

		it("ignores invalid slash command argument completion results", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const provider = new CombinedAutocompleteProvider(
				[
					{
						name: "load-skills",
						description: "Load skills",
						getArgumentCompletions: (() => "not-an-array") as unknown as (
							argumentPrefix: string,
						) => Promise<{ value: string; label: string }[] | null>,
					},
				],
				process.cwd(),
			);
			editor.setAutocompleteProvider(provider);
			editor.setText("/load-skills ");

			editor.handleInput("s");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), false);
			assert.strictEqual(editor.getText(), "/load-skills s");
		});

		it("does not show argument completions when command has no argument completer", async () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const provider = new CombinedAutocompleteProvider(
				[
					{ name: "help", description: "Show help" },
					{
						name: "model",
						description: "Switch model",
						getArgumentCompletions: () => [{ value: "claude-opus", label: "claude-opus" }],
					},
				],
				process.cwd(),
			);
			editor.setAutocompleteProvider(provider);

			editor.handleInput("/");
			editor.handleInput("h");
			editor.handleInput("e");
			await flushAutocomplete();
			assert.strictEqual(editor.isShowingAutocomplete(), true);

			editor.handleInput("\t");
			assert.strictEqual(editor.getText(), "/help ");
			assert.strictEqual(editor.isShowingAutocomplete(), false);
		});
	});

	describe("Character jump (Ctrl+])", () => {
		it("jumps forward to first occurrence of character on same line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("o");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });
		});

		it("jumps forward to next occurrence after cursor", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");

			for (let i = 0; i < 4; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });

			editor.handleInput("\x1d");
			editor.handleInput("o");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });
		});

		it("jumps forward across multiple lines", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("abc\ndef\nghi");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("g");

			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 0 });
		});

		it("jumps backward to first occurrence before cursor on same line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });

			editor.handleInput("\x1b\x1d");
			editor.handleInput("o");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });
		});

		it("jumps backward across multiple lines", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("abc\ndef\nghi");

			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 3 });

			editor.handleInput("\x1b\x1d");
			editor.handleInput("a");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("does nothing when character is not found (forward)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("z");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("does nothing when character is not found (backward)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });

			editor.handleInput("\x1b\x1d");
			editor.handleInput("z");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });
		});

		it("is case-sensitive", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("Hello World");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("h");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("W");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });
		});

		it("cancels jump mode when Ctrl+] is pressed again", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("\x1d");

			editor.handleInput("o");
			assert.strictEqual(editor.getText(), "ohello world");
		});

		it("cancels jump mode on Escape and processes the Escape", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("\x1b");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("o");
			assert.strictEqual(editor.getText(), "ohello world");
		});

		it("cancels backward jump mode when Ctrl+Alt+] is pressed again", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });

			editor.handleInput("\x1b\x1d");
			editor.handleInput("\x1b\x1d");

			editor.handleInput("o");
			assert.strictEqual(editor.getText(), "hello worldo");
		});

		it("searches for special characters", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("foo(bar) = baz;");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("(");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x1d");
			editor.handleInput("=");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 9 });
		});

		it("handles empty text gracefully", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1d");
			editor.handleInput("x");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("resets lastAction when jumping", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world");
			editor.handleInput("\x01");

			editor.handleInput("x");
			assert.strictEqual(editor.getText(), "xhello world");

			editor.handleInput("\x1d");
			editor.handleInput("o");

			editor.handleInput("Y");
			assert.strictEqual(editor.getText(), "xhellYo world");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "xhello world");
		});
	});

	describe("Sticky column", () => {
		function positionCursor(editor: Editor, line: number, col: number): void {
			for (let i = 0; i < 20; i++) editor.handleInput("\x1b[A");

			for (let i = 0; i < line; i++) editor.handleInput("\x1b[B");

			editor.handleInput("\x01");
			for (let i = 0; i < col; i++) editor.handleInput("\x1b[C");
		}

		it("preserves target column when moving up through a shorter line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("2222222222x222\n\n1111111111_111111111111");

			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 23 });
			editor.handleInput("\x01");
			for (let i = 0; i < 10; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 10 });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });
		});

		it("preserves target column when moving down through a shorter line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1111111111_111\n\n2222222222x222222222222");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 10; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 10 });
		});

		it("resets sticky column on horizontal movement (left arrow)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 5 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.handleInput("\x1b[D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 4 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 4 });
		});

		it("resets sticky column on horizontal movement (right arrow)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 5; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 5 });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 6 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });
		});

		it("resets sticky column on typing", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 8; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("X");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 9 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 9 });
		});

		it("resets sticky column on backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 8; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("\x7f");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 7 });
		});

		it("resets sticky column on Ctrl+A (move to line start)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 8; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[A");

			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("resets sticky column on Ctrl+E (move to line end)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("12345\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 3; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x05");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 5 });
		});

		it("resets sticky column on word movement (Ctrl+Left)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world\n\nhello world");

			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 11 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 11 });

			editor.handleInput("\x1b[1;5D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 6 });
		});

		it("resets sticky column on word movement (Ctrl+Right)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("hello world\n\nhello world");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 0 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 5 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });
		});

		it("resets sticky column on undo", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 8; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 8 });

			editor.handleInput("X");
			assert.strictEqual(editor.getText(), "1234567890\n\n12345678X90");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 9 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 9 });

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), "1234567890\n\n1234567890");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 8 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });
		});

		it("handles multiple consecutive up/down movements", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\nab\ncd\nef\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 7; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 4, col: 7 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 7 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 4, col: 7 });
		});

		it("moves correctly through wrapped visual lines without getting stuck", () => {
			const tui = createTestTUI(15, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			editor.setText("short\n123456789012345678901234567890");
			editor.render(15);

			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 30 });

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getCursor().line, 1);

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getCursor().line, 1);

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getCursor().line, 0);
		});

		it("handles setText resetting sticky column", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("1234567890\n\n1234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 8; i++) editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[A");

			editor.setText("abcdefghij\n\nabcdefghij");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 10 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });
		});

		it("sets preferredVisualCol when pressing right at end of prompt (last line)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("111111111x1111111111\n\n333333333_");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x05");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 20 });

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 10 });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 10 });

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });
		});

		it("handles editor resizes when preferredVisualCol is on the same line", () => {
			const tui = createTestTUI(80, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			editor.setText("12345678901234567890\n\n12345678901234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 15; i++) editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 15 });

			editor.render(12);

			editor.handleInput("\x1b[B");
			editor.handleInput("\x1b[B");
			assert.equal(editor.getCursor().col, 4);
		});

		it("handles editor resizes when preferredVisualCol is on a different line", () => {
			const tui = createTestTUI(80, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			editor.setText("short\n12345678901234567890");

			editor.handleInput("\x01");
			for (let i = 0; i < 15; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 15 });

			editor.handleInput("\x1b[A");

			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.render(10);

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 8 });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 5 });

			editor.render(80);

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 15 });
		});

		it("rewrapped lines: target fits current visual column", () => {
			const tui = createTestTUI(80, 24);
			const editor = new Editor(tui, defaultEditorTheme);
			editor.setText("abcdefghijklmnopqr\n123456789012345678");

			positionCursor(editor, 0, 18);
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 18 });

			editor.render(10);

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 8 });

			editor.render(80);
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 8 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 8 });
		});

		it("rewrapped lines: target shorter than current visual column", () => {
			const tui = createTestTUI(80, 24);
			const editor = new Editor(tui, defaultEditorTheme);
			editor.setText("abcdefghijklmnopqr\n123456789012345678\nab");

			positionCursor(editor, 0, 18);
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 18 });

			editor.render(10);
			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 8 });

			editor.render(80);

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 2 });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 8 });
		});
	});

	describe("Paste marker atomic behavior", () => {
		function pasteWithMarker(editor: Editor): string {
			const bigContent = "line\n".repeat(20).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);

			return editor.getText();
		}

		function bigPaste(tag: string): string {
			return Array.from({ length: 12 }, (_, i) => `${tag}${i}`).join("\n");
		}

		it("creates a paste marker for large pastes", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const text = pasteWithMarker(editor);
			assert.match(text, /\[paste #\d+ \+\d+ lines\]/);
		});

		it("treats paste marker as single unit for right arrow", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("A");
			pasteWithMarker(editor);
			editor.handleInput("B");

			editor.handleInput("\x01");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });

			editor.handleInput("\x1b[C");
			const marker = editor.getText().match(/\[paste #\d+ \+\d+ lines\]/)![0];
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 + marker.length });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 + marker.length + 1 });
		});

		it("treats paste marker as single unit for left arrow", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("A");
			pasteWithMarker(editor);
			editor.handleInput("B");

			editor.handleInput("\x1b[D");
			const text = editor.getText();
			const marker = text.match(/\[paste #\d+ \+\d+ lines\]/)![0];
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 + marker.length });

			editor.handleInput("\x1b[D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });

			editor.handleInput("\x1b[D");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 0 });
		});

		it("treats paste marker as single unit for backspace", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("A");
			pasteWithMarker(editor);
			editor.handleInput("B");

			const text = editor.getText();
			const marker = text.match(/\[paste #\d+ \+\d+ lines\]/)![0];

			editor.handleInput("\x01");

			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 + marker.length });

			editor.handleInput("\x7f");
			assert.strictEqual(editor.getText(), "AB");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });
		});

		it("treats paste marker as single unit for forward delete", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("A");
			pasteWithMarker(editor);
			editor.handleInput("B");

			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");

			editor.handleInput("\x1b[3~");
			assert.strictEqual(editor.getText(), "AB");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });
		});

		it("treats paste marker as single unit for word movement", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("X");
			editor.handleInput(" ");
			pasteWithMarker(editor);
			editor.handleInput(" ");
			editor.handleInput("Y");

			const text = editor.getText();
			const marker = text.match(/\[paste #\d+ \+\d+ lines\]/)![0];

			editor.handleInput("\x01");

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });

			editor.handleInput("\x1b[1;5C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 2 + marker.length });
		});

		it("undo restores marker after backspace deletion", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			editor.handleInput("A");
			pasteWithMarker(editor);
			editor.handleInput("B");

			const textBefore = editor.getText();

			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x1b[C");

			editor.handleInput("\x7f");
			assert.strictEqual(editor.getText(), "AB");

			editor.handleInput("\x1b[45;5u");
			assert.strictEqual(editor.getText(), textBefore);
		});

		it("undo after paste marker deletion restores the paste registry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = "";
			editor.onSubmit = (t) => {
				submitted = t;
			};

			const paste = bigPaste("alpha");
			editor.handleInput(`\x1b[200~${paste}\x1b[201~`);
			editor.handleInput("\x7f");
			editor.handleInput("\x1b[45;5u");
			editor.handleInput("\r");
			assert.strictEqual(submitted, paste);
		});

		it("undo after deleting the first of two paste markers restores both registry entries", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = "";
			editor.onSubmit = (t) => {
				submitted = t;
			};

			const pasteA = bigPaste("alpha");
			const pasteB = bigPaste("beta");
			editor.handleInput(`\x1b[200~${pasteA}\x1b[201~`);
			editor.handleInput(`\x1b[200~${pasteB}\x1b[201~`);
			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");
			editor.handleInput("\x7f");
			editor.handleInput("\x1b[45;5u");
			editor.handleInput("\r");
			assert.strictEqual(submitted, pasteA + pasteB);
		});

		it("renumbers the paste registry in ascending id order when markers are out of order in text", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = "";
			editor.onSubmit = (t) => {
				submitted = t;
			};

			const pasteA = bigPaste("alpha");
			const pasteB = bigPaste("beta");
			const pasteC = bigPaste("gamma");
			editor.handleInput(`\x1b[200~${pasteA}\x1b[201~`);
			editor.handleInput("\x01");
			editor.handleInput(`\x1b[200~${pasteB}\x1b[201~`);
			editor.handleInput("\x01");
			editor.handleInput(`\x1b[200~${pasteC}\x1b[201~`);
			editor.handleInput("\x05");
			editor.handleInput("\x7f");
			editor.handleInput("\r");
			assert.strictEqual(submitted, pasteC + pasteB);
		});

		it("undo after setText restores paste markers and registry", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			let submitted = "";
			editor.onSubmit = (t) => {
				submitted = t;
			};

			const paste = bigPaste("alpha");
			editor.handleInput(`\x1b[200~${paste}\x1b[201~`);
			editor.setText("replacement");
			editor.handleInput("\x1b[45;5u");
			editor.handleInput("\r");
			assert.strictEqual(submitted, paste);
		});

		it("handles multiple paste markers in same line", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			pasteWithMarker(editor);
			editor.handleInput(" ");
			pasteWithMarker(editor);

			const text = editor.getText();
			const markers = [...text.matchAll(/\[paste #\d+ \+\d+ lines\]/g)];
			assert.strictEqual(markers.length, 2);

			editor.handleInput("\x01");

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: markers[0]![0].length });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: markers[0]![0].length + 1 });

			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), {
				line: 0,
				col: markers[0]![0].length + 1 + markers[1]![0].length,
			});
		});

		it("does not treat manually typed marker-like text as atomic (no valid paste ID)", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			const fakeMarker = "[paste #99 +5 lines]";
			for (const ch of fakeMarker) editor.handleInput(ch);

			assert.strictEqual(editor.getText(), fakeMarker);

			editor.handleInput("\x01");
			editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 1 });
		});

		it("does not crash when paste marker is wider than terminal width", () => {
			const tui = createTestTUI();
			const editor = new Editor(tui, defaultEditorTheme);
			const bigContent = "line\n".repeat(47).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);

			const text = editor.getText();
			const marker = text.match(/\[paste #\d+ \+\d+ lines\]/);
			assert.ok(marker, "paste marker should be created");
			assert.ok(visibleWidth(marker[0]) > 8, "marker should be wider than render width");

			const lines = editor.render(8);

			for (const line of lines) {
				assert.ok(
					visibleWidth(line) <= 8,
					`line exceeds width 8: visible=${visibleWidth(line)} text=${JSON.stringify(line)}`,
				);
			}
		});

		it("does not crash when text + paste marker exceeds terminal width with cursor on marker", () => {
			const tui = createTestTUI();
			const editor = new Editor(tui, defaultEditorTheme);

			for (let i = 0; i < 35; i++) editor.handleInput("b");

			const bigContent = "line\n".repeat(27).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);

			for (let i = 0; i < 4; i++) editor.handleInput("b");

			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");
			editor.handleInput("\x1b[D");

			const renderWidth = 54;
			const lines = editor.render(renderWidth);
			for (const line of lines) {
				assert.ok(
					visibleWidth(line) <= renderWidth,
					`line exceeds width ${renderWidth}: visible=${visibleWidth(line)} text=${JSON.stringify(line)}`,
				);
			}
		});

		it("wordWrapLine re-checks overflow after backtracking to wrap opportunity", () => {
			const tui = createTestTUI();
			const editor = new Editor(tui, defaultEditorTheme);

			editor.handleInput(" ");
			for (let i = 0; i < 35; i++) editor.handleInput("b");

			const bigContent = "line\n".repeat(27).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);

			for (let i = 0; i < 4; i++) editor.handleInput("b");

			const renderWidth = 54;
			const lines = editor.render(renderWidth);
			for (const line of lines) {
				assert.ok(
					visibleWidth(line) <= renderWidth,
					`line exceeds width ${renderWidth}: visible=${visibleWidth(line)} text=${JSON.stringify(line)}`,
				);
			}
		});

		it("expands large pasted content literally in getExpandedText", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const pastedText = [
				"line 1",
				"line 2",
				"line 3",
				"line 4",
				"line 5",
				"line 6",
				"line 7",
				"line 8",
				"line 9",
				"line 10",
				"tokens $1 $2 $& $$ $` $' end",
			].join("\n");

			editor.handleInput(`\x1b[200~${pastedText}\x1b[201~`);

			assert.match(editor.getText(), /\[paste #\d+ \+\d+ lines\]/);
			assert.strictEqual(editor.getExpandedText(), pastedText);
		});

		it("snaps to the paste marker start when navigating down into it", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);

			editor.setText("12345678901234567890\n\nhello ");

			const bigContent = "x".repeat(2000);
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);
			editor.render(80);

			const text = editor.getText();
			const _marker = text.match(/\[paste #\d+ \d+ chars\]/)![0];

			editor.handleInput("\x1b[A");
			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 10; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 6 });
		});

		it("preserves sticky column when navigating through paste marker line", () => {
			const tui = createTestTUI(30, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			for (const ch of "1234567890123456") editor.handleInput(ch);
			editor.handleInput("\n");
			editor.handleInput("\n");
			editor.handleInput(`\x1b[200~${"x".repeat(2000)}\x1b[201~`);
			editor.handleInput("\n");
			editor.handleInput("\n");
			for (const ch of "abcdefghijklmnop") editor.handleInput(ch);
			editor.render(30);

			for (let i = 0; i < 4; i++) editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 10; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 10 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 0 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 2, col: 0 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 3, col: 0 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 4, col: 10 });
		});

		it("does not get stuck moving down from a multi-visual-line paste marker", () => {
			const tui = createTestTUI(20, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			for (const ch of "abcdefgh") editor.handleInput(ch);
			const bigContent = "line\n".repeat(100).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);
			for (const ch of "ijklmnopqr") editor.handleInput(ch);
			editor.handleInput("\n");
			for (const ch of "123456789012345678") editor.handleInput(ch);
			editor.render(20);

			const text = editor.getText();
			const markerMatch = text.match(/\[paste #\d+ \+\d+ lines]/);
			assert.ok(markerMatch, "paste marker should be created");
			const markerLen = markerMatch[0].length;
			assert.ok(markerLen > 20, "marker should be wider than terminal");
			const markerStart = 8;
			const markerEnd = markerStart + markerLen;

			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 6; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: markerStart });

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getCursor().line, 0);
			assert.strictEqual(editor.getCursor().col, markerEnd);

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: markerStart });

			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 6 });
		});

		it("skips marker continuation VLs when preferred col falls in marker tail", () => {
			const tui = createTestTUI(20, 24);
			const editor = new Editor(tui, defaultEditorTheme);

			for (const ch of "abcdefgh") editor.handleInput(ch);
			const bigContent = "line\n".repeat(100).trimEnd();
			editor.handleInput(`\x1b[200~${bigContent}\x1b[201~`);
			for (const ch of "ijklmnopqr") editor.handleInput(ch);
			editor.handleInput("\n");
			for (const ch of "123456789012345678") editor.handleInput(ch);
			editor.render(20);

			editor.handleInput("\x1b[A");
			editor.handleInput("\x01");
			for (let i = 0; i < 3; i++) editor.handleInput("\x1b[C");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });

			editor.handleInput("\x1b[B");
			assert.strictEqual(editor.getCursor().col, 8);

			editor.handleInput("\x1b[B");
			assert.deepStrictEqual(editor.getCursor(), { line: 1, col: 3 });

			editor.handleInput("\x1b[A");
			assert.strictEqual(editor.getCursor().col, 8);
			editor.handleInput("\x1b[A");
			assert.deepStrictEqual(editor.getCursor(), { line: 0, col: 3 });
		});

		it("submits large pasted content literally", () => {
			const editor = new Editor(createTestTUI(), defaultEditorTheme);
			const pastedText = [
				"line 1",
				"line 2",
				"line 3",
				"line 4",
				"line 5",
				"line 6",
				"line 7",
				"line 8",
				"line 9",
				"line 10",
				"tokens $1 $2 $& $$ $` $' end",
			].join("\n");
			let submitted = "";
			editor.onSubmit = (text) => {
				submitted = text;
			};

			editor.handleInput(`\x1b[200~${pastedText}\x1b[201~`);
			editor.handleInput("\r");

			assert.strictEqual(submitted, pastedText);
		});
	});
});
