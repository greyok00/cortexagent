import { Session, SessionError, } from "@cortexagent/agent-core";
import { uuidv7 } from "@cortexagent/ai";
import { appendEntryToBranchCache, buildCachedBranch, deleteBranchCache, rebuildBranchCache } from "./branch-cache.js";
import { applyMigrations } from "./migrations.js";
import { sql } from "./sql.js";
import { queryCachedBranchRows, readCachedBranch } from "./storage/branch-entries.js";
import { readBranchTipIds } from "./storage/branch-tips.js";
import { deleteEntryRows, entryPayload, idExistsInEntries, insertEntryRow, readEntryRow, readEntryRows, } from "./storage/entries.js";
import { appendFact, deleteFactRows, readFactRows, readLatestFact, readLatestLabelFacts } from "./storage/facts.js";
import { createInitialLane, deleteLaneRows, finishLaneOperation, createLane as insertLane, readLane, readLaneHead, readLaneMoveRows, readLanes, setLaneLeaf, startLaneOperation, moveLane as updateLane, } from "./storage/lanes.js";
import { appendRecordRow, deleteRecordRows, idExistsInRecords, readOpenOperationRows, readRecordRows, } from "./storage/records.js";
import { advanceSequence, createSequence, deleteSequence, getNextSequence, setNextSequence, } from "./storage/session-sequences.js";
import { addUsageToStats, createStats, deleteStats, incrementMessageCount, readStats, } from "./storage/session-stats.js";
import { decodeSessionMetadata, deleteSessionRow, insertSessionRow, readSessionRow, readSessionRows, sessionExists, } from "./storage/sessions.js";
import { acquireWriterLease, deleteWriterLease, releaseWriterLease, renewWriterLease, } from "./storage/writer-leases.js";
function resolveWriterLeaseOptions(options) {
    const ttlMs = options?.ttlMs ?? 30_000;
    const heartbeatIntervalMs = options?.heartbeatIntervalMs ?? 10_000;
    if (!Number.isSafeInteger(ttlMs) || ttlMs <= 0)
        throw new RangeError("writerLease.ttlMs must be positive");
    if (!Number.isSafeInteger(heartbeatIntervalMs) || heartbeatIntervalMs <= 0 || heartbeatIntervalMs >= ttlMs) {
        throw new RangeError("writerLease.heartbeatIntervalMs must be positive and less than ttlMs");
    }
    return { ttlMs, heartbeatIntervalMs };
}
function activeWriterError(sessionId) {
    return new SessionError("storage", `SQLite session ${sessionId} already has an active writer`);
}
function lostWriterError(sessionId) {
    return new SessionError("storage", `SQLite session ${sessionId} writer lease was lost`);
}
function claimWriterLease(db, sessionId, options) {
    const now = Date.now();
    const lease = acquireWriterLease(db, sessionId, uuidv7(), now, now + options.ttlMs);
    if (!lease)
        throw activeWriterError(sessionId);
    return lease;
}
class SerialOperationQueue {
    tail = Promise.resolve();
    enqueue(operation) {
        const result = this.tail.then(operation);
        this.tail = result.then(() => undefined, () => undefined);
        return result;
    }
    async drain() {
        await this.tail;
    }
}
function resultOrThrow(result, message) {
    if (!result.ok) {
        const code = result.error.code === "not_found" ? "not_found" : "storage";
        throw new SessionError(code, `${message}: ${result.error.message}`, result.error);
    }
    return result.value;
}
function getParentPath(path) {
    const normalized = path.replace(/[\\/]+$/, "");
    const lastSlash = Math.max(normalized.lastIndexOf("/"), normalized.lastIndexOf("\\"));
    if (lastSlash < 0)
        return ".";
    if (lastSlash === 0)
        return normalized.slice(0, 1);
    return normalized.slice(0, lastSlash);
}
function configureSqliteDatabase(db) {
    sql `PRAGMA journal_mode=WAL`.exec(db);
    sql `PRAGMA synchronous=FULL`.exec(db);
    sql `PRAGMA busy_timeout=5000`.exec(db);
}
function entryRowFromCached(row) {
    return { ...row, seq: row.entry_seq, type: row.type };
}
function readObjectPayload(row) {
    const payload = JSON.parse(row.payload);
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
        throw new Error("Payload is not an object");
    }
    return payload;
}
function decodeEntry(row) {
    try {
        const payload = readObjectPayload(row);
        const base = { id: row.id, seq: row.seq, parentId: row.parent_id, timestamp: row.timestamp };
        switch (row.type) {
            case "message":
                if (typeof payload.message !== "object" || payload.message === null)
                    throw new Error("Missing message");
                return {
                    ...base,
                    type: "message",
                    message: payload.message,
                    ...(payload.terminate === true ? { terminate: true } : {}),
                };
            case "model_change":
                if (typeof payload.provider !== "string" || typeof payload.modelId !== "string") {
                    throw new Error("Invalid model_change payload");
                }
                return { ...base, type: "model_change", provider: payload.provider, modelId: payload.modelId };
            case "thinking_level_change":
                if (typeof payload.thinkingLevel !== "string")
                    throw new Error("Invalid thinking_level_change payload");
                return { ...base, type: "thinking_level_change", thinkingLevel: payload.thinkingLevel };
            case "active_tools_change":
                if (!Array.isArray(payload.activeToolNames))
                    throw new Error("Invalid active_tools_change payload");
                if (payload.activeToolNames.some((value) => typeof value !== "string")) {
                    throw new Error("Invalid active_tools_change payload");
                }
                return { ...base, type: "active_tools_change", activeToolNames: payload.activeToolNames };
            case "compaction":
                if (typeof payload.summary !== "string" ||
                    !Array.isArray(payload.retainedTail) ||
                    typeof payload.tokensBefore !== "number") {
                    throw new Error("Invalid compaction payload");
                }
                return {
                    ...base,
                    type: "compaction",
                    summary: payload.summary,
                    retainedTail: payload.retainedTail,
                    tokensBefore: payload.tokensBefore,
                    ...(Object.hasOwn(payload, "details") ? { details: payload.details } : {}),
                    ...(Object.hasOwn(payload, "usage")
                        ? { usage: payload.usage }
                        : {}),
                };
            case "branch_summary":
                if (typeof payload.fromId !== "string" || typeof payload.summary !== "string") {
                    throw new Error("Invalid branch_summary payload");
                }
                return {
                    ...base,
                    type: "branch_summary",
                    fromId: payload.fromId,
                    summary: payload.summary,
                    ...(Object.hasOwn(payload, "details") ? { details: payload.details } : {}),
                    ...(Object.hasOwn(payload, "usage")
                        ? { usage: payload.usage }
                        : {}),
                };
            case "custom":
                if (typeof payload.customType !== "string")
                    throw new Error("Invalid custom payload");
                return {
                    ...base,
                    type: "custom",
                    customType: payload.customType,
                    ...(Object.hasOwn(payload, "data") ? { data: payload.data } : {}),
                };
        }
    }
    catch (error) {
        throw new SessionError("invalid_entry", `Invalid SQLite session entry ${row.id}: failed to decode entry ${row.id}`, error instanceof Error ? error : undefined);
    }
}
function recordRunId(record) {
    return record.type === "operation_started" ? record.id : "runId" in record ? record.runId : undefined;
}
function recordOpKind(record) {
    return record.type === "operation_started" ? record.intent.kind : undefined;
}
function decodeRecord(row) {
    try {
        return {
            ...JSON.parse(row.payload),
            seq: row.seq,
            timestamp: row.timestamp,
        };
    }
    catch (error) {
        throw new SessionError("storage", `Invalid SQLite session record at sequence ${row.seq}: failed to decode payload`, error instanceof Error ? error : undefined);
    }
}
function validateCachedBranchRows(rows, query) {
    if (rows.length === 0 || query.type !== undefined || query.customType !== undefined)
        return;
    const path = [...rows].sort((left, right) => left.entry_seq - right.entry_seq);
    const shouldIncludeRoot = query.stopAtId === undefined &&
        query.stopAtType === undefined &&
        query.cursor === undefined &&
        (query.order === "oldestFirst" || query.limit === undefined);
    if (shouldIncludeRoot && path[0]?.parent_id !== null) {
        throw new SessionError("invalid_entry", `Entry ${path[0]?.parent_id} not found`);
    }
    for (let index = 1; index < path.length; index++) {
        const previous = path[index - 1];
        const current = path[index];
        if (current.parent_id !== previous.id) {
            throw new SessionError("invalid_entry", `Entry ${current.parent_id} not found`);
        }
    }
}
function matchesEntryQuery(entry, query) {
    return ((query.type === undefined || entry.type === query.type) &&
        (query.customType === undefined || (entry.type === "custom" && entry.customType === query.customType)) &&
        (query.cursor === undefined ||
            (query.order === "oldestFirst" ? entry.seq > query.cursor.afterSeq : entry.seq < query.cursor.afterSeq)));
}
function assertUnusedId(db, sessionId, id) {
    if (idExistsInEntries(db, sessionId, id) || idExistsInRecords(db, sessionId, id)) {
        throw new SessionError("already_exists", `ID already exists: ${id}`);
    }
}
function requireSessionRow(db, sessionId) {
    const row = readSessionRow(db, sessionId);
    if (!row)
        throw new SessionError("not_found", `Session not found: ${sessionId}`);
    return row;
}
class SqliteSessionStorage {
    db;
    metadata;
    lease;
    leaseOptions;
    onRelease;
    operations = new SerialOperationQueue();
    heartbeatTimer;
    leaseError;
    closing = false;
    releasePromise;
    constructor(db, metadata, lease, leaseOptions, onRelease) {
        this.db = db;
        this.metadata = metadata;
        this.lease = lease;
        this.leaseOptions = leaseOptions;
        this.onRelease = onRelease;
        this.scheduleHeartbeat();
    }
    async release() {
        this.releasePromise ??= this.finishRelease();
        await this.releasePromise;
    }
    async finishRelease() {
        this.closing = true;
        if (this.heartbeatTimer !== undefined)
            clearTimeout(this.heartbeatTimer);
        try {
            await this.operations.enqueue(() => this.db.transaction(() => releaseWriterLease(this.db, this.metadata.id, this.lease)));
        }
        finally {
            this.onRelease();
        }
    }
    enqueueWrite(operation) {
        if (this.closing)
            return Promise.reject(new SessionError("storage", `SQLite session ${this.metadata.id} is closed`));
        return this.operations.enqueue(() => {
            if (this.leaseError)
                throw this.leaseError;
            return this.db.transaction(() => {
                const now = Date.now();
                if (!renewWriterLease(this.db, this.metadata.id, this.lease, now, now + this.leaseOptions.ttlMs)) {
                    this.leaseError = lostWriterError(this.metadata.id);
                    if (this.heartbeatTimer !== undefined)
                        clearTimeout(this.heartbeatTimer);
                    throw this.leaseError;
                }
                return operation();
            });
        });
    }
    scheduleHeartbeat() {
        if (this.closing || this.leaseError)
            return;
        this.heartbeatTimer = setTimeout(async () => {
            this.heartbeatTimer = undefined;
            try {
                await this.operations.enqueue(() => {
                    if (this.closing || this.leaseError)
                        return;
                    this.db.transaction(() => {
                        const now = Date.now();
                        if (!renewWriterLease(this.db, this.metadata.id, this.lease, now, now + this.leaseOptions.ttlMs)) {
                            this.leaseError = lostWriterError(this.metadata.id);
                        }
                    });
                });
            }
            catch {
                // A transient heartbeat failure is retried. Every write still verifies ownership transactionally.
            }
            finally {
                this.scheduleHeartbeat();
            }
        }, this.leaseOptions.heartbeatIntervalMs);
        this.heartbeatTimer.unref();
    }
    async getMetadata() {
        return decodeSessionMetadata(requireSessionRow(this.db, this.metadata.id), this.metadata.path);
    }
    isForSession(sessionId) {
        return this.metadata.id === sessionId;
    }
    async getLanes() {
        return readLanes(this.db, this.metadata.id).map((row) => ({ lane: row.lane, leafId: row.leaf_id }));
    }
    async createLane(lane, at) {
        return this.enqueueWrite(() => {
            if (readLane(this.db, this.metadata.id, lane)) {
                throw new SessionError("already_exists", `Lane already exists: ${lane}`);
            }
            if (at !== null && !readEntryRow(this.db, this.metadata.id, at)) {
                throw new SessionError("not_found", `Entry not found: ${at}`);
            }
            const seq = getNextSequence(this.db, this.metadata.id);
            insertLane(this.db, this.metadata.id, seq, lane, at);
            advanceSequence(this.db, this.metadata.id, seq);
        });
    }
    async moveLane(lane, to) {
        return this.enqueueWrite(() => {
            if (!readLane(this.db, this.metadata.id, lane))
                throw new SessionError("invalid_lane", `Lane not found: ${lane}`);
            if (to !== null && !readEntryRow(this.db, this.metadata.id, to)) {
                throw new SessionError("not_found", `Entry not found: ${to}`);
            }
            const seq = getNextSequence(this.db, this.metadata.id);
            updateLane(this.db, this.metadata.id, seq, lane, to);
            advanceSequence(this.db, this.metadata.id, seq);
        });
    }
    async appendEntry(entry, lane) {
        return this.enqueueWrite(() => {
            const parentId = readLaneHead(this.db, this.metadata.id, lane).leafId;
            assertUnusedId(this.db, this.metadata.id, entry.id);
            const seq = getNextSequence(this.db, this.metadata.id);
            const committed = { ...entry, parentId, seq, timestamp: Date.now() };
            insertEntryRow(this.db, this.metadata.id, {
                seq,
                id: committed.id,
                parentId: committed.parentId,
                type: committed.type,
                timestamp: committed.timestamp,
                payload: JSON.stringify(entryPayload(committed)),
            });
            setLaneLeaf(this.db, this.metadata.id, lane, committed.id);
            appendEntryToBranchCache(this.db, this.metadata.id, committed.id, seq, committed.type, committed.type === "custom" ? committed.customType : null, committed.parentId);
            if (committed.type === "message")
                incrementMessageCount(this.db, this.metadata.id);
            advanceSequence(this.db, this.metadata.id, seq);
            return structuredClone(committed);
        });
    }
    async appendRecord(record) {
        return this.enqueueWrite(() => {
            if (!readLane(this.db, this.metadata.id, record.lane)) {
                throw new SessionError("invalid_lane", `Lane not found: ${record.lane}`);
            }
            assertUnusedId(this.db, this.metadata.id, record.id);
            const seq = getNextSequence(this.db, this.metadata.id);
            const committed = { ...record, seq, timestamp: Date.now() };
            if (record.type === "operation_started") {
                startLaneOperation(this.db, this.metadata.id, record.lane, record.id);
            }
            appendRecordRow(this.db, this.metadata.id, {
                seq,
                id: record.id,
                lane: record.lane,
                runId: recordRunId(record),
                type: record.type,
                opKind: recordOpKind(record),
                timestamp: committed.timestamp,
                payload: JSON.stringify(record),
            });
            if (record.type === "operation_finished") {
                finishLaneOperation(this.db, this.metadata.id, record.lane, record.runId);
            }
            if (record.type === "usage")
                addUsageToStats(this.db, this.metadata.id, record.usage);
            advanceSequence(this.db, this.metadata.id, seq);
            return structuredClone(committed);
        });
    }
    async getEntry(id) {
        const row = readEntryRow(this.db, this.metadata.id, id);
        return row ? decodeEntry(row) : undefined;
    }
    async findEntries(query = {}) {
        const sqlType = query.type ?? (query.customType === undefined ? undefined : "custom");
        const sqlLimit = query.customType === undefined ? query.limit : undefined;
        const rows = readEntryRows(this.db, this.metadata.id, {
            cursor: query.cursor,
            limit: sqlLimit,
            order: query.order,
            type: sqlType,
        });
        const entries = rows.map(decodeEntry).filter((entry) => matchesEntryQuery(entry, query));
        return query.limit === undefined ? entries : entries.slice(0, query.limit);
    }
    async findEntriesOnBranch(query) {
        const cached = readCachedBranch(this.db, this.metadata.id, query.start);
        if (!cached) {
            if (!readEntryRow(this.db, this.metadata.id, query.start))
                throw new SessionError("not_found", `Entry not found: ${query.start}`);
            throw new SessionError("invalid_entry", `Branch cache missing entry ${query.start}`);
        }
        const rows = queryCachedBranchRows(this.db, this.metadata.id, cached, query);
        validateCachedBranchRows(rows, query);
        const entries = rows
            .map(entryRowFromCached)
            .map(decodeEntry)
            .filter((entry) => matchesEntryQuery(entry, query));
        return query.limit === undefined ? entries : entries.slice(0, query.limit);
    }
    async findRecords(query = {}) {
        const rows = readRecordRows(this.db, this.metadata.id, query);
        return rows.map(decodeRecord);
    }
    async findOpenOperations(lane, options) {
        const rows = readOpenOperationRows(this.db, this.metadata.id, lane, options);
        return rows.map((row) => {
            const record = decodeRecord(row);
            if (record.type !== "operation_started") {
                throw new SessionError("storage", "Expected operation_started record");
            }
            return record;
        });
    }
    async getLog(options = {}) {
        const afterSeq = options.afterSeq ?? 0;
        const limit = options.limit;
        const entryRows = readEntryRows(this.db, this.metadata.id, { afterSeq, order: "oldestFirst", limit });
        const recordRows = readRecordRows(this.db, this.metadata.id, { afterSeq, order: "oldestFirst", limit });
        const laneRows = readLaneMoveRows(this.db, this.metadata.id, { afterSeq, limit });
        const factRows = readFactRows(this.db, this.metadata.id, { afterSeq, limit });
        const logRows = [
            ...entryRows.map((row) => ({
                seq: row.seq,
                decode: () => ({ kind: "entry", seq: row.seq, entry: decodeEntry(row) }),
            })),
            ...recordRows.map((row) => ({
                seq: row.seq,
                decode: () => ({ kind: "record", seq: row.seq, record: decodeRecord(row) }),
            })),
            ...laneRows.map((row) => ({
                seq: row.seq,
                decode: () => ({ kind: "lane", seq: row.seq, lane: row.lane, leafId: row.leaf_id }),
            })),
            ...factRows.map((row) => ({
                seq: row.seq,
                decode: () => {
                    if (row.kind === "name")
                        return {
                            kind: "fact",
                            seq: row.seq,
                            fact: "name",
                            name: row.value === null ? undefined : JSON.parse(row.value),
                        };
                    return {
                        kind: "fact",
                        seq: row.seq,
                        fact: "label",
                        targetId: row.key ?? "",
                        label: row.value === null ? undefined : JSON.parse(row.value),
                    };
                },
            })),
        ].sort((left, right) => left.seq - right.seq);
        const selectedRows = options.limit === undefined ? logRows : logRows.slice(0, options.limit);
        return selectedRows.map((row) => row.decode());
    }
    async getName() {
        const row = readLatestFact(this.db, this.metadata.id, "name", null);
        return row?.value === undefined || row.value === null ? undefined : JSON.parse(row.value);
    }
    async setName(name) {
        return this.enqueueWrite(() => {
            const seq = getNextSequence(this.db, this.metadata.id);
            appendFact(this.db, this.metadata.id, seq, "name", null, name === undefined ? null : JSON.stringify(name));
            advanceSequence(this.db, this.metadata.id, seq);
        });
    }
    async getLabel(id) {
        const row = readLatestFact(this.db, this.metadata.id, "label", id);
        return row?.value === undefined || row.value === null ? undefined : JSON.parse(row.value);
    }
    async setLabel(id, label) {
        return this.enqueueWrite(() => {
            if (!readEntryRow(this.db, this.metadata.id, id)) {
                throw new SessionError("not_found", `Entry not found: ${id}`);
            }
            const seq = getNextSequence(this.db, this.metadata.id);
            appendFact(this.db, this.metadata.id, seq, "label", id, label === undefined ? null : JSON.stringify(label));
            advanceSequence(this.db, this.metadata.id, seq);
        });
    }
    async getStats() {
        return readStats(this.db, this.metadata.id);
    }
}
function claimStorage(db, metadata, leaseOptions, onRelease) {
    requireSessionRow(db, metadata.id);
    const claimed = db.transaction(() => {
        const lease = claimWriterLease(db, metadata.id, leaseOptions);
        const row = requireSessionRow(db, metadata.id);
        readLanes(db, metadata.id);
        return { lease, row };
    });
    return new SqliteSessionStorage(db, decodeSessionMetadata(claimed.row, metadata.path), claimed.lease, leaseOptions, onRelease);
}
export class SqliteSessionRepository {
    databasePath;
    database;
    databasePromise;
    operations = new SerialOperationQueue();
    activeStorages = new Set();
    options;
    leaseOptions;
    constructor(options) {
        this.options = options;
        this.leaseOptions = resolveWriterLeaseOptions(options.writerLease);
    }
    async releaseStoragesForSession(sessionId) {
        for (const storage of [...this.activeStorages]) {
            if (storage.isForSession(sessionId))
                await storage.release();
        }
    }
    sessionFromLease(db, metadata, lease) {
        let storage;
        storage = new SqliteSessionStorage(db, metadata, lease, this.leaseOptions, () => {
            this.activeStorages.delete(storage);
        });
        this.activeStorages.add(storage);
        return new Session(storage);
    }
    claimSession(db, metadata) {
        const active = [...this.activeStorages].find((storage) => storage.isForSession(metadata.id));
        if (active) {
            readLanes(db, metadata.id);
            return new Session(active);
        }
        let storage;
        storage = claimStorage(db, metadata, this.leaseOptions, () => {
            this.activeStorages.delete(storage);
        });
        this.activeStorages.add(storage);
        return new Session(storage);
    }
    async create(options) {
        return this.operations.enqueue(async () => {
            const db = await this.getDatabase();
            const path = await this.getDatabasePath();
            const id = options.id ?? uuidv7();
            if (sessionExists(db, id))
                throw new SessionError("already_exists", `Session already exists: ${id}`);
            const createdAt = Date.now();
            const lease = db.transaction(() => {
                insertSessionRow(db, {
                    id,
                    createdAt,
                    cwd: options.cwd,
                    parentSessionId: options.parentSessionId,
                    metadata: options.metadata,
                });
                createSequence(db, id);
                createStats(db, id);
                createInitialLane(db, id);
                return claimWriterLease(db, id, this.leaseOptions);
            });
            const row = requireSessionRow(db, id);
            return this.sessionFromLease(db, decodeSessionMetadata(row, path), lease);
        });
    }
    async open(metadata) {
        return this.operations.enqueue(async () => this.claimSession(await this.getDatabase(), metadata));
    }
    async repairBranchCache(metadata) {
        return this.operations.enqueue(async () => {
            await this.releaseStoragesForSession(metadata.id);
            const db = await this.getDatabase();
            db.transaction(() => {
                const lease = claimWriterLease(db, metadata.id, this.leaseOptions);
                requireSessionRow(db, metadata.id);
                rebuildBranchCache(db, metadata.id);
                releaseWriterLease(db, metadata.id, lease);
            });
        });
    }
    async list(options = {}) {
        return this.operations.enqueue(async () => {
            const path = await this.getDatabasePath();
            if (!resultOrThrow(await this.options.env.exists(path), `Failed to check database ${path}`))
                return [];
            const db = await this.getDatabase();
            const rows = readSessionRows(db, options);
            return rows.map((row) => decodeSessionMetadata(row, path));
        });
    }
    async delete(metadata) {
        return this.operations.enqueue(async () => {
            await this.releaseStoragesForSession(metadata.id);
            const db = await this.getDatabase();
            db.transaction(() => {
                if (!sessionExists(db, metadata.id)) {
                    deleteWriterLease(db, metadata.id);
                    return;
                }
                claimWriterLease(db, metadata.id, this.leaseOptions);
                deleteBranchCache(db, metadata.id);
                deleteFactRows(db, metadata.id);
                deleteLaneRows(db, metadata.id);
                deleteRecordRows(db, metadata.id);
                deleteEntryRows(db, metadata.id);
                deleteWriterLease(db, metadata.id);
                deleteStats(db, metadata.id);
                deleteSequence(db, metadata.id);
                deleteSessionRow(db, metadata.id);
            });
        });
    }
    async fork(source, options) {
        return this.operations.enqueue(async () => {
            const db = await this.getDatabase();
            const path = await this.getDatabasePath();
            const sourceMetadata = decodeSessionMetadata(requireSessionRow(db, source.id), path);
            const id = options.id ?? uuidv7();
            if (sessionExists(db, id))
                throw new SessionError("already_exists", `Session already exists: ${id}`);
            const entries = [];
            const lanes = [];
            const branchTips = [];
            let branchForkTargetId = null;
            if (options.scope === "tree") {
                entries.push(...readEntryRows(db, source.id, { order: "oldestFirst" }));
                lanes.push(...readLanes(db, source.id).map((row) => ({ lane: row.lane, leafId: row.leaf_id })));
                branchTips.push(...readBranchTipIds(db, source.id));
            }
            else {
                const main = readLane(db, source.id, "main");
                if (!main)
                    throw new SessionError("invalid_lane", "Lane not found: main");
                const selectedEntryId = options.entryId ?? main.leaf_id;
                if (selectedEntryId !== null) {
                    const target = readEntryRow(db, source.id, selectedEntryId);
                    if (!target || target.type !== "message") {
                        throw new SessionError("invalid_fork_target", `Fork target is not a message entry: ${selectedEntryId}`);
                    }
                    const position = options.position ?? (options.entryId === undefined ? "at" : "before");
                    branchForkTargetId = position === "at" ? target.id : target.parent_id;
                }
                lanes.push({ lane: "main", leafId: branchForkTargetId });
                if (branchForkTargetId !== null) {
                    const cached = readCachedBranch(db, source.id, branchForkTargetId);
                    if (!cached) {
                        throw new SessionError("invalid_fork_target", `Fork target is not on a cached branch: ${branchForkTargetId}`);
                    }
                    const rows = queryCachedBranchRows(db, source.id, cached, { order: "oldestFirst" });
                    entries.push(...rows.map(entryRowFromCached));
                    branchTips.push(branchForkTargetId);
                }
            }
            const copiedIds = new Set(entries.map((entry) => entry.id));
            const latestName = readLatestFact(db, source.id, "name", null);
            const latestLabels = readLatestLabelFacts(db, source.id);
            const labelsToCopy = latestLabels.filter((row) => options.scope === "tree" || (row.key !== null && copiedIds.has(row.key)));
            const createdAt = Date.now();
            const metadata = options.metadata ?? sourceMetadata.metadata;
            let lease;
            try {
                lease = db.transaction(() => {
                    insertSessionRow(db, {
                        id,
                        createdAt,
                        cwd: options.cwd,
                        parentSessionId: options.parentSessionId ?? source.id,
                        metadata,
                    });
                    createSequence(db, id);
                    createStats(db, id, entries.filter((entry) => entry.type === "message").length);
                    let nextSeq = 1;
                    const allocateSeq = () => nextSeq++;
                    for (const entry of entries) {
                        insertEntryRow(db, id, {
                            seq: allocateSeq(),
                            id: entry.id,
                            parentId: entry.parent_id,
                            type: entry.type,
                            timestamp: entry.timestamp,
                            payload: entry.payload,
                        });
                    }
                    if (options.scope === "tree") {
                        for (const lane of lanes)
                            insertLane(db, id, allocateSeq(), lane.lane, lane.leafId);
                    }
                    else {
                        createInitialLane(db, id, "main", branchForkTargetId);
                    }
                    if (latestName?.value !== undefined && latestName.value !== null) {
                        appendFact(db, id, allocateSeq(), "name", null, latestName.value);
                    }
                    for (const label of labelsToCopy)
                        appendFact(db, id, allocateSeq(), "label", label.key, label.value);
                    setNextSequence(db, id, nextSeq);
                    for (const tip of branchTips)
                        buildCachedBranch(db, id, tip);
                    return claimWriterLease(db, id, this.leaseOptions);
                });
            }
            catch (error) {
                if (error instanceof SessionError)
                    throw error;
                throw new SessionError("storage", `Failed to fork SQLite session ${id}`, error instanceof Error ? error : undefined);
            }
            const row = requireSessionRow(db, id);
            return this.sessionFromLease(db, decodeSessionMetadata(row, path), lease);
        });
    }
    async close() {
        await this.operations.drain();
        for (const storage of [...this.activeStorages])
            await storage.release();
        if (this.database)
            this.database.close();
        this.database = undefined;
        this.databasePromise = undefined;
    }
    async [Symbol.asyncDispose]() {
        await this.close();
    }
    async getDatabasePath() {
        this.databasePath ??= resultOrThrow(await this.options.env.absolutePath(this.options.databasePath), `Failed to resolve SQLite sessions database ${this.options.databasePath}`);
        return this.databasePath;
    }
    async getDatabase() {
        if (!this.databasePromise)
            this.databasePromise = this.openDatabase();
        this.database = await this.databasePromise;
        return this.database;
    }
    async openDatabase() {
        const path = await this.getDatabasePath();
        resultOrThrow(await this.options.env.createDir(getParentPath(path), { recursive: true }), `Failed to create SQLite sessions directory ${path}`);
        const db = await this.options.sqlite.open(path);
        try {
            configureSqliteDatabase(db);
            await applyMigrations(db);
            return db;
        }
        catch (error) {
            db.close();
            throw error;
        }
    }
}
//# sourceMappingURL=repo.js.map