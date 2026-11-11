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
export declare const FEED_SOCKET: string;
/**
 * Whether a compressor is running, and whether it is in the agent's request path.
 *
 * A runs counter only moves when a request passes *through* a compressor, so a
 * frozen counter means one of three different things — compressor gone, idle, or
 * bypassed — and the panel cannot tell which from the counter. This block is the
 * daemon's live probe of the compressor itself.
 */
export interface FeedCompressor {
    running: boolean;
    ports: string[];
    upstreams: string[];
    /** Ports this compressor forwards *to* — the lane proxy's shape. */
    upstream_ports?: string[];
    lane: string | null;
    lane_port: string | null;
    /**
     * True when the compressor fronts the agent's lane: either it listens on the
     * lane's port, or it forwards to it (slimtoken-lane.service :11598 → the
     * local lane :11599). Only the instance fronting the lane reports stages.
     */
    in_path: boolean;
    /** Rewriting stages the fronting instance runs with; empty = pass-through. */
    stages?: string[];
}
export interface FeedCompression {
    runs: number;
    tokens_in: number;
    tokens_out: number;
    tokens_saved: number;
    ratio_pct: number;
    /** Epoch seconds. The ledger's own last-run time — not the file's mtime. */
    last_run_ts: number;
    errors?: number;
    source?: string;
    /** Age at the moment the daemon built the snapshot; recompute, don't trust. */
    age_s?: number;
    live?: boolean;
    compressor?: FeedCompressor | null;
}
export interface FeedRouting {
    route: string;
    model: string;
    base_url: string;
    router_mode: string;
    toolproxy_available?: boolean;
    recorded_at?: number;
    derived_from?: string;
}
export interface FeedTask {
    id: string;
    title: string;
    state: string;
    trigger?: string;
    next_run_at?: string | null;
}
export interface FeedScheduling {
    task_count: number;
    by_state: Record<string, number>;
    tasks: FeedTask[];
}
export interface FeedMemory {
    tiers: {
        hot: number;
        warm: number;
        cold: number;
    };
    last_write_ts: number;
    last_write_age_s: number;
}
export interface FeedState {
    /** True while the socket is open. Data can still be present after a drop. */
    connected: boolean;
    compression: FeedCompression | null;
    routing: FeedRouting | null;
    scheduling: FeedScheduling | null;
    memory: FeedMemory | null;
    /** When the last line arrived, for diagnostics only — not a staleness test. */
    lastMessageAt: number | null;
}
/**
 * Fold one decoded NDJSON object into the state.
 *
 * Pure, so the merge rules are testable without a socket. A `snapshot` replaces
 * every section; an `event` replaces only the section it names. Unknown types
 * are ignored — a newer daemon may emit sections this build doesn't know yet,
 * and that must not blank the panel.
 */
export declare function mergeFeedMessage(prev: FeedState, msg: unknown): FeedState;
/**
 * Split a buffer into complete NDJSON lines.
 *
 * Returns the parsed objects plus the trailing partial line, which must be
 * carried into the next chunk — a socket read can split a JSON line anywhere.
 * Unparseable complete lines are skipped, not thrown.
 */
export declare function parseFeedBuffer(buf: string): {
    messages: unknown[];
    rest: string;
};
/** Latest known feed state. Starts the connection on first call; never blocks. */
export declare function feedState(): FeedState;
/** Tear the client down (tests, and shutdown). Safe to call repeatedly. */
export declare function stopFeed(): void;
/**
 * Age of a feed timestamp in milliseconds, or null when unusable.
 *
 * The daemon writes epoch seconds (`last_run_ts`) and ISO strings in some
 * ledgers, so both are accepted. The caller computes age at RENDER time: the
 * snapshot's own `age_s`/`live` fields describe the instant the daemon built
 * it, which is exactly the figure that goes stale.
 */
export declare function feedAgeMs(ts: number | string | null | undefined, now?: number): number | null;
//# sourceMappingURL=event-feed-client.d.ts.map