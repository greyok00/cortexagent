import type { AgentState } from "@cortexagent/agent-core";
import { SessionManager } from "../session-manager.ts";
export interface ToolHtmlRenderer {
    renderCall(toolCallId: string, toolName: string, args: unknown): string | undefined;
    renderResult(toolCallId: string, toolName: string, result: Array<{
        type: string;
        text?: string;
        data?: string;
        mimeType?: string;
    }>, details: unknown, isError: boolean): {
        collapsed?: string;
        expanded?: string;
    } | undefined;
}
export interface ExportOptions {
    outputPath?: string;
    themeName?: string;
    toolRenderer?: ToolHtmlRenderer;
}
export declare function exportSessionToHtml(sm: SessionManager, state?: AgentState, options?: ExportOptions | string): Promise<string>;
export declare function exportFromFile(inputPath: string, options?: ExportOptions | string): Promise<string>;
//# sourceMappingURL=index.d.ts.map