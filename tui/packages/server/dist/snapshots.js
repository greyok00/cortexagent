import { PROTOCOL_VERSION, } from "@cortexagent/protocol";
export class ServerSnapshotPublisher {
    options;
    revision = 0;
    broadcastQueue = Promise.resolve();
    constructor(options) {
        this.options = options;
    }
    get currentRevision() {
        return this.revision;
    }
    async get(models) {
        return {
            serverId: this.options.serverId,
            protocolVersion: PROTOCOL_VERSION,
            revision: this.revision,
            sessions: await this.options.listSessions(),
            models: models ?? (await this.options.service.listModels()),
        };
    }
    broadcast() {
        const broadcast = this.broadcastQueue.then(() => this.performBroadcast());
        this.broadcastQueue = broadcast.catch((error) => this.options.reportError(error));
        return broadcast;
    }
    async performBroadcast() {
        const readyConnections = [...this.options.connections].filter((connection) => connection.stage === "ready" && !connection.disconnected);
        if (readyConnections.length === 0 || this.options.isClosing())
            return;
        const revision = ++this.revision;
        const models = await this.options.service.listModels();
        const current = await this.get(models);
        const snapshot = { ...current, revision };
        const envelope = { type: "event", event: { type: "server_snapshot", snapshot } };
        for (const connection of readyConnections)
            await this.options.sendMessage(connection, envelope);
    }
}
//# sourceMappingURL=snapshots.js.map