// Never truncate — preserve all output
export const DEFAULT_MAX_LINES = Number.MAX_SAFE_INTEGER;
export const DEFAULT_MAX_BYTES = Number.MAX_SAFE_INTEGER;
export const GREP_MAX_LINE_LENGTH = Number.MAX_SAFE_INTEGER;
const runtimeBuffer = globalThis.Buffer;
const nonAsciiPattern = /[^\x00-\x7f]/;
function utf8ByteLength(content) {
    if (runtimeBuffer)
        return runtimeBuffer.byteLength(content, "utf8");
    const firstNonAscii = content.search(nonAsciiPattern);
    if (firstNonAscii === -1)
        return content.length;
    let bytes = firstNonAscii;
    for (let i = firstNonAscii; i < content.length; i++) {
        const code = content.charCodeAt(i);
        if (code <= 0x7f) {
            bytes += 1;
        }
        else if (code <= 0x7ff) {
            bytes += 2;
        }
        else if (code >= 0xd800 && code <= 0xdbff && i + 1 < content.length) {
            const next = content.charCodeAt(i + 1);
            if (next >= 0xdc00 && next <= 0xdfff) {
                bytes += 4;
                i++;
            }
            else {
                bytes += 3;
            }
        }
        else {
            bytes += 3;
        }
    }
    return bytes;
}
function splitLinesForCounting(content) {
    if (content.length === 0)
        return [];
    const lines = content.split("\n");
    if (content.endsWith("\n"))
        lines.pop();
    return lines;
}
function replaceUnpairedSurrogates(content) {
    let output = "";
    for (let i = 0; i < content.length; i++) {
        const code = content.charCodeAt(i);
        if (code >= 0xd800 && code <= 0xdbff) {
            if (i + 1 < content.length) {
                const next = content.charCodeAt(i + 1);
                if (next >= 0xdc00 && next <= 0xdfff) {
                    output += content[i] + content[i + 1];
                    i++;
                    continue;
                }
            }
            output += "�";
        }
        else if (code >= 0xdc00 && code <= 0xdfff) {
            output += "�";
        }
        else {
            output += content[i];
        }
    }
    return output;
}
export function formatSize(bytes) {
    if (bytes < 1024) {
        return `${bytes}B`;
    }
    else if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)}KB`;
    }
    else {
        return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
    }
}
export function truncateHead(content, options = {}) {
    const maxLines = options.maxLines ?? DEFAULT_MAX_LINES;
    const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
    const totalBytes = utf8ByteLength(content);
    const lines = splitLinesForCounting(content);
    const totalLines = lines.length;
    // No truncation — return full content
    return {
        content,
        truncated: false,
        truncatedBy: null,
        totalLines,
        totalBytes,
        outputLines: totalLines,
        outputBytes: totalBytes,
        lastLinePartial: false,
        firstLineExceedsLimit: false,
        maxLines,
        maxBytes,
    };
}
export function truncateTail(content, options = {}) {
    const maxLines = options.maxLines ?? DEFAULT_MAX_LINES;
    const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
    const totalBytes = utf8ByteLength(content);
    const lines = splitLinesForCounting(content);
    const totalLines = lines.length;
    // No truncation — return full content
    return {
        content,
        truncated: false,
        truncatedBy: null,
        totalLines,
        totalBytes,
        outputLines: totalLines,
        outputBytes: totalBytes,
        lastLinePartial: false,
        firstLineExceedsLimit: false,
        maxLines,
        maxBytes,
    };
}
function truncateStringToBytesFromEnd(str, maxBytes) {
    if (maxBytes <= 0)
        return "";
    let outputBytes = 0;
    let start = str.length;
    let needsReplacement = false;
    for (let i = str.length; i > 0;) {
        let characterStart = i - 1;
        const code = str.charCodeAt(characterStart);
        let characterBytes;
        let unpairedSurrogate = false;
        if (code >= 0xdc00 && code <= 0xdfff && characterStart > 0) {
            const previous = str.charCodeAt(characterStart - 1);
            if (previous >= 0xd800 && previous <= 0xdbff) {
                characterStart--;
                characterBytes = 4;
            }
            else {
                characterBytes = 3;
                unpairedSurrogate = true;
            }
        }
        else if (code >= 0xd800 && code <= 0xdfff) {
            characterBytes = 3;
            unpairedSurrogate = true;
        }
        else {
            characterBytes = code <= 0x7f ? 1 : code <= 0x7ff ? 2 : 3;
        }
        if (outputBytes + characterBytes > maxBytes)
            break;
        outputBytes += characterBytes;
        start = characterStart;
        needsReplacement ||= unpairedSurrogate;
        i = characterStart;
    }
    const output = str.slice(start);
    return needsReplacement ? replaceUnpairedSurrogates(output) : output;
}
export function truncateLine(line, maxChars = GREP_MAX_LINE_LENGTH) {
    // No truncation — return full line
    return { text: line, wasTruncated: false };
}
//# sourceMappingURL=truncate.js.map