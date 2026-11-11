import { SessionError } from "@cortexagent/agent-core";
import { sql } from "../sql.js";
export function createSequence(db, sessionId, nextSeq = 1) {
    sql `INSERT INTO session_sequences (session_id, next_seq) VALUES (${sessionId}, ${nextSeq})`.run(db);
}
export function getNextSequence(db, sessionId) {
    const sequenceRow = sql `SELECT next_seq FROM session_sequences WHERE session_id = ${sessionId}`.get(db);
    if (!sequenceRow) {
        throw new SessionError("storage", `Missing sequence row for session ${sessionId}`);
    }
    return sequenceRow.next_seq;
}
export function setNextSequence(db, sessionId, nextSeq) {
    sql `UPDATE session_sequences SET next_seq = ${nextSeq} WHERE session_id = ${sessionId}`.run(db);
}
export function advanceSequence(db, sessionId, seq) {
    setNextSequence(db, sessionId, seq + 1);
}
export function deleteSequence(db, sessionId) {
    sql `DELETE FROM session_sequences WHERE session_id = ${sessionId}`.run(db);
}
//# sourceMappingURL=session-sequences.js.map