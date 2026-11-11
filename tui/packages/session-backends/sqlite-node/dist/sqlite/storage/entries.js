import { sql } from "../sql.js";
export function entryPayload(entry) {
    const { type: _type, id: _id, seq: _seq, parentId: _parentId, timestamp: _timestamp, ...payload } = entry;
    return payload;
}
export function insertEntryRow(db, sessionId, entry) {
    sql `INSERT INTO entries (session_id, id, seq, parent_id, type, timestamp, payload)
		VALUES (${sessionId}, ${entry.id}, ${entry.seq}, ${entry.parentId}, ${entry.type}, ${entry.timestamp}, ${entry.payload})`.run(db);
}
export function readEntryRow(db, sessionId, entryId) {
    return sql `SELECT session_id, seq, id, parent_id, type, timestamp, payload
		FROM entries
		WHERE session_id = ${sessionId} AND id = ${entryId}`.get(db);
}
export function readEntryRows(db, sessionId, options = {}) {
    const oldestFirst = options.order === "oldestFirst";
    const after = options.afterSeq === undefined ? sql `` : sql ` AND seq > ${options.afterSeq}`;
    const cursor = options.cursor === undefined
        ? sql ``
        : oldestFirst
            ? sql ` AND seq > ${options.cursor.afterSeq}`
            : sql ` AND seq < ${options.cursor.afterSeq}`;
    const type = options.type === undefined ? sql `` : sql ` AND type = ${options.type}`;
    const direction = oldestFirst ? sql `ASC` : sql `DESC`;
    const limit = options.limit === undefined ? sql `` : sql ` LIMIT ${options.limit}`;
    return sql `SELECT session_id, seq, id, parent_id, type, timestamp, payload
		FROM entries
		WHERE session_id = ${sessionId}${after}${cursor}${type}
		ORDER BY seq ${direction}${limit}`.all(db);
}
export function idExistsInEntries(db, sessionId, id) {
    return !!sql `SELECT 1 AS found FROM entries WHERE session_id = ${sessionId} AND id = ${id} LIMIT 1`.get(db);
}
export function deleteEntryRows(db, sessionId) {
    sql `DELETE FROM entries WHERE session_id = ${sessionId}`.run(db);
}
//# sourceMappingURL=entries.js.map