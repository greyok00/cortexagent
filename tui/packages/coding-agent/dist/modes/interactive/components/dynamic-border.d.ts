import type { Component } from "@cortexagent/tui";
export declare class DynamicBorder implements Component {
    private color;
    constructor(color?: (str: string) => string);
    invalidate(): void;
    render(width: number): string[];
}
//# sourceMappingURL=dynamic-border.d.ts.map