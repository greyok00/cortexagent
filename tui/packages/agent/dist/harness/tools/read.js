import { Type } from "typebox";
import { getOrThrow } from "../types.js";
import "../utils/truncate.js";
import { detectSupportedImageMimeType, encodeBase64 } from "./image.js";
import { resolveReadToolPath } from "./path-utils.js";
const readSchema = Type.Object({
    path: Type.String({ description: "Path to the file to read (relative or absolute)" }),
    offset: Type.Optional(Type.Number({ description: "Line number to start reading from (1-indexed)" })),
    limit: Type.Optional(Type.Number({ description: "Maximum number of lines to read" })),
});
export function createReadTool(options) {
    return {
        name: "read",
        label: "read",
        description: `Read the contents of a file. Supports text files and images (jpg, png, gif, webp, bmp). Images are sent as attachments. For text files, output has no truncation limit. Use offset/limit for large files. When you need the full file, continue with offset until complete.`,
        parameters: readSchema,
        async execute(_toolCallId, { path, offset, limit }, signal, _onUpdate, { env }) {
            const absolutePath = await resolveReadToolPath(env, path, signal);
            const bytes = getOrThrow(await env.readBinaryFile(absolutePath, signal));
            const mimeType = detectSupportedImageMimeType(bytes);
            if (mimeType) {
                if (options?.imageProcessor) {
                    const processed = await options.imageProcessor(bytes, mimeType, {
                        autoResizeImages: options.autoResizeImages ?? true,
                    });
                    if (!processed.ok) {
                        return {
                            content: [{ type: "text", text: `Read image file [${mimeType}]\n${processed.message}` }],
                            details: undefined,
                        };
                    }
                    const hints = processed.hints.length > 0 ? `\n${processed.hints.join("\n")}` : "";
                    return {
                        content: [
                            { type: "text", text: `Read image file [${processed.mimeType}]${hints}` },
                            { type: "image", data: processed.data, mimeType: processed.mimeType },
                        ],
                        details: undefined,
                    };
                }
                if (mimeType === "image/bmp") {
                    return {
                        content: [
                            {
                                type: "text",
                                text: "Read image file [image/bmp]\n[Image omitted: configure an imageProcessor to convert BMP images.]",
                            },
                        ],
                        details: undefined,
                    };
                }
                return {
                    content: [
                        { type: "text", text: `Read image file [${mimeType}]` },
                        { type: "image", data: encodeBase64(bytes), mimeType },
                    ],
                    details: undefined,
                };
            }
            const textContent = new TextDecoder().decode(bytes);
            const allLines = textContent.split("\n");
            const totalFileLines = allLines.length;
            const startLine = offset ? Math.max(0, offset - 1) : 0;
            const startLineDisplay = startLine + 1;
            if (startLine >= allLines.length) {
                throw new Error(`Offset ${offset} is beyond end of file (${allLines.length} lines total)`);
            }
            let selectedContent;
            let userLimitedLines;
            if (limit !== undefined) {
                const endLine = Math.min(startLine + limit, allLines.length);
                selectedContent = allLines.slice(startLine, endLine).join("\n");
                userLimitedLines = endLine - startLine;
            }
            else {
                selectedContent = allLines.slice(startLine).join("\n");
            }
            // No truncation — preserve all content
            let outputText = selectedContent;
            if (userLimitedLines !== undefined && startLine + userLimitedLines < allLines.length) {
                const remaining = allLines.length - (startLine + userLimitedLines);
                const nextOffset = startLine + userLimitedLines + 1;
                outputText = `${outputText}\n\n[${remaining} more lines in file. Use offset=${nextOffset} to continue.]`;
            }
            return { content: [{ type: "text", text: outputText }], details: undefined };
        },
    };
}
//# sourceMappingURL=read.js.map