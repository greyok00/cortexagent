import type { AgentSession } from "./agent-session.ts";
import type { AgentSessionRuntimeDiagnostic, AgentSessionServices } from "./agent-session-services.ts";
import type { ProjectTrustContext, ReplacedSessionContext, SessionStartEvent } from "./extensions/index.ts";
import type { CreateAgentSessionResult } from "./sdk.ts";
import { SessionManager } from "./session-manager.ts";
export interface CreateAgentSessionRuntimeResult extends CreateAgentSessionResult {
    services: AgentSessionServices;
    diagnostics: AgentSessionRuntimeDiagnostic[];
}
export type CreateAgentSessionRuntimeFactory = (options: {
    cwd: string;
    agentDir: string;
    sessionManager: SessionManager;
    sessionStartEvent?: SessionStartEvent;
    projectTrustContext?: ProjectTrustContext;
}) => Promise<CreateAgentSessionRuntimeResult>;
export declare class SessionImportFileNotFoundError extends Error {
    readonly filePath: string;
    constructor(filePath: string);
}
export declare class AgentSessionRuntime {
    private rebindSession?;
    private beforeSessionInvalidate?;
    private _session;
    private _services;
    private readonly createRuntime;
    private _diagnostics;
    private _modelFallbackMessage?;
    constructor(_session: AgentSession, _services: AgentSessionServices, createRuntime: CreateAgentSessionRuntimeFactory, _diagnostics?: AgentSessionRuntimeDiagnostic[], _modelFallbackMessage?: string);
    get services(): AgentSessionServices;
    get session(): AgentSession;
    get cwd(): string;
    get diagnostics(): readonly AgentSessionRuntimeDiagnostic[];
    get modelFallbackMessage(): string | undefined;
    setRebindSession(rebindSession?: (session: AgentSession) => Promise<void>): void;
    setBeforeSessionInvalidate(beforeSessionInvalidate?: () => void): void;
    private emitBeforeSwitch;
    private emitBeforeFork;
    private teardownCurrent;
    private apply;
    private finishSessionReplacement;
    switchSession(sessionPath: string, options?: {
        cwdOverride?: string;
        withSession?: (ctx: ReplacedSessionContext) => Promise<void>;
        projectTrustContextFactory?: (cwd: string) => ProjectTrustContext;
    }): Promise<{
        cancelled: boolean;
    }>;
    newSession(options?: {
        parentSession?: string;
        setup?: (sessionManager: SessionManager) => Promise<void>;
        withSession?: (ctx: ReplacedSessionContext) => Promise<void>;
    }): Promise<{
        cancelled: boolean;
    }>;
    fork(entryId: string, options?: {
        position?: "before" | "at";
        withSession?: (ctx: ReplacedSessionContext) => Promise<void>;
    }): Promise<{
        cancelled: boolean;
        selectedText?: string;
    }>;
    importFromJsonl(inputPath: string, cwdOverride?: string): Promise<{
        cancelled: boolean;
    }>;
    dispose(): Promise<void>;
}
export declare function createAgentSessionRuntime(createRuntime: CreateAgentSessionRuntimeFactory, options: {
    cwd: string;
    agentDir: string;
    sessionManager: SessionManager;
    sessionStartEvent?: SessionStartEvent;
}): Promise<AgentSessionRuntime>;
export { type AgentSessionRuntimeDiagnostic, type AgentSessionServices, type CreateAgentSessionFromServicesOptions, type CreateAgentSessionServicesOptions, createAgentSessionFromServices, createAgentSessionServices, } from "./agent-session-services.ts";
//# sourceMappingURL=agent-session-runtime.d.ts.map