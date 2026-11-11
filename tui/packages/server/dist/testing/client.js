import { once } from "node:events";
import { createConnection } from "node:net";
import { encodeClientMessage, PROTOCOL_VERSION, ServerMessageDecoder, } from "@cortexagent/protocol";
import { Deferred } from "./service.js";
export class ProtocolTestClient {
    messages = [];
    channel;
    decoder = new ServerMessageDecoder();
    waiters = new Set();
    closedDeferred = new Deferred();
    requestSequence = 0;
    closedValue = false;
    constructor(channel) {
        this.channel = channel;
    }
    get closed() {
        return this.closedValue;
    }
    hello(version = PROTOCOL_VERSION) {
        const response = this.next((message) => message.type === "hello" || message.type === "hello_error");
        void this.sendMessage({ type: "hello", version });
        return response;
    }
    async request(command, id = `request-${++this.requestSequence}`) {
        const response = this.next((message) => message.type === "response" && message.id === id);
        await this.sendMessage({ type: "request", id, request: command });
        return (await response);
    }
    sendMessage(message) {
        return this.channel.send(encodeClientMessage(message));
    }
    sendBytes(chunk) {
        return this.channel.send(chunk);
    }
    sendFragmentedMessage(message, splitAt) {
        return this.channel.sendFragmented(encodeClientMessage(message), splitAt);
    }
    next(predicate) {
        return this.nextFrom(0, predicate);
    }
    nextFrom(index, predicate) {
        const existing = this.messages.slice(index).find(predicate);
        if (existing)
            return Promise.resolve(existing);
        if (this.closedValue)
            return Promise.reject(new Error("Wire client is closed"));
        return new Promise((resolve, reject) => this.waiters.add({ predicate, resolve, reject }));
    }
    waitForClose() {
        return this.closedValue ? Promise.resolve() : this.closedDeferred.promise;
    }
    close() {
        return this.channel.close();
    }
    receive(chunk) {
        try {
            for (const message of this.decoder.push(chunk)) {
                this.messages.push(message);
                for (const waiter of this.waiters) {
                    if (!waiter.predicate(message))
                        continue;
                    this.waiters.delete(waiter);
                    waiter.resolve(message);
                }
            }
        }
        catch (error) {
            this.fail(error instanceof Error ? error : new Error(String(error)));
        }
    }
    markClosed() {
        if (this.closedValue)
            return;
        this.closedValue = true;
        this.closedDeferred.resolve(undefined);
        this.fail(new Error("Wire connection closed"));
    }
    fail(error) {
        for (const waiter of this.waiters)
            waiter.reject(error);
        this.waiters.clear();
    }
}
export async function connectUnixTestClient(path) {
    const socket = createConnection(path);
    await once(socket, "connect");
    const client = new ProtocolTestClient({
        send: (chunk) => writeSocket(socket, chunk),
        async sendFragmented(chunk, splitAt) {
            await writeSocket(socket, chunk.subarray(0, splitAt));
            await writeSocket(socket, chunk.subarray(splitAt));
        },
        async close() {
            if (socket.destroyed)
                return;
            const closed = once(socket, "close");
            socket.destroy();
            await closed;
        },
    });
    socket.on("data", (chunk) => {
        client.receive(new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength));
    });
    socket.on("error", (error) => client.fail(error));
    socket.once("close", () => client.markClosed());
    return client;
}
function writeSocket(socket, chunk) {
    return new Promise((resolve, reject) => {
        socket.write(chunk, (error) => {
            if (error)
                reject(error);
            else
                resolve();
        });
    });
}
//# sourceMappingURL=client.js.map