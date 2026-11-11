import * as fs from "node:fs";
import * as path from "node:path";
import { deleteKittyImage, isImageLine } from "./terminal-image.js";
import { TuiBase } from "./tui.js";
import { visibleWidth } from "./utils.js";
const KITTY_SEQUENCE_PREFIX = "\x1b_G";
function parseKittyImageHeader(line) {
    const sequenceStart = line.indexOf(KITTY_SEQUENCE_PREFIX);
    if (sequenceStart === -1)
        return undefined;
    const paramsStart = sequenceStart + KITTY_SEQUENCE_PREFIX.length;
    const paramsEnd = line.indexOf(";", paramsStart);
    if (paramsEnd === -1)
        return undefined;
    const ids = [];
    let rows = 1;
    for (const param of line.slice(paramsStart, paramsEnd).split(",")) {
        const [key, value] = param.split("=", 2);
        if (value === undefined)
            continue;
        const numberValue = Number(value);
        if (!Number.isInteger(numberValue) || numberValue <= 0 || numberValue > 0xffffffff)
            continue;
        if (key === "i")
            ids.push(numberValue);
        else if (key === "r")
            rows = numberValue;
    }
    return { ids, rows };
}
function extractKittyImageIds(line) {
    return parseKittyImageHeader(line)?.ids ?? [];
}
function extractKittyImageRows(line) {
    return parseKittyImageHeader(line)?.rows ?? 1;
}
function isTermuxSession() {
    return Boolean(process.env.TERMUX_VERSION);
}
export class TuiMainScreen extends TuiBase {
    mode = "regular";
    previousLines = [];
    previousKittyImageIds = new Set();
    previousWidth = 0;
    previousHeight = 0;
    cursorRow = 0;
    hardwareCursorRow = 0;
    maxLinesRendered = 0;
    previousViewportTop = 0;
    captureRenderState() {
        return {
            previousLines: [...this.previousLines],
            previousWidth: this.previousWidth,
            previousHeight: this.previousHeight,
            cursorRow: this.cursorRow,
            hardwareCursorRow: this.hardwareCursorRow,
            maxLinesRendered: this.maxLinesRendered,
            previousViewportTop: this.previousViewportTop,
        };
    }
    restoreRenderState(state) {
        this.previousLines = state.previousLines.map((line) => (isImageLine(line) ? "" : line));
        this.previousKittyImageIds = new Set();
        this.previousWidth = state.previousWidth;
        this.previousHeight = state.previousHeight;
        this.cursorRow = state.cursorRow;
        this.hardwareCursorRow = state.hardwareCursorRow;
        this.maxLinesRendered = state.maxLinesRendered;
        this.previousViewportTop = state.previousViewportTop;
    }
    resetRenderState() {
        this.previousLines = [];
        this.previousWidth = -1;
        this.previousHeight = -1;
        this.cursorRow = 0;
        this.hardwareCursorRow = 0;
        this.maxLinesRendered = 0;
        this.previousViewportTop = 0;
    }
    beforeTerminalStop(options) {
        if (options.preserveScreen || this.previousLines.length === 0)
            return;
        this.terminal.write(" ");
        const targetRow = this.previousLines.length;
        const lineDiff = targetRow - this.hardwareCursorRow;
        if (lineDiff > 0)
            this.terminal.write(`\x1b[${lineDiff}B`);
        else if (lineDiff < 0)
            this.terminal.write(`\x1b[${-lineDiff}A`);
        this.terminal.write("\r\n");
    }
    collectKittyImageIds(lines) {
        const ids = new Set();
        for (const line of lines) {
            for (const id of extractKittyImageIds(line)) {
                ids.add(id);
            }
        }
        return ids;
    }
    deleteKittyImages(ids) {
        let buffer = "";
        for (const id of ids) {
            buffer += deleteKittyImage(id);
        }
        return buffer;
    }
    getKittyImageReservedRows(lines, index, maxIndex = lines.length - 1) {
        const rows = extractKittyImageRows(lines[index] ?? "");
        if (rows <= 1)
            return 1;
        const maxRows = Math.min(rows, maxIndex - index + 1, lines.length - index);
        let reservedRows = 1;
        while (reservedRows < maxRows) {
            const line = lines[index + reservedRows] ?? "";
            if (isImageLine(line) || visibleWidth(line) > 0)
                break;
            reservedRows++;
        }
        return reservedRows;
    }
    expandChangedRangeForKittyImages(firstChanged, lastChanged, newLines) {
        let expandedFirstChanged = firstChanged;
        let expandedLastChanged = lastChanged;
        const expandForLines = (lines) => {
            for (let i = 0; i < lines.length; i++) {
                if (extractKittyImageIds(lines[i]).length === 0)
                    continue;
                const blockEnd = i + this.getKittyImageReservedRows(lines, i) - 1;
                if (i >= firstChanged || (i <= lastChanged && blockEnd >= firstChanged)) {
                    expandedFirstChanged = Math.min(expandedFirstChanged, i);
                    expandedLastChanged = Math.max(expandedLastChanged, blockEnd);
                }
            }
        };
        expandForLines(this.previousLines);
        expandForLines(newLines);
        return { firstChanged: expandedFirstChanged, lastChanged: expandedLastChanged };
    }
    deleteChangedKittyImages(firstChanged, lastChanged) {
        if (firstChanged < 0 || lastChanged < firstChanged)
            return "";
        const ids = new Set();
        const maxLine = Math.min(lastChanged, this.previousLines.length - 1);
        for (let i = firstChanged; i <= maxLine; i++) {
            for (const id of extractKittyImageIds(this.previousLines[i] ?? "")) {
                ids.add(id);
            }
        }
        return this.deleteKittyImages(ids);
    }
    doRender() {
        if (this.stopped)
            return;
        const width = this.terminal.columns;
        const height = this.terminal.rows;
        const widthChanged = this.previousWidth !== 0 && this.previousWidth !== width;
        const heightChanged = this.previousHeight !== 0 && this.previousHeight !== height;
        const previousBufferLength = this.previousHeight > 0 ? this.previousViewportTop + this.previousHeight : height;
        let prevViewportTop = heightChanged ? Math.max(0, previousBufferLength - height) : this.previousViewportTop;
        let viewportTop = prevViewportTop;
        let hardwareCursorRow = this.hardwareCursorRow;
        const computeLineDiff = (targetRow) => {
            const currentScreenRow = hardwareCursorRow - prevViewportTop;
            const targetScreenRow = targetRow - viewportTop;
            return targetScreenRow - currentScreenRow;
        };
        let newLines = this.render(width);
        if (this.hasOverlayEntries) {
            newLines = this.compositeOverlays(newLines, width, height);
        }
        const cursorPos = this.extractCursorPosition(newLines, height);
        newLines = this.applyLineResets(newLines);
        const fullRender = (clear) => {
            this.fullRedrawCount += 1;
            let buffer = "\x1b[?2026h";
            if (clear) {
                buffer += this.deleteKittyImages(this.previousKittyImageIds);
                buffer += "\x1b[2J\x1b[H\x1b[3J";
            }
            for (let i = 0; i < newLines.length; i++) {
                if (i > 0)
                    buffer += "\r\n";
                const line = newLines[i];
                const isImage = isImageLine(line);
                const imageReservedRows = isImage ? this.getKittyImageReservedRows(newLines, i) : 1;
                if (imageReservedRows > 1 && imageReservedRows <= height) {
                    for (let row = 1; row < imageReservedRows; row++) {
                        buffer += "\r\n";
                    }
                    buffer += `\x1b[${imageReservedRows - 1}A`;
                    buffer += line;
                    buffer += `\x1b[${imageReservedRows - 1}B`;
                    i += imageReservedRows - 1;
                    continue;
                }
                buffer += line;
            }
            buffer += "\x1b[?2026l";
            this.terminal.write(buffer);
            this.cursorRow = Math.max(0, newLines.length - 1);
            this.hardwareCursorRow = this.cursorRow;
            if (clear) {
                this.maxLinesRendered = newLines.length;
            }
            else {
                this.maxLinesRendered = Math.max(this.maxLinesRendered, newLines.length);
            }
            const bufferLength = Math.max(height, newLines.length);
            this.previousViewportTop = Math.max(0, bufferLength - height);
            this.positionHardwareCursor(cursorPos, newLines.length);
            this.previousLines = newLines;
            this.previousKittyImageIds = this.collectKittyImageIds(newLines);
            this.previousWidth = width;
            this.previousHeight = height;
        };
        const debugRedraw = process.env.CORTEXENGINE_DEBUG_REDRAW === "1";
        const logRedraw = (reason) => {
            if (!debugRedraw)
                return;
            const logPath = path.join(this.logDirectory, "cortexagent-debug.log");
            const msg = `[${new Date().toISOString()}] fullRender: ${reason} (prev=${this.previousLines.length}, new=${newLines.length}, height=${height})\n`;
            fs.mkdirSync(path.dirname(logPath), { recursive: true });
            fs.appendFileSync(logPath, msg);
        };
        if (this.previousLines.length === 0 && !widthChanged && !heightChanged) {
            logRedraw("first render");
            fullRender(false);
            return;
        }
        if (widthChanged) {
            logRedraw(`terminal width changed (${this.previousWidth} -> ${width})`);
            fullRender(true);
            return;
        }
        if (heightChanged && !isTermuxSession()) {
            logRedraw(`terminal height changed (${this.previousHeight} -> ${height})`);
            fullRender(true);
            return;
        }
        if (this.getClearOnShrink() && newLines.length < this.maxLinesRendered && !this.hasOverlayEntries) {
            logRedraw(`clearOnShrink (maxLinesRendered=${this.maxLinesRendered})`);
            fullRender(true);
            return;
        }
        let firstChanged = -1;
        let lastChanged = -1;
        const maxLines = Math.max(newLines.length, this.previousLines.length);
        for (let i = 0; i < maxLines; i++) {
            const oldLine = i < this.previousLines.length ? this.previousLines[i] : "";
            const newLine = i < newLines.length ? newLines[i] : "";
            if (oldLine !== newLine) {
                if (firstChanged === -1) {
                    firstChanged = i;
                }
                lastChanged = i;
            }
        }
        const appendedLines = newLines.length > this.previousLines.length;
        if (appendedLines) {
            if (firstChanged === -1) {
                firstChanged = this.previousLines.length;
            }
            lastChanged = newLines.length - 1;
        }
        if (firstChanged !== -1) {
            const expandedRange = this.expandChangedRangeForKittyImages(firstChanged, lastChanged, newLines);
            firstChanged = expandedRange.firstChanged;
            lastChanged = expandedRange.lastChanged;
        }
        const appendStart = appendedLines && firstChanged === this.previousLines.length && firstChanged > 0;
        if (firstChanged === -1) {
            this.positionHardwareCursor(cursorPos, newLines.length);
            this.previousViewportTop = prevViewportTop;
            this.previousHeight = height;
            return;
        }
        if (firstChanged >= newLines.length) {
            if (this.previousLines.length > newLines.length) {
                let buffer = "\x1b[?2026h";
                buffer += this.deleteChangedKittyImages(firstChanged, lastChanged);
                const targetRow = Math.max(0, newLines.length - 1);
                if (targetRow < prevViewportTop) {
                    logRedraw(`deleted lines moved viewport up (${targetRow} < ${prevViewportTop})`);
                    fullRender(true);
                    return;
                }
                const lineDiff = computeLineDiff(targetRow);
                if (lineDiff > 0)
                    buffer += `\x1b[${lineDiff}B`;
                else if (lineDiff < 0)
                    buffer += `\x1b[${-lineDiff}A`;
                buffer += "\r";
                const extraLines = this.previousLines.length - newLines.length;
                if (extraLines > height) {
                    logRedraw(`extraLines > height (${extraLines} > ${height})`);
                    fullRender(true);
                    return;
                }
                const clearStartOffset = newLines.length === 0 ? 0 : 1;
                if (extraLines > 0 && clearStartOffset > 0) {
                    buffer += `\x1b[${clearStartOffset}B`;
                }
                for (let i = 0; i < extraLines; i++) {
                    buffer += "\r\x1b[2K";
                    if (i < extraLines - 1)
                        buffer += "\x1b[1B";
                }
                const moveBack = Math.max(0, extraLines - 1 + clearStartOffset);
                if (moveBack > 0) {
                    buffer += `\x1b[${moveBack}A`;
                }
                buffer += "\x1b[?2026l";
                this.terminal.write(buffer);
                this.cursorRow = targetRow;
                this.hardwareCursorRow = targetRow;
            }
            this.positionHardwareCursor(cursorPos, newLines.length);
            this.previousLines = newLines;
            this.previousKittyImageIds = this.collectKittyImageIds(newLines);
            this.previousWidth = width;
            this.previousHeight = height;
            this.previousViewportTop = prevViewportTop;
            return;
        }
        if (firstChanged < prevViewportTop) {
            logRedraw(`firstChanged < viewportTop (${firstChanged} < ${prevViewportTop})`);
            fullRender(true);
            return;
        }
        let buffer = "\x1b[?2026h";
        buffer += this.deleteChangedKittyImages(firstChanged, lastChanged);
        const prevViewportBottom = prevViewportTop + height - 1;
        const moveTargetRow = appendStart ? firstChanged - 1 : firstChanged;
        if (moveTargetRow > prevViewportBottom) {
            const currentScreenRow = Math.max(0, Math.min(height - 1, hardwareCursorRow - prevViewportTop));
            const moveToBottom = height - 1 - currentScreenRow;
            if (moveToBottom > 0) {
                buffer += `\x1b[${moveToBottom}B`;
            }
            const scroll = moveTargetRow - prevViewportBottom;
            buffer += "\r\n".repeat(scroll);
            prevViewportTop += scroll;
            viewportTop += scroll;
            hardwareCursorRow = moveTargetRow;
        }
        const lineDiff = computeLineDiff(moveTargetRow);
        if (lineDiff > 0) {
            buffer += `\x1b[${lineDiff}B`;
        }
        else if (lineDiff < 0) {
            buffer += `\x1b[${-lineDiff}A`;
        }
        buffer += appendStart ? "\r\n" : "\r";
        const renderEnd = Math.min(lastChanged, newLines.length - 1);
        for (let i = firstChanged; i <= renderEnd; i++) {
            if (i > firstChanged)
                buffer += "\r\n";
            const line = newLines[i];
            const isImage = isImageLine(line);
            const imageReservedRows = isImage ? this.getKittyImageReservedRows(newLines, i, renderEnd) : 1;
            if (imageReservedRows > 1) {
                const imageStartScreenRow = i - viewportTop;
                if (imageStartScreenRow < 0 || imageStartScreenRow + imageReservedRows > height) {
                    logRedraw(`kitty image pre-clear would scroll (${imageStartScreenRow} + ${imageReservedRows} > ${height})`);
                    fullRender(true);
                    return;
                }
                buffer += "\x1b[2K";
                for (let row = 1; row < imageReservedRows; row++) {
                    buffer += "\r\n\x1b[2K";
                }
                buffer += `\x1b[${imageReservedRows - 1}A`;
                buffer += line;
                buffer += `\x1b[${imageReservedRows - 1}B`;
                i += imageReservedRows - 1;
                continue;
            }
            buffer += "\x1b[2K";
            if (!isImage && visibleWidth(line) > width) {
                const crashLogPath = path.join(this.logDirectory, "cortexagent-crash.log");
                const crashData = [
                    `Crash at ${new Date().toISOString()}`,
                    `Terminal width: ${width}`,
                    `Line ${i} visible width: ${visibleWidth(line)}`,
                    "",
                    "=== All rendered lines ===",
                    ...newLines.map((l, idx) => `[${idx}] (w=${visibleWidth(l)}) ${l}`),
                    "",
                ].join("\n");
                fs.mkdirSync(path.dirname(crashLogPath), { recursive: true });
                fs.writeFileSync(crashLogPath, crashData);
                this.stop();
                const errorMsg = [
                    `Rendered line ${i} exceeds terminal width (${visibleWidth(line)} > ${width}).`,
                    "",
                    "This is likely caused by a custom TUI component not truncating its output.",
                    "Use visibleWidth() to measure and truncateToWidth() to truncate lines.",
                    "",
                    `Debug log written to: ${crashLogPath}`,
                ].join("\n");
                throw new Error(errorMsg);
            }
            buffer += line;
        }
        let finalCursorRow = renderEnd;
        if (this.previousLines.length > newLines.length) {
            if (renderEnd < newLines.length - 1) {
                const moveDown = newLines.length - 1 - renderEnd;
                buffer += `\x1b[${moveDown}B`;
                finalCursorRow = newLines.length - 1;
            }
            const extraLines = this.previousLines.length - newLines.length;
            for (let i = newLines.length; i < this.previousLines.length; i++) {
                buffer += "\r\n\x1b[2K";
            }
            buffer += `\x1b[${extraLines}A`;
        }
        buffer += "\x1b[?2026l";
        if (process.env.CORTEXENGINE_TUI_DEBUG === "1") {
            const debugDir = "/tmp/tui";
            fs.mkdirSync(debugDir, { recursive: true });
            const debugPath = path.join(debugDir, `render-${Date.now()}-${Math.random().toString(36).slice(2)}.log`);
            const debugData = [
                `firstChanged: ${firstChanged}`,
                `viewportTop: ${viewportTop}`,
                `cursorRow: ${this.cursorRow}`,
                `height: ${height}`,
                `lineDiff: ${lineDiff}`,
                `hardwareCursorRow: ${hardwareCursorRow}`,
                `renderEnd: ${renderEnd}`,
                `finalCursorRow: ${finalCursorRow}`,
                `cursorPos: ${JSON.stringify(cursorPos)}`,
                `newLines.length: ${newLines.length}`,
                `previousLines.length: ${this.previousLines.length}`,
                "",
                "=== newLines ===",
                JSON.stringify(newLines, null, 2),
                "",
                "=== previousLines ===",
                JSON.stringify(this.previousLines, null, 2),
                "",
                "=== buffer ===",
                JSON.stringify(buffer),
            ].join("\n");
            fs.writeFileSync(debugPath, debugData);
        }
        this.terminal.write(buffer);
        this.cursorRow = Math.max(0, newLines.length - 1);
        this.hardwareCursorRow = finalCursorRow;
        this.maxLinesRendered = Math.max(this.maxLinesRendered, newLines.length);
        this.previousViewportTop = Math.max(prevViewportTop, finalCursorRow - height + 1);
        this.positionHardwareCursor(cursorPos, newLines.length);
        this.previousLines = newLines;
        this.previousKittyImageIds = this.collectKittyImageIds(newLines);
        this.previousWidth = width;
        this.previousHeight = height;
    }
    positionHardwareCursor(cursorPos, totalLines) {
        if (!cursorPos || totalLines <= 0) {
            this.terminal.hideCursor();
            return;
        }
        const targetRow = Math.max(0, Math.min(cursorPos.row, totalLines - 1));
        const targetCol = Math.max(0, cursorPos.col);
        const rowDelta = targetRow - this.hardwareCursorRow;
        let buffer = "";
        if (rowDelta > 0) {
            buffer += `\x1b[${rowDelta}B`;
        }
        else if (rowDelta < 0) {
            buffer += `\x1b[${-rowDelta}A`;
        }
        buffer += `\x1b[${targetCol + 1}G`;
        if (buffer) {
            this.terminal.write(buffer);
        }
        this.hardwareCursorRow = targetRow;
        if (this.getShowHardwareCursor()) {
            this.terminal.showCursor();
        }
        else {
            this.terminal.hideCursor();
        }
    }
}
//# sourceMappingURL=tui-main-screen.js.map