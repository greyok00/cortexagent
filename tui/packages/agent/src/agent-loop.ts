import {
	type AssistantMessage,
	type Context,
	EventStream,
	type ToolResultMessage,
	validateToolArguments,
} from "@cortexagent/ai";
import { assistantText, autoContinueMax, buildAutoContinueNudge, isUnfinishedAnnouncement } from "./auto-continue.ts";
import { getDefaultStreamFn } from "./stream-fn.ts";
import type {
	AgentContext,
	AgentEvent,
	AgentLoopConfig,
	AgentMessage,
	AgentTool,
	AgentToolCall,
	AgentToolResult,
	StreamFn,
} from "./types.ts";

export type AgentEventSink = (event: AgentEvent) => Promise<void> | void;

export function agentLoop(
	prompts: AgentMessage[],
	context: AgentContext,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	streamFn: StreamFn,
): EventStream<AgentEvent, AgentMessage[]> {
	const stream = createAgentStream();

	void runAgentLoop(
		prompts,
		context,
		config,
		async (event) => {
			stream.push(event);
		},
		signal,
		streamFn,
	).then((messages) => {
		stream.end(messages);
	});

	return stream;
}

export function agentLoopContinue(
	context: AgentContext,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	streamFn: StreamFn,
): EventStream<AgentEvent, AgentMessage[]> {
	if (context.messages.length === 0) {
		throw new Error("Cannot continue: no messages in context");
	}

	if (context.messages[context.messages.length - 1].role === "assistant") {
		throw new Error("Cannot continue from message role: assistant");
	}

	const stream = createAgentStream();

	void runAgentLoopContinue(
		context,
		config,
		async (event) => {
			stream.push(event);
		},
		signal,
		streamFn,
	).then((messages) => {
		stream.end(messages);
	});

	return stream;
}

export async function runAgentLoop(
	prompts: AgentMessage[],
	context: AgentContext,
	config: AgentLoopConfig,
	emit: AgentEventSink,
	signal: AbortSignal | undefined,
	streamFn: StreamFn,
): Promise<AgentMessage[]> {
	const newMessages: AgentMessage[] = [...prompts];
	const currentContext: AgentContext = {
		...context,
		messages: [...context.messages, ...prompts],
	};

	await emit({ type: "agent_start" });
	await emit({ type: "turn_start" });
	for (const prompt of prompts) {
		await emit({ type: "message_start", message: prompt });
		await emit({ type: "message_end", message: prompt });
	}

	await runLoop(currentContext, newMessages, config, signal, emit, streamFn ?? getDefaultStreamFn());
	return newMessages;
}

export async function runAgentLoopContinue(
	context: AgentContext,
	config: AgentLoopConfig,
	emit: AgentEventSink,
	signal: AbortSignal | undefined,
	streamFn: StreamFn,
): Promise<AgentMessage[]> {
	if (context.messages.length === 0) {
		throw new Error("Cannot continue: no messages in context");
	}

	if (context.messages[context.messages.length - 1].role === "assistant") {
		throw new Error("Cannot continue from message role: assistant");
	}

	const newMessages: AgentMessage[] = [];
	const currentContext: AgentContext = { ...context };

	await emit({ type: "agent_start" });
	await emit({ type: "turn_start" });

	await runLoop(currentContext, newMessages, config, signal, emit, streamFn ?? getDefaultStreamFn());
	return newMessages;
}

function createAgentStream(): EventStream<AgentEvent, AgentMessage[]> {
	return new EventStream<AgentEvent, AgentMessage[]>(
		(event: AgentEvent) => event.type === "agent_end",
		(event: AgentEvent) => (event.type === "agent_end" ? event.messages : []),
	);
}

// Override with CORTEXAGENT_LOOP_GUARD_MAX_REPEATS.
function loopGuardMaxRepeats(): number {
	const parsed = Number.parseInt(process.env.CORTEXAGENT_LOOP_GUARD_MAX_REPEATS ?? "10000000", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : 10000000;
}

function loopGuardContinueMax(): number {
	const parsed = Number.parseInt(process.env.CORTEXAGENT_LOOP_GUARD_MAX_CONTINUES ?? "0", 10);
	return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function loopGuardArgsMaxRepeats(): number {
	const parsed = Number.parseInt(process.env.CORTEXAGENT_LOOP_GUARD_ARGS_MAX_REPEATS ?? "10000000", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : 10000000;
}

function loopGuardCallsPerMessage(): number {
	// 2026-11-09: real cap (6) — tonight's burst of 20+ identical reads ran
	// because the cap was 10,000,000. Env override kept for emergencies.
	const parsed = Number.parseInt(process.env.CORTEXAGENT_LOOP_GUARD_CALLS_PER_MESSAGE ?? "6", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : 10000000;
}

type RepeatedToolCallBurst = {
	dropped: number;
	worstName: string;
	worstCount: number;
	// Signature of the most-repeated call, so the burst can also block it for
	// the rest of the session (guards alone are per-run; blocking closes the
	// kill-run-and-retry hole a fresh run otherwise re-opens).
	worstKey: string;
};

type StreamedAssistantTurn = {
	message: AssistantMessage;
	// Set when the in-message cap removed calls from this message. A burst is
	// also the signal that ends the run.
	repeatBurst: RepeatedToolCallBurst | null;
};

// Drop identical repeat calls from one message, in place. `null` means the
// message was clean, so the caller can tell "nothing happened" from "capped".
function capRepeatedToolCalls(message: AssistantMessage, cap: number): RepeatedToolCallBurst | null {
	const seen = new Map<string, number>();
	const doomed: number[] = [];
	let worstName = "";
	let worstCount = 0;
	let worstKey = "";
	message.content.forEach((block, index) => {
		if (block.type !== "toolCall") return;
		const key = `${block.name}|${loopGuardArgsKey(block.arguments)}`;
		const count = (seen.get(key) ?? 0) + 1;
		seen.set(key, count);
		if (count > worstCount) {
			worstCount = count;
			worstName = block.name;
			worstKey = key;
		}
		if (count > cap) doomed.push(index);
	});
	if (doomed.length === 0) return null;
	for (let i = doomed.length - 1; i >= 0; i--) message.content.splice(doomed[i], 1);
	return { dropped: doomed.length, worstName, worstCount, worstKey };
}

function markRepeatedToolCallBurst(message: AssistantMessage, cap: number, burst: RepeatedToolCallBurst): void {
	message.content.push({
		type: "text",
		text:
			`\n\n[LOOP GUARD] ${burst.dropped} repeated tool call(s) were removed from this turn before ` +
			`anything ran: \`${burst.worstName}\` was issued ${burst.worstCount} times with identical ` +
			`arguments in a single message (at most ${cap} of each identical call are kept). The run has ` +
			`been stopped. Do NOT re-issue the same call; change approach or report the blocker to the user.`,
	});
}

function loopGuardArgsKey(args: Record<string, any> | undefined): string {
	const command = args?.command;
	if (typeof command === "string") {
		// Models often prepend a per-attempt comment to an otherwise identical
		// bash command — drop comment lines so those still count as the same call.
		return command
			.split("\n")
			.filter((line) => !line.trim().startsWith("#"))
			.join("\n")
			.trim();
	}
	return JSON.stringify(args ?? null);
}

// Result text often carries volatile noise — the bash tool's trailing
// "Took 0.4s" duration line, timeout annotations, whitespace churn — that
// differs between otherwise identical re-runs and made the byte-exact
// signature never match (2026-09-23: one smbclient listing re-issued 7+
// times with the guard silent). Strip the noise before comparing; only real
// output changes count as progress.
function loopGuardResultKey(text: string): string {
	return text
		.split("\n")
		.filter((line) => !/^\s*took\s+[\d.]+\s*(ms|s|m)?\s*$/i.test(line))
		.join("\n")
		.replace(/\(timeout\s+[\d.]+(?:ms|s)\)/gi, " ")
		.replace(/[ \t]+/g, " ")
		.trim();
}

function toolResultText(result: ToolResultMessage): string {
	return result.content
		.filter((c) => c.type === "text")
		.map((c) => (c as { type: "text"; text: string }).text)
		.join("\n")
		.trim();
}

function markLoopGuardResult(result: ToolResultMessage, count: number): void {
	const marker =
		`\n\n[LOOP GUARD] This exact tool call has now been issued ${count} times in a row ` +
		`with identical arguments and an identical result — nothing changed between attempts. ` +
		`The run has been stopped. Do NOT re-issue this call; step back and try a ` +
		`fundamentally different approach or report the blocker to the user.`;
	markGuardResult(result, marker);
}

function markGuardResult(result: ToolResultMessage, marker: string): void {
	result.isError = true;
	const first = result.content[0];
	if (first && first.type === "text") {
		result.content[0] = { type: "text", text: `${(first as { text: string }).text}${marker}` };
	} else {
		result.content.unshift({ type: "text", text: marker.trim() });
	}
}

// Loop guard v2: models also spin by re-issuing the same SHAPED failing
// command with cosmetic argument changes (different paths, hosts, or user
// names). Normalize the command to a shape; N consecutive same-shaped FAILING
// calls hard-stop the run. Successful calls (e.g. polling) reset the streak
// and never count.
function loopGuardShapeKey(args: Record<string, any> | undefined): string {
	const command = args?.command;
	if (typeof command !== "string") return JSON.stringify(args ?? null);
	return command
		.split("\n")
		.filter((line) => !line.trim().startsWith("#"))
		.join("\n")
		.toLowerCase()
		.replace(/"[^"]*"|'[^']*'/g, " Q ")
		.replace(/\d{1,3}(?:\.\d{1,3}){3}\b/g, " IP ")
		.replace(/(?:[/\\][^\s/\\]+)+/g, " P ")
		.replace(/\b\d+\b/g, " N ")
		.replace(/\s+/g, " ")
		.trim();
}

// ---------------------------------------------------------------------------
// Session-scoped call blocklist.
//
// The guards above are all PER-RUN state. That leaves a hole the 2026-10-02
// incident exploited end to end: the user aborted a looping run (Ctrl+C →
// "Operation aborted"), the run's counters died with it, every new user reply
// spawned a FRESH run with zeroed counters, and the same dead-end call sailed
// straight through again — aborts, steering notes, and "STOP" instructions all
// came and went without anything persisting. Two fixes live here:
//
//   1. When a guard hard-stops a run, the offending signature is BLOCKED for
//      the rest of the TUI session (module scope === process scope, cleared on
//      restart). A later run cannot dispatch that exact call again; it gets a
//      hard error telling it to respond in words.
//   2. An aborted run blocks its own repeated call on the way out — a single
//      abort of a first-time call never blocks anything, but an abort during
//      the SAME call repeating (count ≥ ABORT_BLOCK_MIN_REPEATS) means the
//      user just killed the exact pattern the next run would resume.
//
// Enforcement is in executeToolCallsSequential / executeToolCallsParallel:
// blocked calls are never executed and never reach a real tool.
// ---------------------------------------------------------------------------

const sessionBlockedCalls = new Map<string, string>();
const sessionBlockedShapes = new Map<string, string>();

// A call must have repeated at least this many times in a run before an abort
// of that run blocks its signature. An abort during a first, legitimate attempt
// (a long scan, a slow build) blocks nothing.
const ABORT_BLOCK_MIN_REPEATS = 2;

function sessionCallKey(name: string, args: Record<string, any> | undefined): string {
	return `${name}|${loopGuardArgsKey(args)}`;
}

function sessionShapeKey(name: string, args: Record<string, any> | undefined): string {
	return `${name}|${loopGuardShapeKey(args)}|err`;
}

function blockSessionCall(key: string, reason: string): void {
	if (key && !sessionBlockedCalls.has(key)) sessionBlockedCalls.set(key, reason);
}

// Test hook: session blocks are module-scoped, so vitest files (which share one
// module instance) must reset them between guard-triggering tests or an earlier
// test's block poisons later runs' identical calls.
export function clearSessionCallBlocks(): void {
	sessionBlockedCalls.clear();
	sessionBlockedShapes.clear();
}

function blockSessionShape(key: string, reason: string): void {
	if (key && !sessionBlockedShapes.has(key)) sessionBlockedShapes.set(key, reason);
}

function blockedCallMessage(name: string, reason: string): string {
	return (
		`[LOOP GUARD - BLOCKED] \`${name}\` was ${reason} ` +
		`The user already saw this call run (or repeat) and stopped it. It will not run again ` +
		`in this session. Do NOT re-issue it, and do NOT trivially change the arguments to ` +
		`get around this block. Stop and answer the user in words.`
	);
}

// Returns a hard-error outcome when the call matches a session block, null when
// the call may proceed to the real tool.
//
// 2026-11-11 (the 600x/20x incident): blocked echoes were previously FREE —
// the model could re-issue a session-blocked call forever, receive the same
// "[LOOP GUARD - BLOCKED]" error text each time, and nothing counted them, so
// guard caps (which only watch the DETECTION path) never fired. The loop had
// to be stopped by hand. Now each blocked echo is counted per session-block
// entry, and when an entry's echo count reaches MAX_ECHOES the loop raises a
// terminal guard flag the run-check machinery already knows how to handle.
const MAX_ECHOES_PER_BLOCK = 3;

const sessionEchoCounts = new Map<string, number>();
let echoCapTriggered = false;
let echoCapSignature: string | null = null;

function recordEchoAndMaybeCap(key: string, name: string, kind: "exact" | "shape"): void {
	const echoes = (sessionEchoCounts.get(key) ?? 0) + 1;
	sessionEchoCounts.set(key, echoes);
	if (echoes >= MAX_ECHOES_PER_BLOCK && !echoCapTriggered) {
		echoCapTriggered = true;
		echoCapSignature =
			`${name} re-issued a ${kind}-blocked call ${echoes} times after the block. ` +
			`Every resume just re-issues the refused call; the run cannot make progress.`;
	}
}

/** Test hook: forget all echo accounting (session blocks themselves persist). */
export function clearSessionEchoCounts(): void {
	sessionEchoCounts.clear();
	echoCapTriggered = false;
	echoCapSignature = null;
}

/** Consume the echo-cap tripwire; true exactly once when it has fired. */
export function consumeEchoCap(): { fired: boolean; reason: string | null } {
	if (echoCapTriggered) {
		echoCapTriggered = false;
		const reason = echoCapSignature;
		echoCapSignature = null;
		return { fired: true, reason };
	}
	return { fired: false, reason: null };
}

/** Self-heal support: wipe echo accounting so a healed run can retry a blocked
 * call ONCE more under fresh caps (the block list itself persists — the model
 * must still find an alternate route, not echo-loop the same call). */
export function clearSessionEchoCountsExport(): void {
	clearSessionEchoCounts();
}

function sessionBlockOutcome(toolCall: AgentToolCall): { kind: "immediate"; result: AgentToolResult<any>; isError: true } | null {
	const exactKey = sessionCallKey(toolCall.name, toolCall.arguments);
	const exactReason = sessionBlockedCalls.get(exactKey);
	if (exactReason) {
		recordEchoAndMaybeCap(exactKey, toolCall.name, "exact");
		return {
			kind: "immediate",
			result: createErrorToolResult(blockedCallMessage(toolCall.name, exactReason)),
			isError: true,
		};
	}
	const shapeKey = sessionShapeKey(toolCall.name, toolCall.arguments);
	const shapeReason = sessionBlockedShapes.get(shapeKey);
	if (shapeReason) {
		recordEchoAndMaybeCap(shapeKey, toolCall.name, "shape");
		return {
			kind: "immediate",
			result: createErrorToolResult(blockedCallMessage(toolCall.name, shapeReason)),
			isError: true,
		};
	}
	return null;
}

// Auth-failure tripwire: a runaway run retrying credentials can lock out the
// target account (2026-09-23 wolf incident). N failed-auth results in one run
// hard-stop it.
const AUTH_FAILURE_PATTERN =
	/NT_STATUS_LOGON_FAILURE|LOGON_FAILURE|ACCOUNT_LOCKED_OUT|ACCOUNT_LOCKED|WRONG_PASSWORD|PASSWORD_EXPIRED|LOGON_TYPE_NOT_GRANTED/i;

function authGuardMaxFailures(): number {
	const parsed = Number.parseInt(process.env.CORTEXAGENT_AUTH_GUARD_MAX_FAILURES ?? "3", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : 3;
}

async function runLoop(
	initialContext: AgentContext,
	newMessages: AgentMessage[],
	initialConfig: AgentLoopConfig,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
	streamFunction: StreamFn,
): Promise<void> {
	let currentContext = initialContext;
	let config = initialConfig;
	let firstTurn = true;
	// 2026-08-30: transient upstream errors (proxy 400/500, stream hiccups) used to
	// hard-stop the whole agent run at the stopReason check below. Retry a bounded
	// number of times before surfacing the failure so temporary model/proxy errors
	// no longer orphan a task mid-way.
	let errorRetries = 0;
	const MAX_ERROR_RETRIES = 2;

	let pendingMessages: AgentMessage[] = (await config.getSteeringMessages?.()) || [];

	let truncationRetries = 0;
	// Hard limit to prevent infinite retry loops when the LLM keeps truncating.
	// Without this guard, a misbehaving LLM could loop forever, retrying the
	// same truncation indefinitely.
	const MAX_TRUNCATION_RETRIES = 2;

	let loopGuardSignature: string | null = null;
	let loopGuardCount = 0;
	let loopGuardTriggered = false;
	// Which call tripped the exact-match guard, remembered as name+arguments so
	// the resume can block it — the full signature is unrecoverable once the
	// result has been marked.
	let loopGuardCallKey: string | null = null;
	// 2026-11-09 owner ("any time it loops or breaks, fix it and implement the
	// fix into it; supervise from start to finish"): the 2026-10-31 removal
	// (MAX_SAFE_INTEGER) let tonight's session read the same skill file pair
	// 20+ consecutive times. Re-enabled with generous budgets — the trip now
	// BLOCKS the offender + resumes (no run-ending), so a false positive
	// costs one harness note, while a real loop stops burning turns.
	const MAX_LOOP_REPEATS = 4;

	// Resume budget: a trip blocks its offender and hands the run back to the
	// model with an instruction to change course, instead of ending the run.
	let guardContinueCount = 0;
	const MAX_GUARD_CONTINUES = 4; // 2026-11-09 re-enabled with the loop guards (4 resumes per run)
	// 2026-11-11 owner law ("when the runs terminate, there should be a self-healing
	// mechanism... it should assume I want to continue and find an alternate route"):
	// a stop is never terminal until the self-heal budget is spent. Each self-heal
	// injects an alternate-route directive and keeps the run going.
	const MAX_SELF_HEALS = 3;
	let selfHealCount = 0;

	// v2 shape guard + auth-failure tripwire state (per run).
	let shapeGuardSignature: string | null = null;
	let shapeGuardCount = 0;
	let shapeGuardTriggered = false;
	let authFailureCount = 0;
	let authGuardTriggered = false;
	const MAX_AUTH_FAILURES = authGuardMaxFailures();

	// v3 args-streak guard: same tool + same arguments, any result. Catches
	// success churn where the output differs only in metrics (transfer rates,
	// timings) so neither the exact-match guard nor the failing-only shape
	// guard can ever trip (2026-09-24: same smbclient put re-issued 4+ times).
	// Auto-continue budget: turns that ANNOUNCE an action ("Let me check the
	// status:", "I'll retry once it's back up.") but issue no tool call used to
	// end the run there, leaving the agent halted mid-task having told the user
	// what it was about to do (owner report 2026-09-27). Bounded so the cure
	// cannot become the loop it is meant to prevent.
	let autoContinueCount = 0;
	const MAX_AUTO_CONTINUE = autoContinueMax();

	let argsStreakSignature: string | null = null;
	let argsStreakCount = 0;
	let argsStreakTriggered = false;
	const MAX_ARGS_STREAK_REPEATS = 6; // 2026-11-09 re-enabled (tonight's 20+ identical reads)

	// Session blocklist registration on any exit that ended a run mid-loop:
	// hard guard stop, or a user abort. Guards reset per run; the blocklist
	// does not — that is the entire point (2026-10-02 incident).
	const registerSessionBlocksOnExit = (): void => {
		// latestRepeatBurst is set whenever the in-message cap trimmed a burst
		// in the run's most recent streamed message.
		if (
			argsStreakSignature !== null &&
			((signal?.aborted && argsStreakCount >= ABORT_BLOCK_MIN_REPEATS) ||
				((loopGuardTriggered || argsStreakTriggered) && argsStreakCount >= MAX_LOOP_REPEATS))
		) {
			blockSessionCall(
				argsStreakSignature,
				signal?.aborted
					? `stopped: the user aborted this run while the identical call had already been issued ${argsStreakCount} times in a row.`
					: `stopped after this run issued the identical call ${argsStreakCount} times in a row.`,
			);
		}
		if (shapeGuardTriggered && shapeGuardSignature !== null) {
			blockSessionShape(
				shapeGuardSignature,
				`blocked after same-shaped failing calls repeated ${shapeGuardCount} times with only cosmetic argument changes.`,
			);
		}
		if (latestRepeatBurst) {
			// The burst's most-repeated identical call never even ran (it was
			// trimmed); registration happens only at the run's exit, after this
			// message's kept calls already executed — so this cannot strangle the
			// already-dispatched batch, only future re-issues.
			blockSessionCall(
				latestRepeatBurst.worstKey,
				`stopped: one turn tried to issue the identical call ${latestRepeatBurst.worstCount} times.`,
			);
		}
	};

	// A guard trip has to be visible. markGuardResult writes its marker onto the
	// tool result AFTER that result was already emitted and recorded, so neither
	// the transcript nor the UI ever showed it — the run just stopped with no
	// explanation (2026-10-02). A harness note goes through the normal message
	// pipeline instead, so both record it and the model reads it as the next turn.
	const emitHarnessNote = async (content: string): Promise<void> => {
		const note: AgentMessage = { role: "user", content, timestamp: Date.now() };
		await emit({ type: "message_start", message: note });
		await emit({ type: "message_end", message: note });
		currentContext.messages.push(note);
		newMessages.push(note);
	};

	// v4 in-message cap: identical calls inside ONE assistant message are
	// trimmed before the message is published or dispatched, and a burst stops
	// the run. The trim lives in streamAssistantResponse — see the `publish`
	// helper there for why it must happen before the message is emitted — and
	// this flag is how the burst gets back here to end the run.
	let repeatBurstTriggered = false;
	let latestRepeatBurst: RepeatedToolCallBurst | null = null;

	while (true) {
		let hasMoreToolCalls = true;

		while (hasMoreToolCalls || pendingMessages.length > 0) {
			if (signal?.aborted) {
				// Terminal abort: once the user interrupts, the run ends for good.
				// Without this check an aborted tool result ("Operation aborted") is
				// fed back to the model as an ordinary error and it just plans the
				// next step of the abandoned task (2026-09-23 runaway incident).
				// Queued steering is intentionally NOT consumed after an abort.
				//
				// Session blocklist: an aborted run that was already repeating a
				// call blocks it for the rest of the session (2026-10-02 incident).
				registerSessionBlocksOnExit();
				await emit({ type: "agent_end", messages: newMessages });
				return;
			}
			if (!firstTurn) {
				await emit({ type: "turn_start" });
			} else {
				firstTurn = false;
			}

			if (pendingMessages.length > 0) {
				for (const message of pendingMessages) {
					await emit({ type: "message_start", message });
					await emit({ type: "message_end", message });
					currentContext.messages.push(message);
					newMessages.push(message);
				}
				// Supersession note: messages steered in mid-run were previously
				// obeyed once and then dropped, with the model drifting back to the
				// older unfinished task it was working on. Make the override explicit.
				const supersessionNote: AgentMessage = {
					role: "user",
					content:
						"[steering] The message(s) above were submitted while a task was running. " +
						"The NEWEST user instruction supersedes all earlier instructions and tasks. " +
						"Complete the newest request (or report a blocker) — do NOT resume or " +
						"continue previously-abandoned tasks unless the user explicitly asks. " +
						"If your next action would repeat what the user just told you to stop " +
						"doing, do NOT repeat it — comply with the newest instruction or report " +
						"what you already did.",
					timestamp: Date.now(),
				};
				await emit({ type: "message_start", message: supersessionNote });
				await emit({ type: "message_end", message: supersessionNote });
				currentContext.messages.push(supersessionNote);
				newMessages.push(supersessionNote);
				pendingMessages = [];
			}

			const { message, repeatBurst } = await streamAssistantResponse(
				currentContext,
				config,
				signal,
				emit,
				streamFunction,
			);
			newMessages.push(message);
			// The message was capped in place before it was published, so the
			// transcript, the UI and this context all agree on what ran. Every
			// guard below this point reads tool RESULTS, so none of them could
			// have caught a single message repeating one call: by the time a
			// result exists, every call in that message has already been
			// dispatched. The stop therefore has to be decided right here.
			if (repeatBurst) repeatBurstTriggered = true;
			if (repeatBurst) latestRepeatBurst = repeatBurst;

			if (message.stopReason === "error" || message.stopReason === "aborted") {
				if (message.stopReason === "error" && errorRetries < MAX_ERROR_RETRIES) {
					// Transient failure — re-query the model on the same context instead
					// of ending the run. The errored message is dropped from context, so
					// the retry is clean.
					errorRetries++;
					continue;
				}
				// Abort while streaming: register repeated-call blocks before the
				// run ends (2026-10-02 incident).
				if (message.stopReason === "aborted") registerSessionBlocksOnExit();
				await emit({ type: "turn_end", message, toolResults: [] });
				await emit({ type: "agent_end", messages: newMessages });
				return;
			}
			errorRetries = 0;

			const toolCalls = message.content.filter((c) => c.type === "toolCall");

			const toolResults: ToolResultMessage[] = [];
			hasMoreToolCalls = false;
			if (toolCalls.length > 0) {
				const executedToolBatch =
					message.stopReason === "length"
						? await failToolCallsFromTruncatedMessage(toolCalls, emit)
						: await executeToolCalls(currentContext, message, config, signal, emit);
				toolResults.push(...executedToolBatch.messages);
				hasMoreToolCalls = !executedToolBatch.terminate;

				// Echo cap: a session-blocked call being RE-ISSUED repeatedly means
				// every resume is just re-feeding the refusal back to a model that
				// ignores it. Past the echo limit, no amount of resumes fixes it.
				// 2026-11-11 owner law: a stop must never be the END — the run
				// self-heals: one alternate-route directive, keep going, bounded
				// (MAX_SELF_HEALS total), so the cure cannot itself loop.
				const echoCap = consumeEchoCap();
				if (echoCap.fired) {
					selfHealCount++;
					if (selfHealCount > MAX_SELF_HEALS) {
						await emitHarnessNote(
							"[harness] Self-heal budget exhausted " +
								`(${MAX_SELF_HEALS}/${MAX_SELF_HEALS}). Stopping for real — summarize ` +
								"what you learned and hand the decision to the owner in one message.",
						);
						await emit({ type: "agent_end", messages: newMessages });
						return;
					}
					clearSessionEchoCountsExport();
					await emitHarnessNote(
						`[harness] SELF-HEAL ${selfHealCount}/${MAX_SELF_HEALS}: the route you were on ` +
							"is dead (a blocked call kept being echoed). The owner's standing law is " +
							"that you FIND ANOTHER WAY — never re-issue the blocked call, never vary it " +
							"cosmetically. Do ALL of the following now: (1) say in one sentence what " +
							"you were trying to achieve (not the command — the goal); (2) name the two " +
							"alternative routes you considered; (3) take the most promising one with a " +
							"real tool call. Iteration belongs in a background subagent or one compound " +
							"command, not in this loop. If truly no route exists, say so in one message " +
							"and summarize what you learned for the owner.",
						);
						hasMoreToolCalls = true;
						continue;
					}

				if (message.stopReason === "length") {
					truncationRetries++;
					if (truncationRetries >= MAX_TRUNCATION_RETRIES) {
						// After MAX_TRUNCATION_RETRIES consecutive length-truncated responses,
						// force the inner loop to exit to prevent infinite retry.
						hasMoreToolCalls = false;
					}
				} else {
					truncationRetries = 0;
				}

				for (const result of toolResults) {
					// Loop guard: the same tool call with the same arguments returning
					// the same result means the model is making no progress. This is
					// how a run ends up re-issuing a dead-end command dozens of times
					// (e.g. smbclient exits 0 even when its sub-command fails, so the
					// failure never surfaces as an error result).
					const call = message.content.find(
						(c): c is AgentToolCall => c.type === "toolCall" && c.id === result.toolCallId,
					);
					const signature = call
						? `${call.name}|${loopGuardArgsKey(call.arguments)}|${loopGuardResultKey(toolResultText(result))}`
						: null;
					const callKey = call ? sessionCallKey(call.name, call.arguments) : null;
					if (signature !== null && signature === loopGuardSignature) {
						loopGuardCount++;
					} else {
						loopGuardSignature = signature;
						loopGuardCount = 1;
					}
					if (signature !== null && loopGuardCount >= MAX_LOOP_REPEATS) {
						markLoopGuardResult(result, loopGuardCount);
						loopGuardTriggered = true;
						loopGuardCallKey = callKey;
					}

					// v3: identical arguments re-issued regardless of result. The
					// exact-match guard can't see it when the output churns only in
					// metrics, and the v2 shape guard resets on success — this closes
					// the remaining unbounded repeat.
					const argsStreakKey = call ? `${call.name}|${loopGuardArgsKey(call.arguments)}` : null;
					if (argsStreakKey !== null && argsStreakKey === argsStreakSignature) {
						argsStreakCount++;
					} else {
						argsStreakSignature = argsStreakKey;
						argsStreakCount = 1;
					}
					if (argsStreakKey !== null && argsStreakCount >= MAX_ARGS_STREAK_REPEATS) {
						markGuardResult(
							result,
							`\n\n[LOOP GUARD] The identical tool call has now been issued ${argsStreakCount} ` +
								`times in a row; the outputs differ only in timing or transfer metrics. ` +
								`The run has been stopped. Re-running the same command again will not ` +
								`change the outcome — verify the previous result, step back, and try a ` +
								`fundamentally different approach or report to the user.`,
						);
						argsStreakTriggered = true;
					}

					// v2: same-shaped failing call with only cosmetic argument churn.
					const shapeKey = call ? `${call.name}|${loopGuardShapeKey(call.arguments)}|err` : null;
					if (result.isError) {
						if (shapeKey !== null && shapeKey === shapeGuardSignature) {
							shapeGuardCount++;
						} else {
							shapeGuardSignature = shapeKey;
							shapeGuardCount = 1;
						}
						if (shapeKey !== null && shapeGuardCount >= MAX_LOOP_REPEATS) {
							markGuardResult(
								result,
								`\n\n[LOOP GUARD] This same-shaped tool call has now failed ${shapeGuardCount} ` +
									`times in a row with only cosmetic argument changes (different paths, ` +
									`hosts, or values). The run has been stopped. Do NOT keep varying the ` +
									`arguments; step back and try a fundamentally different approach or ` +
									`report the blocker to the user.`,
							);
							shapeGuardTriggered = true;
						}
					} else {
						// Success resets the streak — polling patterns stay safe.
						shapeGuardSignature = null;
						shapeGuardCount = 0;
					}

					if (AUTH_FAILURE_PATTERN.test(toolResultText(result))) {
						authFailureCount++;
						if (authFailureCount >= MAX_AUTH_FAILURES) {
							markGuardResult(
								result,
								`\n\n[AUTH GUARD] ${authFailureCount} authentication failures (logon denied, ` +
									`wrong password, or account lockout) have now occurred in this run. The run ` +
									`has been stopped to prevent locking out the target account. Do NOT retry ` +
									`with different credentials; report the credential problem to the user.`,
							);
							authGuardTriggered = true;
						}
					}
					currentContext.messages.push(result);
					newMessages.push(result);
				}
			}

			await emit({ type: "turn_end", message, toolResults });

			if (
				loopGuardTriggered ||
				shapeGuardTriggered ||
				authGuardTriggered ||
				argsStreakTriggered ||
				repeatBurstTriggered
			) {
				// Session blocklist: persist the offenders so a fresh run cannot
				// re-issue them (guards are per-run; the blocklist is per-session).
				registerSessionBlocksOnExit();
				if (loopGuardCallKey !== null) {
					blockSessionCall(
						loopGuardCallKey,
						`stopped after this run issued the identical call ${loopGuardCount} times in a row.`,
					);
				}

				// An authentication tripwire still ends the run: more turns cannot
				// fix a wrong credential, and retrying risks locking out a real
				// account. Everything else RESUMES. Ending the run here is what the
				// owner saw as "it never did it and kept stopping" — the repeat was
				// caught, and the task the repeat was part of was thrown away with
				// it. The offender is blocked above, so resuming cannot re-issue it,
				// and MAX_GUARD_CONTINUES bounds the cure so it cannot become the
				// loop it exists to prevent.
				if (authGuardTriggered || guardContinueCount >= MAX_GUARD_CONTINUES) {
					// 2026-11-11 owner law: resume-budget exhausted is NOT a stop —
					// it graduates to a self-heal: one directive to find an alternate
					// route and CONTINUE, bounded by MAX_SELF_HEALS so the cure
					// cannot become the loop it cures.
					selfHealCount++;
					if (selfHealCount > MAX_SELF_HEALS) {
						await emitHarnessNote(
							"[harness] Self-heal budget exhausted " +
								`(${MAX_SELF_HEALS}/${MAX_SELF_HEALS}). Stopping for real — summarize ` +
								"what you learned and hand the decision to the owner in one message.",
						);
						await emit({ type: "agent_end", messages: newMessages });
						return;
					}
					await emitHarnessNote(
						`[harness] SELF-HEAL ${selfHealCount}/${MAX_SELF_HEALS}: repeated-call resumes are spent, ` +
							"so this exact approach is dead. The owner's standing law: assume they want to " +
							"continue and FIND ANOTHER WAY. Do ALL of the following now: (1) state the GOAL " +
							"you were pursuing in one sentence; (2) name two genuinely different routes; " +
							"(3) take the most promising one with a real tool call immediately. Do not " +
							"re-issue blocked calls and do not merely vary arguments — change the METHOD " +
							"(different tool, different file, compound command, or background subagent). " +
							"If no route exists, say so once in plain words and summarize what you learned.",
						);
						guardContinueCount = 0;
						loopGuardTriggered = false;
						loopGuardSignature = null;
						loopGuardCount = 0;
						loopGuardCallKey = null;
						argsStreakTriggered = false;
						argsStreakSignature = null;
						argsStreakCount = 0;
						shapeGuardTriggered = false;
						shapeGuardSignature = null;
						shapeGuardCount = 0;
						repeatBurstTriggered = false;
						latestRepeatBurst = null;
						hasMoreToolCalls = true;
						continue;
					}

				guardContinueCount++;
				await emitHarnessNote(
					"[harness] A repeated tool call was detected and stopped. That exact call is now " +
						"BLOCKED for the rest of this session, so issuing it again will not run it — do " +
						"NOT re-issue it, and do NOT change the arguments to work around the block. " +
						"RESUME the task instead: take a different approach (a different tool, input, " +
						"or step), or, if the task genuinely cannot proceed, say so in words and finish. " +
						`(loop-guard resume ${guardContinueCount}/${MAX_GUARD_CONTINUES})`,
				);

				// The streak state that caught the repeat is spent. The call it was
				// tracking is blocked now, so leaving the counters armed would trip
				// them again on the very next turn and burn the whole budget at once.
				loopGuardTriggered = false;
				loopGuardSignature = null;
				loopGuardCount = 0;
				loopGuardCallKey = null;
				argsStreakTriggered = false;
				argsStreakSignature = null;
				argsStreakCount = 0;
				shapeGuardTriggered = false;
				shapeGuardSignature = null;
				shapeGuardCount = 0;
				repeatBurstTriggered = false;
				latestRepeatBurst = null;
				hasMoreToolCalls = true;
				continue;
			}

			const nextTurnContext = {
				message,
				toolResults,
				context: currentContext,
				newMessages,
			};
			const nextTurnSnapshot = await config.prepareNextTurn?.(nextTurnContext);
			if (nextTurnSnapshot) {
				currentContext = nextTurnSnapshot.context ?? currentContext;
				config = {
					...config,
					model: nextTurnSnapshot.model ?? config.model,
					reasoning:
						nextTurnSnapshot.thinkingLevel === undefined
							? config.reasoning
							: nextTurnSnapshot.thinkingLevel === "off"
								? undefined
								: nextTurnSnapshot.thinkingLevel,
				};
			}

			if (
				await config.shouldStopAfterTurn?.({
					message,
					toolResults,
					context: currentContext,
					newMessages,
				})
			) {
				await emit({ type: "agent_end", messages: newMessages });
				return;
			}

			pendingMessages = (await config.getSteeringMessages?.()) || [];

			// A turn with no tool call normally ends the run. When that turn was
			// an announcement of work about to happen, ending here is the bug the
			// owner reported: the agent says "I'll do X now" and stops. Nudge it
			// to either act in this turn or declare the task finished. Steering
			// and an explicit stop policy both win over this — it only runs when
			// nothing else is queued and the model volunteered no action.
			if (
				toolCalls.length === 0 &&
				pendingMessages.length === 0 &&
				autoContinueCount < MAX_AUTO_CONTINUE &&
				isUnfinishedAnnouncement(assistantText(message.content))
			) {
				autoContinueCount++;
				const nudge: AgentMessage = {
					role: "user",
					content: buildAutoContinueNudge(autoContinueCount, MAX_AUTO_CONTINUE),
					timestamp: Date.now(),
				};
				await emit({ type: "message_start", message: nudge });
				await emit({ type: "message_end", message: nudge });
				currentContext.messages.push(nudge);
				newMessages.push(nudge);
				hasMoreToolCalls = true;
			}
		}

		const followUpMessages = (await config.getFollowUpMessages?.()) || [];
		if (followUpMessages.length > 0) {
			pendingMessages = followUpMessages;
			continue;
		}

		break;
	}

	await emit({ type: "agent_end", messages: newMessages });
}

async function streamAssistantResponse(
	context: AgentContext,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
	streamFunction: StreamFn,
): Promise<StreamedAssistantTurn> {
	let repeatBurst: RepeatedToolCallBurst | null = null;

	// Publish the finished message to the session store and the UI. The
	// in-message repeat cap runs HERE, before the emit, because everything
	// downstream records whatever this emit carries. Trimming after the fact
	// (2026-09-27) left the stored transcript holding calls that never ran — six
	// identical calls streamed, three executed, the session file kept all six
	// with no note explaining the other three, and a resumed session inherited
	// tool calls with no results. The cap has to be in place before anyone sees
	// the message, and that includes this function's own partial stream.
	const publish = async (message: AssistantMessage, emitStart: boolean): Promise<void> => {
		const cap = loopGuardCallsPerMessage();
		const burst = capRepeatedToolCalls(message, cap);
		if (burst) {
			markRepeatedToolCallBurst(message, cap, burst);
			repeatBurst = burst;
		}
		if (emitStart) {
			await emit({ type: "message_start", message: { ...message } });
		}
		await emit({ type: "message_end", message });
	};

	let messages = context.messages;
	if (config.transformContext) {
		messages = await config.transformContext(messages, signal);
	}

	const llmMessages = await config.convertToLlm(messages);

	const llmContext: Context = {
		systemPrompt: context.systemPrompt,
		messages: llmMessages,
		tools: context.tools,
	};

	const resolvedApiKey =
		(config.getApiKey ? await config.getApiKey(config.model.provider) : undefined) || config.apiKey;

	const response = await streamFunction(config.model, llmContext, {
		...config,
		apiKey: resolvedApiKey,
		signal,
	});

	let partialMessage: AssistantMessage | null = null;
	let addedPartial = false;

	for await (const event of response) {
		switch (event.type) {
			case "start":
				partialMessage = event.partial;
				context.messages.push(partialMessage);
				addedPartial = true;
				await emit({ type: "message_start", message: { ...partialMessage } });
				break;

			case "text_start":
			case "text_delta":
			case "text_end":
			case "thinking_start":
			case "thinking_delta":
			case "thinking_end":
			case "toolcall_start":
			case "toolcall_delta":
			case "toolcall_end":
				if (partialMessage) {
					partialMessage = event.partial;
					context.messages[context.messages.length - 1] = partialMessage;
					await emit({
						type: "message_update",
						assistantMessageEvent: event,
						message: { ...partialMessage },
					});
				}
				break;

			case "done":
			case "error": {
				const finalMessage = await response.result();
				if (addedPartial) {
					context.messages[context.messages.length - 1] = finalMessage;
				} else {
					context.messages.push(finalMessage);
				}
				await publish(finalMessage, !addedPartial);
				return { message: finalMessage, repeatBurst };
			}
		}
	}

	const finalMessage = await response.result();
	if (addedPartial) {
		context.messages[context.messages.length - 1] = finalMessage;
	} else {
		context.messages.push(finalMessage);
	}
	await publish(finalMessage, !addedPartial);
	return { message: finalMessage, repeatBurst };
}

async function failToolCallsFromTruncatedMessage(
	toolCalls: AgentToolCall[],
	emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
	const messages: ToolResultMessage[] = [];
	for (const toolCall of toolCalls) {
		await emit({
			type: "tool_execution_start",
			toolCallId: toolCall.id,
			toolName: toolCall.name,
			args: toolCall.arguments,
		});
		const finalized: FinalizedToolCallOutcome = {
			toolCall,
			result: createErrorToolResult(
				`Tool call "${toolCall.name}" was not executed: the response hit the output token limit, so its arguments may be truncated. Re-issue the tool call with complete arguments.`,
			),
			isError: true,
		};
		await emitToolExecutionEnd(finalized, emit);
		const toolResultMessage = createToolResultMessage(finalized);
		await emitToolResultMessage(toolResultMessage, emit);
		messages.push(toolResultMessage);
	}
	return { messages, terminate: false };
}

async function executeToolCalls(
	currentContext: AgentContext,
	assistantMessage: AssistantMessage,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
	const toolCalls = assistantMessage.content.filter((c) => c.type === "toolCall");
	const hasSequentialToolCall = toolCalls.some(
		(tc) => currentContext.tools?.find((t) => t.name === tc.name)?.executionMode === "sequential",
	);
	if (config.toolExecution === "sequential" || hasSequentialToolCall) {
		return executeToolCallsSequential(currentContext, assistantMessage, toolCalls, config, signal, emit);
	}
	return executeToolCallsParallel(currentContext, assistantMessage, toolCalls, config, signal, emit);
}

type ExecutedToolCallBatch = {
	messages: ToolResultMessage[];
	terminate: boolean;
};

async function executeToolCallsSequential(
	currentContext: AgentContext,
	assistantMessage: AssistantMessage,
	toolCalls: AgentToolCall[],
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
	const finalizedCalls: FinalizedToolCallOutcome[] = [];
	const messages: ToolResultMessage[] = [];

	for (const toolCall of toolCalls) {
		const blocked = sessionBlockOutcome(toolCall);
		if (blocked) {
			// Session blocklist: this exact call (or shape) was stopped by the
			// user or tripped a guard in an earlier run. Refuse it without
			// dispatching, and keep the batch alive so the model can still answer.
			await emit({
				type: "tool_execution_start",
				toolCallId: toolCall.id,
				toolName: toolCall.name,
				args: toolCall.arguments,
			});
			const finalized: FinalizedToolCallOutcome = {
				toolCall,
				result: blocked.result,
				isError: blocked.isError,
			};
			await emitToolExecutionEnd(finalized, emit);
			const toolResultMessage = createToolResultMessage(finalized);
			await emitToolResultMessage(toolResultMessage, emit);
			finalizedCalls.push(finalized);
			messages.push(toolResultMessage);
			continue;
		}
		await emit({
			type: "tool_execution_start",
			toolCallId: toolCall.id,
			toolName: toolCall.name,
			args: toolCall.arguments,
		});

		const preparation = await prepareToolCall(currentContext, assistantMessage, toolCall, config, signal);
		let finalized: FinalizedToolCallOutcome;
		if (preparation.kind === "immediate") {
			finalized = {
				toolCall,
				result: preparation.result,
				isError: preparation.isError,
			};
		} else {
			const executed = await executePreparedToolCall(preparation, signal, emit);
			finalized = await finalizeExecutedToolCall(
				currentContext,
				assistantMessage,
				preparation,
				executed,
				config,
				signal,
			);
		}

		await emitToolExecutionEnd(finalized, emit);
		const toolResultMessage = createToolResultMessage(finalized);
		await emitToolResultMessage(toolResultMessage, emit);
		finalizedCalls.push(finalized);
		messages.push(toolResultMessage);

		if (signal?.aborted) {
			break;
		}
	}

	return {
		messages,
		terminate: shouldTerminateToolBatch(finalizedCalls),
	};
}

async function executeToolCallsParallel(
	currentContext: AgentContext,
	assistantMessage: AssistantMessage,
	toolCalls: AgentToolCall[],
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
	const finalizedCalls: FinalizedToolCallEntry[] = [];

	for (const toolCall of toolCalls) {
		const blocked = sessionBlockOutcome(toolCall);
		if (blocked) {
			await emit({
				type: "tool_execution_start",
				toolCallId: toolCall.id,
				toolName: toolCall.name,
				args: toolCall.arguments,
			});
			const finalized = {
				toolCall,
				result: blocked.result,
				isError: blocked.isError,
			} satisfies FinalizedToolCallOutcome;
			await emitToolExecutionEnd(finalized, emit);
			await emitToolResultMessage(createToolResultMessage(finalized), emit);
			finalizedCalls.push(finalized);
			continue;
		}
		await emit({
			type: "tool_execution_start",
			toolCallId: toolCall.id,
			toolName: toolCall.name,
			args: toolCall.arguments,
		});

		const preparation = await prepareToolCall(currentContext, assistantMessage, toolCall, config, signal);
		if (preparation.kind === "immediate") {
			const finalized = {
				toolCall,
				result: preparation.result,
				isError: preparation.isError,
			} satisfies FinalizedToolCallOutcome;
			await emitToolExecutionEnd(finalized, emit);
			finalizedCalls.push(finalized);
			if (signal?.aborted) {
				break;
			}
			continue;
		}

		finalizedCalls.push(async () => {
			const executed = await executePreparedToolCall(preparation, signal, emit);
			const finalized = await finalizeExecutedToolCall(
				currentContext,
				assistantMessage,
				preparation,
				executed,
				config,
				signal,
			);
			await emitToolExecutionEnd(finalized, emit);
			return finalized;
		});
		if (signal?.aborted) {
			break;
		}
	}

	const orderedFinalizedCalls = await Promise.all(
		finalizedCalls.map((entry) => (typeof entry === "function" ? entry() : Promise.resolve(entry))),
	);
	const messages: ToolResultMessage[] = [];
	for (const finalized of orderedFinalizedCalls) {
		const toolResultMessage = createToolResultMessage(finalized);
		await emitToolResultMessage(toolResultMessage, emit);
		messages.push(toolResultMessage);
	}

	return {
		messages,
		terminate: shouldTerminateToolBatch(orderedFinalizedCalls),
	};
}

type PreparedToolCall = {
	kind: "prepared";
	toolCall: AgentToolCall;
	tool: AgentTool<any>;
	args: unknown;
};

type ImmediateToolCallOutcome = {
	kind: "immediate";
	result: AgentToolResult<any>;
	isError: boolean;
};

type ExecutedToolCallOutcome = {
	result: AgentToolResult<any>;
	isError: boolean;
};

type FinalizedToolCallOutcome = {
	toolCall: AgentToolCall;
	result: AgentToolResult<any>;
	isError: boolean;
};

type FinalizedToolCallEntry = FinalizedToolCallOutcome | (() => Promise<FinalizedToolCallOutcome>);

function shouldTerminateToolBatch(finalizedCalls: FinalizedToolCallOutcome[]): boolean {
	return finalizedCalls.length > 0 && finalizedCalls.every((finalized) => finalized.result.terminate === true);
}

function prepareToolCallArguments(tool: AgentTool<any>, toolCall: AgentToolCall): AgentToolCall {
	if (!tool.prepareArguments) {
		return toolCall;
	}
	const preparedArguments = tool.prepareArguments(toolCall.arguments);
	if (preparedArguments === toolCall.arguments) {
		return toolCall;
	}
	return {
		...toolCall,
		arguments: preparedArguments as Record<string, any>,
	};
}

async function prepareToolCall(
	currentContext: AgentContext,
	assistantMessage: AssistantMessage,
	toolCall: AgentToolCall,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
): Promise<PreparedToolCall | ImmediateToolCallOutcome> {
	const tool = currentContext.tools?.find((t) => t.name === toolCall.name);
	if (!tool) {
		return {
			kind: "immediate",
			result: createErrorToolResult(`Tool ${toolCall.name} not found`),
			isError: true,
		};
	}

	try {
		const preparedToolCall = prepareToolCallArguments(tool, toolCall);
		const validatedArgs = validateToolArguments(tool, preparedToolCall);
		if (config.beforeToolCall) {
			const beforeResult = await config.beforeToolCall(
				{
					assistantMessage,
					toolCall,
					args: validatedArgs,
					context: currentContext,
				},
				signal,
			);
			if (signal?.aborted) {
				return {
					kind: "immediate",
					result: createErrorToolResult("Operation aborted"),
					isError: true,
				};
			}
			if (beforeResult?.block) {
				const result = createErrorToolResult(beforeResult.reason || "Tool execution was blocked");
				if (beforeResult.terminate === true) {
					result.terminate = true;
				}
				return {
					kind: "immediate",
					result,
					isError: true,
				};
			}
		}
		if (signal?.aborted) {
			return {
				kind: "immediate",
				result: createErrorToolResult("Operation aborted"),
				isError: true,
			};
		}
		return {
			kind: "prepared",
			toolCall,
			tool,
			args: validatedArgs,
		};
	} catch (error) {
		return {
			kind: "immediate",
			result: createErrorToolResult(error instanceof Error ? error.message : String(error)),
			isError: true,
		};
	}
}

async function executePreparedToolCall(
	prepared: PreparedToolCall,
	signal: AbortSignal | undefined,
	emit: AgentEventSink,
): Promise<ExecutedToolCallOutcome> {
	const updateEvents: Promise<void>[] = [];
	let acceptingUpdates = true;

	try {
		const result = await prepared.tool.execute(
			prepared.toolCall.id,
			prepared.args as never,
			signal,
			(partialResult) => {
				if (!acceptingUpdates) return;
				updateEvents.push(
					Promise.resolve(
						emit({
							type: "tool_execution_update",
							toolCallId: prepared.toolCall.id,
							toolName: prepared.toolCall.name,
							args: prepared.toolCall.arguments,
							partialResult,
						}),
					),
				);
			},
		);
		acceptingUpdates = false;
		await Promise.all(updateEvents);
		return { result, isError: false };
	} catch (error) {
		acceptingUpdates = false;
		await Promise.all(updateEvents);
		return {
			result: createErrorToolResult(error instanceof Error ? error.message : String(error)),
			isError: true,
		};
	} finally {
		acceptingUpdates = false;
	}
}

async function finalizeExecutedToolCall(
	currentContext: AgentContext,
	assistantMessage: AssistantMessage,
	prepared: PreparedToolCall,
	executed: ExecutedToolCallOutcome,
	config: AgentLoopConfig,
	signal: AbortSignal | undefined,
): Promise<FinalizedToolCallOutcome> {
	let result = executed.result;
	let isError = executed.isError;

	if (config.afterToolCall) {
		try {
			const afterResult = await config.afterToolCall(
				{
					assistantMessage,
					toolCall: prepared.toolCall,
					args: prepared.args,
					result,
					isError,
					context: currentContext,
				},
				signal,
			);
			if (afterResult) {
				result = {
					...result,
					content: afterResult.content ?? result.content,
					details: afterResult.details ?? result.details,
					usage: afterResult.usage ?? result.usage,
					terminate: afterResult.terminate ?? result.terminate,
				};
				isError = afterResult.isError ?? isError;
			}
		} catch (error) {
			result = createErrorToolResult(error instanceof Error ? error.message : String(error));
			isError = true;
		}
	}

	return {
		toolCall: prepared.toolCall,
		result,
		isError,
	};
}

function createErrorToolResult(message: string): AgentToolResult<any> {
	return {
		content: [{ type: "text", text: message }],
		details: {},
	};
}

async function emitToolExecutionEnd(finalized: FinalizedToolCallOutcome, emit: AgentEventSink): Promise<void> {
	await emit({
		type: "tool_execution_end",
		toolCallId: finalized.toolCall.id,
		toolName: finalized.toolCall.name,
		result: finalized.result,
		isError: finalized.isError,
	});
}

// 2026-10-03 owner directive: no truncation, anywhere. Tool results are
// ingested verbatim at full length. A single huge tool output can push the
// very next request past the context window, and overflow-recovery compaction
// is the backstop for that — we do not silently delete the model's own data.
function createToolResultMessage(finalized: FinalizedToolCallOutcome): ToolResultMessage {
	return {
		role: "toolResult",
		toolCallId: finalized.toolCall.id,
		toolName: finalized.toolCall.name,

		content: finalized.result.content ?? [],
		details: finalized.result.details,
		usage: finalized.result.usage,
		...(finalized.result.addedToolNames?.length ? { addedToolNames: finalized.result.addedToolNames } : {}),
		isError: finalized.isError,
		timestamp: Date.now(),
	};
}

async function emitToolResultMessage(toolResultMessage: ToolResultMessage, emit: AgentEventSink): Promise<void> {
	await emit({ type: "message_start", message: toolResultMessage });
	await emit({ type: "message_end", message: toolResultMessage });
}
