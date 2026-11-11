import { randomUUID } from "node:crypto";
import { CortexServerError } from "./errors.js";
function toMetadata(snapshot) {
    return {
        id: snapshot.id,
        createdAt: snapshot.createdAt,
        updatedAt: snapshot.updatedAt,
        sessionName: snapshot.name,
        cwd: snapshot.cwd,
    };
}
export class LiveSessionManager {
    options;
    liveSessions = new Map();
    openingSessions = new Map();
    constructor(options) {
        this.options = options;
    }
    async executeCommand(connection, command) {
        switch (command.command) {
            case "list":
                return { command: "list", sessions: await this.listMetadata() };
            case "create": {
                const id = randomUUID();
                const options = {
                    id,
                    cwd: command.cwd,
                    name: command.name,
                    model: command.model,
                    thinkingLevel: command.thinkingLevel,
                };
                const live = await this.acquire(id, () => this.options.service.createSession(options));
                await this.attach(connection, live);
                const session = this.forConnection(await this.broadcastSnapshot(live), connection);
                this.options.broadcastServerSnapshot();
                return { command: "create", session };
            }
            case "attach": {
                const live = await this.acquire(command.sessionId, () => this.options.service.openSession(command.sessionId));
                await this.attach(connection, live);
                const session = this.forConnection(await this.broadcastSnapshot(live), connection);
                this.options.broadcastServerSnapshot();
                return { command: "attach", session };
            }
            case "detach": {
                const live = this.liveSessions.get(command.sessionId);
                if (connection.sessionIds.has(command.sessionId)) {
                    connection.sessionIds.delete(command.sessionId);
                    if (live) {
                        live.connections.delete(connection);
                        if (live.connections.size > 0 && !live.terminal && !live.disposing) {
                            await this.broadcastSnapshot(live);
                        }
                        await this.maybeDispose(live);
                    }
                    this.options.broadcastServerSnapshot();
                }
                return { command: "detach", sessionId: command.sessionId };
            }
            case "prompt": {
                const live = this.requireAttached(connection, command.sessionId);
                const session = await this.runOperation(connection, live, () => live.runtime.prompt({ text: command.text }));
                return { command: "prompt", session };
            }
            case "steer": {
                const live = this.requireAttached(connection, command.sessionId);
                const session = await this.runOperation(connection, live, () => live.runtime.steer({ text: command.text }));
                return { command: "steer", session };
            }
            case "abort": {
                const live = this.requireAttached(connection, command.sessionId);
                const session = await this.runOperation(connection, live, () => live.runtime.abort());
                return { command: "abort", session };
            }
            case "set_model": {
                const live = this.requireAttached(connection, command.sessionId);
                const session = await this.runOperation(connection, live, () => live.runtime.setModel(command.model));
                return { command: "set_model", session };
            }
            case "set_thinking": {
                const live = this.requireAttached(connection, command.sessionId);
                const session = await this.runOperation(connection, live, () => live.runtime.setThinking(command.thinkingLevel));
                return { command: "set_thinking", session };
            }
        }
    }
    async disconnect(connection) {
        const sessions = [...connection.sessionIds]
            .map((id) => this.liveSessions.get(id))
            .filter((live) => live !== undefined);
        connection.sessionIds.clear();
        for (const live of sessions)
            live.connections.delete(connection);
        const results = await Promise.allSettled(sessions.map((live) => this.maybeDispose(live)));
        for (const result of results) {
            if (result.status === "rejected")
                this.options.reportError(result.reason);
        }
    }
    async listMetadata() {
        const stored = await this.options.service.listSessions();
        const liveSnapshots = await Promise.all([...this.liveSessions.values()]
            .filter((live) => !live.disposing)
            .map(async (live) => [live.id, await this.normalizedSnapshot(live)]));
        const liveById = new Map(liveSnapshots);
        const metadata = stored.map((item) => {
            const snapshot = liveById.get(item.id);
            if (!snapshot)
                return item;
            liveById.delete(item.id);
            return { ...item, ...toMetadata(snapshot) };
        });
        for (const snapshot of liveById.values())
            metadata.push(toMetadata(snapshot));
        return metadata;
    }
    async close() {
        const openingResults = await Promise.allSettled([...this.openingSessions.values()]);
        for (const result of openingResults) {
            if (result.status === "rejected")
                this.options.reportError(result.reason);
        }
        const sessions = [...this.liveSessions.values()];
        this.liveSessions.clear();
        await Promise.all(sessions.map(async (live) => {
            if (live.disposing) {
                await live.disposing;
                return;
            }
            live.unsubscribe();
            await live.runtime.dispose();
        }));
    }
    async runOperation(connection, live, operation) {
        live.operationCount += 1;
        try {
            await operation();
            return this.forConnection(await this.broadcastSnapshot(live), connection);
        }
        finally {
            live.operationCount -= 1;
            this.scheduleMaybeDispose(live);
        }
    }
    async acquire(id, acquireRuntime) {
        for (;;) {
            const existing = this.liveSessions.get(id);
            if (existing) {
                if (existing.terminal)
                    throw new CortexServerError("session_locked", `Session runtime is terminating: ${id}`);
                if (existing.disposing) {
                    await existing.disposing;
                    continue;
                }
                return existing;
            }
            const opening = this.openingSessions.get(id);
            if (opening)
                return opening;
            const pending = this.create(id, acquireRuntime);
            this.openingSessions.set(id, pending);
            try {
                return await pending;
            }
            finally {
                if (this.openingSessions.get(id) === pending)
                    this.openingSessions.delete(id);
            }
        }
    }
    async create(id, acquireRuntime) {
        const runtime = await acquireRuntime();
        if (this.options.isClosing()) {
            await runtime.dispose();
            throw new Error("CortexServer closed while acquiring a session runtime");
        }
        let live;
        try {
            const snapshot = await runtime.snapshot();
            if (snapshot.id !== id) {
                throw new CortexServerError("invalid_request", `Service returned session ${snapshot.id} for server-assigned session ${id}`);
            }
            live = {
                id,
                runtime,
                connections: new Set(),
                unsubscribe: () => { },
                operationCount: 0,
                ready: false,
                terminal: false,
            };
            live.unsubscribe = runtime.subscribe((event) => this.handleRuntimeEvent(live, event));
            this.liveSessions.set(id, live);
            live.ready = true;
            return live;
        }
        catch (error) {
            if (live)
                live.unsubscribe();
            try {
                await runtime.dispose();
            }
            catch (disposeError) {
                this.options.reportError(disposeError);
            }
            throw error;
        }
    }
    handleRuntimeEvent(live, event) {
        if (event.type === "error") {
            void this.terminate(live, event.error).catch((error) => this.options.reportError(error));
            return;
        }
        if (event.type === "progress") {
            const envelope = {
                type: "event",
                event: { type: "session_progress", sessionId: live.id, progress: event.progress },
            };
            for (const connection of live.connections)
                void this.options.sendMessage(connection, envelope);
        }
        else {
            void this.broadcastSnapshot(live).catch((error) => this.options.reportError(error));
        }
        this.scheduleMaybeDispose(live);
    }
    async terminate(live, error) {
        if (live.terminal)
            return;
        live.terminal = true;
        this.options.reportError(error);
        live.unsubscribe();
        const connections = [...live.connections];
        await Promise.all(connections.map((connection) => this.options.closeConnection(connection.connection)));
        await Promise.all(connections.map((connection) => this.options.disconnect(connection)));
        await this.maybeDispose(live);
    }
    async normalizedSnapshot(live) {
        const snapshot = await live.runtime.snapshot();
        if (snapshot.id !== live.id) {
            throw new CortexServerError("invalid_request", `Runtime session ID changed from ${live.id} to ${snapshot.id}`);
        }
        return {
            ...snapshot,
            phase: live.runtime.getPhase(),
            attached: live.connections.size > 0,
            locked: true,
        };
    }
    forConnection(snapshot, connection) {
        return { ...snapshot, attached: connection.sessionIds.has(snapshot.id) };
    }
    async broadcastSnapshot(live) {
        const snapshot = await this.normalizedSnapshot(live);
        const envelope = { type: "event", event: { type: "session_snapshot", snapshot } };
        for (const connection of live.connections)
            void this.options.sendMessage(connection, envelope);
        return snapshot;
    }
    async attach(connection, live) {
        if (connection.disconnected || connection.stage !== "ready" || connection.connection.closed) {
            await this.maybeDispose(live);
            throw new CortexServerError("invalid_request", "Connection closed while attaching to a session");
        }
        connection.sessionIds.add(live.id);
        live.connections.add(connection);
    }
    requireAttached(connection, sessionId) {
        if (!connection.sessionIds.has(sessionId)) {
            throw new CortexServerError("invalid_request", `Connection is not attached to session ${sessionId}`);
        }
        const live = this.liveSessions.get(sessionId);
        if (!live || live.terminal || live.disposing) {
            throw new CortexServerError("not_found", `Session is not live: ${sessionId}`);
        }
        return live;
    }
    scheduleMaybeDispose(live) {
        void this.maybeDispose(live).catch((error) => this.options.reportError(error));
    }
    async maybeDispose(live) {
        if (this.options.isClosing() ||
            !live.ready ||
            live.disposing ||
            live.connections.size > 0 ||
            live.operationCount > 0 ||
            (!live.terminal && live.runtime.getPhase() !== "idle")) {
            return live.disposing;
        }
        live.unsubscribe();
        live.disposing = (async () => {
            try {
                await live.runtime.dispose();
            }
            finally {
                if (this.liveSessions.get(live.id) === live)
                    this.liveSessions.delete(live.id);
            }
        })();
        await live.disposing;
        if (!this.options.isClosing())
            this.options.broadcastServerSnapshot();
    }
}
//# sourceMappingURL=sessions.js.map