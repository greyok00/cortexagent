import * as Diff from "diff";
export function detectLineEnding(content) {
    const crlfIdx = content.indexOf("\r\n");
    const lfIdx = content.indexOf("\n");
    if (lfIdx === -1)
        return "\n";
    if (crlfIdx === -1)
        return "\n";
    return crlfIdx < lfIdx ? "\r\n" : "\n";
}
export function normalizeToLF(text) {
    return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}
export function restoreLineEndings(text, ending) {
    return ending === "\r\n" ? text.replace(/\n/g, "\r\n") : text;
}
export function normalizeForFuzzyMatch(text) {
    return (text
        .normalize("NFKC")
        // Strip trailing whitespace per line
        .split("\n")
        .map((line) => line.trimEnd())
        .join("\n")
        // Smart single quotes → '
        .replace(/[\u2018\u2019\u201A\u201B]/g, "'")
        // Smart double quotes → "
        .replace(/[\u201C\u201D\u201E\u201F]/g, '"')
        // Various dashes/hyphens → -
        // U+2010 hyphen, U+2011 non-breaking hyphen, U+2012 figure dash,
        // U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar, U+2212 minus
        .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, "-")
        // Special spaces → regular space
        // U+00A0 NBSP, U+2002-U+200A various spaces, U+202F narrow NBSP,
        // U+205F medium math space, U+3000 ideographic space
        .replace(/[\u00A0\u2002-\u200A\u202F\u205F\u3000]/g, " "));
}
function splitLinesWithEndings(content) {
    return content.match(/[^\n]*\n|[^\n]+/g) ?? [];
}
function getLineSpans(content) {
    let offset = 0;
    return splitLinesWithEndings(content).map((line) => {
        const span = { start: offset, end: offset + line.length };
        offset = span.end;
        return span;
    });
}
function getReplacementLineRange(lines, replacement) {
    const replacementStart = replacement.matchIndex;
    const replacementEnd = replacement.matchIndex + replacement.matchLength;
    let startLine = -1;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (replacementStart >= line.start && replacementStart < line.end) {
            startLine = i;
            break;
        }
    }
    if (startLine === -1) {
        throw new Error("Replacement range is outside the base content.");
    }
    let endLine = startLine;
    while (endLine < lines.length && lines[endLine].end < replacementEnd) {
        endLine++;
    }
    if (endLine >= lines.length) {
        throw new Error("Replacement range is outside the base content.");
    }
    return { startLine, endLine: endLine + 1 };
}
function applyReplacements(content, replacements, offset = 0) {
    let result = content;
    for (let i = replacements.length - 1; i >= 0; i--) {
        const replacement = replacements[i];
        const matchIndex = replacement.matchIndex - offset;
        result =
            result.substring(0, matchIndex) + replacement.newText + result.substring(matchIndex + replacement.matchLength);
    }
    return result;
}
export function applyReplacementsPreservingUnchangedLines(originalContent, baseContent, replacements) {
    const originalLines = splitLinesWithEndings(originalContent);
    const baseLines = getLineSpans(baseContent);
    if (originalLines.length !== baseLines.length) {
        throw new Error("Cannot preserve unchanged lines because the base content has a different line count.");
    }
    const groups = [];
    const sortedReplacements = [...replacements].sort((a, b) => a.matchIndex - b.matchIndex);
    for (const replacement of sortedReplacements) {
        const range = getReplacementLineRange(baseLines, replacement);
        const current = groups[groups.length - 1];
        if (current && range.startLine < current.endLine) {
            current.endLine = Math.max(current.endLine, range.endLine);
            current.replacements.push(replacement);
            continue;
        }
        groups.push({ ...range, replacements: [replacement] });
    }
    let originalLineIndex = 0;
    let result = "";
    for (const group of groups) {
        result += originalLines.slice(originalLineIndex, group.startLine).join("");
        const groupStartOffset = baseLines[group.startLine].start;
        const groupEndOffset = baseLines[group.endLine - 1].end;
        result += applyReplacements(baseContent.slice(groupStartOffset, groupEndOffset), group.replacements, groupStartOffset);
        originalLineIndex = group.endLine;
    }
    result += originalLines.slice(originalLineIndex).join("");
    return result;
}
export function fuzzyFindText(content, oldText) {
    const exactIndex = content.indexOf(oldText);
    if (exactIndex !== -1) {
        return {
            found: true,
            index: exactIndex,
            matchLength: oldText.length,
            usedFuzzyMatch: false,
            contentForReplacement: content,
        };
    }
    const fuzzyContent = normalizeForFuzzyMatch(content);
    const fuzzyOldText = normalizeForFuzzyMatch(oldText);
    const fuzzyIndex = fuzzyContent.indexOf(fuzzyOldText);
    if (fuzzyIndex === -1) {
        return {
            found: false,
            index: -1,
            matchLength: 0,
            usedFuzzyMatch: false,
            contentForReplacement: content,
        };
    }
    return {
        found: true,
        index: fuzzyIndex,
        matchLength: fuzzyOldText.length,
        usedFuzzyMatch: true,
        contentForReplacement: fuzzyContent,
    };
}
export function stripBom(content) {
    return content.startsWith("\uFEFF") ? { bom: "\uFEFF", text: content.slice(1) } : { bom: "", text: content };
}
function countOccurrences(content, oldText) {
    const fuzzyContent = normalizeForFuzzyMatch(content);
    const fuzzyOldText = normalizeForFuzzyMatch(oldText);
    return fuzzyContent.split(fuzzyOldText).length - 1;
}
function getNotFoundError(path, editIndex, totalEdits) {
    if (totalEdits === 1) {
        return new Error(`Could not find the exact text in ${path}. The old text must match exactly including all whitespace and newlines.`);
    }
    return new Error(`Could not find edits[${editIndex}] in ${path}. The oldText must match exactly including all whitespace and newlines.`);
}
function getDuplicateError(path, editIndex, totalEdits, occurrences) {
    if (totalEdits === 1) {
        return new Error(`Found ${occurrences} occurrences of the text in ${path}. The text must be unique. Please provide more context to make it unique.`);
    }
    return new Error(`Found ${occurrences} occurrences of edits[${editIndex}] in ${path}. Each oldText must be unique. Please provide more context to make it unique.`);
}
function getEmptyOldTextError(path, editIndex, totalEdits) {
    if (totalEdits === 1) {
        return new Error(`oldText must not be empty in ${path}.`);
    }
    return new Error(`edits[${editIndex}].oldText must not be empty in ${path}.`);
}
function getNoChangeError(path, totalEdits) {
    if (totalEdits === 1) {
        return new Error(`No changes made to ${path}. The replacement produced identical content. This might indicate an issue with special characters or the text not existing as expected.`);
    }
    return new Error(`No changes made to ${path}. The replacements produced identical content.`);
}
export function applyEditsToNormalizedContent(normalizedContent, edits, path) {
    const normalizedEdits = edits.map((edit) => ({
        oldText: normalizeToLF(edit.oldText),
        newText: normalizeToLF(edit.newText),
    }));
    for (let i = 0; i < normalizedEdits.length; i++) {
        if (normalizedEdits[i].oldText.length === 0) {
            throw getEmptyOldTextError(path, i, normalizedEdits.length);
        }
    }
    const initialMatches = normalizedEdits.map((edit) => fuzzyFindText(normalizedContent, edit.oldText));
    const usedFuzzyMatch = initialMatches.some((match) => match.usedFuzzyMatch);
    const replacementBaseContent = usedFuzzyMatch ? normalizeForFuzzyMatch(normalizedContent) : normalizedContent;
    const matchedEdits = [];
    for (let i = 0; i < normalizedEdits.length; i++) {
        const edit = normalizedEdits[i];
        const matchResult = fuzzyFindText(replacementBaseContent, edit.oldText);
        if (!matchResult.found) {
            throw getNotFoundError(path, i, normalizedEdits.length);
        }
        const occurrences = countOccurrences(replacementBaseContent, edit.oldText);
        if (occurrences > 1) {
            throw getDuplicateError(path, i, normalizedEdits.length, occurrences);
        }
        matchedEdits.push({
            editIndex: i,
            matchIndex: matchResult.index,
            matchLength: matchResult.matchLength,
            newText: edit.newText,
        });
    }
    matchedEdits.sort((a, b) => a.matchIndex - b.matchIndex);
    for (let i = 1; i < matchedEdits.length; i++) {
        const previous = matchedEdits[i - 1];
        const current = matchedEdits[i];
        if (previous.matchIndex + previous.matchLength > current.matchIndex) {
            throw new Error(`edits[${previous.editIndex}] and edits[${current.editIndex}] overlap in ${path}. Merge them into one edit or target disjoint regions.`);
        }
    }
    const baseContent = normalizedContent;
    const newContent = usedFuzzyMatch
        ? applyReplacementsPreservingUnchangedLines(normalizedContent, replacementBaseContent, matchedEdits)
        : applyReplacements(replacementBaseContent, matchedEdits);
    if (baseContent === newContent) {
        throw getNoChangeError(path, normalizedEdits.length);
    }
    return { baseContent, newContent };
}
export function generateUnifiedPatch(path, oldContent, newContent, contextLines = 4) {
    return Diff.createTwoFilesPatch(path, path, oldContent, newContent, undefined, undefined, {
        context: contextLines,
        headerOptions: Diff.FILE_HEADERS_ONLY,
    });
}
export function generateDiffString(oldContent, newContent, contextLines = 4) {
    const parts = Diff.diffLines(oldContent, newContent);
    const output = [];
    const oldLines = oldContent.split("\n");
    const newLines = newContent.split("\n");
    const maxLineNum = Math.max(oldLines.length, newLines.length);
    const lineNumWidth = String(maxLineNum).length;
    let oldLineNum = 1;
    let newLineNum = 1;
    let lastWasChange = false;
    let firstChangedLine;
    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const raw = part.value.split("\n");
        if (raw[raw.length - 1] === "") {
            raw.pop();
        }
        if (part.added || part.removed) {
            if (firstChangedLine === undefined) {
                firstChangedLine = newLineNum;
            }
            for (const line of raw) {
                if (part.added) {
                    const lineNum = String(newLineNum).padStart(lineNumWidth, " ");
                    output.push(`+${lineNum} ${line}`);
                    newLineNum++;
                }
                else {
                    const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                    output.push(`-${lineNum} ${line}`);
                    oldLineNum++;
                }
            }
            lastWasChange = true;
        }
        else {
            const nextPartIsChange = i < parts.length - 1 && (parts[i + 1].added || parts[i + 1].removed);
            const hasLeadingChange = lastWasChange;
            const hasTrailingChange = nextPartIsChange;
            if (hasLeadingChange && hasTrailingChange) {
                if (raw.length <= contextLines * 2) {
                    for (const line of raw) {
                        const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                        output.push(` ${lineNum} ${line}`);
                        oldLineNum++;
                        newLineNum++;
                    }
                }
                else {
                    const leadingLines = raw.slice(0, contextLines);
                    const trailingLines = raw.slice(raw.length - contextLines);
                    const skippedLines = raw.length - leadingLines.length - trailingLines.length;
                    for (const line of leadingLines) {
                        const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                        output.push(` ${lineNum} ${line}`);
                        oldLineNum++;
                        newLineNum++;
                    }
                    output.push(` ${"".padStart(lineNumWidth, " ")} ...`);
                    oldLineNum += skippedLines;
                    newLineNum += skippedLines;
                    for (const line of trailingLines) {
                        const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                        output.push(` ${lineNum} ${line}`);
                        oldLineNum++;
                        newLineNum++;
                    }
                }
            }
            else if (hasLeadingChange) {
                const shownLines = raw.slice(0, contextLines);
                const skippedLines = raw.length - shownLines.length;
                for (const line of shownLines) {
                    const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                    output.push(` ${lineNum} ${line}`);
                    oldLineNum++;
                    newLineNum++;
                }
                if (skippedLines > 0) {
                    output.push(` ${"".padStart(lineNumWidth, " ")} ...`);
                    oldLineNum += skippedLines;
                    newLineNum += skippedLines;
                }
            }
            else if (hasTrailingChange) {
                const skippedLines = Math.max(0, raw.length - contextLines);
                if (skippedLines > 0) {
                    output.push(` ${"".padStart(lineNumWidth, " ")} ...`);
                    oldLineNum += skippedLines;
                    newLineNum += skippedLines;
                }
                for (const line of raw.slice(skippedLines)) {
                    const lineNum = String(oldLineNum).padStart(lineNumWidth, " ");
                    output.push(` ${lineNum} ${line}`);
                    oldLineNum++;
                    newLineNum++;
                }
            }
            else {
                oldLineNum += raw.length;
                newLineNum += raw.length;
            }
            lastWasChange = false;
        }
    }
    return { diff: output.join("\n"), firstChangedLine };
}
//# sourceMappingURL=edit-diff.js.map