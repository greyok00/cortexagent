import type { ImageContent, TextContent } from "@cortexagent/ai";
import { processImage } from "./image-process.ts";

export type ToolResultContent = TextContent | ImageContent;

export interface NormalizeToolResultImagesOptions {
	autoResizeImages?: boolean;
}

export async function normalizeToolResultImages(
	content: ToolResultContent[],
	options?: NormalizeToolResultImagesOptions,
): Promise<ToolResultContent[]> {
	if (!content.some((block) => block.type === "image")) {
		return content;
	}

	const autoResizeImages = options?.autoResizeImages ?? true;
	const normalized: ToolResultContent[] = [];
	let changed = false;

	for (const block of content) {
		if (block.type !== "image") {
			normalized.push(block);
			continue;
		}

		const processed = await processImage(Buffer.from(block.data, "base64"), block.mimeType, { autoResizeImages });
		if (!processed.ok) {
			normalized.push(block);
			continue;
		}

		if (processed.data === block.data && processed.mimeType === block.mimeType && processed.hints.length === 0) {
			normalized.push(block);
			continue;
		}

		normalized.push({ type: "image", data: processed.data, mimeType: processed.mimeType });
		if (processed.hints.length > 0) {
			normalized.push({ type: "text", text: processed.hints.join("\n") });
		}
		changed = true;
	}

	return changed ? normalized : content;
}
