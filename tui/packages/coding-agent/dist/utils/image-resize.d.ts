import { type ImageResizeOptions, type ResizedImage } from "./image-resize-core.ts";
export type { ImageResizeOptions, ResizedImage } from "./image-resize-core.ts";
export declare function resizeImage(inputBytes: Uint8Array, mimeType: string, options?: ImageResizeOptions): Promise<ResizedImage | null>;
export declare function formatDimensionNote(result: ResizedImage): string | undefined;
//# sourceMappingURL=image-resize.d.ts.map