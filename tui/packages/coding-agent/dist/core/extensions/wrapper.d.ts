import type { AgentTool } from "@cortexagent/agent-core";
import type { ExtensionRunner } from "./runner.ts";
import type { RegisteredTool } from "./types.ts";
export declare function wrapRegisteredTool(registeredTool: RegisteredTool, runner: ExtensionRunner): AgentTool;
export declare function wrapRegisteredTools(registeredTools: RegisteredTool[], runner: ExtensionRunner): AgentTool[];
//# sourceMappingURL=wrapper.d.ts.map