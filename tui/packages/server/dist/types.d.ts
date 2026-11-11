import type { Command, ModelMetadata, ModelRef, SessionMetadata, SessionPhase, SessionSnapshot, ThinkingLevel, TranscriptProgress } from "@cortexagent/protocol";
import type { CortexServerError } from "./errors.ts";
import type { CortexServerListener } from "./listener.ts";
export interface CortexServerOptions {
    listeners: readonly CortexServerListener[];
    maxFrameLength?: number;
    handshakeTimeoutMs?: number;
    serverId?: string;
    onError?: (error: Error) => void;
}
export type MaybePromise<T> = T | Promise<T>;
export type PromptInput = Omit<Extract<Command, {
    command: "prompt";
}>, "command" | "sessionId">;
export type SteerInput = Omit<Extract<Command, {
    command: "steer";
}>, "command" | "sessionId">;
export interface CreateSessionOptions {
    id: string;
    cwd?: string;
    name?: string;
    model?: ModelRef;
    thinkingLevel?: ThinkingLevel;
}
export type CortexSessionRuntimeEvent = {
    type: "snapshot";
} | {
    type: "progress";
    progress: TranscriptProgress;
} | {
    type: "error";
    error: CortexServerError;
};
export interface CortexSessionRuntime {
    snapshot(): MaybePromise<SessionSnapshot>;
    getPhase(): SessionPhase;
    prompt(input: PromptInput): Promise<void>;
    steer(input: SteerInput): Promise<void>;
    abort(): Promise<void>;
    setModel(model: ModelRef): Promise<void>;
    setThinking(thinkingLevel: ThinkingLevel): Promise<void>;
    subscribe(listener: (event: CortexSessionRuntimeEvent) => void): () => void;
    dispose(): Promise<void>;
}
export interface CortexServerService {
    listSessions(): Promise<SessionMetadata[]>;
    listModels(): Promise<ModelMetadata[]>;
    createSession(options: CreateSessionOptions): Promise<CortexSessionRuntime>;
    openSession(sessionId: string): Promise<CortexSessionRuntime>;
}
export type SessionRuntime = CortexSessionRuntime;
export type SessionRuntimeEvent = CortexSessionRuntimeEvent;
//# sourceMappingURL=types.d.ts.map