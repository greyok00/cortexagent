import { Container, Loader, Spacer, Text } from "@cortexagent/tui";
import "../../../core/tools/truncate.js";
import { stripAnsi } from "../../../utils/ansi.js";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { keyHint, keyText } from "./keybinding-hints.js";
import { truncateToVisualLines } from "./visual-truncate.js";
const PREVIEW_LINES = 20;
export class BashExecutionComponent extends Container {
    command;
    outputLines = [];
    status = "running";
    exitCode = undefined;
    loader;
    truncationResult;
    fullOutputPath;
    expanded = false;
    contentContainer;
    constructor(command, ui, excludeFromContext = false) {
        super();
        this.command = command;
        const colorKey = excludeFromContext ? "dim" : "bashMode";
        const borderColor = (str) => theme.fg(colorKey, str);
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder(borderColor));
        this.contentContainer = new Container();
        this.addChild(this.contentContainer);
        const header = new Text(theme.fg(colorKey, theme.bold(`$ ${command}`)), 1, 0);
        this.contentContainer.addChild(header);
        this.loader = new Loader(ui, (spinner) => theme.fg(colorKey, spinner), (text) => theme.fg("muted", text), `Running... (${keyText("tui.select.cancel")} to cancel)`);
        this.contentContainer.addChild(this.loader);
        this.addChild(new DynamicBorder(borderColor));
    }
    setExpanded(expanded) {
        this.expanded = expanded;
        this.updateDisplay();
    }
    invalidate() {
        super.invalidate();
        this.updateDisplay();
    }
    appendOutput(chunk) {
        const clean = stripAnsi(chunk).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        const newLines = clean.split("\n");
        if (this.outputLines.length > 0 && newLines.length > 0) {
            this.outputLines[this.outputLines.length - 1] += newLines[0];
            this.outputLines.push(...newLines.slice(1));
        }
        else {
            this.outputLines.push(...newLines);
        }
        this.updateDisplay();
    }
    setComplete(exitCode, cancelled, truncationResult, fullOutputPath) {
        this.exitCode = exitCode;
        this.status = cancelled
            ? "cancelled"
            : exitCode !== 0 && exitCode !== undefined && exitCode !== null
                ? "error"
                : "complete";
        this.truncationResult = truncationResult;
        this.fullOutputPath = fullOutputPath;
        this.loader.stop();
        this.updateDisplay();
    }
    updateDisplay() {
        const fullOutput = this.outputLines.join("\n");
        // No truncation — full output always preserved
        const availableLines = fullOutput ? fullOutput.split("\n") : [];
        const previewLogicalLines = availableLines.slice(-PREVIEW_LINES);
        const hiddenLineCount = availableLines.length - previewLogicalLines.length;
        this.contentContainer.clear();
        const header = new Text(theme.fg("bashMode", theme.bold(`$ ${this.command}`)), 1, 0);
        this.contentContainer.addChild(header);
        if (availableLines.length > 0) {
            if (this.expanded) {
                const displayText = availableLines.map((line) => theme.fg("muted", line)).join("\n");
                this.contentContainer.addChild(new Text(`\n${displayText}`, 1, 0));
            }
            else {
                const styledOutput = previewLogicalLines.map((line) => theme.fg("muted", line)).join("\n");
                const styledInput = `\n${styledOutput}`;
                let cachedWidth;
                let cachedLines;
                this.contentContainer.addChild({
                    render: (width) => {
                        if (cachedLines === undefined || cachedWidth !== width) {
                            const result = truncateToVisualLines(styledInput, PREVIEW_LINES, width, 1);
                            cachedLines = result.visualLines;
                            cachedWidth = width;
                        }
                        return cachedLines ?? [];
                    },
                    invalidate: () => {
                        cachedWidth = undefined;
                        cachedLines = undefined;
                    },
                });
            }
        }
        if (this.status === "running") {
            this.contentContainer.addChild(this.loader);
        }
        else {
            const statusParts = [];
            if (hiddenLineCount > 0) {
                if (this.expanded) {
                    statusParts.push(`${theme.fg("muted", "(")}${keyHint("app.tools.expand", "to collapse")}${theme.fg("muted", ")")}`);
                }
                else {
                    statusParts.push(`${theme.fg("muted", `... ${hiddenLineCount} more lines (`)}${keyHint("app.tools.expand", "to expand")}${theme.fg("muted", ")")}`);
                }
            }
            if (this.status === "cancelled") {
                statusParts.push(theme.fg("warning", "(cancelled)"));
            }
            else if (this.status === "error") {
                statusParts.push(theme.fg("error", `(exit ${this.exitCode})`));
            }
            // No truncation — full output always preserved
            if (this.fullOutputPath) {
                statusParts.push(theme.fg("muted", `Full output: ${this.fullOutputPath}`));
            }
            if (statusParts.length > 0) {
                this.contentContainer.addChild(new Text(`\n${statusParts.join("\n")}`, 1, 0));
            }
        }
    }
    getOutput() {
        return this.outputLines.join("\n");
    }
    getCommand() {
        return this.command;
    }
}
//# sourceMappingURL=bash-execution.js.map