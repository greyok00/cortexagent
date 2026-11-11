import type { ImageContent } from "@cortexagent/ai";
import type { AgentSessionRuntime } from "../core/agent-session-runtime.ts";
export interface PrintModeOptions {
    mode: "text" | "json";
    messages?: string[];
    initialMessage?: string;
    initialImages?: ImageContent[];
}
export declare function runPrintMode(runtimeHost: AgentSessionRuntime, options: PrintModeOptions): Promise<number>;
//# sourceMappingURL=print-mode.d.ts.map