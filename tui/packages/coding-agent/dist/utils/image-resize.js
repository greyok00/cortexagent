import { Worker } from "node:worker_threads";
import { resizeImageInProcess } from "./image-resize-core.js";
function toTransferableBytes(input) {
    return new Uint8Array(input);
}
function isResizeImageWorkerResponse(value) {
    return value !== null && typeof value === "object";
}
function createResizeWorker(workerSpecifier) {
    return new Worker(workerSpecifier);
}
async function resizeImageInWorker(workerSpecifier, inputBytes, mimeType, options) {
    const worker = createResizeWorker(workerSpecifier);
    try {
        const inputBytesForWorker = toTransferableBytes(inputBytes);
        return await new Promise((resolve, reject) => {
            let settled = false;
            const settle = (result) => {
                if (settled)
                    return;
                settled = true;
                resolve(result);
            };
            const fail = (error) => {
                if (settled)
                    return;
                settled = true;
                reject(error);
            };
            worker.once("message", (message) => {
                if (!isResizeImageWorkerResponse(message)) {
                    fail(new Error("Invalid image resize worker response"));
                    return;
                }
                if (message.error) {
                    fail(new Error(message.error));
                    return;
                }
                settle(message.result ?? null);
            });
            worker.once("error", fail);
            worker.once("exit", (code) => {
                if (!settled) {
                    fail(new Error(`Image resize worker exited with code ${code}`));
                }
            });
            worker.postMessage({
                inputBytes: inputBytesForWorker,
                mimeType,
                options,
            }, [inputBytesForWorker.buffer]);
        });
    }
    finally {
        void worker.terminate().catch(() => undefined);
    }
}
export async function resizeImage(inputBytes, mimeType, options) {
    const isTypeScriptRuntime = import.meta.url.endsWith(".ts");
    const workerUrl = new URL(isTypeScriptRuntime ? "./image-resize-worker.ts" : "./image-resize-worker.js", import.meta.url);
    if (typeof process.versions.bun === "string") {
        try {
            return await resizeImageInWorker("./src/utils/image-resize-worker.ts", inputBytes, mimeType, options);
        }
        catch { }
    }
    try {
        return await resizeImageInWorker(workerUrl, inputBytes, mimeType, options);
    }
    catch {
        return resizeImageInProcess(inputBytes, mimeType, options);
    }
}
export function formatDimensionNote(result) {
    if (!result.wasResized) {
        return undefined;
    }
    const scale = result.originalWidth / result.width;
    return `[Image: original ${result.originalWidth}x${result.originalHeight}, displayed at ${result.width}x${result.height}. Multiply coordinates by ${scale.toFixed(2)} to map to original image.]`;
}
//# sourceMappingURL=image-resize.js.map