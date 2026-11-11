import { EventStream } from "@cortexagent/ai";
import type { AgentContext, AgentEvent, AgentLoopConfig, AgentMessage, StreamFn } from "./types.ts";
export type AgentEventSink = (event: AgentEvent) => Promise<void> | void;
export declare function agentLoop(prompts: AgentMessage[], context: AgentContext, config: AgentLoopConfig, signal: AbortSignal | undefined, streamFn: StreamFn): EventStream<AgentEvent, AgentMessage[]>;
export declare function agentLoopContinue(context: AgentContext, config: AgentLoopConfig, signal: AbortSignal | undefined, streamFn: StreamFn): EventStream<AgentEvent, AgentMessage[]>;
export declare function runAgentLoop(prompts: AgentMessage[], context: AgentContext, config: AgentLoopConfig, emit: AgentEventSink, signal: AbortSignal | undefined, streamFn: StreamFn): Promise<AgentMessage[]>;
export declare function runAgentLoopContinue(context: AgentContext, config: AgentLoopConfig, emit: AgentEventSink, signal: AbortSignal | undefined, streamFn: StreamFn): Promise<AgentMessage[]>;
export declare function clearSessionCallBlocks(): void;
/** Test hook: forget all echo accounting (session blocks themselves persist). */
export declare function clearSessionEchoCounts(): void;
/** Consume the echo-cap tripwire; true exactly once when it has fired. */
export declare function consumeEchoCap(): {
    fired: boolean;
    reason: string | null;
};
/** Self-heal support: wipe echo accounting so a healed run can retry a blocked
 * call ONCE more under fresh caps (the block list itself persists — the model
 * must still find an alternate route, not echo-loop the same call). */
export declare function clearSessionEchoCountsExport(): void;
//# sourceMappingURL=agent-loop.d.ts.map