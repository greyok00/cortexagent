export type ImageProtocol = "kitty" | "iterm2" | null;
export interface TerminalCapabilities {
    images: ImageProtocol;
    trueColor: boolean;
    hyperlinks: boolean;
}
export interface CellDimensions {
    widthPx: number;
    heightPx: number;
}
export interface ImageDimensions {
    widthPx: number;
    heightPx: number;
}
export interface ImageRenderOptions {
    maxWidthCells?: number;
    maxHeightCells?: number;
    preserveAspectRatio?: boolean;
    imageId?: number;
    moveCursor?: boolean;
}
export declare function getCellDimensions(): CellDimensions;
export declare function setCellDimensions(dims: CellDimensions): void;
export declare function detectCapabilities(tmuxForwardsHyperlink?: () => boolean): TerminalCapabilities;
export declare function getCapabilities(): TerminalCapabilities;
export declare function resetCapabilitiesCache(): void;
export declare function setCapabilities(caps: TerminalCapabilities): void;
export declare function isImageLine(line: string): boolean;
export declare function allocateImageId(): number;
export declare function encodeKitty(base64Data: string, options?: {
    columns?: number;
    rows?: number;
    imageId?: number;
    moveCursor?: boolean;
}): string;
export declare function deleteKittyImage(imageId: number): string;
export declare function deleteAllKittyImages(): string;
export declare function deleteAllKittyPlacements(): string;
export declare function encodeITerm2(base64Data: string, options?: {
    width?: number | string;
    height?: number | string;
    name?: string;
    preserveAspectRatio?: boolean;
    inline?: boolean;
}): string;
export interface ImageCellSize {
    columns: number;
    rows: number;
}
export interface KittyImageMetadata extends ImageCellSize {
    imageId: number;
    widthPx: number;
    heightPx: number;
}
export interface KittyImagePlacement {
    imageId: number;
    transmissionGeneration: number;
    transmissionBytes: number;
    estimatedDecodedBytes: number;
    sequence: string;
    replacementLine: string;
}
export declare function registerKittyImageMetadata(metadata: KittyImageMetadata): void;
export declare function getKittyImageMetadata(line: string): KittyImageMetadata | undefined;
export declare function getKittyImagePlacement(line: string): KittyImagePlacement | undefined;
export declare function cropKittyImageLine(line: string, hiddenRows: number, visibleRows: number): string;
export declare function calculateImageCellSize(imageDimensions: ImageDimensions, maxWidthCells: number, maxHeightCells?: number, cellDimensions?: CellDimensions): ImageCellSize;
export declare function calculateImageRows(imageDimensions: ImageDimensions, targetWidthCells: number, cellDimensions?: CellDimensions): number;
export declare function getPngDimensions(base64Data: string): ImageDimensions | null;
export declare function getJpegDimensions(base64Data: string): ImageDimensions | null;
export declare function getGifDimensions(base64Data: string): ImageDimensions | null;
export declare function getWebpDimensions(base64Data: string): ImageDimensions | null;
export declare function getImageDimensions(base64Data: string, mimeType: string): ImageDimensions | null;
export declare function renderImage(base64Data: string, imageDimensions: ImageDimensions, options?: ImageRenderOptions): {
    sequence: string;
    columns: number;
    rows: number;
    imageId?: number;
} | null;
export declare function hyperlink(text: string, url: string): string;
export declare function imageFallback(mimeType: string, dimensions?: ImageDimensions, filename?: string): string;
//# sourceMappingURL=terminal-image.d.ts.map