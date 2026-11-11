import type { BashOperations } from "./tools/bash.ts";
export interface BashExecutorOptions {
    onChunk?: (chunk: string) => void;
    signal?: AbortSignal;
}
export interface BashResult {
    output: string;
    exitCode: number | undefined;
    cancelled: boolean;
    truncated: boolean;
    fullOutputPath?: string;
}
export declare function executeBashWithOperations(command: string, cwd: string, operations: BashOperations, options?: BashExecutorOptions): Promise<BashResult>;
//# sourceMappingURL=bash-executor.d.ts.map