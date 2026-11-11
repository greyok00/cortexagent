import { randomBytes } from "node:crypto";
import { createWriteStream } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { stripAnsi } from "../utils/ansi.js";
import { sanitizeBinaryOutput } from "../utils/shell.js";
import { DEFAULT_MAX_BYTES } from "./tools/truncate.js";
export async function executeBashWithOperations(command, cwd, operations, options) {
    const outputChunks = [];
    const maxOutputBytes = DEFAULT_MAX_BYTES * 2;
    let tempFilePath;
    let tempFileStream;
    let totalBytes = 0;
    const ensureTempFile = () => {
        if (tempFilePath) {
            return;
        }
        const id = randomBytes(8).toString("hex");
        tempFilePath = join(tmpdir(), `cortex-bash-${id}.log`);
        tempFileStream = createWriteStream(tempFilePath);
        for (const chunk of outputChunks) {
            tempFileStream.write(chunk);
        }
    };
    const decoder = new TextDecoder();
    const onData = (data) => {
        totalBytes += data.length;
        const text = sanitizeBinaryOutput(stripAnsi(decoder.decode(data, { stream: true }))).replace(/\r/g, "");
        if (tempFileStream) {
            tempFileStream.write(text);
        }
        else if (totalBytes > maxOutputBytes) {
            ensureTempFile();
            tempFileStream.write(text);
        }
        outputChunks.push(text);
        const outputBytes = outputChunks.join("").length;
        // No truncation — keep all chunks
        if (options?.onChunk) {
            options.onChunk(text);
        }
    };
    try {
        const result = await operations.exec(command, cwd, {
            onData,
            signal: options?.signal,
        });
        const fullOutput = outputChunks.join("");
        const cancelled = options?.signal?.aborted ?? false;
        return {
            output: fullOutput,
            exitCode: cancelled ? undefined : (result.exitCode ?? undefined),
            cancelled,
            truncated: false,
            fullOutputPath: tempFilePath,
        };
    }
    catch (err) {
        if (options?.signal?.aborted) {
            const fullOutput = outputChunks.join("");
            return {
                output: fullOutput,
                exitCode: undefined,
                cancelled: true,
                truncated: false,
                fullOutputPath: tempFilePath,
            };
        }
        if (tempFileStream) {
            tempFileStream.end();
        }
        throw err;
    }
}
//# sourceMappingURL=bash-executor.js.map