import { sql } from "../sql.js";
export function acquireWriterLease(db, sessionId, ownerId, now, expiresAtMs) {
    const row = sql `INSERT INTO writer_leases (session_id, owner_id, fence, expires_at_ms)
		VALUES (${sessionId}, ${ownerId}, 1, ${expiresAtMs})
		ON CONFLICT(session_id) DO UPDATE SET
			owner_id = excluded.owner_id,
			fence = writer_leases.fence + 1,
			expires_at_ms = excluded.expires_at_ms
		WHERE writer_leases.expires_at_ms <= ${now}
		RETURNING owner_id, fence, expires_at_ms`.get(db);
    return row === undefined ? undefined : { ownerId: row.owner_id, fence: row.fence, expiresAtMs: row.expires_at_ms };
}
export function renewWriterLease(db, sessionId, lease, now, expiresAtMs) {
    const result = sql `UPDATE writer_leases
		SET expires_at_ms = ${expiresAtMs}
		WHERE session_id = ${sessionId}
			AND owner_id = ${lease.ownerId}
			AND fence = ${lease.fence}
			AND expires_at_ms > ${now}`.run(db);
    if (result.changes === 1)
        lease.expiresAtMs = expiresAtMs;
    return result.changes === 1;
}
export function releaseWriterLease(db, sessionId, lease) {
    sql `DELETE FROM writer_leases
		WHERE session_id = ${sessionId} AND owner_id = ${lease.ownerId} AND fence = ${lease.fence}`.run(db);
}
export function deleteWriterLease(db, sessionId) {
    sql `DELETE FROM writer_leases WHERE session_id = ${sessionId}`.run(db);
}
//# sourceMappingURL=writer-leases.js.map