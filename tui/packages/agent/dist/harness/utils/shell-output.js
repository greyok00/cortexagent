import { ExecutionError, err, ok, toError } from "../types.js";
import { DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES } from "./truncate.js";
function toExecutionError(error) {
    if (error instanceof ExecutionError)
        return error;
    const cause = toError(error);
    return new ExecutionError("unknown", cause.message, cause);
}
export function sanitizeBinaryOutput(str) {
    return Array.from(str)
        .filter((char) => {
        const code = char.codePointAt(0);
        if (code === undefined)
            return false;
        if (code === 0x09 || code === 0x0a || code === 0x0d)
            return true;
        if (code <= 0x1f)
            return false;
        if (code >= 0xfff9 && code <= 0xfffb)
            return false;
        return true;
    })
        .join("");
}
export async function executeShellWithCapture(env, command, options) {
    let tailOutput = "";
    const encoder = new TextEncoder();
    let totalBytes = 0;
    let completedLines = 0;
    let hasOpenLine = false;
    let currentLineBytes = 0;
    let fullOutputPath;
    let fullOutputRequested = false;
    let acceptingOutput = true;
    let writeChain = Promise.resolve(ok(undefined));
    let captureError;
    const appendFullOutput = (text) => {
        if (!fullOutputRequested || captureError)
            return;
        writeChain = writeChain.then(async (previous) => {
            if (!previous.ok)
                return previous;
            if (!fullOutputPath)
                return err(new ExecutionError("unknown", "Full output path was not created"));
            const appendResult = await env.appendFile(fullOutputPath, text);
            return appendResult.ok ? ok(undefined) : err(toExecutionError(appendResult.error));
        });
    };
    const ensureFullOutputFile = (initialContent) => {
        if (fullOutputRequested || captureError)
            return;
        fullOutputRequested = true;
        writeChain = writeChain.then(async (previous) => {
            if (!previous.ok)
                return previous;
            const tempFile = await env.createTempFile({ prefix: "bash-", suffix: ".log" });
            if (!tempFile.ok)
                return err(toExecutionError(tempFile.error));
            fullOutputPath = tempFile.value;
            const appendResult = await env.appendFile(tempFile.value, initialContent);
            return appendResult.ok ? ok(undefined) : err(toExecutionError(appendResult.error));
        });
    };
    const createProgress = () => {
        const totalLines = completedLines + (hasOpenLine ? 1 : 0);
        const truncation = {
            content: tailOutput,
            truncated: false,
            truncatedBy: null,
            totalLines,
            totalBytes,
            outputLines: totalLines,
            outputBytes: totalBytes,
            lastLinePartial: false,
            firstLineExceedsLimit: false,
            maxLines: DEFAULT_MAX_LINES,
            maxBytes: DEFAULT_MAX_BYTES,
        };
        return {
            output: tailOutput,
            truncation,
            fullOutputPath,
            lastLineBytes: currentLineBytes,
        };
    };
    const onChunk = (chunk) => {
        if (!acceptingOutput)
            return;
        try {
            const text = sanitizeBinaryOutput(chunk).replace(/\r/g, "");
            const textBytes = encoder.encode(text).byteLength;
            totalBytes += textBytes;
            const newlineCount = text.split("\n").length - 1;
            completedLines += newlineCount;
            const lastNewline = text.lastIndexOf("\n");
            if (lastNewline >= 0) {
                const trailingText = text.slice(lastNewline + 1);
                currentLineBytes = encoder.encode(trailingText).byteLength;
                hasOpenLine = trailingText.length > 0;
            }
            else if (text.length > 0) {
                currentLineBytes += textBytes;
                hasOpenLine = true;
            }
            tailOutput += text;
            // Always write to full output file — no truncation
            if (!fullOutputRequested) {
                ensureFullOutputFile(tailOutput);
            }
            options?.onChunk?.(text, createProgress);
        }
        catch (error) {
            captureError = toExecutionError(error);
        }
    };
    try {
        const result = await env.exec(command, {
            cwd: options?.cwd,
            env: options?.env,
            inheritEnv: options?.inheritEnv,
            timeout: options?.timeout,
            abortSignal: options?.abortSignal,
            onStdout: onChunk,
            onStderr: onChunk,
        });
        acceptingOutput = false;
        const progress = createProgress();
        const writeResult = await writeChain;
        if (!writeResult.ok)
            return err(writeResult.error);
        if (captureError)
            return err(captureError);
        if (!result.ok) {
            if (result.error.code === "aborted" || options?.abortSignal?.aborted) {
                return ok({
                    ...progress,
                    exitCode: undefined,
                    cancelled: true,
                    truncated: false,
                });
            }
            if (options?.returnExecutionErrors) {
                return ok({
                    ...progress,
                    exitCode: undefined,
                    cancelled: false,
                    truncated: false,
                    executionError: result.error,
                });
            }
            return err(result.error);
        }
        const cancelled = options?.abortSignal?.aborted ?? false;
        return ok({
            ...progress,
            exitCode: cancelled ? undefined : result.value.exitCode,
            cancelled,
            truncated: false,
        });
    }
    catch (error) {
        acceptingOutput = false;
        return err(toExecutionError(error));
    }
}
//# sourceMappingURL=shell-output.js.map