import { Type } from "typebox";
import { getOrThrow } from "../types.js";
import { executeShellWithCapture } from "../utils/shell-output.js";
import "../utils/truncate.js";
const MAX_TIMEOUT_SECONDS = 2_147_483_647 / 1000;
const BASH_UPDATE_THROTTLE_MS = 100;
const bashSchema = Type.Object({
    command: Type.String({ description: "Bash command to execute" }),
    timeout: Type.Optional(Type.Number({ description: "Timeout in seconds (optional, no default timeout)" })),
});
function validateTimeout(timeout) {
    if (timeout === undefined)
        return;
    if (!Number.isFinite(timeout) || timeout <= 0) {
        throw new Error("Invalid timeout: must be a finite number of seconds");
    }
    if (timeout > MAX_TIMEOUT_SECONDS) {
        throw new Error(`Invalid timeout: maximum is ${MAX_TIMEOUT_SECONDS} seconds`);
    }
}
export function createBashTool(options) {
    return {
        name: "bash",
        label: "bash",
        description: `Execute a bash command in the current working directory. Returns stdout and stderr with no truncation. Optionally provide a timeout in seconds.`,
        parameters: bashSchema,
        async execute(_toolCallId, { command, timeout }, signal, onUpdate, context) {
            validateTimeout(timeout);
            const { env } = context;
            const execution = {
                command: options?.commandPrefix ? `${options.commandPrefix}\n${command}` : command,
                cwd: env.cwd,
                env: {},
                inheritEnv: true,
            };
            await options?.prepare?.(execution, context, signal);
            let getLatestProgress;
            let updateTimer;
            let updateDirty = false;
            let lastUpdateAt = 0;
            const emitOutputUpdate = () => {
                if (!onUpdate || !updateDirty || !getLatestProgress)
                    return;
                updateDirty = false;
                lastUpdateAt = Date.now();
                const progress = getLatestProgress();
                onUpdate({
                    content: [{ type: "text", text: progress.output }],
                    details: {},
                });
            };
            const clearUpdateTimer = () => {
                if (!updateTimer)
                    return;
                clearTimeout(updateTimer);
                updateTimer = undefined;
            };
            const scheduleOutputUpdate = () => {
                if (!onUpdate)
                    return;
                updateDirty = true;
                const delay = BASH_UPDATE_THROTTLE_MS - (Date.now() - lastUpdateAt);
                if (delay <= 0) {
                    clearUpdateTimer();
                    emitOutputUpdate();
                    return;
                }
                updateTimer ??= setTimeout(() => {
                    updateTimer = undefined;
                    emitOutputUpdate();
                }, delay);
            };
            onUpdate?.({ content: [], details: undefined });
            try {
                const capture = getOrThrow(await executeShellWithCapture(env, execution.command, {
                    cwd: execution.cwd,
                    env: execution.env,
                    inheritEnv: execution.inheritEnv,
                    timeout,
                    abortSignal: signal,
                    returnExecutionErrors: true,
                    onChunk: (_chunk, getProgress) => {
                        getLatestProgress = getProgress;
                        scheduleOutputUpdate();
                    },
                }));
                clearUpdateTimer();
                getLatestProgress = () => capture;
                updateDirty = true;
                emitOutputUpdate();
                const outputText = capture.output;
                // No truncation — all output preserved
                const details = undefined;
                const appendStatus = (status) => `${outputText ? `${outputText}\n\n` : ""}${status}`;
                if (capture.cancelled)
                    throw new Error(appendStatus("Command aborted"));
                if (capture.executionError?.code === "timeout") {
                    throw new Error(appendStatus(`Command timed out after ${timeout} seconds`), {
                        cause: capture.executionError,
                    });
                }
                if (capture.executionError)
                    throw capture.executionError;
                if (capture.exitCode !== 0 && capture.exitCode !== undefined) {
                    throw new Error(appendStatus(`Command exited with code ${capture.exitCode}`));
                }
                return { content: [{ type: "text", text: outputText || "(no output)" }], details };
            }
            finally {
                clearUpdateTimer();
            }
        },
    };
}
//# sourceMappingURL=bash.js.map