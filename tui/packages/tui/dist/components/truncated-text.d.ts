import type { Component } from "../tui.ts";
export declare class TruncatedText implements Component {
    private text;
    private paddingX;
    private paddingY;
    constructor(text: string, paddingX?: number, paddingY?: number);
    invalidate(): void;
    render(width: number): string[];
}
//# sourceMappingURL=truncated-text.d.ts.map