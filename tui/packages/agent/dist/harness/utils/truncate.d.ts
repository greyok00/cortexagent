export declare const DEFAULT_MAX_LINES: number;
export declare const DEFAULT_MAX_BYTES: number;
export declare const GREP_MAX_LINE_LENGTH: number;
export interface TruncationResult {
    content: string;
    truncated: boolean;
    truncatedBy: "lines" | "bytes" | null;
    totalLines: number;
    totalBytes: number;
    outputLines: number;
    outputBytes: number;
    lastLinePartial: boolean;
    firstLineExceedsLimit: boolean;
    maxLines: number;
    maxBytes: number;
}
export interface TruncationOptions {
    maxLines?: number;
    maxBytes?: number;
}
export declare function formatSize(bytes: number): string;
export declare function truncateHead(content: string, options?: TruncationOptions): TruncationResult;
export declare function truncateTail(content: string, options?: TruncationOptions): TruncationResult;
export declare function truncateLine(line: string, maxChars?: number): {
    text: string;
    wasTruncated: boolean;
};
//# sourceMappingURL=truncate.d.ts.map