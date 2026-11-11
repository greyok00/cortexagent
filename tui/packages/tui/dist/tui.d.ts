import type { Terminal } from "./terminal.ts";
import { type RgbColor, type TerminalColorScheme } from "./terminal-colors.ts";
import { visibleWidth } from "./utils.ts";
export interface Component {
    render(width: number): string[];
    handleInput?(data: string): void;
    wantsKeyRelease?: boolean;
    invalidate(): void;
}
export type TuiInputListenerResult = {
    consume?: boolean;
    data?: string;
} | undefined;
export type TuiInputListener = (data: string) => TuiInputListenerResult;
export interface Focusable {
    focused: boolean;
}
export declare function isFocusable(component: Component | null): component is Component & Focusable;
export declare const CURSOR_MARKER = "\u001B_pi:c\u0007";
export { visibleWidth };
export type OverlayAnchor = "center" | "top-left" | "top-right" | "bottom-left" | "bottom-right" | "top-center" | "bottom-center" | "left-center" | "right-center";
export interface OverlayMargin {
    top?: number;
    right?: number;
    bottom?: number;
    left?: number;
}
export type SizeValue = number | `${number}%`;
export interface OverlayOptions {
    width?: SizeValue;
    minWidth?: number;
    maxHeight?: SizeValue;
    anchor?: OverlayAnchor;
    offsetX?: number;
    offsetY?: number;
    row?: SizeValue;
    col?: SizeValue;
    margin?: OverlayMargin | number;
    visible?: (termWidth: number, termHeight: number) => boolean;
    nonCapturing?: boolean;
}
export interface OverlayUnfocusOptions {
    target: Component | null;
}
export interface OverlayHandle {
    hide(): void;
    setHidden(hidden: boolean): void;
    isHidden(): boolean;
    focus(): void;
    unfocus(options?: OverlayUnfocusOptions): void;
    isFocused(): boolean;
}
export declare class Container implements Component {
    children: Component[];
    addChild(component: Component): void;
    removeChild(component: Component): void;
    clear(): void;
    invalidate(): void;
    render(width: number): string[];
}
export declare function compositeTuiLine(baseLine: string, overlayLine: string, startCol: number, overlayWidth: number, totalWidth: number): string;
export type TuiMode = "regular" | "fullscreen";
export interface TuiStopOptions {
    preserveScreen?: boolean;
}
export interface TUI extends Component {
    readonly mode: TuiMode;
    children: Component[];
    terminal: Terminal;
    onDebug?: () => void;
    readonly fullRedraws: number;
    addChild(component: Component): void;
    removeChild(component: Component): void;
    clear(): void;
    getShowHardwareCursor(): boolean;
    setShowHardwareCursor(enabled: boolean): void;
    getClearOnShrink(): boolean;
    setClearOnShrink(enabled: boolean): void;
    setFocus(component: Component | null): void;
    showOverlay(component: Component, options?: OverlayOptions): OverlayHandle;
    hideOverlay(): void;
    hasOverlay(): boolean;
    start(): void;
    stop(options?: TuiStopOptions): void;
    renderNow(force?: boolean): void;
    requestRender(force?: boolean): void;
    addInputListener(listener: TuiInputListener): () => void;
    removeInputListener(listener: TuiInputListener): void;
    onTerminalColorSchemeChange(listener: (scheme: TerminalColorScheme) => void): () => void;
    setTerminalColorSchemeNotifications(enabled: boolean): void;
    queryTerminalBackgroundColor(options: {
        timeoutMs: number;
    }): Promise<RgbColor | undefined>;
    queryTerminalColorScheme(options: {
        timeoutMs: number;
    }): Promise<TerminalColorScheme | undefined>;
}
export declare const VIEWPORT_TUI: unique symbol;
export interface ViewportTUI extends TUI {
    readonly [VIEWPORT_TUI]: true;
    setLayoutRoot(component: Component | undefined): void;
}
export declare function isViewportTUI(tui: TUI): tui is ViewportTUI;
export declare abstract class TuiBase extends Container implements TUI {
    abstract readonly mode: TuiMode;
    terminal: Terminal;
    private focusedComponent;
    private inputListeners;
    onDebug?: () => void;
    private renderRequested;
    private immediateRenderScheduled;
    private renderTimer;
    private lastRenderAt;
    private static readonly MIN_RENDER_INTERVAL_MS;
    private showHardwareCursor;
    private clearOnShrink;
    protected fullRedrawCount: number;
    protected stopped: boolean;
    private pendingOsc11BackgroundReplies;
    private pendingOsc11BackgroundQueries;
    private terminalColorSchemeListeners;
    private terminalColorSchemeNotificationsEnabled;
    protected readonly logDirectory: string;
    private focusOrderCounter;
    private overlayStack;
    get hasOverlayEntries(): boolean;
    private overlayFocusRestore;
    constructor(terminal: Terminal, showHardwareCursor?: boolean, logDirectory?: string);
    protected abstract doRender(): void;
    protected resetRenderState(): void;
    protected beforeTerminalStart(): void;
    protected afterTerminalStart(): void;
    protected beforeTerminalStop(_options: TuiStopOptions): void;
    protected afterTerminalStop(_options: TuiStopOptions): void;
    get fullRedraws(): number;
    getShowHardwareCursor(): boolean;
    setShowHardwareCursor(enabled: boolean): void;
    getClearOnShrink(): boolean;
    setClearOnShrink(enabled: boolean): void;
    getFocusedComponent(): Component | null;
    setFocus(component: Component | null): void;
    private setFocusInternal;
    private clearOverlayFocusRestore;
    private clearOverlayFocusRestoreFor;
    private resolveBlockedOverlayFocusResume;
    private getVisibleOverlayFocusRestore;
    private isOverlayFocusAncestor;
    private retargetOverlayPreFocus;
    protected getMountedRoots(): readonly Component[];
    private isComponentMounted;
    private containsComponent;
    showOverlay(component: Component, options?: OverlayOptions): OverlayHandle;
    hideOverlay(): void;
    hasOverlay(): boolean;
    protected isOverlayFocused(): boolean;
    private isOverlayVisible;
    private getTopmostVisibleOverlay;
    invalidate(): void;
    start(): void;
    addInputListener(listener: TuiInputListener): () => void;
    removeInputListener(listener: TuiInputListener): void;
    onTerminalColorSchemeChange(listener: (scheme: TerminalColorScheme) => void): () => void;
    setTerminalColorSchemeNotifications(enabled: boolean): void;
    private queryCellSize;
    stop(options?: TuiStopOptions): void;
    renderNow(force?: boolean): void;
    requestRender(force?: boolean): void;
    private requestImmediateRender;
    private cancelRenderTimer;
    private scheduleRender;
    private handleTerminalInput;
    private consumeOsc11BackgroundResponse;
    private consumeTerminalColorSchemeReport;
    private consumeCellSizeResponse;
    private resolveOverlayLayout;
    private resolveAnchorRow;
    private resolveAnchorCol;
    protected compositeOverlays(lines: string[], termWidth: number, termHeight: number): string[];
    protected applyLineResets(lines: string[]): string[];
    private compositeLineAt;
    protected extractCursorPosition(lines: string[], height: number): {
        row: number;
        col: number;
    } | null;
    queryTerminalBackgroundColor({ timeoutMs }: {
        timeoutMs: number;
    }): Promise<RgbColor | undefined>;
    queryTerminalColorScheme({ timeoutMs }: {
        timeoutMs: number;
    }): Promise<TerminalColorScheme | undefined>;
}
//# sourceMappingURL=tui.d.ts.map