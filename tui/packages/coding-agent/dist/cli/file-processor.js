import { access, readFile, stat } from "node:fs/promises";
import chalk from "chalk";
import { resolve } from "path";
import { resolveReadPath } from "../core/tools/path-utils.js";
import { processImage } from "../utils/image-process.js";
import { detectSupportedImageMimeTypeFromFile } from "../utils/mime.js";
export async function processFileArguments(fileArgs, options) {
    const autoResizeImages = options?.autoResizeImages ?? true;
    let text = "";
    const images = [];
    for (const fileArg of fileArgs) {
        const absolutePath = resolve(resolveReadPath(fileArg, process.cwd()));
        try {
            await access(absolutePath);
        }
        catch {
            console.error(chalk.red(`Error: File not found: ${absolutePath}`));
            process.exit(1);
        }
        const stats = await stat(absolutePath);
        if (stats.size === 0) {
            continue;
        }
        const mimeType = await detectSupportedImageMimeTypeFromFile(absolutePath);
        if (mimeType) {
            const content = await readFile(absolutePath);
            const processed = await processImage(content, mimeType, { autoResizeImages });
            if (!processed.ok) {
                text += `<file name="${absolutePath}">${processed.message}</file>\n`;
                continue;
            }
            const attachment = {
                type: "image",
                mimeType: processed.mimeType,
                data: processed.data,
            };
            images.push(attachment);
            if (processed.hints.length > 0) {
                text += `<file name="${absolutePath}">${processed.hints.join("\n")}</file>\n`;
            }
            else {
                text += `<file name="${absolutePath}"></file>\n`;
            }
        }
        else {
            try {
                const content = await readFile(absolutePath, "utf-8");
                text += `<file name="${absolutePath}">\n${content}\n</file>\n`;
            }
            catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                console.error(chalk.red(`Error: Could not read file ${absolutePath}: ${message}`));
                process.exit(1);
            }
        }
    }
    return { text, images };
}
//# sourceMappingURL=file-processor.js.map