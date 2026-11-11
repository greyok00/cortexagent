import { getKeybindings } from "../keybindings.js";
import { decodeKittyPrintable } from "../keys.js";
import { KillRing } from "../kill-ring.js";
import { CURSOR_MARKER } from "../tui.js";
import { UndoStack } from "../undo-stack.js";
import { getGraphemeSegmenter, isWhitespaceChar, sliceByColumn, visibleWidth } from "../utils.js";
import { findWordBackward, findWordForward } from "../word-navigation.js";
const segmenter = getGraphemeSegmenter();
export class Input {
    value = "";
    cursor = 0;
    onSubmit;
    onEscape;
    focused = false;
    pasteBuffer = "";
    isInPaste = false;
    killRing = new KillRing();
    lastAction = null;
    undoStack = new UndoStack();
    getValue() {
        return this.value;
    }
    setValue(value) {
        this.value = value;
        this.cursor = Math.min(this.cursor, value.length);
    }
    handleInput(data) {
        if (data.includes("\x1b[200~")) {
            this.isInPaste = true;
            this.pasteBuffer = "";
            data = data.replace("\x1b[200~", "");
        }
        if (this.isInPaste) {
            this.pasteBuffer += data;
            const endIndex = this.pasteBuffer.indexOf("\x1b[201~");
            if (endIndex !== -1) {
                const pasteContent = this.pasteBuffer.substring(0, endIndex);
                this.handlePaste(pasteContent);
                this.isInPaste = false;
                const remaining = this.pasteBuffer.substring(endIndex + 6);
                this.pasteBuffer = "";
                if (remaining) {
                    this.handleInput(remaining);
                }
            }
            return;
        }
        const kb = getKeybindings();
        if (kb.matches(data, "tui.select.cancel")) {
            if (this.onEscape)
                this.onEscape();
            return;
        }
        if (kb.matches(data, "tui.editor.undo")) {
            this.undo();
            return;
        }
        if (kb.matches(data, "tui.input.submit") || data === "\n") {
            if (this.onSubmit)
                this.onSubmit(this.value);
            return;
        }
        if (kb.matches(data, "tui.editor.deleteCharBackward")) {
            this.handleBackspace();
            return;
        }
        if (kb.matches(data, "tui.editor.deleteCharForward")) {
            this.handleForwardDelete();
            return;
        }
        if (kb.matches(data, "tui.editor.deleteWordBackward")) {
            this.deleteWordBackwards();
            return;
        }
        if (kb.matches(data, "tui.editor.deleteWordForward")) {
            this.deleteWordForward();
            return;
        }
        if (kb.matches(data, "tui.editor.deleteToLineStart")) {
            this.deleteToLineStart();
            return;
        }
        if (kb.matches(data, "tui.editor.deleteToLineEnd")) {
            this.deleteToLineEnd();
            return;
        }
        if (kb.matches(data, "tui.editor.yank")) {
            this.yank();
            return;
        }
        if (kb.matches(data, "tui.editor.yankPop")) {
            this.yankPop();
            return;
        }
        if (kb.matches(data, "tui.editor.cursorLeft")) {
            this.lastAction = null;
            if (this.cursor > 0) {
                const beforeCursor = this.value.slice(0, this.cursor);
                const graphemes = [...segmenter.segment(beforeCursor)];
                const lastGrapheme = graphemes[graphemes.length - 1];
                this.cursor -= lastGrapheme ? lastGrapheme.segment.length : 1;
            }
            return;
        }
        if (kb.matches(data, "tui.editor.cursorRight")) {
            this.lastAction = null;
            if (this.cursor < this.value.length) {
                const afterCursor = this.value.slice(this.cursor);
                const graphemes = [...segmenter.segment(afterCursor)];
                const firstGrapheme = graphemes[0];
                this.cursor += firstGrapheme ? firstGrapheme.segment.length : 1;
            }
            return;
        }
        if (kb.matches(data, "tui.editor.cursorLineStart")) {
            this.lastAction = null;
            this.cursor = 0;
            return;
        }
        if (kb.matches(data, "tui.editor.cursorLineEnd")) {
            this.lastAction = null;
            this.cursor = this.value.length;
            return;
        }
        if (kb.matches(data, "tui.editor.cursorWordLeft")) {
            this.moveWordBackwards();
            return;
        }
        if (kb.matches(data, "tui.editor.cursorWordRight")) {
            this.moveWordForwards();
            return;
        }
        const kittyPrintable = decodeKittyPrintable(data);
        if (kittyPrintable !== undefined) {
            this.insertCharacter(kittyPrintable);
            return;
        }
        const hasControlChars = [...data].some((ch) => {
            const code = ch.charCodeAt(0);
            return code < 32 || code === 0x7f || (code >= 0x80 && code <= 0x9f);
        });
        if (!hasControlChars) {
            this.insertCharacter(data);
        }
    }
    insertCharacter(char) {
        if (isWhitespaceChar(char) || this.lastAction !== "type-word") {
            this.pushUndo();
        }
        this.lastAction = "type-word";
        this.value = this.value.slice(0, this.cursor) + char + this.value.slice(this.cursor);
        this.cursor += char.length;
    }
    handleBackspace() {
        this.lastAction = null;
        if (this.cursor > 0) {
            this.pushUndo();
            const beforeCursor = this.value.slice(0, this.cursor);
            const graphemes = [...segmenter.segment(beforeCursor)];
            const lastGrapheme = graphemes[graphemes.length - 1];
            const graphemeLength = lastGrapheme ? lastGrapheme.segment.length : 1;
            this.value = this.value.slice(0, this.cursor - graphemeLength) + this.value.slice(this.cursor);
            this.cursor -= graphemeLength;
        }
    }
    handleForwardDelete() {
        this.lastAction = null;
        if (this.cursor < this.value.length) {
            this.pushUndo();
            const afterCursor = this.value.slice(this.cursor);
            const graphemes = [...segmenter.segment(afterCursor)];
            const firstGrapheme = graphemes[0];
            const graphemeLength = firstGrapheme ? firstGrapheme.segment.length : 1;
            this.value = this.value.slice(0, this.cursor) + this.value.slice(this.cursor + graphemeLength);
        }
    }
    deleteToLineStart() {
        if (this.cursor === 0)
            return;
        this.pushUndo();
        const deletedText = this.value.slice(0, this.cursor);
        this.killRing.push(deletedText, { prepend: true, accumulate: this.lastAction === "kill" });
        this.lastAction = "kill";
        this.value = this.value.slice(this.cursor);
        this.cursor = 0;
    }
    deleteToLineEnd() {
        if (this.cursor >= this.value.length)
            return;
        this.pushUndo();
        const deletedText = this.value.slice(this.cursor);
        this.killRing.push(deletedText, { prepend: false, accumulate: this.lastAction === "kill" });
        this.lastAction = "kill";
        this.value = this.value.slice(0, this.cursor);
    }
    deleteWordBackwards() {
        if (this.cursor === 0)
            return;
        const wasKill = this.lastAction === "kill";
        this.pushUndo();
        const oldCursor = this.cursor;
        this.moveWordBackwards();
        const deleteFrom = this.cursor;
        this.cursor = oldCursor;
        const deletedText = this.value.slice(deleteFrom, this.cursor);
        this.killRing.push(deletedText, { prepend: true, accumulate: wasKill });
        this.lastAction = "kill";
        this.value = this.value.slice(0, deleteFrom) + this.value.slice(this.cursor);
        this.cursor = deleteFrom;
    }
    deleteWordForward() {
        if (this.cursor >= this.value.length)
            return;
        const wasKill = this.lastAction === "kill";
        this.pushUndo();
        const oldCursor = this.cursor;
        this.moveWordForwards();
        const deleteTo = this.cursor;
        this.cursor = oldCursor;
        const deletedText = this.value.slice(this.cursor, deleteTo);
        this.killRing.push(deletedText, { prepend: false, accumulate: wasKill });
        this.lastAction = "kill";
        this.value = this.value.slice(0, this.cursor) + this.value.slice(deleteTo);
    }
    yank() {
        const text = this.killRing.peek();
        if (!text)
            return;
        this.pushUndo();
        this.value = this.value.slice(0, this.cursor) + text + this.value.slice(this.cursor);
        this.cursor += text.length;
        this.lastAction = "yank";
    }
    yankPop() {
        if (this.lastAction !== "yank" || this.killRing.length <= 1)
            return;
        this.pushUndo();
        const prevText = this.killRing.peek() || "";
        this.value = this.value.slice(0, this.cursor - prevText.length) + this.value.slice(this.cursor);
        this.cursor -= prevText.length;
        this.killRing.rotate();
        const text = this.killRing.peek() || "";
        this.value = this.value.slice(0, this.cursor) + text + this.value.slice(this.cursor);
        this.cursor += text.length;
        this.lastAction = "yank";
    }
    pushUndo() {
        this.undoStack.push({ value: this.value, cursor: this.cursor });
    }
    undo() {
        const snapshot = this.undoStack.pop();
        if (!snapshot)
            return;
        this.value = snapshot.value;
        this.cursor = snapshot.cursor;
        this.lastAction = null;
    }
    moveWordBackwards() {
        if (this.cursor === 0)
            return;
        this.lastAction = null;
        this.cursor = findWordBackward(this.value, this.cursor);
    }
    moveWordForwards() {
        if (this.cursor >= this.value.length)
            return;
        this.lastAction = null;
        this.cursor = findWordForward(this.value, this.cursor);
    }
    handlePaste(pastedText) {
        this.lastAction = null;
        this.pushUndo();
        const cleanText = pastedText.replace(/\r\n/g, "").replace(/\r/g, "").replace(/\n/g, "").replace(/\t/g, "    ");
        this.value = this.value.slice(0, this.cursor) + cleanText + this.value.slice(this.cursor);
        this.cursor += cleanText.length;
    }
    invalidate() {
        // No cached state to invalidate currently
    }
    render(width) {
        const prompt = "> ";
        const availableWidth = width - prompt.length;
        if (availableWidth <= 0) {
            return [prompt];
        }
        let visibleText = "";
        let cursorDisplay = this.cursor;
        const totalWidth = visibleWidth(this.value);
        if (totalWidth < availableWidth) {
            visibleText = this.value;
        }
        else {
            const scrollWidth = this.cursor === this.value.length ? availableWidth - 1 : availableWidth;
            const cursorCol = visibleWidth(this.value.slice(0, this.cursor));
            if (scrollWidth > 0) {
                const halfWidth = Math.floor(scrollWidth / 2);
                let startCol = 0;
                if (cursorCol < halfWidth) {
                    startCol = 0;
                }
                else if (cursorCol > totalWidth - halfWidth) {
                    startCol = Math.max(0, totalWidth - scrollWidth);
                }
                else {
                    startCol = Math.max(0, cursorCol - halfWidth);
                }
                visibleText = sliceByColumn(this.value, startCol, scrollWidth, true);
                const beforeCursor = sliceByColumn(this.value, startCol, Math.max(0, cursorCol - startCol), true);
                cursorDisplay = beforeCursor.length;
            }
            else {
                visibleText = "";
                cursorDisplay = 0;
            }
        }
        const graphemes = [...segmenter.segment(visibleText.slice(cursorDisplay))];
        const cursorGrapheme = graphemes[0];
        const beforeCursor = visibleText.slice(0, cursorDisplay);
        const atCursor = cursorGrapheme?.segment ?? " ";
        const afterCursor = visibleText.slice(cursorDisplay + atCursor.length);
        const marker = this.focused ? CURSOR_MARKER : "";
        const cursorChar = `\x1b[7m${atCursor}\x1b[27m`;
        const textWithCursor = beforeCursor + marker + cursorChar + afterCursor;
        const visualLength = visibleWidth(textWithCursor);
        const padding = " ".repeat(Math.max(0, availableWidth - visualLength));
        const line = prompt + textWithCursor + padding;
        return [line];
    }
}
//# sourceMappingURL=input.js.map