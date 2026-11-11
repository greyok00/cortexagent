export declare function getGraphemeSegmenter(): Intl.Segmenter;
export declare function getWordSegmenter(): Intl.Segmenter;
export declare const cjkBreakRegex: RegExp;
export declare function visibleWidth(str: string): number;
export declare function stripTerminalSequences(str: string): string;
interface GraphemeCellRange {
    start: number;
    end: number;
}
export declare function getGraphemeCellRange(line: string, column: number): GraphemeCellRange | undefined;
export declare function getOsc8LinkAtColumn(line: string, column: number): string | undefined;
export declare function normalizeTerminalOutput(str: string): string;
export declare function extractAnsiCode(str: string, pos: number): {
    code: string;
    length: number;
} | null;
export declare function wrapTextWithAnsi(text: string, width: number): string[];
export declare const PUNCTUATION_REGEX: RegExp;
export declare function isWhitespaceChar(char: string): boolean;
export declare function isPunctuationChar(char: string): boolean;
export declare function applyBackgroundToLine(line: string, width: number, bgFn: (text: string) => string): string;
export declare function truncateToWidth(text: string, maxWidth: number, ellipsis?: string, pad?: boolean): string;
export declare function sliceByColumn(line: string, startCol: number, length: number, strict?: boolean): string;
export declare function sliceWithWidth(line: string, startCol: number, length: number, strict?: boolean): {
    text: string;
    width: number;
};
export declare function extractSegments(line: string, beforeEnd: number, afterStart: number, afterLen: number, strictAfter?: boolean): {
    before: string;
    beforeWidth: number;
    after: string;
    afterWidth: number;
};
export {};
//# sourceMappingURL=utils.d.ts.map