// 2026-10-14 (owner order): thinking is HARD-LOCKED to the highest level in
// CortexAgent (local). This constant is the pivot every default path falls back
// to, and agent-session.ts pins every thinking-level change to it — the level
// can never be cycled, picked, or restored lower than this.
export const DEFAULT_THINKING_LEVEL = "max";
export const LOCKED_THINKING_LEVEL = "max";
//# sourceMappingURL=defaults.js.map