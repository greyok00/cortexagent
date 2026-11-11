import { Container, type TUI } from "@cortexagent/tui";
import { type TruncationResult } from "../../../core/tools/truncate.ts";
export declare class BashExecutionComponent extends Container {
    private command;
    private outputLines;
    private status;
    private exitCode;
    private loader;
    private truncationResult?;
    private fullOutputPath?;
    private expanded;
    private contentContainer;
    constructor(command: string, ui: TUI, excludeFromContext?: boolean);
    setExpanded(expanded: boolean): void;
    invalidate(): void;
    appendOutput(chunk: string): void;
    setComplete(exitCode: number | undefined, cancelled: boolean, truncationResult?: TruncationResult, fullOutputPath?: string): void;
    private updateDisplay;
    getOutput(): string;
    getCommand(): string;
}
//# sourceMappingURL=bash-execution.d.ts.map