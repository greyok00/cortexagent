import type { ThinkingLevel } from "@cortexagent/agent-core";
import type { Model } from "@cortexagent/ai";
import type { SessionStartEvent, ToolDefinition } from "./extensions/index.ts";
import { ModelRuntime } from "./model-runtime.ts";
import { type DefaultResourceLoaderOptions, type ResourceLoader, type ResourceLoaderReloadOptions } from "./resource-loader.ts";
import { type CreateAgentSessionOptions, type CreateAgentSessionResult } from "./sdk.ts";
import type { SessionManager } from "./session-manager.ts";
import { SettingsManager } from "./settings-manager.ts";
export interface AgentSessionRuntimeDiagnostic {
    type: "info" | "warning" | "error";
    message: string;
}
export interface CreateAgentSessionServicesOptions {
    cwd: string;
    agentDir?: string;
    settingsManager?: SettingsManager;
    modelRuntime?: ModelRuntime;
    modelRuntimeSignal?: AbortSignal;
    extensionFlagValues?: Map<string, boolean | string>;
    resourceLoaderOptions?: Omit<DefaultResourceLoaderOptions, "cwd" | "agentDir" | "settingsManager">;
    resourceLoaderReloadOptions?: ResourceLoaderReloadOptions;
}
export interface CreateAgentSessionFromServicesOptions {
    services: AgentSessionServices;
    sessionManager: SessionManager;
    sessionStartEvent?: SessionStartEvent;
    model?: Model<any>;
    thinkingLevel?: ThinkingLevel;
    scopedModels?: Array<{
        model: Model<any>;
        thinkingLevel?: ThinkingLevel;
    }>;
    tools?: string[];
    excludeTools?: CreateAgentSessionOptions["excludeTools"];
    noTools?: CreateAgentSessionOptions["noTools"];
    customTools?: ToolDefinition[];
}
export interface AgentSessionServices {
    cwd: string;
    agentDir: string;
    modelRuntime: ModelRuntime;
    settingsManager: SettingsManager;
    resourceLoader: ResourceLoader;
    diagnostics: AgentSessionRuntimeDiagnostic[];
}
export declare function createAgentSessionServices(options: CreateAgentSessionServicesOptions): Promise<AgentSessionServices>;
export declare function createAgentSessionFromServices(options: CreateAgentSessionFromServicesOptions): Promise<CreateAgentSessionResult>;
//# sourceMappingURL=agent-session-services.d.ts.map