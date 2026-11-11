import { randomBytes } from "node:crypto";
import { createWriteStream } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import "./truncate.js";
function defaultTempFilePath(prefix) {
    const id = randomBytes(8).toString("hex");
    return join(tmpdir(), `${prefix}-${id}.log`);
}
function byteLength(text) {
    return Buffer.byteLength(text, "utf-8");
}
export class OutputAccumulator {
    maxLines;
    maxBytes;
    maxRollingBytes;
    tempFilePrefix;
    decoder = new TextDecoder();
    rawChunks = [];
    tailText = "";
    tailBytes = 0;
    tailStartsAtLineBoundary = true;
    totalRawBytes = 0;
    totalDecodedBytes = 0;
    completedLines = 0;
    totalLines = 0;
    currentLineBytes = 0;
    hasOpenLine = false;
    finished = false;
    tempFilePath;
    tempFileStream;
    constructor(options = {}) {
        // No truncation limits
        this.maxLines = Number.MAX_SAFE_INTEGER;
        this.maxBytes = Number.MAX_SAFE_INTEGER;
        this.maxRollingBytes = Number.MAX_SAFE_INTEGER;
        this.tempFilePrefix = options.tempFilePrefix ?? "cortex-output";
    }
    append(data) {
        if (this.finished) {
            throw new Error("Cannot append to a finished output accumulator");
        }
        this.totalRawBytes += data.length;
        this.appendDecodedText(this.decoder.decode(data, { stream: true }));
        if (this.tempFileStream || this.shouldUseTempFile()) {
            this.ensureTempFile();
            this.tempFileStream?.write(data);
        }
        else if (data.length > 0) {
            this.rawChunks.push(data);
        }
    }
    finish() {
        if (this.finished) {
            return;
        }
        this.finished = true;
        this.appendDecodedText(this.decoder.decode());
        if (this.shouldUseTempFile()) {
            this.ensureTempFile();
        }
    }
    snapshot(options = {}) {
        // No truncation — return full content
        const content = this.getSnapshotText();
        const truncation = {
            content,
            truncated: false,
            truncatedBy: null,
            totalLines: this.totalLines,
            totalBytes: this.totalDecodedBytes,
            outputLines: this.totalLines,
            outputBytes: this.totalDecodedBytes,
            lastLinePartial: this.hasOpenLine,
            firstLineExceedsLimit: false,
            maxLines: this.maxLines,
            maxBytes: this.maxBytes,
        };
        if (options.persistIfTruncated) {
            this.ensureTempFile();
        }
        return {
            content,
            truncation,
            fullOutputPath: this.tempFilePath,
        };
    }
    async closeTempFile() {
        if (!this.tempFileStream) {
            return;
        }
        const stream = this.tempFileStream;
        this.tempFileStream = undefined;
        await new Promise((resolve, reject) => {
            const onError = (error) => {
                stream.off("finish", onFinish);
                reject(error);
            };
            const onFinish = () => {
                stream.off("error", onError);
                resolve();
            };
            stream.once("error", onError);
            stream.once("finish", onFinish);
            stream.end();
        });
    }
    getLastLineBytes() {
        return this.currentLineBytes;
    }
    appendDecodedText(text) {
        if (text.length === 0) {
            return;
        }
        const bytes = byteLength(text);
        this.totalDecodedBytes += bytes;
        this.tailText += text;
        this.tailBytes += bytes;
        // No truncation — no trimming needed
        this.tailBytes = this.tailText.length;
        let newlines = 0;
        let lastNewline = -1;
        for (let i = text.indexOf("\n"); i !== -1; i = text.indexOf("\n", i + 1)) {
            newlines++;
            lastNewline = i;
        }
        if (newlines === 0) {
            this.currentLineBytes += bytes;
            this.hasOpenLine = true;
        }
        else {
            this.completedLines += newlines;
            const tail = text.slice(lastNewline + 1);
            this.currentLineBytes = byteLength(tail);
            this.hasOpenLine = tail.length > 0;
        }
        this.totalLines = this.completedLines + (this.hasOpenLine ? 1 : 0);
    }
    trimTail() {
        // No trimming — no truncation
    }
    getSnapshotText() {
        if (this.tailStartsAtLineBoundary) {
            return this.tailText;
        }
        const firstNewline = this.tailText.indexOf("\n");
        return firstNewline === -1 ? this.tailText : this.tailText.slice(firstNewline + 1);
    }
    shouldUseTempFile() {
        // No truncation triggers — always use temp file for large output
        return this.totalRawBytes > 10 * 1024 * 1024 || this.totalDecodedBytes > 10 * 1024 * 1024;
    }
    ensureTempFile() {
        if (this.tempFilePath) {
            return;
        }
        this.tempFilePath = defaultTempFilePath(this.tempFilePrefix);
        this.tempFileStream = createWriteStream(this.tempFilePath);
        for (const chunk of this.rawChunks) {
            this.tempFileStream.write(chunk);
        }
        this.rawChunks = [];
    }
}
//# sourceMappingURL=output-accumulator.js.map