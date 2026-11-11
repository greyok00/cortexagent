import type { Component } from "../tui.ts";
export declare class Spacer implements Component {
    private lines;
    constructor(lines?: number);
    setLines(lines: number): void;
    invalidate(): void;
    render(_width: number): string[];
}
//# sourceMappingURL=spacer.d.ts.map