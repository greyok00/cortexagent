import { type Component } from "@cortexagent/tui";
import { type FeedCompression, type FeedCompressor, type FeedState } from "./event-feed-client.ts";
interface SchedulerTask {
    id?: string;
    title?: string;
    state?: string;
    status?: string;
    next_run_at?: string | null;
}
/**
 * The scheduler's task list as the feed reports it.
 *
 * `null` means "the feed isn't serving" — an empty array is a real answer and
 * must not be confused with it, or a live feed with zero tasks would fall back
 * to the file and resurrect stale rows.
 */
declare function schedulerTasksFromFeed(s: FeedState["scheduling"]): SchedulerTask[] | null;
interface CompressionStats {
    runs: number;
    tokensIn: number;
    tokensOut: number;
    saved: number;
    ratio: number;
    ok: boolean;
    /** Milliseconds since the numbers were written, or null when unknown. */
    ageMs: number | null;
    /** Which file the numbers came from. */
    source: string | null;
    /** True when the numbers are recent enough to describe current traffic. */
    live: boolean;
    /** Live state of the compressor itself, when the feed reports it. */
    compressor?: FeedCompressor | null;
}
/**
 * The feed's compression section as panel stats.
 *
 * Age is recomputed from the ledger's own `last_run_ts` rather than the feed's
 * `age_s`/`live` fields: those were true when the daemon built the snapshot, and
 * a snapshot is sent only once per connection, so trusting them would label a
 * five-day-old figure as current — the exact fault being fixed here.
 */
declare function compressionFromFeed(c: FeedCompression | null): CompressionStats | null;
/**
 * How old the numbers are: the ledger's own `last_run_ts`, and only if that is
 * missing, the file's mtime.
 *
 * The mtime was the old answer and it lied by design — `token_tracker.json` is
 * rewritten on every agent restart, so its mtime is minutes old while the runs
 * it totals are five days old. `last_run_ts` is the writer's own word.
 */
declare function ledgerAgeMs(t: {
    last_run_ts?: number | string;
} | null, mtimeMs: number): number | null;
/**
 * What the footer's ⚡ capsule should say — the panel's number, or an honest
 * "off".
 *
 * The footer used to read `~/.cortex-agent/minify_stats.json` on its own, a
 * different writer from the panel's, so one screen showed two compression
 * figures at once ("0.0%" beside "75.5%", owner report 2026-09-27). Both now
 * come from this one reader, and neither prints a percentage that no live
 * traffic backs — a figure that cannot move is the stub the owner rejected.
 * `null` means there is nothing to claim, so the capsule is omitted rather
 * than replaced by a guess.
 */
export declare function compressionCapsuleText(s: {
    ok: boolean;
    live: boolean;
    ratio: number;
}): {
    text: string;
    live: boolean;
} | null;
/** The capsule for whatever the ledgers (or the feed) say right now. */
export declare function compressionCapsule(): {
    text: string;
    live: boolean;
} | null;
/** "7h ago" / "12m ago" — short enough for the panel's second line. */
declare function formatAge(ms: number): string;
/**
 * The same idea, but past a day it names the date instead of counting.
 *
 * "5d ago" invites the reading that this is a slow trickle of recent work. A
 * total that stopped five days ago should look stopped, so say when it stopped.
 */
declare function formatLedgerAge(ms: number, now?: number): string;
/**
 * Why a frozen counter is frozen.
 *
 * Four different situations produce the same non-moving number, and naming
 * which one it is is the difference between a status panel and a stub: the
 * compressor is gone, it is up but nothing is routed through it, it is up and
 * idle on a lane the agent does not use (the live 2026-09-27 case — traffic goes
 * to engine-server :11599 while slimtoken fronts ollama :11600), or it is in the
 * lane with every rewriting stage switched off, which is a pass-through and not
 * a fault (owner's staged ramp, 2026-09-27: the lane proxy starts gutted so it
 * cannot mangle data; a "not compressing" panel is then the truth, not a
 * breakage). With no probe at all the honest answer is that we don't know, not
 * that slimtoken is down: the panel used to call a missing probe "slimtoken not
 * running" while slimtoken was in fact running, which is a worse lie than a
 * stale number.
 */
declare function compressionReason(c: FeedCompressor | null | undefined): string;
/**
 * The two ⚡ Compression lines.
 *
 * Line 1 is a claim about now, so it carries a percentage only while traffic is
 * actually being compressed. A total frozen five days ago — 9,516 runs from a
 * proxy deleted 2026-09-22 — rendered as "76% saved" is the stub the owner
 * rejected (2026-09-27: "it's just stub text that never updates"): a ledger's
 * numbers are evidence of past runs, not status, and they belong on line 1 only
 * while they move. When they don't, line 1 says what is true of the compressor
 * now and line 2 carries the reason, sized to the panel.
 */
declare function compressionStatusLines(s: CompressionStats, spinner: string, changed: boolean, contentW?: number): {
    l1: string;
    l2: string;
};
/**
 * The 📅 Tasks rows: the scheduler's own tasks, most live first.
 *
 * These rows used to come from the dispatcher queue — a different subsystem,
 * and an empty one — so the scheduler's tasks were never listed and the box
 * read "queue empty" while the store held 17 of them (owner report 2026-09-27:
 * "the tasks scheduler doesn't show any tasks").
 */
declare function schedulerTaskLines(tasks: readonly SchedulerTask[], frame: number, max?: number): {
    lines: string[];
    total: number;
};
/** Does the feed have a memory tier line to show? */
declare function feedTierLine(feedMem: FeedState["memory"]): string | null;
/** "5-min auto-check on · last 14:25" from the messenger payload's line 2. */
declare function latestMessengerStamp(): string | null;
/** The browser status word from line 2: "live" | "closed" | null. */
declare function latestMessengerBrowser(): string | null;
declare function readLastExecutions(): Map<string, {
    status: string;
    ts: string;
}>;
declare function panelTop(title: string, w: number, padAdjust?: number): string;
declare function panelRow(content: string, w: number, padAdjust?: number): string;
declare function panelBottom(w: number, padAdjust?: number): string;
interface HelperStatus {
    /** panel-status file stem: "messenger" or "secops" */
    key: string;
    summary: string;
    stale: boolean;
    latest?: string;
}
declare function readHelperStatus(key: string): HelperStatus;
/** The ☁️ Services row payloads (2026-10-13 owner: say what it DOES and how
 * to act, sized to fit). Renderers pick the form that fits the width so
 * nothing ends in an ellipsis:
 *   M Messenger — 1 text waiting · 0 emails waiting · 0 sent today · browser closed (/messenger up)
 *   🛡 Security Operations — no threats today · protection on + the deep fact
 *     it rotated in this refresh (what it actually did), then the jobs line
 *     ("auto: responderd reacts to threats · fail2ban bans brute · ...").
 */
declare function servicePayloads(): {
    messenger: {
        icon: string;
        name: string;
        forms: string[];
        stale: boolean;
    };
    secops: {
        icon: string;
        name: string;
        forms: string[];
        stale: boolean;
    };
    footer: string;
};
/** First service form that fits in `w` visible cells; the last form is the
 * floor so the line never ends in an ellipsis. Stale payloads render warning. */
declare function fitForm(forms: readonly string[], w: number, stale: boolean): string;
interface ToolCallRow {
    name: string;
    count: number;
}
declare function readRecentToolCalls(): ToolCallRow[];
/** Label a recent toolCall in owner vocabulary: mcp_messenger_* → the
 * researcher/worker doing messenger work, plain names stay plain. */
declare function helperLabel(name: string): {
    label: string;
    who: "messenger" | "research" | "worker" | "agent";
};
export declare const PANELS_FALLBACK_MS = 30000;
/** Safety net: a view that never composes must still get its panels. */
export declare function panelsMayJoinFrame(state: {
    sessionViewComposed: boolean;
    fallbackAt: number;
}, now?: number): boolean;
export interface StatusPanelSessionProvider {
    /** Session totals; undefined = no session yet, panel shows an honest 0. */
    getSessionStats?(): {
        tokens: {
            total: number;
            output: number;
            input: number;
        };
    } | undefined;
}
export interface LaneMetrics {
    requests: number;
    promptTokens: number;
    completionTokens: number;
    avgTokS: number;
    epochMs: number;
}
export declare class StatusPanelsComponent implements Component {
    private frame;
    private timer;
    private lastDataHash;
    private flashTimer;
    private readonly onTick?;
    private readonly sessionProvider?;
    private laneStats;
    private laneLastPoll;
    private laneUrl;
    private deltaTimestamps;
    private generatingUntil;
    constructor(onTick?: () => void, sessionProvider?: StatusPanelSessionProvider);
    private pollLane;
    /** One streamed token landed. Called from the agent session's
     * message_update (text_delta/thinking_delta) events by the owner mode. */
    onStreamDelta(): void;
    /** Session-level generate/idle transition (agent_start / agent_end). */
    onGenerationState(active: boolean): void;
    dispose(): void;
    invalidate(): void;
    render(width: number): string[];
}
export declare const __test: {
    panelTop: typeof panelTop;
    panelRow: typeof panelRow;
    panelBottom: typeof panelBottom;
    formatAge: typeof formatAge;
    formatLedgerAge: typeof formatLedgerAge;
    compressionStatusLines: typeof compressionStatusLines;
    compressionReason: typeof compressionReason;
    compressionCapsuleText: typeof compressionCapsuleText;
    schedulerTaskLines: typeof schedulerTaskLines;
    compressionFromFeed: typeof compressionFromFeed;
    schedulerTasksFromFeed: typeof schedulerTasksFromFeed;
    feedTierLine: typeof feedTierLine;
    ledgerAgeMs: typeof ledgerAgeMs;
    panelsMayJoinFrame: typeof panelsMayJoinFrame;
    PANELS_FALLBACK_MS: number;
    servicePayloads: typeof servicePayloads;
    fitForm: typeof fitForm;
    readHelperStatus: typeof readHelperStatus;
    helperLabel: typeof helperLabel;
    readRecentToolCalls: typeof readRecentToolCalls;
    readLastExecutions: typeof readLastExecutions;
    latestMessengerStamp: typeof latestMessengerStamp;
    latestMessengerBrowser: typeof latestMessengerBrowser;
};
export {};
//# sourceMappingURL=status-panels.d.ts.map