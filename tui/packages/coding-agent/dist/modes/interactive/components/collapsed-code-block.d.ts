/**
 * Collapses code blocks in markdown text to a placeholder line.
 *
 * When collapseCodeBlocks is enabled in settings, this function replaces
 * fenced code blocks with a single line like:
 *   `[Code Block (42 lines)]`
 *
 * This keeps the assistant's response compact while still showing that
 * code was generated. The user can see line counts to gauge scope.
 */
export interface CollapsedCodeBlock {
    placeholder: string;
    originalText: string;
}
/**
 * Replace all fenced code blocks in markdown text with collapsed placeholders.
 * Returns the transformed text and a map of placeholders to their original content.
 */
export declare function collapseCodeBlocks(markdown: string): {
    transformed: string;
    codeBlocks: CollapsedCodeBlock[];
};
//# sourceMappingURL=collapsed-code-block.d.ts.map