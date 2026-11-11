// 2026-10-26 (owner order: "IT MUST KEEP WORKING IF THERE'S A SCREEN GRAB").
//
// Root cause of the 2026-10-25 11-hour freeze: on POSIX, Node writes to a
// TTY *synchronously*. A dead X client (ImageMagick `import` stuck on a
// destroyed window) holds XGrabServer, the terminal emulator stops reading
// its pty, the pty buffer fills, and the next `process.stdout.write()` parks
// the whole event loop inside write(2) — model requests, timers and tool
// calls all stop, even though the model server is healthy.
//
// Fix: never let this process write to the pty directly. Each channel gets a
// tiny relay child that owns the TTY write (`process.stdin.pipe(stdout)`), so
// the blocking write happens in *that* process. Our write() only enqueues
// into the relay's stdin pipe, which is asynchronous. stdout/stderr objects
// are otherwise untouched (isTTY, columns, rows, resize events all keep
// working because fd 1/2 still point at the terminal).
//
// Backlog is bounded: if the display is grabbed for a long time the pipe
// would otherwise buffer every frame in memory. Past the cap, frames are
// dropped and a full repaint is requested once the relay drains.
import { spawn } from "node:child_process";
import * as fs from "node:fs";
const RELAY_SOURCE = "process.stdin.pipe(process.stdout);";
/** Per-channel queue limit. ~8 MiB is many minutes of frames, small enough to be harmless. */
const MAX_BACKLOG_BYTES = 8 * 1024 * 1024;
let installed = false;
let recoveryHandler;
/** Register the TUI hook used after dropped frames (full repaint). */
export function setDisplayRelayRecoveryHandler(handler) {
    recoveryHandler = handler;
}
export function isDisplayRelayActive() {
    return installed;
}
function writeDirect(channel, text) {
    try {
        fs.writeSync(channel.fd, text);
    }
    catch {
        // Display is gone; nothing left to do.
    }
}
function restoreChannel(channel) {
    if (channel.broken)
        return;
    channel.broken = true;
    // Deliberately do NOT reinstall the original writer. If the relay died, the
    // terminal may be the thing that stalled, and a direct write to a full pty
    // blocks the event loop forever — the exact failure this module exists to
    // prevent. Losing output is recoverable (restart repaints); freezing is not.
    try {
        channel.child?.stdin?.end();
    }
    catch {
        // ignore
    }
}
function installChannel(fd) {
    const stream = fd === 1 ? process.stdout : process.stderr;
    const original = stream.write.bind(stream);
    const channel = {
        fd,
        stream,
        original,
        child: undefined,
        sink: undefined,
        overflowed: false,
        broken: false,
        pending: new Map(),
        nextId: 0,
    };
    const stdio = ["pipe", fd, 2];
    try {
        channel.child = spawn(process.execPath, ["-e", RELAY_SOURCE], {
            stdio,
            detached: false,
        });
    }
    catch {
        return; // No relay possible — keep the original (blocking) writer.
    }
    const child = channel.child;
    if (!child.stdin) {
        return;
    }
    channel.sink = child.stdin;
    // The relay is infrastructure, not a reason to stay alive: without unref
    // the live child handle (and its stdin pipe) would keep the event loop
    // open forever — cortexagent would never exit after quit.
    child.unref();
    child.stdin.unref?.();
    // The relay must not outlive us, and must not hold the terminal open.
    child.on("error", () => restoreChannel(channel));
    child.on("exit", () => restoreChannel(channel));
    child.stdin.on("drain", () => {
        // Mirror the event on the real stream for any code awaiting it.
        try {
            stream.emit("drain");
        }
        catch {
            // ignore
        }
        if (channel.overflowed) {
            channel.overflowed = false;
            try {
                recoveryHandler?.();
            }
            catch {
                // A broken repaint must never throw into the writer.
            }
        }
    });
    const relayed = ((chunk, encodingOrCallback, callback) => {
        if (channel.broken || !channel.sink || channel.sink.destroyed) {
            // Never fall back to the blocking tty writer (see restoreChannel).
            const done = typeof encodingOrCallback === "function"
                ? encodingOrCallback
                : typeof callback === "function"
                    ? callback
                    : undefined;
            if (done)
                queueMicrotask(() => done(null));
            return true;
        }
        const text = typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8");
        const queued = channel.sink.writableLength ?? 0;
        if (channel.overflowed || queued > MAX_BACKLOG_BYTES) {
            // Display stalled past the cap: drop this frame. recoveryHandler()
            // repaints from scratch once the relay catches up, so dropped
            // diffs cannot leave a half-drawn screen behind.
            channel.overflowed = true;
            const done = typeof encodingOrCallback === "function"
                ? encodingOrCallback
                : typeof callback === "function"
                    ? callback
                    : undefined;
            if (done)
                queueMicrotask(() => done(null));
            return true;
        }
        const id = channel.nextId++;
        channel.pending.set(id, text);
        const onWritten = (error) => {
            channel.pending.delete(id);
            if (typeof encodingOrCallback === "function") {
                encodingOrCallback(error);
            }
            else if (typeof callback === "function") {
                callback(error);
            }
        };
        try {
            if (typeof encodingOrCallback === "string") {
                channel.sink.write(text, encodingOrCallback, onWritten);
            }
            else {
                channel.sink.write(text, onWritten);
            }
        }
        catch {
            channel.pending.delete(id);
            writeDirect(channel, text);
        }
        return true;
    });
    stream.write = relayed;
    // Hard exits (process.exit) would truncate bytes still queued in JS.
    // Flush them straight to the terminal; the relay's own already-transmitted
    // bytes precede them on the pipe in every non-frozen case.
    process.on("exit", () => {
        if (channel.broken || channel.pending.size === 0)
            return;
        let tail = "";
        for (const text of channel.pending.values())
            tail += text;
        channel.pending.clear();
        writeDirect(channel, tail);
    });
}
/**
 * Route terminal output through relay processes so a grabbed X server (or any
 * terminal that stops reading) can never block this process's event loop.
 */
export function installDisplayRelay() {
    if (installed)
        return;
    if (process.env.CORTEXENGINE_DISPLAY_RELAY === "0")
        return;
    if (!process.stdout.isTTY)
        return;
    if (process.platform === "win32")
        return;
    installed = true;
    installChannel(1);
    if (process.stderr.isTTY)
        installChannel(2);
}
//# sourceMappingURL=display-relay.js.map