import type { Theme } from "../../modes/interactive/theme/theme.ts";
import type { ToolDefinition } from "../extensions/types.ts";
export interface ToolHtmlRendererDeps {
    getToolDefinition: (name: string) => ToolDefinition | undefined;
    theme: Theme;
    cwd: string;
    width?: number;
}
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
export declare function createToolHtmlRenderer(deps: ToolHtmlRendererDeps): ToolHtmlRenderer;
//# sourceMappingURL=tool-renderer.d.ts.map