import * as fs from "node:fs";
import { createRequire } from "node:module";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { setKittyProtocolActive } from "./keys.js";
import { isNativeModifierPressed } from "./native-modifiers.js";
import { StdinBuffer } from "./stdin-buffer.js";
const cjsRequire = createRequire(import.meta.url);
const TERMINAL_PROGRESS_KEEPALIVE_MS = 1000;
const TERMINAL_PROGRESS_ACTIVE_SEQUENCE = "\x1b]9;4;3\x07";
const TERMINAL_PROGRESS_CLEAR_SEQUENCE = "\x1b]9;4;0\x07";
const NATIVE_SHIFT_ENTER_SEQUENCE = "\x1b[13;2u";
const DESIRED_KITTY_KEYBOARD_PROTOCOL_FLAGS = 7;
const KEYBOARD_PROTOCOL_RESPONSE_FRAGMENT_TIMEOUT_MS = 150;
const KITTY_KEYBOARD_PROTOCOL_QUERY = `\x1b[>${DESIRED_KITTY_KEYBOARD_PROTOCOL_FLAGS}u\x1b[?u\x1b[c`;
export function parseKeyboardProtocolNegotiationSequence(sequence) {
    const kittyFlags = sequence.match(/^\x1b\[\?(\d+)u$/);
    if (kittyFlags) {
        return { type: "kitty-flags", flags: Number.parseInt(kittyFlags[1], 10) };
    }
    if (/^\x1b\[\?[\d;]*c$/.test(sequence)) {
        return { type: "device-attributes" };
    }
    return undefined;
}
function isKeyboardProtocolNegotiationSequencePrefix(sequence) {
    return sequence === "\x1b[" || /^\x1b\[\?[\d;]*$/.test(sequence);
}
export function isAppleTerminalSession() {
    return process.platform === "darwin" && process.env.TERM_PROGRAM === "Apple_Terminal";
}
export function normalizeNativeShiftEnterInput(data, shouldDetectNativeShiftEnter, isShiftPressed) {
    if (shouldDetectNativeShiftEnter && data === "\r" && isShiftPressed)
        return NATIVE_SHIFT_ENTER_SEQUENCE;
    return data;
}
export function normalizeAppleTerminalInput(data, isAppleTerminal, isShiftPressed) {
    return normalizeNativeShiftEnterInput(data, isAppleTerminal, isShiftPressed);
}
const DEFAULT_ESCAPE_TIMEOUT_MS = 10;
const DEFAULT_SSH_ESCAPE_TIMEOUT_MS = 100;
export function resolveEscapeTimeoutMs(env = process.env) {
    const configured = Number(env.CORTEXENGINE_TUI_ESC_TIMEOUT);
    if (Number.isFinite(configured) && configured > 0) {
        return configured;
    }
    if (env.SSH_CONNECTION || env.SSH_TTY) {
        return DEFAULT_SSH_ESCAPE_TIMEOUT_MS;
    }
    return DEFAULT_ESCAPE_TIMEOUT_MS;
}
export class ProcessTerminal {
    wasRaw = false;
    inputHandler;
    resizeHandler;
    _kittyProtocolActive = false;
    _modifyOtherKeysActive = false;
    keyboardProtocolPushed = false;
    keyboardProtocolNegotiationBuffer = "";
    keyboardProtocolBufferFlushTimer;
    stdinBuffer;
    stdinDataHandler;
    progressInterval;
    writeLogPath = (() => {
        const env = process.env.CORTEXENGINE_TUI_WRITE_LOG || "";
        if (!env)
            return "";
        try {
            if (fs.statSync(env).isDirectory()) {
                const now = new Date();
                const ts = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}-${String(now.getMinutes()).padStart(2, "0")}-${String(now.getSeconds()).padStart(2, "0")}`;
                return path.join(env, `tui-${ts}-${process.pid}.log`);
            }
        }
        catch {
            // Not an existing directory - use as-is (file path)
        }
        return env;
    })();
    get kittyProtocolActive() {
        return this._kittyProtocolActive;
    }
    get modifyOtherKeysActive() {
        return this._modifyOtherKeysActive;
    }
    start(onInput, onResize) {
        this.inputHandler = onInput;
        this.resizeHandler = onResize;
        this.wasRaw = process.stdin.isRaw || false;
        if (process.stdin.setRawMode) {
            process.stdin.setRawMode(true);
        }
        process.stdin.setEncoding("utf8");
        process.stdin.resume();
        process.stdout.write("\x1b[?2004h");
        process.stdout.on("resize", this.resizeHandler);
        if (process.platform !== "win32") {
            process.kill(process.pid, "SIGWINCH");
        }
        this.enableWindowsVTInput();
        this.queryAndEnableKittyProtocol();
    }
    setupStdinBuffer() {
        this.stdinBuffer = new StdinBuffer({ escapeTimeout: resolveEscapeTimeoutMs() });
        this.stdinBuffer.on("data", (sequence) => {
            const negotiationSequence = this.readKeyboardProtocolNegotiationSequence(sequence);
            if (negotiationSequence === "pending") {
                this.scheduleKeyboardProtocolNegotiationBufferFlush();
                return;
            }
            if (this.handleKeyboardProtocolNegotiationSequence(negotiationSequence)) {
                return;
            }
            this.forwardInputSequence(sequence);
        });
        this.stdinBuffer.on("paste", (content) => {
            if (this.inputHandler) {
                this.inputHandler(`\x1b[200~${content}\x1b[201~`);
            }
        });
        this.stdinDataHandler = (data) => {
            this.stdinBuffer.process(data);
        };
    }
    queryAndEnableKittyProtocol() {
        this.setupStdinBuffer();
        process.stdin.on("data", this.stdinDataHandler);
        this.keyboardProtocolPushed = true;
        this.clearKeyboardProtocolNegotiationBuffer();
        process.stdout.write(KITTY_KEYBOARD_PROTOCOL_QUERY);
    }
    handleKeyboardProtocolNegotiationSequence(negotiationSequence) {
        if (!negotiationSequence)
            return false;
        this.clearKeyboardProtocolNegotiationBuffer();
        if (negotiationSequence.type === "kitty-flags") {
            if (negotiationSequence.flags !== 0) {
                this.disableModifyOtherKeys();
                if (!this._kittyProtocolActive) {
                    this._kittyProtocolActive = true;
                    setKittyProtocolActive(true);
                }
            }
            else {
                this.enableModifyOtherKeys();
            }
            return true;
        }
        if (!this._kittyProtocolActive) {
            this.enableModifyOtherKeys();
        }
        return true;
    }
    readKeyboardProtocolNegotiationSequence(sequence) {
        if (this.keyboardProtocolNegotiationBuffer) {
            const bufferedSequence = this.keyboardProtocolNegotiationBuffer + sequence;
            const negotiationSequence = parseKeyboardProtocolNegotiationSequence(bufferedSequence);
            if (negotiationSequence) {
                this.clearKeyboardProtocolNegotiationBuffer();
                return negotiationSequence;
            }
            if (isKeyboardProtocolNegotiationSequencePrefix(bufferedSequence)) {
                this.setKeyboardProtocolNegotiationBuffer(bufferedSequence);
                return "pending";
            }
            this.flushKeyboardProtocolNegotiationBufferAsInput();
        }
        const negotiationSequence = parseKeyboardProtocolNegotiationSequence(sequence);
        if (negotiationSequence)
            return negotiationSequence;
        if (isKeyboardProtocolNegotiationSequencePrefix(sequence)) {
            this.setKeyboardProtocolNegotiationBuffer(sequence);
            return "pending";
        }
        return undefined;
    }
    setKeyboardProtocolNegotiationBuffer(sequence) {
        this.clearKeyboardProtocolNegotiationBufferFlushTimer();
        this.keyboardProtocolNegotiationBuffer = sequence;
    }
    clearKeyboardProtocolNegotiationBuffer() {
        this.clearKeyboardProtocolNegotiationBufferFlushTimer();
        this.keyboardProtocolNegotiationBuffer = "";
    }
    flushKeyboardProtocolNegotiationBufferAsInput() {
        if (!this.keyboardProtocolNegotiationBuffer)
            return;
        const sequence = this.keyboardProtocolNegotiationBuffer;
        this.clearKeyboardProtocolNegotiationBuffer();
        this.forwardInputSequence(sequence);
    }
    scheduleKeyboardProtocolNegotiationBufferFlush() {
        if (!this.keyboardProtocolNegotiationBuffer || this.keyboardProtocolBufferFlushTimer)
            return;
        this.keyboardProtocolBufferFlushTimer = setTimeout(() => {
            this.keyboardProtocolBufferFlushTimer = undefined;
            this.flushKeyboardProtocolNegotiationBufferAsInput();
        }, KEYBOARD_PROTOCOL_RESPONSE_FRAGMENT_TIMEOUT_MS);
    }
    clearKeyboardProtocolNegotiationBufferFlushTimer() {
        if (!this.keyboardProtocolBufferFlushTimer)
            return;
        clearTimeout(this.keyboardProtocolBufferFlushTimer);
        this.keyboardProtocolBufferFlushTimer = undefined;
    }
    forwardInputSequence(sequence) {
        if (!this.inputHandler)
            return;
        const shouldDetectNativeShiftEnter = sequence === "\r" && (isAppleTerminalSession() || process.platform === "win32");
        const input = normalizeNativeShiftEnterInput(sequence, shouldDetectNativeShiftEnter, shouldDetectNativeShiftEnter && isNativeModifierPressed("shift"));
        this.inputHandler(input);
    }
    enableModifyOtherKeys() {
        if (this._kittyProtocolActive || this._modifyOtherKeysActive)
            return;
        process.stdout.write("\x1b[>4;2m");
        this._modifyOtherKeysActive = true;
    }
    disableModifyOtherKeys() {
        if (!this._modifyOtherKeysActive)
            return;
        process.stdout.write("\x1b[>4;0m");
        this._modifyOtherKeysActive = false;
    }
    enableWindowsVTInput() {
        if (process.platform !== "win32")
            return;
        try {
            const arch = process.arch;
            if (arch !== "x64" && arch !== "arm64")
                return;
            const moduleDir = path.dirname(fileURLToPath(import.meta.url));
            const nativePath = path.join("native", "win32", "prebuilds", `win32-${arch}`, "win32-console-mode.node");
            const candidates = [
                path.join(moduleDir, "..", nativePath),
                path.join(moduleDir, nativePath),
                path.join(path.dirname(process.execPath), nativePath),
            ];
            for (const modulePath of candidates) {
                try {
                    const helper = cjsRequire(modulePath);
                    helper.enableVirtualTerminalInput?.();
                    return;
                }
                catch {
                    // Try the next possible packaging location.
                }
            }
        }
        catch {
            // Native helper not available — Shift+Tab won't be distinguishable from Tab.
        }
    }
    async drainInput(maxMs = 1000, idleMs = 50) {
        const shouldDisableKittyProtocol = this.keyboardProtocolPushed || this._kittyProtocolActive;
        this.clearKeyboardProtocolNegotiationBuffer();
        if (shouldDisableKittyProtocol) {
            process.stdout.write("\x1b[<u");
            this.keyboardProtocolPushed = false;
            this._kittyProtocolActive = false;
            setKittyProtocolActive(false);
        }
        this.disableModifyOtherKeys();
        const previousHandler = this.inputHandler;
        this.inputHandler = undefined;
        let lastDataTime = Date.now();
        const onData = () => {
            lastDataTime = Date.now();
        };
        process.stdin.on("data", onData);
        const endTime = Date.now() + maxMs;
        try {
            while (true) {
                const now = Date.now();
                const timeLeft = endTime - now;
                if (timeLeft <= 0)
                    break;
                if (now - lastDataTime >= idleMs)
                    break;
                await new Promise((resolve) => setTimeout(resolve, Math.min(idleMs, timeLeft)));
            }
        }
        finally {
            process.stdin.removeListener("data", onData);
            this.inputHandler = previousHandler;
        }
    }
    stop() {
        if (this.clearProgressInterval()) {
            process.stdout.write(TERMINAL_PROGRESS_CLEAR_SEQUENCE);
        }
        process.stdout.write("\x1b[?2004l");
        const shouldDisableKittyProtocol = this.keyboardProtocolPushed || this._kittyProtocolActive;
        this.clearKeyboardProtocolNegotiationBuffer();
        if (shouldDisableKittyProtocol) {
            process.stdout.write("\x1b[<u");
            this.keyboardProtocolPushed = false;
            this._kittyProtocolActive = false;
            setKittyProtocolActive(false);
        }
        this.disableModifyOtherKeys();
        if (this.stdinBuffer) {
            this.stdinBuffer.destroy();
            this.stdinBuffer = undefined;
        }
        if (this.stdinDataHandler) {
            process.stdin.removeListener("data", this.stdinDataHandler);
            this.stdinDataHandler = undefined;
        }
        this.inputHandler = undefined;
        if (this.resizeHandler) {
            process.stdout.removeListener("resize", this.resizeHandler);
            this.resizeHandler = undefined;
        }
        process.stdin.pause();
        if (process.stdin.setRawMode) {
            process.stdin.setRawMode(this.wasRaw);
        }
    }
    write(data) {
        process.stdout.write(data);
        if (this.writeLogPath) {
            try {
                fs.appendFileSync(this.writeLogPath, data, { encoding: "utf8" });
            }
            catch {
                // Ignore logging errors
            }
        }
    }
    get columns() {
        return process.stdout.columns || Number(process.env.COLUMNS) || 80;
    }
    get rows() {
        return process.stdout.rows || Number(process.env.LINES) || 24;
    }
    moveBy(lines) {
        if (lines > 0) {
            process.stdout.write(`\x1b[${lines}B`);
        }
        else if (lines < 0) {
            process.stdout.write(`\x1b[${-lines}A`);
        }
        // lines === 0: no movement
    }
    hideCursor() {
        process.stdout.write("\x1b[?25l");
    }
    showCursor() {
        process.stdout.write("\x1b[?25h");
    }
    clearLine() {
        process.stdout.write("\x1b[K");
    }
    clearFromCursor() {
        process.stdout.write("\x1b[J");
    }
    clearScreen() {
        process.stdout.write("\x1b[2J\x1b[H");
    }
    setTitle(title) {
        process.stdout.write(`\x1b]0;${title}\x07`);
    }
    setProgress(active) {
        if (active) {
            process.stdout.write(TERMINAL_PROGRESS_ACTIVE_SEQUENCE);
            if (!this.progressInterval) {
                this.progressInterval = setInterval(() => {
                    process.stdout.write(TERMINAL_PROGRESS_ACTIVE_SEQUENCE);
                }, TERMINAL_PROGRESS_KEEPALIVE_MS);
            }
        }
        else {
            this.clearProgressInterval();
            process.stdout.write(TERMINAL_PROGRESS_CLEAR_SEQUENCE);
        }
    }
    clearProgressInterval() {
        if (!this.progressInterval)
            return false;
        clearInterval(this.progressInterval);
        this.progressInterval = undefined;
        return true;
    }
}
//# sourceMappingURL=terminal.js.map