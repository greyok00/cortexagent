import type { AgentTool } from "@cortexagent/agent-core";
import type { ExtensionContext, ToolDefinition } from "../extensions/types.ts";
export declare function wrapToolDefinition<TDetails = unknown>(definition: ToolDefinition<any, TDetails>, ctxFactory?: () => ExtensionContext): AgentTool<any, TDetails>;
export declare function wrapToolDefinitions(definitions: ToolDefinition<any, any>[], ctxFactory?: () => ExtensionContext): AgentTool<any>[];
export declare function createToolDefinitionFromAgentTool(tool: AgentTool<any>): ToolDefinition<any, unknown>;
//# sourceMappingURL=tool-definition-wrapper.d.ts.map