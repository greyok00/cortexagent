import { SessionError } from "@cortexagent/agent-core";
import { joinSqlFragments, sql } from "../sql.js";
export function appendRecordRow(db, sessionId, record) {
    sql `INSERT INTO records
			(session_id, seq, id, lane, run_id, type, op_kind, timestamp, payload)
			VALUES (${sessionId}, ${record.seq}, ${record.id}, ${record.lane}, ${record.runId ?? null}, ${record.type}, ${record.opKind ?? null}, ${record.timestamp}, ${record.payload})`.run(db);
}
export function idExistsInRecords(db, sessionId, id) {
    return !!sql `SELECT 1 AS found FROM records WHERE session_id = ${sessionId} AND id = ${id} LIMIT 1`.get(db);
}
export function deleteRecordRows(db, sessionId) {
    sql `DELETE FROM records WHERE session_id = ${sessionId}`.run(db);
}
export function readRecordRows(db, sessionId, query = {}) {
    const predicates = [sql `session_id = ${sessionId}`];
    if (query.lane !== undefined)
        predicates.push(sql `lane = ${query.lane}`);
    if (query.type !== undefined)
        predicates.push(sql `type = ${query.type}`);
    if (query.runId !== undefined)
        predicates.push(sql `run_id = ${query.runId}`);
    if (query.operationKind !== undefined)
        predicates.push(sql `op_kind = ${query.operationKind}`);
    if (query.afterSeq !== undefined)
        predicates.push(sql `seq > ${query.afterSeq}`);
    const direction = query.order === "oldestFirst" ? sql `ASC` : sql `DESC`;
    const limit = query.limit === undefined ? sql `` : sql ` LIMIT ${query.limit}`;
    return sql `SELECT session_id, seq, id, lane, run_id, type, op_kind, timestamp, payload
		FROM records
		WHERE ${joinSqlFragments(predicates, " AND ")}
		ORDER BY seq ${direction}${limit}`.all(db);
}
export function readOpenOperationRows(db, sessionId, lane, _options = {}) {
    const laneRow = sql `SELECT open_operation_id FROM lanes WHERE session_id = ${sessionId} AND lane = ${lane}`.get(db);
    if (!laneRow?.open_operation_id)
        return [];
    const record = sql `SELECT session_id, seq, id, lane, run_id, type, op_kind, timestamp, payload
		FROM records
		WHERE session_id = ${sessionId}
			AND id = ${laneRow.open_operation_id}`.get(db);
    if (!record) {
        throw new SessionError("storage", `Lane ${lane} points at missing open operation ${laneRow.open_operation_id}`);
    }
    if (record.lane !== lane || record.type !== "operation_started") {
        throw new SessionError("storage", `Lane ${lane} points at invalid open operation ${laneRow.open_operation_id}`);
    }
    return [record];
}
//# sourceMappingURL=records.js.map