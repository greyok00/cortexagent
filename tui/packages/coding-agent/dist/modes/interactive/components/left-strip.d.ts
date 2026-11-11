import { type Component } from "@cortexagent/tui";
export declare const STRIP_COLLAPSED_W = 5;
export declare const STRIP_EXPANDED_W = 22;
export declare const STRIP_ANIM_MS = 250;
export declare class LeftStripComponent implements Component {
    private _expanded;
    private _animWidth;
    private _animTarget;
    private _animStart;
    private _lastRenderAt;
    private readonly onChange;
    constructor(onChange: () => void);
    dispose(): void;
    invalidate(): void;
    isExpanded(): boolean;
    toggle(): void;
    /** Width the layout should currently allocate for this strip. Animates
     * toward the target. Always returns at least STRIP_COLLAPSED_W so even
     * mid-animation the strip is visible. */
    getWidth(): number;
    /** Called by the host every render tick so the animation advances. */
    tick(): void;
    render(maxWidth: number): string[];
    private renderExpanded;
}
//# sourceMappingURL=left-strip.d.ts.map