export interface ExecOptions {
    signal?: AbortSignal;
    timeout?: number;
    cwd?: string;
}
export interface ExecResult {
    stdout: string;
    stderr: string;
    code: number;
    killed: boolean;
}
export declare function execCommand(command: string, args: string[], cwd: string, options?: ExecOptions): Promise<ExecResult>;
//# sourceMappingURL=exec.d.ts.map