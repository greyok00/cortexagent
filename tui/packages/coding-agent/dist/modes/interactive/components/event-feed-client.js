/**
 * Event-feed client — the TUI's live view of the running stack.
 *
 * The daemon side (`lib/event_feed.py`) serves NDJSON over a Unix socket: one
 * `snapshot` line on connect, then change-only `event` lines. Until now nothing
 * consumed it, so every panel re-read a file on disk — and a file stops moving
 * the moment its writer does, while the panel keeps rendering the last numbers
 * as if they were current. That is the "static numbers" the owner saw
 * (2026-09-27): 9,516 compression runs shown as a live figure when the writer
 * behind them had been deleted five days earlier.
 *
 * Design rules, all in service of never lying and never blocking the UI:
 *   - `feedState()` is synchronous and returns the last known state. It never
 *     reads the socket inline, so a slow or absent daemon cannot stall a render.
 *   - Connection is lazy (first call starts it), background, and self-healing
 *     with capped exponential backoff.
 *   - Nothing here throws: a missing socket, a malformed line, or a daemon
 *     restart degrades to "not connected" and the caller falls back to files.
 *   - The socket and the reconnect timer are `unref`'d so the agent can exit
 *     normally without waiting on this client.
 */
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
// 2026-10-14 (local port): path follows CORTEXAGENT_STATE_DIR (set by the launcher);
// the default stays the local agent's own dir.
export const FEED_SOCKET = path.join(process.env.CORTEXAGENT_STATE_DIR ?? path.join(os.homedir(), ".cortex-agent"), "state", "event_feed.sock");
function emptyState() {
    return {
        connected: false,
        compression: null,
        routing: null,
        scheduling: null,
        memory: null,
        lastMessageAt: null,
    };
}
/**
 * Fold one decoded NDJSON object into the state.
 *
 * Pure, so the merge rules are testable without a socket. A `snapshot` replaces
 * every section; an `event` replaces only the section it names. Unknown types
 * are ignored — a newer daemon may emit sections this build doesn't know yet,
 * and that must not blank the panel.
 */
export function mergeFeedMessage(prev, msg) {
    if (!msg || typeof msg !== "object")
        return prev;
    const m = msg;
    const data = (m.data && typeof m.data === "object" ? m.data : {});
    if (m.type === "snapshot") {
        return {
            ...prev,
            compression: data.compression ?? prev.compression,
            routing: data.routing ?? prev.routing,
            scheduling: data.scheduling ?? prev.scheduling,
            memory: data.memory ?? prev.memory,
        };
    }
    if (m.type !== "event")
        return prev;
    switch (m.event_type) {
        case "compression":
            return { ...prev, compression: data };
        case "routing":
            return { ...prev, routing: data };
        case "scheduling":
            return { ...prev, scheduling: data };
        case "memory":
            return { ...prev, memory: data };
        default:
            return prev;
    }
}
/**
 * Split a buffer into complete NDJSON lines.
 *
 * Returns the parsed objects plus the trailing partial line, which must be
 * carried into the next chunk — a socket read can split a JSON line anywhere.
 * Unparseable complete lines are skipped, not thrown.
 */
export function parseFeedBuffer(buf) {
    const messages = [];
    const lines = buf.split("\n");
    const rest = lines.pop() ?? "";
    for (const line of lines) {
        const t = line.trim();
        if (!t)
            continue;
        try {
            messages.push(JSON.parse(t));
        }
        catch {
            /* partial or corrupt line — drop it, keep the stream */
        }
    }
    return { messages, rest };
}
const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
let state = emptyState();
let socket = null;
let buffer = "";
let started = false;
let backoffMs = RECONNECT_MIN_MS;
let reconnectTimer = null;
function scheduleReconnect() {
    if (reconnectTimer)
        return;
    const delay = backoffMs;
    backoffMs = Math.min(RECONNECT_MAX_MS, backoffMs * 2);
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
    }, delay);
    // Never hold the process open just to retry a socket.
    reconnectTimer.unref?.();
}
function connect() {
    if (socket)
        return;
    try {
        socket = net.createConnection(FEED_SOCKET);
    }
    catch {
        socket = null;
        scheduleReconnect();
        return;
    }
    const s = socket;
    s.setEncoding("utf8");
    s.on("connect", () => {
        backoffMs = RECONNECT_MIN_MS;
        state = { ...state, connected: true };
    });
    s.on("data", (chunk) => {
        buffer += chunk;
        const { messages, rest } = parseFeedBuffer(buffer);
        buffer = rest;
        for (const msg of messages)
            state = mergeFeedMessage(state, msg);
        if (messages.length)
            state = { ...state, lastMessageAt: Date.now() };
    });
    // An error always precedes a close on a socket; handle the retry there so
    // the two paths can't schedule two reconnects.
    s.on("error", () => { });
    s.on("close", () => {
        socket = null;
        buffer = "";
        state = { ...state, connected: false };
        scheduleReconnect();
    });
    s.unref?.();
}
/** Latest known feed state. Starts the connection on first call; never blocks. */
export function feedState() {
    if (!started) {
        started = true;
        connect();
    }
    return state;
}
/** Tear the client down (tests, and shutdown). Safe to call repeatedly. */
export function stopFeed() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (socket) {
        socket.removeAllListeners();
        try {
            socket.destroy();
        }
        catch {
            /* already gone */
        }
        socket = null;
    }
    buffer = "";
    state = emptyState();
    started = false;
    backoffMs = RECONNECT_MIN_MS;
}
/**
 * Age of a feed timestamp in milliseconds, or null when unusable.
 *
 * The daemon writes epoch seconds (`last_run_ts`) and ISO strings in some
 * ledgers, so both are accepted. The caller computes age at RENDER time: the
 * snapshot's own `age_s`/`live` fields describe the instant the daemon built
 * it, which is exactly the figure that goes stale.
 */
export function feedAgeMs(ts, now = Date.now()) {
    if (ts === null || ts === undefined)
        return null;
    let ms;
    if (typeof ts === "number") {
        if (!Number.isFinite(ts) || ts <= 0)
            return null;
        // Epoch seconds (1.7e9) vs milliseconds (1.7e12) — anything below the
        // year-2001-in-ms mark is seconds.
        ms = ts < 1e11 ? ts * 1000 : ts;
    }
    else {
        const parsed = Date.parse(ts);
        if (Number.isNaN(parsed))
            return null;
        ms = parsed;
    }
    return Math.max(0, now - ms);
}
//# sourceMappingURL=event-feed-client.js.map