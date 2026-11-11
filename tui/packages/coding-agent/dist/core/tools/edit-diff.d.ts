export declare function detectLineEnding(content: string): "\r\n" | "\n";
export declare function normalizeToLF(text: string): string;
export declare function restoreLineEndings(text: string, ending: "\r\n" | "\n"): string;
export declare function normalizeForFuzzyMatch(text: string): string;
interface MatchedEdit {
    editIndex: number;
    matchIndex: number;
    matchLength: number;
    newText: string;
}
type TextReplacement = Pick<MatchedEdit, "matchIndex" | "matchLength" | "newText">;
export declare function applyReplacementsPreservingUnchangedLines(originalContent: string, baseContent: string, replacements: TextReplacement[]): string;
export interface FuzzyMatchResult {
    found: boolean;
    index: number;
    matchLength: number;
    usedFuzzyMatch: boolean;
    contentForReplacement: string;
}
export interface Edit {
    oldText: string;
    newText: string;
}
export interface AppliedEditsResult {
    baseContent: string;
    newContent: string;
}
export declare function fuzzyFindText(content: string, oldText: string): FuzzyMatchResult;
export declare function stripBom(content: string): {
    bom: string;
    text: string;
};
export declare function applyEditsToNormalizedContent(normalizedContent: string, edits: Edit[], path: string): AppliedEditsResult;
export declare function generateUnifiedPatch(path: string, oldContent: string, newContent: string, contextLines?: number): string;
export declare function generateDiffString(oldContent: string, newContent: string, contextLines?: number): {
    diff: string;
    firstChangedLine: number | undefined;
};
export interface EditDiffResult {
    diff: string;
    firstChangedLine: number | undefined;
}
export interface EditDiffError {
    error: string;
}
export declare function computeEditsDiff(path: string, edits: Edit[], cwd: string): Promise<EditDiffResult | EditDiffError>;
export declare function computeEditDiff(path: string, oldText: string, newText: string, cwd: string): Promise<EditDiffResult | EditDiffError>;
export {};
//# sourceMappingURL=edit-diff.d.ts.map