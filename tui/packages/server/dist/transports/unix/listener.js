import { createHash, randomUUID } from "node:crypto";
import { chmod, link, lstat, mkdir, rename, unlink } from "node:fs/promises";
import { createConnection, createServer } from "node:net";
import { dirname, join } from "node:path";
import { DEFAULT_MAX_FRAME_LENGTH } from "@cortexagent/protocol";
const DEFAULT_SOCKET_MODE = 0o600;
const DEFAULT_GRACEFUL_CLOSE_TIMEOUT_MS = 5_000;
const MAX_UINT32 = 0xffff_ffff;
const MAX_TIMER_DELAY_MS = 2_147_483_647;
const SOCKET_PROBE_TIMEOUT_MS = 1_000;
const MAX_UNIX_SOCKET_PATH_BYTES = process.platform === "linux" ? 107 : 103;
export function validateUnixSocketPath(path, description = "Unix socket path") {
    if (!path)
        throw new TypeError(`${description} must not be empty`);
    if (Buffer.byteLength(path) > MAX_UNIX_SOCKET_PATH_BYTES) {
        throw new TypeError(`${description} is too long; maximum is ${MAX_UNIX_SOCKET_PATH_BYTES} UTF-8 bytes`);
    }
}
class UnixListener {
    options;
    path;
    mode;
    connections = new Set();
    server;
    socketIdentity;
    ownedBindPath;
    boundPath;
    closing = false;
    closePromise;
    accept;
    constructor(options) {
        this.options = resolveUnixListenerOptions(options);
        this.path = this.options.path;
        this.mode = this.options.mode;
    }
    get address() {
        return this.boundPath;
    }
    async start(accept) {
        if (this.server)
            throw new Error("Unix listener is already started");
        if (this.closing)
            throw new Error("Unix listener is closing or closed");
        this.accept = accept;
        const ownedBindPath = getOwnedBindPath(this.path);
        validateUnixSocketPath(ownedBindPath, "CortexServer private Unix bind path");
        await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
        await removeStaleSocket(this.path);
        await removeStaleSocket(ownedBindPath);
        this.ownedBindPath = ownedBindPath;
        const server = createServer((socket) => this.acceptSocket(socket));
        server.on("error", (error) => this.reportError(error));
        this.server = server;
        try {
            await new Promise((resolve, reject) => {
                const onError = (error) => {
                    server.off("listening", onListening);
                    reject(error);
                };
                const onListening = () => {
                    server.off("error", onError);
                    resolve();
                };
                server.once("error", onError);
                server.once("listening", onListening);
                server.listen(ownedBindPath);
            });
            const stats = await lstat(ownedBindPath);
            if (!stats.isSocket())
                throw new Error(`Unix listener path is not a socket after binding: ${ownedBindPath}`);
            this.socketIdentity = { dev: stats.dev, ino: stats.ino };
            await link(ownedBindPath, this.path);
            await setSocketMode(this.path, this.mode);
            this.boundPath = this.path;
        }
        catch (error) {
            await this.closeServerAndCleanup(server);
            this.server = undefined;
            throw error;
        }
    }
    async close() {
        if (this.closePromise)
            return this.closePromise;
        this.closing = true;
        this.closePromise = this.closeInternal();
        return this.closePromise;
    }
    acceptSocket(socket) {
        if (this.closing) {
            socket.destroy();
            return;
        }
        const connection = new UnixByteConnection(socket, this.options.gracefulCloseTimeoutMs, this.options.maxPendingBytes);
        this.connections.add(connection);
        const accept = this.accept;
        if (!accept) {
            socket.destroy();
            return;
        }
        const handler = accept(connection);
        socket.on("data", (chunk) => {
            handler.onData(new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength));
        });
        socket.on("error", (error) => {
            handler.onError(error);
            socket.destroy();
        });
        socket.once("close", () => {
            connection.markClosed();
            this.connections.delete(connection);
            handler.onClose();
        });
    }
    async closeInternal() {
        this.boundPath = undefined;
        const serverClosed = this.server ? this.closeServerAndCleanup(this.server) : this.cleanupOwnedSocket();
        await Promise.all([...this.connections].map((connection) => connection.close()));
        await serverClosed;
        if (this.ownedBindPath)
            await removePath(this.ownedBindPath);
        this.ownedBindPath = undefined;
        this.connections.clear();
        this.server = undefined;
    }
    async closeServerAndCleanup(server) {
        try {
            await closeNetServer(server, (error) => this.reportError(error));
        }
        finally {
            await this.cleanupOwnedSocket();
            if (this.ownedBindPath)
                await removePath(this.ownedBindPath);
            this.ownedBindPath = undefined;
        }
    }
    async cleanupOwnedSocket() {
        const identity = this.socketIdentity;
        this.socketIdentity = undefined;
        if (!identity)
            return;
        let current;
        try {
            current = await lstat(this.path);
        }
        catch (error) {
            if (isErrorCode(error, "ENOENT"))
                return;
            throw error;
        }
        if (!current.isSocket() || current.dev !== identity.dev || current.ino !== identity.ino)
            return;
        const preserved = join(dirname(this.path), `.c-${randomUUID().slice(0, 6)}`);
        try {
            await rename(this.path, preserved);
        }
        catch (error) {
            if (isErrorCode(error, "ENOENT"))
                return;
            throw error;
        }
        const moved = await lstat(preserved);
        if (moved.isSocket() && moved.dev === identity.dev && moved.ino === identity.ino) {
            await removePath(preserved);
            return;
        }
        try {
            await lstat(this.path);
        }
        catch (error) {
            if (isErrorCode(error, "ENOENT"))
                await rename(preserved, this.path);
            else
                throw error;
        }
        throw new Error(`Unix listener path changed during cleanup; preserved replacement at ${preserved}`);
    }
    reportError(error) {
        try {
            this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
        }
        catch {
            // Error observers cannot affect listener state.
        }
    }
}
export class UnixByteConnection {
    socket;
    gracefulCloseTimeoutMs;
    maxPendingBytes;
    pendingBytes = 0;
    closedValue = false;
    closing = false;
    writeTail = Promise.resolve();
    closePromise;
    resolveClose;
    constructor(socket, gracefulCloseTimeoutMs, maxPendingBytes) {
        this.socket = socket;
        this.gracefulCloseTimeoutMs = gracefulCloseTimeoutMs;
        this.maxPendingBytes = maxPendingBytes;
    }
    get closed() {
        return this.closedValue;
    }
    send(chunk) {
        if (!(chunk instanceof Uint8Array)) {
            return Promise.reject(new TypeError("Unix connection chunks must be Uint8Array"));
        }
        if (this.closedValue || this.closing)
            return Promise.reject(new Error("Unix connection is closed"));
        if (this.pendingBytes + chunk.byteLength > this.maxPendingBytes) {
            return Promise.reject(new Error("Unix connection exceeded its pending byte limit"));
        }
        this.pendingBytes += chunk.byteLength;
        const bytes = chunk.slice();
        const write = this.writeTail.then(() => this.write(bytes));
        const tracked = write.finally(() => {
            this.pendingBytes -= bytes.byteLength;
        });
        this.writeTail = tracked.catch(() => { });
        return tracked;
    }
    close(finalChunk) {
        if (this.closedValue || this.socket.destroyed) {
            this.markClosed();
            return Promise.resolve();
        }
        if (this.closePromise)
            return this.closePromise;
        this.closing = true;
        const finalBytes = finalChunk?.slice();
        this.closePromise = new Promise((resolve) => {
            this.resolveClose = resolve;
            const timer = setTimeout(() => {
                if (!this.socket.destroyed)
                    this.socket.destroy();
                this.markClosed();
            }, this.gracefulCloseTimeoutMs);
            timer.unref();
            this.socket.once("close", () => clearTimeout(timer));
            void this.writeTail.then(() => {
                if (this.socket.destroyed) {
                    this.markClosed();
                    return;
                }
                try {
                    if (finalBytes)
                        this.socket.end(finalBytes);
                    else
                        this.socket.end();
                }
                catch {
                    this.socket.destroy();
                }
            });
        });
        return this.closePromise;
    }
    markClosed() {
        if (this.closedValue)
            return;
        this.closedValue = true;
        this.closing = true;
        this.resolveClose?.();
        this.resolveClose = undefined;
    }
    write(chunk) {
        if (this.closedValue || this.closing || !this.socket.writable) {
            return Promise.reject(new Error("Unix connection is closed"));
        }
        return new Promise((resolve, reject) => {
            let settled = false;
            const onClose = () => finish(new Error("Unix connection closed during write"));
            const finish = (error) => {
                if (settled)
                    return;
                settled = true;
                this.socket.off("close", onClose);
                if (error)
                    reject(error);
                else
                    resolve();
            };
            this.socket.once("close", onClose);
            try {
                this.socket.write(chunk, finish);
            }
            catch (error) {
                finish(error instanceof Error ? error : new Error(String(error)));
            }
        });
    }
}
function getOwnedBindPath(path) {
    const suffix = createHash("sha256").update(path).digest("hex").slice(0, 8);
    return join(dirname(path), `.p-${suffix}`);
}
async function removeStaleSocket(path) {
    let original;
    try {
        original = await lstat(path);
    }
    catch (error) {
        if (isErrorCode(error, "ENOENT"))
            return;
        throw error;
    }
    if (!original.isSocket())
        throw new Error(`Refusing to remove non-socket Unix listener path: ${path}`);
    if (await isSocketLive(path))
        throw new Error(`Unix listener is already running: ${path}`);
    const preserved = join(dirname(path), `.s-${randomUUID().slice(0, 6)}`);
    try {
        await rename(path, preserved);
    }
    catch (error) {
        if (isErrorCode(error, "ENOENT"))
            return;
        throw error;
    }
    const current = await lstat(preserved);
    if (!current.isSocket() || current.dev !== original.dev || current.ino !== original.ino) {
        try {
            await lstat(path);
        }
        catch (error) {
            if (isErrorCode(error, "ENOENT"))
                await rename(preserved, path);
            else
                throw error;
        }
        throw new Error(`Unix listener path changed while checking for a stale socket: ${path}`);
    }
    await removePath(preserved);
}
async function removePath(path) {
    try {
        await unlink(path);
    }
    catch (error) {
        if (!isErrorCode(error, "ENOENT"))
            throw error;
    }
}
function isSocketLive(path) {
    return new Promise((resolve, reject) => {
        const socket = createConnection(path);
        let settled = false;
        let timer;
        const finish = (result, error) => {
            if (settled)
                return;
            settled = true;
            if (timer)
                clearTimeout(timer);
            socket.removeAllListeners();
            socket.destroy();
            if (error)
                reject(error);
            else
                resolve(result);
        };
        socket.once("connect", () => finish(true));
        socket.once("error", (error) => {
            if (["ECONNREFUSED", "ENOENT", "EPIPE", "ECONNRESET"].includes(error.code ?? "")) {
                finish(false);
                return;
            }
            finish(false, error);
        });
        timer = setTimeout(() => finish(true), SOCKET_PROBE_TIMEOUT_MS);
        timer.unref();
    });
}
async function setSocketMode(path, mode) {
    if (process.platform === "win32")
        return;
    try {
        await chmod(path, mode);
    }
    catch (error) {
        if (!isErrorCode(error, "ENOSYS") && !isErrorCode(error, "ENOTSUP"))
            throw error;
    }
}
function closeNetServer(server, reportError) {
    if (!server.listening)
        return Promise.resolve();
    return new Promise((resolve) => {
        server.close((error) => {
            if (error)
                reportError(error);
            resolve();
        });
    });
}
function isErrorCode(error, code) {
    return error instanceof Error && "code" in error && error.code === code;
}
export function createUnixListener(options) {
    return new UnixListener(options);
}
function resolveUnixListenerOptions(options) {
    validateUnixSocketPath(options.path, "CortexServer Unix socket path");
    const mode = options.mode ?? DEFAULT_SOCKET_MODE;
    if (!Number.isInteger(mode) || mode < 0 || mode > 0o777) {
        throw new TypeError("CortexServer Unix socket mode must be an integer between 0 and 0o777");
    }
    const maxFrameLength = options.maxFrameLength ?? DEFAULT_MAX_FRAME_LENGTH;
    if (!Number.isSafeInteger(maxFrameLength) || maxFrameLength <= 0 || maxFrameLength > MAX_UINT32) {
        throw new TypeError(`CortexServer maxFrameLength must be an integer between 1 and ${MAX_UINT32}`);
    }
    const maxPendingBytes = options.maxPendingBytes ?? maxFrameLength * 4;
    if (!Number.isSafeInteger(maxPendingBytes) || maxPendingBytes < maxFrameLength + 4) {
        throw new TypeError("CortexServer maxPendingBytes must be a safe integer at least maxFrameLength + 4");
    }
    const gracefulCloseTimeoutMs = options.gracefulCloseTimeoutMs ?? DEFAULT_GRACEFUL_CLOSE_TIMEOUT_MS;
    if (!Number.isSafeInteger(gracefulCloseTimeoutMs) ||
        gracefulCloseTimeoutMs <= 0 ||
        gracefulCloseTimeoutMs > MAX_TIMER_DELAY_MS) {
        throw new TypeError(`CortexServer gracefulCloseTimeoutMs must be an integer between 1 and ${MAX_TIMER_DELAY_MS}`);
    }
    return {
        path: options.path,
        mode,
        maxPendingBytes,
        gracefulCloseTimeoutMs,
        onError: options.onError,
    };
}
//# sourceMappingURL=listener.js.map