import { sql } from "../sql.js";
export function readBranchTipIds(db, sessionId) {
    return sql `SELECT tip_id FROM branch_tips WHERE session_id = ${sessionId} ORDER BY tip_id`
        .all(db)
        .map((row) => row.tip_id);
}
export function readBranchTipBranchId(db, sessionId, tipId) {
    const tip = sql `SELECT branch_id FROM branch_tips WHERE session_id = ${sessionId} AND tip_id = ${tipId}`.get(db);
    return tip?.branch_id;
}
export function insertBranchTip(db, sessionId, tipId, branchId) {
    sql `INSERT INTO branch_tips (session_id, tip_id, branch_id) VALUES (${sessionId}, ${tipId}, ${branchId})`.run(db);
}
export function updateBranchTip(db, sessionId, branchId, oldTipId, newTipId) {
    const result = sql `UPDATE branch_tips SET tip_id = ${newTipId}
		WHERE session_id = ${sessionId} AND branch_id = ${branchId} AND tip_id = ${oldTipId}`.run(db);
    return result.changes === 1;
}
export function deleteBranchTips(db, sessionId) {
    sql `DELETE FROM branch_tips WHERE session_id = ${sessionId}`.run(db);
}
//# sourceMappingURL=branch-tips.js.map