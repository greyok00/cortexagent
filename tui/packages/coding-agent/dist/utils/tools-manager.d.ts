export declare function getToolPath(tool: "fd" | "rg"): string | null;
export interface ToolStatus {
    type: "info" | "warning";
    message: string;
}
export declare function ensureTool(tool: "fd" | "rg", onStatus?: (status: ToolStatus) => void): Promise<string | undefined>;
//# sourceMappingURL=tools-manager.d.ts.map