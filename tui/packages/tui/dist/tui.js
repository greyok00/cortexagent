import * as os from "node:os";
import * as path from "node:path";
import { performance } from "node:perf_hooks";
import { isKeyRelease, matchesKey } from "./keys.js";
import { isOsc11BackgroundColorResponse, parseOsc11BackgroundColor, parseTerminalColorSchemeReport, } from "./terminal-colors.js";
import { getCapabilities, isImageLine, setCellDimensions } from "./terminal-image.js";
import { extractSegments, normalizeTerminalOutput, sliceByColumn, sliceWithWidth, visibleWidth } from "./utils.js";
export function isFocusable(component) {
    return component !== null && "focused" in component;
}
export const CURSOR_MARKER = "\x1b_pi:c\x07";
export { visibleWidth };
function parseSizeValue(value, referenceSize) {
    if (value === undefined)
        return undefined;
    if (typeof value === "number")
        return value;
    const match = value.match(/^(\d+(?:\.\d+)?)%$/);
    if (match) {
        return Math.floor((referenceSize * parseFloat(match[1])) / 100);
    }
    return undefined;
}
export class Container {
    children = [];
    addChild(component) {
        this.children.push(component);
    }
    removeChild(component) {
        const index = this.children.indexOf(component);
        if (index !== -1) {
            this.children.splice(index, 1);
        }
    }
    clear() {
        this.children = [];
    }
    invalidate() {
        for (const child of this.children) {
            child.invalidate?.();
        }
    }
    render(width) {
        const lines = [];
        for (const child of this.children) {
            const childLines = child.render(width);
            for (const line of childLines) {
                lines.push(line);
            }
        }
        return lines;
    }
}
const SEGMENT_RESET = "\x1b[0m\x1b]8;;\x07";
export function compositeTuiLine(baseLine, overlayLine, startCol, overlayWidth, totalWidth) {
    if (isImageLine(baseLine))
        return baseLine;
    const afterStart = startCol + overlayWidth;
    const base = extractSegments(baseLine, startCol, afterStart, totalWidth - afterStart, true);
    const overlay = sliceWithWidth(overlayLine, 0, overlayWidth, true);
    const beforePad = Math.max(0, startCol - base.beforeWidth);
    const overlayPad = Math.max(0, overlayWidth - overlay.width);
    const actualBeforeWidth = Math.max(startCol, base.beforeWidth);
    const actualOverlayWidth = Math.max(overlayWidth, overlay.width);
    const afterTarget = Math.max(0, totalWidth - actualBeforeWidth - actualOverlayWidth);
    const afterPad = Math.max(0, afterTarget - base.afterWidth);
    const result = base.before +
        " ".repeat(beforePad) +
        SEGMENT_RESET +
        overlay.text +
        " ".repeat(overlayPad) +
        SEGMENT_RESET +
        base.after +
        " ".repeat(afterPad);
    return visibleWidth(result) <= totalWidth ? result : sliceByColumn(result, 0, totalWidth, true);
}
export const VIEWPORT_TUI = Symbol.for("@cortexagent/tui/viewport");
export function isViewportTUI(tui) {
    return tui[VIEWPORT_TUI] === true;
}
export class TuiBase extends Container {
    terminal;
    focusedComponent = null;
    inputListeners = new Set();
    onDebug;
    renderRequested = false;
    immediateRenderScheduled = false;
    renderTimer;
    lastRenderAt = 0;
    // 2026-11-09 owner ("a lot of flashing when the screen updates"): 16ms
    // (60fps) made loaders re-erase-and-rewrite lines at terminal speed the
    // GPU-poor eye reads as strobe. 50ms (20fps) keeps motion smooth and
    // halves+ the erase churn; line-diffing already skips unchanged rows.
    static MIN_RENDER_INTERVAL_MS = 50;
    showHardwareCursor = process.env.CORTEXENGINE_HARDWARE_CURSOR === "1";
    clearOnShrink = process.env.CORTEXENGINE_CLEAR_ON_SHRINK === "1";
    fullRedrawCount = 0;
    stopped = false;
    pendingOsc11BackgroundReplies = 0;
    pendingOsc11BackgroundQueries = [];
    terminalColorSchemeListeners = new Set();
    terminalColorSchemeNotificationsEnabled = false;
    logDirectory;
    focusOrderCounter = 0;
    overlayStack = [];
    get hasOverlayEntries() {
        return this.overlayStack.length > 0;
    }
    overlayFocusRestore = { status: "inactive" };
    constructor(terminal, showHardwareCursor, logDirectory) {
        super();
        this.terminal = terminal;
        this.logDirectory =
            logDirectory ?? process.env.CORTEXENGINE_CODING_AGENT_DIR ?? path.join(os.homedir(), ".cortex-agent", "agent");
        if (showHardwareCursor !== undefined) {
            this.showHardwareCursor = showHardwareCursor;
        }
    }
    resetRenderState() { }
    beforeTerminalStart() { }
    afterTerminalStart() { }
    beforeTerminalStop(_options) { }
    afterTerminalStop(_options) { }
    get fullRedraws() {
        return this.fullRedrawCount;
    }
    getShowHardwareCursor() {
        return this.showHardwareCursor;
    }
    setShowHardwareCursor(enabled) {
        if (this.showHardwareCursor === enabled)
            return;
        this.showHardwareCursor = enabled;
        if (!enabled) {
            this.terminal.hideCursor();
        }
        this.requestRender();
    }
    getClearOnShrink() {
        return this.clearOnShrink;
    }
    setClearOnShrink(enabled) {
        this.clearOnShrink = enabled;
    }
    getFocusedComponent() {
        return this.focusedComponent;
    }
    setFocus(component) {
        this.setFocusInternal({ component, overlayFocusRestore: "clear" });
    }
    setFocusInternal({ component, overlayFocusRestore, }) {
        const previousFocus = this.focusedComponent;
        let nextFocus = component;
        const previousFocusedOverlay = previousFocus
            ? this.overlayStack.find((entry) => entry.component === previousFocus && this.isOverlayVisible(entry))
            : undefined;
        const nextFocusIsOverlay = nextFocus ? this.overlayStack.some((entry) => entry.component === nextFocus) : false;
        const restoreState = this.getVisibleOverlayFocusRestore();
        if (nextFocus && !nextFocusIsOverlay) {
            if (restoreState.status === "blocked" && restoreState.blockedBy === previousFocus) {
                if (restoreState.resume.status === "focus-target" || !this.isComponentMounted(restoreState.blockedBy)) {
                    nextFocus = this.resolveBlockedOverlayFocusResume(restoreState);
                }
                else {
                    this.overlayFocusRestore = {
                        status: "blocked",
                        overlay: restoreState.overlay,
                        blockedBy: nextFocus,
                        resume: restoreState.resume,
                    };
                }
            }
            else if (previousFocusedOverlay &&
                restoreState.status !== "inactive" &&
                restoreState.overlay === previousFocusedOverlay &&
                !this.isOverlayFocusAncestor(previousFocusedOverlay, nextFocus)) {
                this.overlayFocusRestore = {
                    status: "blocked",
                    overlay: previousFocusedOverlay,
                    blockedBy: nextFocus,
                    resume: { status: "restore-overlay" },
                };
            }
        }
        else if (nextFocus === null) {
            if (restoreState.status === "blocked" && restoreState.blockedBy === previousFocus) {
                nextFocus = this.resolveBlockedOverlayFocusResume(restoreState);
            }
            else if (overlayFocusRestore === "clear") {
                this.clearOverlayFocusRestore();
            }
        }
        if (isFocusable(this.focusedComponent)) {
            this.focusedComponent.focused = false;
        }
        this.focusedComponent = nextFocus;
        if (isFocusable(nextFocus)) {
            nextFocus.focused = true;
        }
        const focusedOverlay = nextFocus
            ? this.overlayStack.find((entry) => entry.component === nextFocus && this.isOverlayVisible(entry))
            : undefined;
        if (focusedOverlay) {
            this.overlayFocusRestore = { status: "eligible", overlay: focusedOverlay };
        }
    }
    clearOverlayFocusRestore() {
        this.overlayFocusRestore = { status: "inactive" };
    }
    clearOverlayFocusRestoreFor(overlay) {
        if (this.overlayFocusRestore.status !== "inactive" && this.overlayFocusRestore.overlay === overlay) {
            this.clearOverlayFocusRestore();
        }
    }
    resolveBlockedOverlayFocusResume(restoreState) {
        if (restoreState.resume.status === "restore-overlay")
            return restoreState.overlay.component;
        this.clearOverlayFocusRestore();
        return restoreState.resume.target;
    }
    getVisibleOverlayFocusRestore() {
        const restoreState = this.overlayFocusRestore;
        if (restoreState.status === "inactive")
            return restoreState;
        if (!this.overlayStack.includes(restoreState.overlay) || !this.isOverlayVisible(restoreState.overlay)) {
            return { status: "inactive" };
        }
        return restoreState;
    }
    isOverlayFocusAncestor(entry, component) {
        const visited = new Set();
        let current = entry.preFocus;
        while (current && !visited.has(current)) {
            visited.add(current);
            if (current === component)
                return true;
            current = this.overlayStack.find((overlay) => overlay.component === current)?.preFocus ?? null;
        }
        return false;
    }
    retargetOverlayPreFocus(removed) {
        for (const overlay of this.overlayStack) {
            if (overlay !== removed && overlay.preFocus === removed.component) {
                overlay.preFocus = removed.preFocus;
            }
        }
    }
    getMountedRoots() {
        return this.children;
    }
    isComponentMounted(component) {
        return this.getMountedRoots().some((child) => this.containsComponent(child, component));
    }
    containsComponent(root, target) {
        if (root === target)
            return true;
        if (!(root instanceof Container))
            return false;
        return root.children.some((child) => this.containsComponent(child, target));
    }
    showOverlay(component, options) {
        const entry = {
            component,
            ...(options === undefined ? {} : { options }),
            preFocus: this.focusedComponent,
            hidden: false,
            focusOrder: ++this.focusOrderCounter,
        };
        this.overlayStack.push(entry);
        if (!options?.nonCapturing && this.isOverlayVisible(entry)) {
            this.setFocus(component);
        }
        this.terminal.hideCursor();
        this.requestRender();
        return {
            hide: () => {
                const index = this.overlayStack.indexOf(entry);
                if (index !== -1) {
                    this.clearOverlayFocusRestoreFor(entry);
                    this.retargetOverlayPreFocus(entry);
                    this.overlayStack.splice(index, 1);
                    if (this.focusedComponent === component) {
                        const topVisible = this.getTopmostVisibleOverlay();
                        this.setFocus(topVisible?.component ?? entry.preFocus);
                    }
                    if (this.overlayStack.length === 0)
                        this.terminal.hideCursor();
                    this.requestRender();
                }
            },
            setHidden: (hidden) => {
                if (entry.hidden === hidden)
                    return;
                entry.hidden = hidden;
                if (hidden) {
                    this.clearOverlayFocusRestoreFor(entry);
                    if (this.focusedComponent === component) {
                        const topVisible = this.getTopmostVisibleOverlay();
                        this.setFocus(topVisible?.component ?? entry.preFocus);
                    }
                }
                else {
                    if (!options?.nonCapturing && this.isOverlayVisible(entry)) {
                        entry.focusOrder = ++this.focusOrderCounter;
                        this.setFocus(component);
                    }
                }
                this.requestRender();
            },
            isHidden: () => entry.hidden,
            focus: () => {
                if (!this.overlayStack.includes(entry) || !this.isOverlayVisible(entry))
                    return;
                entry.focusOrder = ++this.focusOrderCounter;
                this.setFocus(component);
                this.requestRender();
            },
            unfocus: (unfocusOptions) => {
                const isFocused = this.focusedComponent === component;
                const restoreState = this.overlayFocusRestore;
                const hasPendingRestore = restoreState.status !== "inactive" && restoreState.overlay === entry;
                if (!isFocused && !hasPendingRestore)
                    return;
                if (restoreState.status === "blocked" &&
                    restoreState.overlay === entry &&
                    this.focusedComponent === restoreState.blockedBy) {
                    if (unfocusOptions) {
                        this.overlayFocusRestore = {
                            status: "blocked",
                            overlay: entry,
                            blockedBy: restoreState.blockedBy,
                            resume: { status: "focus-target", target: unfocusOptions.target },
                        };
                    }
                    else {
                        this.clearOverlayFocusRestore();
                    }
                    this.requestRender();
                    return;
                }
                this.clearOverlayFocusRestoreFor(entry);
                if (isFocused || unfocusOptions) {
                    const topVisible = this.getTopmostVisibleOverlay();
                    const fallbackTarget = topVisible && topVisible !== entry ? topVisible.component : entry.preFocus;
                    this.setFocus(unfocusOptions ? unfocusOptions.target : fallbackTarget);
                }
                this.requestRender();
            },
            isFocused: () => this.focusedComponent === component,
        };
    }
    hideOverlay() {
        const overlay = this.overlayStack[this.overlayStack.length - 1];
        if (!overlay)
            return;
        this.clearOverlayFocusRestoreFor(overlay);
        this.retargetOverlayPreFocus(overlay);
        this.overlayStack.pop();
        if (this.focusedComponent === overlay.component) {
            const topVisible = this.getTopmostVisibleOverlay();
            this.setFocus(topVisible?.component ?? overlay.preFocus);
        }
        if (this.overlayStack.length === 0)
            this.terminal.hideCursor();
        this.requestRender();
    }
    hasOverlay() {
        return this.overlayStack.some((o) => this.isOverlayVisible(o));
    }
    isOverlayFocused() {
        return this.overlayStack.some((entry) => entry.component === this.focusedComponent && this.isOverlayVisible(entry));
    }
    isOverlayVisible(entry) {
        if (entry.hidden)
            return false;
        if (entry.options?.visible) {
            return entry.options.visible(this.terminal.columns, this.terminal.rows);
        }
        return true;
    }
    getTopmostVisibleOverlay() {
        let topmost;
        for (const overlay of this.overlayStack) {
            if (overlay.options?.nonCapturing || !this.isOverlayVisible(overlay))
                continue;
            if (!topmost || overlay.focusOrder > topmost.focusOrder) {
                topmost = overlay;
            }
        }
        return topmost;
    }
    invalidate() {
        for (const root of this.getMountedRoots())
            root.invalidate();
        for (const overlay of this.overlayStack)
            overlay.component.invalidate();
    }
    start() {
        this.stopped = false;
        this.beforeTerminalStart();
        this.terminal.start((data) => this.handleTerminalInput(data), () => this.requestRender());
        this.afterTerminalStart();
        this.terminal.hideCursor();
        if (this.terminalColorSchemeNotificationsEnabled) {
            this.terminal.write("\x1b[?2031h");
        }
        this.queryCellSize();
        this.requestRender();
    }
    addInputListener(listener) {
        this.inputListeners.add(listener);
        return () => {
            this.inputListeners.delete(listener);
        };
    }
    removeInputListener(listener) {
        this.inputListeners.delete(listener);
    }
    onTerminalColorSchemeChange(listener) {
        this.terminalColorSchemeListeners.add(listener);
        return () => {
            this.terminalColorSchemeListeners.delete(listener);
        };
    }
    setTerminalColorSchemeNotifications(enabled) {
        if (this.terminalColorSchemeNotificationsEnabled === enabled) {
            return;
        }
        this.terminalColorSchemeNotificationsEnabled = enabled;
        if (!this.stopped) {
            this.terminal.write(enabled ? "\x1b[?2031h" : "\x1b[?2031l");
        }
    }
    queryCellSize() {
        if (!getCapabilities().images) {
            return;
        }
        this.terminal.write("\x1b[16t");
    }
    stop(options = {}) {
        this.stopped = true;
        this.cancelRenderTimer();
        if (this.terminalColorSchemeNotificationsEnabled) {
            this.terminal.write("\x1b[?2031l");
        }
        this.beforeTerminalStop(options);
        this.terminal.showCursor();
        this.terminal.stop();
        this.afterTerminalStop(options);
    }
    renderNow(force = false) {
        if (force)
            this.resetRenderState();
        this.renderRequested = false;
        this.cancelRenderTimer();
        this.lastRenderAt = performance.now();
        this.doRender();
    }
    requestRender(force = false) {
        if (force) {
            this.resetRenderState();
            this.requestImmediateRender();
            return;
        }
        if (this.renderRequested)
            return;
        this.renderRequested = true;
        process.nextTick(() => this.scheduleRender());
    }
    requestImmediateRender() {
        this.cancelRenderTimer();
        this.renderRequested = true;
        if (this.immediateRenderScheduled)
            return;
        this.immediateRenderScheduled = true;
        process.nextTick(() => {
            this.immediateRenderScheduled = false;
            if (this.stopped || !this.renderRequested)
                return;
            this.cancelRenderTimer();
            this.renderRequested = false;
            this.lastRenderAt = performance.now();
            this.doRender();
        });
    }
    cancelRenderTimer() {
        if (!this.renderTimer)
            return;
        clearTimeout(this.renderTimer);
        this.renderTimer = undefined;
    }
    scheduleRender() {
        if (this.stopped || this.renderTimer || !this.renderRequested) {
            return;
        }
        const elapsed = performance.now() - this.lastRenderAt;
        const delay = Math.max(0, TuiBase.MIN_RENDER_INTERVAL_MS - elapsed);
        this.renderTimer = setTimeout(() => {
            this.renderTimer = undefined;
            if (this.stopped || !this.renderRequested) {
                return;
            }
            this.renderRequested = false;
            this.lastRenderAt = performance.now();
            this.doRender();
            if (this.renderRequested) {
                this.scheduleRender();
            }
        }, delay);
    }
    handleTerminalInput(data) {
        if (this.consumeOsc11BackgroundResponse(data)) {
            return;
        }
        if (this.consumeTerminalColorSchemeReport(data)) {
            return;
        }
        if (this.inputListeners.size > 0) {
            let current = data;
            for (const listener of this.inputListeners) {
                const result = listener(current);
                if (result?.consume) {
                    return;
                }
                if (result?.data !== undefined) {
                    current = result.data;
                }
            }
            if (current.length === 0) {
                return;
            }
            data = current;
        }
        if (this.consumeCellSizeResponse(data)) {
            return;
        }
        if (matchesKey(data, "shift+ctrl+d") && this.onDebug) {
            this.onDebug();
            return;
        }
        const focusedOverlay = this.overlayStack.find((o) => o.component === this.focusedComponent);
        if (focusedOverlay && !this.isOverlayVisible(focusedOverlay)) {
            const topVisible = this.getTopmostVisibleOverlay();
            if (topVisible) {
                this.setFocus(topVisible.component);
            }
            else {
                this.setFocusInternal({ component: focusedOverlay.preFocus, overlayFocusRestore: "preserve" });
            }
        }
        const focusIsOverlay = this.overlayStack.some((o) => o.component === this.focusedComponent);
        if (!focusIsOverlay) {
            const restoreState = this.getVisibleOverlayFocusRestore();
            if (restoreState.status === "eligible") {
                this.setFocus(restoreState.overlay.component);
            }
            else if (restoreState.status === "blocked" && restoreState.blockedBy !== this.focusedComponent) {
                if (restoreState.resume.status === "restore-overlay") {
                    this.setFocus(restoreState.overlay.component);
                }
                else {
                    this.clearOverlayFocusRestore();
                    this.setFocus(restoreState.resume.target);
                }
            }
        }
        if (this.focusedComponent?.handleInput) {
            if (isKeyRelease(data) && !this.focusedComponent.wantsKeyRelease) {
                return;
            }
            this.focusedComponent.handleInput(data);
            this.requestImmediateRender();
        }
    }
    consumeOsc11BackgroundResponse(data) {
        if (this.pendingOsc11BackgroundReplies <= 0) {
            return false;
        }
        if (!isOsc11BackgroundColorResponse(data)) {
            return false;
        }
        const rgb = parseOsc11BackgroundColor(data);
        this.pendingOsc11BackgroundReplies -= 1;
        const query = this.pendingOsc11BackgroundQueries.shift();
        if (query && !query.settled) {
            query.settled = true;
            if (query.timer) {
                clearTimeout(query.timer);
                query.timer = undefined;
            }
            query.resolve?.(rgb);
            query.resolve = undefined;
        }
        return true;
    }
    consumeTerminalColorSchemeReport(data) {
        const scheme = parseTerminalColorSchemeReport(data);
        if (!scheme) {
            return false;
        }
        for (const listener of this.terminalColorSchemeListeners) {
            listener(scheme);
        }
        return true;
    }
    consumeCellSizeResponse(data) {
        const match = data.match(/^\x1b\[6;(\d+);(\d+)t$/);
        if (!match) {
            return false;
        }
        const heightPx = parseInt(match[1], 10);
        const widthPx = parseInt(match[2], 10);
        if (heightPx <= 0 || widthPx <= 0) {
            return true;
        }
        setCellDimensions({ widthPx, heightPx });
        this.invalidate();
        this.requestRender();
        return true;
    }
    resolveOverlayLayout(options, overlayHeight, termWidth, termHeight) {
        const opt = options ?? {};
        const margin = typeof opt.margin === "number"
            ? { top: opt.margin, right: opt.margin, bottom: opt.margin, left: opt.margin }
            : (opt.margin ?? {});
        const marginTop = Math.max(0, margin.top ?? 0);
        const marginRight = Math.max(0, margin.right ?? 0);
        const marginBottom = Math.max(0, margin.bottom ?? 0);
        const marginLeft = Math.max(0, margin.left ?? 0);
        const availWidth = Math.max(1, termWidth - marginLeft - marginRight);
        const availHeight = Math.max(1, termHeight - marginTop - marginBottom);
        let width = parseSizeValue(opt.width, termWidth) ?? Math.min(80, availWidth);
        if (opt.minWidth !== undefined) {
            width = Math.max(width, opt.minWidth);
        }
        width = Math.max(1, Math.min(width, availWidth));
        let maxHeight = parseSizeValue(opt.maxHeight, termHeight);
        if (maxHeight !== undefined) {
            maxHeight = Math.max(1, Math.min(maxHeight, availHeight));
        }
        const effectiveHeight = maxHeight !== undefined ? Math.min(overlayHeight, maxHeight) : overlayHeight;
        let row;
        let col;
        if (opt.row !== undefined) {
            if (typeof opt.row === "string") {
                const match = opt.row.match(/^(\d+(?:\.\d+)?)%$/);
                if (match) {
                    const maxRow = Math.max(0, availHeight - effectiveHeight);
                    const percent = parseFloat(match[1]) / 100;
                    row = marginTop + Math.floor(maxRow * percent);
                }
                else {
                    row = this.resolveAnchorRow("center", effectiveHeight, availHeight, marginTop);
                }
            }
            else {
                row = opt.row;
            }
        }
        else {
            const anchor = opt.anchor ?? "center";
            row = this.resolveAnchorRow(anchor, effectiveHeight, availHeight, marginTop);
        }
        if (opt.col !== undefined) {
            if (typeof opt.col === "string") {
                const match = opt.col.match(/^(\d+(?:\.\d+)?)%$/);
                if (match) {
                    const maxCol = Math.max(0, availWidth - width);
                    const percent = parseFloat(match[1]) / 100;
                    col = marginLeft + Math.floor(maxCol * percent);
                }
                else {
                    col = this.resolveAnchorCol("center", width, availWidth, marginLeft);
                }
            }
            else {
                col = opt.col;
            }
        }
        else {
            const anchor = opt.anchor ?? "center";
            col = this.resolveAnchorCol(anchor, width, availWidth, marginLeft);
        }
        if (opt.offsetY !== undefined)
            row += opt.offsetY;
        if (opt.offsetX !== undefined)
            col += opt.offsetX;
        row = Math.max(marginTop, Math.min(row, termHeight - marginBottom - effectiveHeight));
        col = Math.max(marginLeft, Math.min(col, termWidth - marginRight - width));
        return { width, row, col, maxHeight };
    }
    resolveAnchorRow(anchor, height, availHeight, marginTop) {
        switch (anchor) {
            case "top-left":
            case "top-center":
            case "top-right":
                return marginTop;
            case "bottom-left":
            case "bottom-center":
            case "bottom-right":
                return marginTop + availHeight - height;
            case "left-center":
            case "center":
            case "right-center":
                return marginTop + Math.floor((availHeight - height) / 2);
        }
    }
    resolveAnchorCol(anchor, width, availWidth, marginLeft) {
        switch (anchor) {
            case "top-left":
            case "left-center":
            case "bottom-left":
                return marginLeft;
            case "top-right":
            case "right-center":
            case "bottom-right":
                return marginLeft + availWidth - width;
            case "top-center":
            case "center":
            case "bottom-center":
                return marginLeft + Math.floor((availWidth - width) / 2);
        }
    }
    compositeOverlays(lines, termWidth, termHeight) {
        if (this.overlayStack.length === 0)
            return lines;
        const result = [...lines];
        const rendered = [];
        let minLinesNeeded = result.length;
        const visibleEntries = this.overlayStack.filter((e) => this.isOverlayVisible(e));
        visibleEntries.sort((a, b) => a.focusOrder - b.focusOrder);
        for (const entry of visibleEntries) {
            const { component, options } = entry;
            const { width, maxHeight } = this.resolveOverlayLayout(options, 0, termWidth, termHeight);
            let overlayLines = component.render(width);
            if (maxHeight !== undefined && overlayLines.length > maxHeight) {
                overlayLines = overlayLines.slice(0, maxHeight);
            }
            const { row, col } = this.resolveOverlayLayout(options, overlayLines.length, termWidth, termHeight);
            rendered.push({ overlayLines, row, col, w: width });
            minLinesNeeded = Math.max(minLinesNeeded, row + overlayLines.length);
        }
        const workingHeight = Math.max(result.length, termHeight, minLinesNeeded);
        while (result.length < workingHeight) {
            result.push("");
        }
        const viewportStart = Math.max(0, workingHeight - termHeight);
        for (const { overlayLines, row, col, w } of rendered) {
            for (let i = 0; i < overlayLines.length; i++) {
                const idx = viewportStart + row + i;
                if (idx >= 0 && idx < result.length) {
                    const truncatedOverlayLine = visibleWidth(overlayLines[i]) > w ? sliceByColumn(overlayLines[i], 0, w, true) : overlayLines[i];
                    result[idx] = this.compositeLineAt(result[idx], truncatedOverlayLine, col, w, termWidth);
                }
            }
        }
        return result;
    }
    applyLineResets(lines) {
        const reset = SEGMENT_RESET;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (!isImageLine(line)) {
                lines[i] = normalizeTerminalOutput(line) + reset;
            }
        }
        return lines;
    }
    compositeLineAt(baseLine, overlayLine, startCol, overlayWidth, totalWidth) {
        return compositeTuiLine(baseLine, overlayLine, startCol, overlayWidth, totalWidth);
    }
    extractCursorPosition(lines, height) {
        const viewportTop = Math.max(0, lines.length - height);
        for (let row = lines.length - 1; row >= viewportTop; row--) {
            const line = lines[row];
            const markerIndex = line.indexOf(CURSOR_MARKER);
            if (markerIndex !== -1) {
                const beforeMarker = line.slice(0, markerIndex);
                const col = visibleWidth(beforeMarker);
                lines[row] = line.slice(0, markerIndex) + line.slice(markerIndex + CURSOR_MARKER.length);
                return { row, col };
            }
        }
        return null;
    }
    queryTerminalBackgroundColor({ timeoutMs }) {
        return new Promise((resolve) => {
            const query = {
                settled: false,
                resolve,
                timer: undefined,
            };
            query.timer = setTimeout(() => {
                if (query.settled) {
                    return;
                }
                query.settled = true;
                query.timer = undefined;
                query.resolve?.(undefined);
                query.resolve = undefined;
            }, timeoutMs);
            this.pendingOsc11BackgroundQueries.push(query);
            this.pendingOsc11BackgroundReplies += 1;
            this.terminal.write("\x1b]11;?\x07");
        });
    }
    queryTerminalColorScheme({ timeoutMs }) {
        return new Promise((resolve) => {
            let settled = false;
            let timer;
            let unsubscribe = () => { };
            const settle = (scheme) => {
                if (settled)
                    return;
                settled = true;
                if (timer) {
                    clearTimeout(timer);
                    timer = undefined;
                }
                unsubscribe();
                resolve(scheme);
            };
            unsubscribe = this.onTerminalColorSchemeChange(settle);
            timer = setTimeout(() => settle(undefined), timeoutMs);
            this.terminal.write("\x1b[?996n");
        });
    }
}
//# sourceMappingURL=tui.js.map