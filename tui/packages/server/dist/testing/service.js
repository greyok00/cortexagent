import { CortexServerError } from "../errors.js";
export const TEST_MODEL = {
    provider: "test",
    id: "small",
    name: "Test Small",
    api: "test-api",
    reasoning: true,
    input: ["text", "image"],
    contextWindow: 16_000,
    maxTokens: 2_000,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    supportedThinkingLevels: ["off", "medium", "high"],
    authenticated: true,
};
export class Deferred {
    promise;
    resolvePromise;
    constructor() {
        this.promise = new Promise((resolve) => {
            this.resolvePromise = resolve;
        });
    }
    resolve(value) {
        this.resolvePromise(value);
    }
}
export class TestSessionRuntime {
    disposed = new Deferred();
    disposeCount = 0;
    steers = [];
    stored;
    onDispose;
    listeners = new Set();
    pendingPrompt;
    constructor(stored, onDispose) {
        this.stored = stored;
        this.onDispose = onDispose;
    }
    snapshot() {
        return structuredClone(this.stored.snapshot);
    }
    getPhase() {
        return this.stored.snapshot.phase;
    }
    async prompt(input) {
        if (this.getPhase() !== "idle")
            throw new CortexServerError("busy", "A prompt is already running");
        const done = new Deferred();
        this.pendingPrompt = { input, done };
        this.update({
            phase: "turn",
            transcript: [
                ...this.stored.snapshot.transcript,
                {
                    id: `user-${this.stored.snapshot.revision + 1}`,
                    role: "user",
                    content: [{ type: "text", text: input.text }],
                    timestamp: this.stored.snapshot.revision + 1,
                },
            ],
        });
        const outcome = await done.promise;
        const assistant = outcome === "complete"
            ? {
                id: `assistant-${this.stored.snapshot.revision + 1}`,
                role: "assistant",
                content: [{ type: "text", text: `reply:${input.text}` }],
                status: "complete",
                model: this.stored.snapshot.model,
                stopReason: "stop",
                timestamp: this.stored.snapshot.revision + 1,
            }
            : {
                id: `assistant-${this.stored.snapshot.revision + 1}`,
                role: "assistant",
                content: [{ type: "text", text: "" }],
                status: "aborted",
                model: this.stored.snapshot.model,
                stopReason: "aborted",
                timestamp: this.stored.snapshot.revision + 1,
            };
        this.update({
            phase: "idle",
            transcript: [...this.stored.snapshot.transcript, assistant],
        });
        this.pendingPrompt = undefined;
    }
    async steer(input) {
        if (this.getPhase() === "idle")
            throw new CortexServerError("busy", "There is no active prompt to steer");
        this.steers.push(input);
        this.update({
            queuedSteerCount: this.stored.snapshot.queuedSteerCount + 1,
            queuedSteer: [
                ...this.stored.snapshot.queuedSteer,
                {
                    id: `steer-${this.stored.snapshot.revision + 1}`,
                    role: "user",
                    content: [{ type: "text", text: input.text }],
                    timestamp: this.stored.snapshot.revision + 1,
                },
            ],
        });
    }
    async abort() {
        if (!this.pendingPrompt)
            throw new CortexServerError("busy", "There is no active prompt to abort");
        this.pendingPrompt.done.resolve("aborted");
    }
    async setModel(model) {
        if (this.getPhase() !== "idle")
            throw new CortexServerError("busy", "Session is busy");
        this.update({ model });
    }
    async setThinking(thinkingLevel) {
        if (this.getPhase() !== "idle")
            throw new CortexServerError("busy", "Session is busy");
        this.update({ thinkingLevel });
    }
    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    async dispose() {
        this.disposeCount += 1;
        this.onDispose();
        this.disposed.resolve(undefined);
    }
    setPhase(phase) {
        this.stored.snapshot = { ...this.stored.snapshot, phase };
    }
    finishPrompt() {
        if (!this.pendingPrompt)
            throw new Error("No prompt is pending");
        this.pendingPrompt.done.resolve("complete");
    }
    emitProgress(progress) {
        for (const listener of this.listeners)
            listener({ type: "progress", progress });
    }
    emitError(error) {
        for (const listener of this.listeners)
            listener({ type: "error", error });
    }
    emitSnapshot() {
        for (const listener of this.listeners)
            listener({ type: "snapshot" });
    }
    update(updates) {
        this.stored.snapshot = {
            ...this.stored.snapshot,
            ...updates,
            revision: this.stored.snapshot.revision + 1,
            updatedAt: this.stored.snapshot.updatedAt + 1,
        };
        this.emitSnapshot();
    }
}
export class TestServerService {
    sessions = new Map();
    runtimes = new Map();
    locked = new Set();
    lastCreatedId;
    nextListDelay;
    async listSessions() {
        const delay = this.nextListDelay;
        if (delay) {
            this.nextListDelay = undefined;
            delay.entered.resolve(undefined);
            await delay.release.promise;
        }
        return [...this.sessions.values()].map(({ snapshot }) => ({
            id: snapshot.id,
            createdAt: snapshot.createdAt,
            updatedAt: snapshot.updatedAt,
            sessionName: snapshot.name,
            cwd: snapshot.cwd,
        }));
    }
    async listModels() {
        return [TEST_MODEL];
    }
    async createSession(options) {
        this.lastCreatedId = options.id;
        if (this.sessions.has(options.id))
            throw new CortexServerError("session_locked", "Session already exists");
        this.seed(options.id, options.name, options.cwd, options.model, options.thinkingLevel);
        return this.acquire(options.id);
    }
    async openSession(sessionId) {
        if (!this.sessions.has(sessionId))
            throw new CortexServerError("not_found", `Unknown session: ${sessionId}`);
        if (this.locked.has(sessionId))
            throw new CortexServerError("session_locked", `Session is locked: ${sessionId}`);
        return this.acquire(sessionId);
    }
    seed(id = "session-1", name = `Session ${id}`, cwd = "/tmp/cortex-agent-conformance", model = { provider: TEST_MODEL.provider, id: TEST_MODEL.id }, thinkingLevel = "off") {
        this.sessions.set(id, {
            snapshot: {
                id,
                name,
                cwd,
                createdAt: 1,
                updatedAt: 1,
                phase: "idle",
                model,
                thinkingLevel,
                attached: false,
                locked: false,
                revision: 0,
                transcript: [],
                queuedSteer: [],
                queuedSteerCount: 0,
            },
        });
    }
    delayNextList() {
        const delay = { entered: new Deferred(), release: new Deferred() };
        this.nextListDelay = delay;
        return delay;
    }
    latestRuntime(id) {
        const runtimes = this.runtimes.get(id);
        if (!runtimes?.length)
            throw new Error(`No runtime for ${id}`);
        return runtimes.at(-1);
    }
    acquire(id) {
        const stored = this.sessions.get(id);
        if (!stored)
            throw new Error(`Unknown session: ${id}`);
        this.locked.add(id);
        const runtime = new TestSessionRuntime(stored, () => this.locked.delete(id));
        const runtimes = this.runtimes.get(id) ?? [];
        runtimes.push(runtime);
        this.runtimes.set(id, runtimes);
        return runtime;
    }
}
//# sourceMappingURL=service.js.map