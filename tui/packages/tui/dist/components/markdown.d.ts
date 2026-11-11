import type { Component } from "../tui.ts";
export interface DefaultTextStyle {
    color?: (text: string) => string;
    bgColor?: (text: string) => string;
    bold?: boolean;
    italic?: boolean;
    strikethrough?: boolean;
    underline?: boolean;
}
export interface MarkdownTheme {
    heading: (text: string) => string;
    link: (text: string) => string;
    linkUrl: (text: string) => string;
    code: (text: string) => string;
    codeBlock: (text: string) => string;
    codeBlockBorder: (text: string) => string;
    quote: (text: string) => string;
    quoteBorder: (text: string) => string;
    hr: (text: string) => string;
    listBullet: (text: string) => string;
    bold: (text: string) => string;
    italic: (text: string) => string;
    strikethrough: (text: string) => string;
    underline: (text: string) => string;
    highlightCode?: (code: string, lang?: string) => string[];
    codeBlockIndent?: string;
}
export interface MarkdownOptions {
    preserveOrderedListMarkers?: boolean;
    preserveBackslashEscapes?: boolean;
    transform?: (markdown: string, availableWidth: number) => string;
    renderLatex?: boolean;
}
export declare class Markdown implements Component {
    private text;
    private paddingX;
    private paddingY;
    private defaultTextStyle?;
    private theme;
    private options;
    private defaultStylePrefix?;
    private cachedText?;
    private cachedWidth?;
    private cachedLines?;
    constructor(text: string, paddingX: number, paddingY: number, theme: MarkdownTheme, defaultTextStyle?: DefaultTextStyle, options?: MarkdownOptions);
    setText(text: string): void;
    invalidate(): void;
    render(width: number): string[];
    private applyDefaultStyle;
    private getDefaultStylePrefix;
    private getStylePrefix;
    private getDefaultInlineStyleContext;
    private renderToken;
    private renderInlineTokens;
    private getOrderedListMarker;
    private getUnorderedListMarker;
    private renderList;
    private getLongestWordWidth;
    private wrapCellText;
    private renderTable;
}
//# sourceMappingURL=markdown.d.ts.map