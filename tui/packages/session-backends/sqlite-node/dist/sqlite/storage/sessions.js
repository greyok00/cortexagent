import { assertJsonSerializable, SessionError } from "@cortexagent/agent-core";
import { sql } from "../sql.js";
function parseMetadata(metadata, sessionId) {
    if (metadata === null)
        return undefined;
    let parsed;
    try {
        parsed = JSON.parse(metadata);
    }
    catch (error) {
        throw new SessionError("storage", `Invalid SQLite session ${sessionId}: metadata is not valid JSON`, error instanceof Error ? error : undefined);
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new SessionError("storage", `Invalid SQLite session ${sessionId}: metadata must be an object`);
    }
    return parsed;
}
export function sessionExists(db, sessionId) {
    return !!sql `SELECT 1 AS found FROM sessions WHERE id = ${sessionId}`.get(db);
}
function serializeMetadata(metadata) {
    if (metadata === undefined)
        return null;
    if (typeof metadata !== "object" || metadata === null || Array.isArray(metadata)) {
        throw new SessionError("invalid_payload", "SQLite session metadata must be an object");
    }
    assertJsonSerializable(metadata);
    return JSON.stringify(metadata);
}
export function insertSessionRow(db, session) {
    sql `INSERT INTO sessions (id, created_at, metadata, cwd, parent_session_id)
		VALUES (${session.id}, ${session.createdAt}, ${serializeMetadata(session.metadata)}, ${session.cwd}, ${session.parentSessionId ?? null})`.run(db);
}
export function readSessionRow(db, sessionId) {
    return sql `SELECT s.id, s.created_at, s.metadata, s.cwd, s.parent_session_id,
			name_fact.seq IS NOT NULL AS has_session_name,
			name_fact.value AS session_name
		FROM sessions AS s
		LEFT JOIN facts AS name_fact
			ON name_fact.session_id = s.id
			AND name_fact.kind = 'name'
			AND name_fact.key IS NULL
			AND name_fact.seq = (
				SELECT MAX(f.seq)
				FROM facts AS f
				WHERE f.session_id = s.id AND f.kind = 'name' AND f.key IS NULL
			)
		WHERE s.id = ${sessionId}`.get(db);
}
export function readSessionRows(db, options = {}) {
    const where = options.cwd === undefined ? sql `` : sql `WHERE s.cwd = ${options.cwd}`;
    return sql `SELECT s.id, s.created_at, s.metadata, s.cwd, s.parent_session_id,
			name_fact.seq IS NOT NULL AS has_session_name,
			name_fact.value AS session_name
		FROM sessions AS s
		LEFT JOIN facts AS name_fact
			ON name_fact.session_id = s.id
			AND name_fact.kind = 'name'
			AND name_fact.key IS NULL
			AND name_fact.seq = (
				SELECT MAX(f.seq)
				FROM facts AS f
				WHERE f.session_id = s.id AND f.kind = 'name' AND f.key IS NULL
			)
		${where}
		ORDER BY s.created_at DESC`.all(db);
}
export function deleteSessionRow(db, sessionId) {
    sql `DELETE FROM sessions WHERE id = ${sessionId}`.run(db);
}
function parseSessionName(value, sessionId) {
    if (value === null)
        return undefined;
    let parsed;
    try {
        parsed = JSON.parse(value);
    }
    catch (error) {
        throw new SessionError("storage", `Invalid SQLite session ${sessionId}: name is not valid JSON`, error instanceof Error ? error : undefined);
    }
    if (typeof parsed !== "string") {
        throw new SessionError("storage", `Invalid SQLite session ${sessionId}: name must be a string`);
    }
    return parsed;
}
export function decodeSessionMetadata(row, path) {
    const metadata = parseMetadata(row.metadata, row.id);
    const name = row.has_session_name === 0 ? undefined : parseSessionName(row.session_name, row.id);
    return {
        id: row.id,
        createdAt: row.created_at,
        ...(name === undefined ? {} : { name }),
        cwd: row.cwd,
        path,
        parentSessionId: row.parent_session_id ?? undefined,
        metadata,
    };
}
//# sourceMappingURL=sessions.js.map