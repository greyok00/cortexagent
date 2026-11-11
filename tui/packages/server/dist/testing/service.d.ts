import type { ModelMetadata, ModelRef, SessionMetadata, SessionPhase, SessionSnapshot, ThinkingLevel, TranscriptProgress } from "@cortexagent/protocol";
import { CortexServerError } from "../errors.ts";
import type { CortexServerService, CortexSessionRuntime, CortexSessionRuntimeEvent, CreateSessionOptions, PromptInput } from "../types.ts";
export declare const TEST_MODEL: ModelMetadata;
export declare class Deferred<T> {
    readonly promise: Promise<T>;
    private resolvePromise;
    constructor();
    resolve(value: T): void;
}
interface StoredSession {
    snapshot: SessionSnapshot;
}
export declare class TestSessionRuntime implements CortexSessionRuntime {
    readonly disposed: Deferred<void>;
    disposeCount: number;
    readonly steers: PromptInput[];
    private readonly stored;
    private readonly onDispose;
    private readonly listeners;
    private pendingPrompt?;
    constructor(stored: StoredSession, onDispose: () => void);
    snapshot(): SessionSnapshot;
    getPhase(): SessionPhase;
    prompt(input: PromptInput): Promise<void>;
    steer(input: PromptInput): Promise<void>;
    abort(): Promise<void>;
    setModel(model: ModelRef): Promise<void>;
    setThinking(thinkingLevel: ThinkingLevel): Promise<void>;
    subscribe(listener: (event: CortexSessionRuntimeEvent) => void): () => void;
    dispose(): Promise<void>;
    setPhase(phase: SessionPhase): void;
    finishPrompt(): void;
    emitProgress(progress: TranscriptProgress): void;
    emitError(error: CortexServerError): void;
    emitSnapshot(): void;
    private update;
}
interface ListDelay {
    entered: Deferred<void>;
    release: Deferred<void>;
}
export declare class TestServerService implements CortexServerService {
    readonly sessions: Map<string, StoredSession>;
    readonly runtimes: Map<string, TestSessionRuntime[]>;
    readonly locked: Set<string>;
    lastCreatedId?: string;
    private nextListDelay?;
    listSessions(): Promise<SessionMetadata[]>;
    listModels(): Promise<ModelMetadata[]>;
    createSession(options: CreateSessionOptions): Promise<CortexSessionRuntime>;
    openSession(sessionId: string): Promise<CortexSessionRuntime>;
    seed(id?: string, name?: string, cwd?: string, model?: ModelRef, thinkingLevel?: ThinkingLevel): void;
    delayNextList(): ListDelay;
    latestRuntime(id: string): TestSessionRuntime;
    private acquire;
}
export {};
//# sourceMappingURL=service.d.ts.map