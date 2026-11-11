import { randomUUID } from "node:crypto";
import { ClientMessageDecoder, DEFAULT_MAX_FRAME_LENGTH, encodeServerMessage, isSupportedProtocolVersion, PROTOCOL_VERSION, ProtocolValidationError, } from "@cortexagent/protocol";
import { isTerminalConnection, } from "./connection.js";
import { CortexServerError, INTERNAL_SERVER_ERROR_MESSAGE, InternalServerError, NOT_IMPLEMENTED_MESSAGE, } from "./errors.js";
import { LiveSessionManager } from "./sessions.js";
import { ServerSnapshotPublisher } from "./snapshots.js";
const DEFAULT_HANDSHAKE_TIMEOUT_MS = 5_000;
const MAX_UINT32 = 0xffff_ffff;
const MAX_TIMER_DELAY_MS = 2_147_483_647;
export class CortexServer {
    id;
    listeners;
    maxFrameLength;
    handshakeTimeoutMs;
    onError;
    connections = new Set();
    sessions;
    snapshots;
    closing = false;
    closePromise;
    startPromise;
    started = false;
    constructor(service, options) {
        const resolved = resolveOptions(options);
        this.listeners = options.listeners;
        this.id = options.serverId ?? randomUUID();
        this.maxFrameLength = resolved.maxFrameLength;
        this.handshakeTimeoutMs = resolved.handshakeTimeoutMs;
        this.onError = options.onError;
        this.sessions = new LiveSessionManager({
            service,
            isClosing: () => this.closing,
            sendMessage: (connection, message) => this.sendMessage(connection, message),
            closeConnection: (connection) => this.closeConnection(connection),
            disconnect: (connection) => this.disconnect(connection),
            broadcastServerSnapshot: () => void this.snapshots.broadcast(),
            reportError: (error) => this.reportError(error),
        });
        this.snapshots = new ServerSnapshotPublisher({
            serverId: this.id,
            service,
            connections: this.connections,
            isClosing: () => this.closing,
            listSessions: () => this.sessions.listMetadata(),
            sendMessage: (connection, message) => this.sendMessage(connection, message),
            reportError: (error) => this.reportError(error),
        });
    }
    get addresses() {
        return this.listeners.flatMap((listener) => (listener.address === undefined ? [] : [listener.address]));
    }
    start() {
        if (this.started)
            return Promise.reject(new Error("CortexServer is already started"));
        if (this.startPromise)
            return Promise.reject(new Error("CortexServer is already starting"));
        if (this.closing)
            return Promise.reject(new Error("CortexServer is closing or closed"));
        this.startPromise = this.startInternal();
        return this.startPromise;
    }
    async startInternal() {
        const started = [];
        try {
            for (const listener of this.listeners) {
                await listener.start((connection) => this.accept(connection));
                started.push(listener);
            }
            this.started = true;
            return this;
        }
        catch (error) {
            this.closing = true;
            await Promise.allSettled(started.map((listener) => listener.close()));
            await this.closeServerState();
            throw error;
        }
        finally {
            this.startPromise = undefined;
        }
    }
    accept(connection) {
        if (this.closing) {
            void this.closeConnection(connection);
            return {
                onData: () => { },
                onClose: () => { },
                onError: (error) => this.reportError(error),
            };
        }
        let state;
        const handshakeTimeout = setTimeout(() => {
            void this.failProtocol(state, {
                code: "invalid_request",
                message: "Handshake timeout",
            });
        }, this.handshakeTimeoutMs);
        handshakeTimeout.unref();
        state = {
            id: randomUUID(),
            connection,
            decoder: new ClientMessageDecoder({ maxFrameLength: this.maxFrameLength }),
            sessionIds: new Set(),
            stage: "awaitingHello",
            disconnected: false,
            handshakeComplete: false,
            handshakeTimeout,
        };
        this.connections.add(state);
        return {
            onData: (chunk) => this.receive(state, chunk),
            onClose: () => this.transportClosed(state),
            onError: (error) => {
                this.reportError(error);
                void this.closeConnection(connection).then(() => this.disconnect(state));
            },
        };
    }
    async close() {
        if (this.closePromise)
            return this.closePromise;
        this.closing = true;
        this.closePromise = this.closeInternal();
        return this.closePromise;
    }
    async closeInternal() {
        const starting = this.startPromise;
        if (starting)
            await starting.catch(() => { });
        try {
            await Promise.all(this.listeners.map((listener) => listener.close()));
        }
        finally {
            await this.closeServerState();
            this.started = false;
        }
    }
    receive(state, chunk) {
        if (isTerminalConnection(state))
            return;
        let messages;
        try {
            messages = state.decoder.push(chunk);
        }
        catch (error) {
            void this.failProtocol(state, this.toProtocolError(error));
            return;
        }
        for (const message of messages) {
            if (isTerminalConnection(state))
                return;
            this.dispatchMessage(state, message);
        }
    }
    dispatchMessage(state, message) {
        if (state.stage === "awaitingHello") {
            if (message.type !== "hello") {
                void this.failProtocol(state, {
                    code: "invalid_request",
                    message: "The first client message must be hello",
                });
                return;
            }
            state.stage = "handshaking";
            state.handshake = this.finishHandshake(state, message).catch((error) => this.failProtocol(state, this.toProtocolError(error)));
            return;
        }
        if (message.type === "hello") {
            void this.failProtocol(state, {
                code: "invalid_request",
                message: "hello may only be sent as the first message",
            });
            return;
        }
        if (state.stage === "ready") {
            void this.handleRequest(state, message);
            return;
        }
        if (state.stage !== "handshaking")
            return;
        const handshake = state.handshake;
        if (!handshake)
            return;
        void handshake.then(() => {
            if (state.stage === "ready" && !state.disconnected)
                void this.handleRequest(state, message);
        });
    }
    async finishHandshake(state, hello) {
        if (!isSupportedProtocolVersion(hello.version)) {
            await this.failProtocol(state, {
                code: "version",
                message: `Unsupported protocol version ${hello.version}; expected ${PROTOCOL_VERSION}`,
            });
            return;
        }
        const snapshot = await this.snapshots.get();
        if (this.closing || state.disconnected || state.stage !== "handshaking" || state.connection.closed)
            return;
        const sent = await this.sendMessage(state, {
            type: "hello",
            version: PROTOCOL_VERSION,
            connectionId: state.id,
            snapshot,
        });
        if (sent && !state.disconnected && state.stage === "handshaking") {
            state.handshakeComplete = true;
            state.stage = "ready";
            clearTimeout(state.handshakeTimeout);
            if (snapshot.revision !== this.snapshots.currentRevision) {
                const current = await this.snapshots.get();
                await this.sendMessage(state, {
                    type: "event",
                    event: { type: "server_snapshot", snapshot: current },
                });
            }
        }
    }
    async handleRequest(state, envelope) {
        try {
            const result = await this.sessions.executeCommand(state, envelope.request);
            await this.sendMessage(state, {
                type: "response",
                id: envelope.id,
                ok: true,
                result,
            });
        }
        catch (error) {
            await this.sendMessage(state, {
                type: "response",
                id: envelope.id,
                ok: false,
                error: this.toProtocolError(error),
            });
        }
    }
    transportClosed(connection) {
        if (!connection.disconnected && connection.stage !== "closing") {
            try {
                connection.decoder.end();
            }
            catch (error) {
                this.reportError(error);
            }
        }
        void this.disconnect(connection);
    }
    async disconnect(connection) {
        if (connection.disconnected)
            return;
        const handshakeComplete = connection.handshakeComplete;
        connection.disconnected = true;
        connection.stage = "closed";
        clearTimeout(connection.handshakeTimeout);
        this.connections.delete(connection);
        await this.sessions.disconnect(connection);
        if (!this.closing && handshakeComplete)
            void this.snapshots.broadcast();
    }
    async sendMessage(connection, message) {
        if (connection.disconnected || connection.connection.closed)
            return false;
        let frame;
        try {
            frame = encodeServerMessage(message, { maxFrameLength: this.maxFrameLength });
        }
        catch (error) {
            this.reportError(error);
            await this.closeConnection(connection.connection);
            await this.disconnect(connection);
            return false;
        }
        try {
            await connection.connection.send(frame);
            return true;
        }
        catch (error) {
            this.reportError(error);
            await this.closeConnection(connection.connection);
            await this.disconnect(connection);
            return false;
        }
    }
    async failProtocol(connection, error) {
        if (connection.disconnected || connection.stage === "closing" || connection.stage === "closed")
            return;
        connection.stage = "closing";
        clearTimeout(connection.handshakeTimeout);
        const message = { type: "hello_error", error };
        let finalFrame;
        try {
            finalFrame = encodeServerMessage(message, { maxFrameLength: this.maxFrameLength });
        }
        catch (encodeError) {
            this.reportError(encodeError);
        }
        await this.closeConnection(connection.connection, finalFrame);
        await this.disconnect(connection);
    }
    async closeServerState() {
        const connections = [...this.connections];
        for (const connection of connections) {
            connection.stage = "closing";
            clearTimeout(connection.handshakeTimeout);
        }
        await Promise.all(connections.map((connection) => this.closeConnection(connection.connection)));
        await Promise.all(connections.map((connection) => this.disconnect(connection)));
        await this.sessions.close();
        this.connections.clear();
    }
    async closeConnection(connection, finalChunk) {
        try {
            await connection.close(finalChunk);
        }
        catch (error) {
            this.reportError(error);
        }
    }
    toProtocolError(error) {
        if (error instanceof InternalServerError) {
            this.reportError(error.cause);
            return { code: "internal_error", message: INTERNAL_SERVER_ERROR_MESSAGE };
        }
        if (error instanceof CortexServerError) {
            if (error.code === "not_implemented") {
                return { code: "not_implemented", message: NOT_IMPLEMENTED_MESSAGE };
            }
            return error.details === undefined
                ? { code: error.code, message: error.message }
                : { code: error.code, message: error.message, details: error.details };
        }
        if (error instanceof ProtocolValidationError) {
            return { code: "invalid_request", message: error.message };
        }
        this.reportError(error);
        return { code: "internal_error", message: INTERNAL_SERVER_ERROR_MESSAGE };
    }
    reportError(error) {
        try {
            this.onError?.(error instanceof Error ? error : new Error(String(error)));
        }
        catch {
            // Error observers cannot affect server state.
        }
    }
}
function resolveOptions(options) {
    if (!Array.isArray(options.listeners))
        throw new TypeError("CortexServer listeners must be an array");
    if (options.serverId === "")
        throw new TypeError("CortexServer serverId must not be empty");
    const maxFrameLength = options.maxFrameLength ?? DEFAULT_MAX_FRAME_LENGTH;
    if (!Number.isSafeInteger(maxFrameLength) || maxFrameLength <= 0 || maxFrameLength > MAX_UINT32) {
        throw new TypeError(`CortexServer maxFrameLength must be an integer between 1 and ${MAX_UINT32}`);
    }
    const handshakeTimeoutMs = options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS;
    if (!Number.isSafeInteger(handshakeTimeoutMs) ||
        handshakeTimeoutMs <= 0 ||
        handshakeTimeoutMs > MAX_TIMER_DELAY_MS) {
        throw new TypeError(`CortexServer handshakeTimeoutMs must be an integer between 1 and ${MAX_TIMER_DELAY_MS}`);
    }
    return { maxFrameLength, handshakeTimeoutMs };
}
//# sourceMappingURL=server.js.map