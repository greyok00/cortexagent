import { Marked } from "@cortexagent/tui";
import { render } from "grok-mermaid";
const markdownParser = new Marked();
function isMermaid(token) {
    return token.type === "code" && token.lang?.trim().split(/\s+/, 1)[0]?.toLowerCase() === "mermaid";
}
function codeSpan(line) {
    const content = line || "\u00a0";
    const longestBacktickRun = Math.max(0, ...Array.from(content.matchAll(/`+/g), (match) => match[0].length));
    const fence = "`".repeat(longestBacktickRun + 1);
    const padding = content.startsWith("`") || content.endsWith("`") ? " " : "";
    return `${fence}${padding}${content}${padding}${fence}`;
}
function styleSpan(span, theme) {
    switch (span.cls) {
        case "border":
            return theme.fg("borderMuted", span.text);
        case "text":
            return theme.fg("text", span.text);
        case "edge":
            return theme.fg("accent", span.text);
        case "edgeLabel":
            return theme.fg("muted", span.text);
        case "title":
            return theme.fg("accent", theme.bold(span.text));
        case "none":
            return span.text;
    }
}
function themedLines(art, theme) {
    return art.styled.map((row) => row.map((span) => styleSpan(span, theme)).join(""));
}
export function createMermaidMarkdownTransformer(options) {
    return (markdown, context) => {
        const mode = options.getMode();
        if (mode === "off" ||
            context.messageType === "assistant-thinking" ||
            (context.isStreaming && mode !== "streaming")) {
            return markdown;
        }
        return markdownParser
            .lexer(markdown)
            .map((token) => {
            if (!isMermaid(token))
                return token.raw;
            const art = render(token.text);
            if (!art || art.width > context.availableWidth)
                return token.raw;
            if (!context.isStreaming && art.warnings.length > 0) {
                const suffix = art.warnings.length > 1 ? ` (+${art.warnings.length - 1} more)` : "";
                const warning = `Mermaid diagram not rendered: ${art.warnings[0]}${suffix}`;
                const styledWarning = options.theme ? options.theme.fg("warning", warning) : warning;
                return `${token.raw}\n${codeSpan(styledWarning)}  \n`;
            }
            const lines = options.theme ? themedLines(art, options.theme) : art.plain;
            return `${lines.map(codeSpan).join("  \n")}\n`;
        })
            .join("");
    };
}
//# sourceMappingURL=mermaid.js.map