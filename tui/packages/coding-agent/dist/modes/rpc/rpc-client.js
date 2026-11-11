import { spawn } from "node:child_process";
import { attachJsonlLineReader, serializeJsonLine } from "./jsonl.js";
export class RpcClient {
    process = null;
    stopReadingStdout = null;
    eventListeners = [];
    pendingRequests = new Map();
    requestId = 0;
    stderr = "";
    exitError = null;
    options;
    constructor(options = {}) {
        this.options = options;
    }
    async start() {
        if (this.process) {
            throw new Error("Client already started");
        }
        this.exitError = null;
        const cliPath = this.options.cliPath ?? "dist/cli.js";
        const args = ["--mode", "rpc"];
        if (this.options.provider) {
            args.push("--provider", this.options.provider);
        }
        if (this.options.model) {
            args.push("--model", this.options.model);
        }
        if (this.options.args) {
            args.push(...this.options.args);
        }
        const childProcess = spawn("node", [cliPath, ...args], {
            cwd: this.options.cwd,
            env: { ...process.env, ...this.options.env },
            stdio: ["pipe", "pipe", "pipe"],
        });
        this.process = childProcess;
        childProcess.stderr?.on("data", (data) => {
            this.stderr += data.toString();
            process.stderr.write(data);
        });
        childProcess.once("exit", (code, signal) => {
            if (this.process !== childProcess)
                return;
            const error = this.createProcessExitError(code, signal);
            this.exitError = error;
            this.rejectPendingRequests(error);
        });
        childProcess.once("error", (error) => {
            if (this.process !== childProcess)
                return;
            const processError = new Error(`Agent process error: ${error.message}. Stderr: ${this.stderr}`);
            this.exitError = processError;
            this.rejectPendingRequests(processError);
        });
        childProcess.stdin?.on("error", (error) => {
            if (this.process !== childProcess)
                return;
            const stdinError = this.exitError ?? new Error(`Agent process stdin error: ${error.message}. Stderr: ${this.stderr}`);
            this.exitError = stdinError;
            this.rejectPendingRequests(stdinError);
        });
        this.stopReadingStdout = attachJsonlLineReader(childProcess.stdout, (line) => {
            this.handleLine(line);
        });
        await new Promise((resolve) => setTimeout(resolve, 100));
        if (this.process.exitCode !== null) {
            const error = this.exitError ?? this.createProcessExitError(this.process.exitCode, this.process.signalCode);
            this.exitError = error;
            throw error;
        }
    }
    async stop() {
        if (!this.process)
            return;
        this.stopReadingStdout?.();
        this.stopReadingStdout = null;
        this.process.kill("SIGTERM");
        await new Promise((resolve) => {
            const timeout = setTimeout(() => {
                this.process?.kill("SIGKILL");
                resolve();
            }, 1000);
            this.process?.on("exit", () => {
                clearTimeout(timeout);
                resolve();
            });
        });
        this.process = null;
        this.pendingRequests.clear();
    }
    onEvent(listener) {
        this.eventListeners.push(listener);
        return () => {
            const index = this.eventListeners.indexOf(listener);
            if (index !== -1) {
                this.eventListeners.splice(index, 1);
            }
        };
    }
    getStderr() {
        return this.stderr;
    }
    async prompt(message, images) {
        await this.send({ type: "prompt", message, images });
    }
    async steer(message, images) {
        await this.send({ type: "steer", message, images });
    }
    async followUp(message, images) {
        await this.send({ type: "follow_up", message, images });
    }
    async abort() {
        await this.send({ type: "abort" });
    }
    async newSession(parentSession) {
        const response = await this.send({ type: "new_session", parentSession });
        return this.getData(response);
    }
    async getState() {
        const response = await this.send({ type: "get_state" });
        return this.getData(response);
    }
    async setModel(provider, modelId) {
        const response = await this.send({ type: "set_model", provider, modelId });
        return this.getData(response);
    }
    async cycleModel() {
        const response = await this.send({ type: "cycle_model" });
        return this.getData(response);
    }
    async getAvailableModels() {
        const response = await this.send({ type: "get_available_models" });
        return this.getData(response).models;
    }
    async setThinkingLevel(level) {
        await this.send({ type: "set_thinking_level", level });
    }
    async cycleThinkingLevel() {
        const response = await this.send({ type: "cycle_thinking_level" });
        return this.getData(response);
    }
    async getAvailableThinkingLevels() {
        const response = await this.send({ type: "get_available_thinking_levels" });
        return this.getData(response).levels;
    }
    async setSteeringMode(mode) {
        await this.send({ type: "set_steering_mode", mode });
    }
    async setFollowUpMode(mode) {
        await this.send({ type: "set_follow_up_mode", mode });
    }
    async compact(customInstructions) {
        const response = await this.send({ type: "compact", customInstructions });
        return this.getData(response);
    }
    async setAutoCompaction(enabled) {
        await this.send({ type: "set_auto_compaction", enabled });
    }
    async setAutoRetry(enabled) {
        await this.send({ type: "set_auto_retry", enabled });
    }
    async abortRetry() {
        await this.send({ type: "abort_retry" });
    }
    async bash(command) {
        const response = await this.send({ type: "bash", command });
        return this.getData(response);
    }
    async abortBash() {
        await this.send({ type: "abort_bash" });
    }
    async getSessionStats() {
        const response = await this.send({ type: "get_session_stats" });
        return this.getData(response);
    }
    async exportHtml(outputPath) {
        const response = await this.send({ type: "export_html", outputPath });
        return this.getData(response);
    }
    async switchSession(sessionPath) {
        const response = await this.send({ type: "switch_session", sessionPath });
        return this.getData(response);
    }
    async fork(entryId) {
        const response = await this.send({ type: "fork", entryId });
        return this.getData(response);
    }
    async clone() {
        const response = await this.send({ type: "clone" });
        return this.getData(response);
    }
    async getForkMessages() {
        const response = await this.send({ type: "get_fork_messages" });
        return this.getData(response).messages;
    }
    async getEntries(since) {
        const response = await this.send({ type: "get_entries", since });
        return this.getData(response);
    }
    async getTree() {
        const response = await this.send({ type: "get_tree" });
        return this.getData(response);
    }
    async getLastAssistantText() {
        const response = await this.send({ type: "get_last_assistant_text" });
        return this.getData(response).text;
    }
    async setSessionName(name) {
        await this.send({ type: "set_session_name", name });
    }
    async getMessages() {
        const response = await this.send({ type: "get_messages" });
        return this.getData(response).messages;
    }
    async getCommands() {
        const response = await this.send({ type: "get_commands" });
        return this.getData(response).commands;
    }
    waitForIdle(timeout = 60000) {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                unsubscribe();
                reject(new Error(`Timeout waiting for agent to become idle. Stderr: ${this.stderr}`));
            }, timeout);
            const unsubscribe = this.onEvent((event) => {
                if (event.type === "agent_settled") {
                    clearTimeout(timer);
                    unsubscribe();
                    resolve();
                }
            });
        });
    }
    collectEvents(timeout = 60000) {
        return new Promise((resolve, reject) => {
            const events = [];
            const timer = setTimeout(() => {
                unsubscribe();
                reject(new Error(`Timeout collecting events. Stderr: ${this.stderr}`));
            }, timeout);
            const unsubscribe = this.onEvent((event) => {
                events.push(event);
                if (event.type === "agent_settled") {
                    clearTimeout(timer);
                    unsubscribe();
                    resolve(events);
                }
            });
        });
    }
    async promptAndWait(message, images, timeout = 60000) {
        const eventsPromise = this.collectEvents(timeout);
        await this.prompt(message, images);
        return eventsPromise;
    }
    handleLine(line) {
        try {
            const data = JSON.parse(line);
            if (data.type === "response" && data.id && this.pendingRequests.has(data.id)) {
                const pending = this.pendingRequests.get(data.id);
                this.pendingRequests.delete(data.id);
                pending.resolve(data);
                return;
            }
            for (const listener of this.eventListeners) {
                listener(data);
            }
        }
        catch {
            // Ignore non-JSON lines
        }
    }
    createProcessExitError(code, signal) {
        return new Error(`Agent process exited (code=${code} signal=${signal}). Stderr: ${this.stderr}`);
    }
    rejectPendingRequests(error) {
        for (const pending of this.pendingRequests.values()) {
            pending.reject(error);
        }
        this.pendingRequests.clear();
    }
    async send(command) {
        const childProcess = this.process;
        const stdin = childProcess?.stdin;
        if (!childProcess || !stdin) {
            throw new Error("Client not started");
        }
        if (this.exitError) {
            throw this.exitError;
        }
        if (childProcess.exitCode !== null) {
            const error = this.createProcessExitError(childProcess.exitCode, childProcess.signalCode);
            this.exitError = error;
            throw error;
        }
        if (stdin.destroyed || !stdin.writable) {
            const error = new Error(`Agent process stdin is not writable. Stderr: ${this.stderr}`);
            this.exitError = error;
            throw error;
        }
        const id = `req_${++this.requestId}`;
        const fullCommand = { ...command, id };
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                this.pendingRequests.delete(id);
                reject(new Error(`Timeout waiting for response to ${command.type}. Stderr: ${this.stderr}`));
            }, 30000);
            this.pendingRequests.set(id, {
                resolve: (response) => {
                    clearTimeout(timeout);
                    resolve(response);
                },
                reject: (error) => {
                    clearTimeout(timeout);
                    reject(error);
                },
            });
            try {
                stdin.write(serializeJsonLine(fullCommand));
            }
            catch (error) {
                const writeError = error instanceof Error ? error : new Error(String(error));
                const pending = this.pendingRequests.get(id);
                this.pendingRequests.delete(id);
                pending?.reject(writeError);
            }
        });
    }
    getData(response) {
        if (!response.success) {
            const errorResponse = response;
            throw new Error(errorResponse.error);
        }
        const successResponse = response;
        return successResponse.data;
    }
}
//# sourceMappingURL=rpc-client.js.map