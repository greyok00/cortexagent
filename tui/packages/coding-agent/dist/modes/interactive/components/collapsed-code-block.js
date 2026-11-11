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
/**
 * Replace all fenced code blocks in markdown text with collapsed placeholders.
 * Returns the transformed text and a map of placeholders to their original content.
 */
export function collapseCodeBlocks(markdown) {
    const codeBlocks = [];
    let index = 0;
    let result = "";
    while (index < markdown.length) {
        const remaining = markdown.slice(index);
        // Find the first occurrence of ``` in the remaining text
        const firstBackticks = remaining.indexOf("```");
        if (firstBackticks === -1) {
            // No more code blocks found — exit loop, remaining text appended after
            break;
        }
        const codeBlockStart = index + firstBackticks;
        // Check if this is at the start of a line
        const atLineStart = codeBlockStart === 0 || markdown[codeBlockStart - 1] === "\n";
        if (!atLineStart) {
            // Not at line start — not a fenced code block, skip past it
            result += markdown.slice(index, codeBlockStart + 3);
            index = codeBlockStart + 3;
            continue;
        }
        // Count the number of backticks
        let btCount = 0;
        let btPos = codeBlockStart;
        while (btPos < markdown.length && markdown[btPos] === "`") {
            btCount++;
            btPos++;
        }
        const backtickPattern = "`".repeat(btCount);
        const contentStart = btPos;
        // Look for the closing backticks on their own line
        let closeIndex = -1;
        let searchPos = contentStart;
        while (searchPos < markdown.length) {
            const nextNewline = markdown.indexOf("\n", searchPos);
            if (nextNewline === -1)
                break;
            const lineStart = nextNewline + 1;
            const line = markdown.slice(lineStart);
            if (line.startsWith(backtickPattern) &&
                (line.length === btCount || line[btCount] === "\n" || line[btCount] === "\r" || line.length === btCount)) {
                closeIndex = lineStart;
                break;
            }
            searchPos = nextNewline + 1;
        }
        if (closeIndex === -1) {
            // Unclosed code block — leave it as-is
            result += markdown.slice(index);
            index = markdown.length;
            continue;
        }
        const codeContent = markdown.slice(contentStart, closeIndex);
        // Exclude the fence's language tag (first segment) and the trailing
        // newline before the closing fence from the visible line count.
        const lineCount = Math.max(0, codeContent.replace(/\n$/, "").split("\n").length - 1);
        // Collapsing must keep a visible placeholder (owner directive
        // 2026-09-23: deleting the block entirely hides commands the model
        // showed while streaming — placeholder restored 2026-09-23).
        const placeholder = `[Code Block (${lineCount} lines)]`;
        codeBlocks.push({
            placeholder,
            originalText: markdown.slice(index, closeIndex),
        });
        // Replace the code block with the placeholder, skipping past the
        // closing backticks. Preserve text before this code block that wasn't
        // part of a previous one.
        if (codeBlockStart > index) {
            result += markdown.slice(index, codeBlockStart);
        }
        result += placeholder;
        index = closeIndex + btCount;
    }
    // Append remaining text
    result += markdown.slice(index);
    return { transformed: result, codeBlocks };
}
//# sourceMappingURL=collapsed-code-block.js.map