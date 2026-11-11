import { type ThinkingLevel } from "@cortexagent/agent-core";
import { type Model } from "@cortexagent/ai/compat";
import { AgentSession } from "./agent-session.ts";
import type { LoadExtensionsResult, SessionStartEvent, ToolDefinition } from "./extensions/index.ts";
import { ModelRuntime } from "./model-runtime.ts";
import type { ResourceLoader } from "./resource-loader.ts";
import { SessionManager } from "./session-manager.ts";
import { SettingsManager } from "./settings-manager.ts";
import { createBashTool, createCodingTools, createEditTool, createFindTool, createGrepTool, createLsTool, createReadOnlyTools, createReadTool, createWriteTool, withFileMutationQueue } from "./tools/index.ts";
export interface CreateAgentSessionOptions {
    cwd?: string;
    agentDir?: string;
    modelRuntime?: ModelRuntime;
    model?: Model<any>;
    thinkingLevel?: ThinkingLevel;
    scopedModels?: Array<{
        model: Model<any>;
        thinkingLevel?: ThinkingLevel;
    }>;
    noTools?: "all" | "builtin";
    tools?: string[];
    excludeTools?: string[];
    customTools?: ToolDefinition[];
    resourceLoader?: ResourceLoader;
    sessionManager?: SessionManager;
    settingsManager?: SettingsManager;
    sessionStartEvent?: SessionStartEvent;
}
export interface CreateAgentSessionResult {
    session: AgentSession;
    extensionsResult: LoadExtensionsResult;
    modelFallbackMessage?: string;
}
export * from "./agent-session-runtime.ts";
export type { ExtensionAPI, ExtensionCommandContext, ExtensionContext, ExtensionFactory, InlineExtension, SlashCommandInfo, SlashCommandSource, ToolDefinition, } from "./extensions/index.ts";
export type { PromptTemplate } from "./prompt-templates.ts";
export type { Skill } from "./skills.ts";
export type { Tool } from "./tools/index.ts";
export { withFileMutationQueue, createCodingTools, createReadOnlyTools, createReadTool, createBashTool, createEditTool, createWriteTool, createGrepTool, createFindTool, createLsTool, };
export declare function createAgentSession(options?: CreateAgentSessionOptions): Promise<CreateAgentSessionResult>;
//# sourceMappingURL=sdk.d.ts.map