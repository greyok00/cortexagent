import type { SessionInfo, SessionListProgress } from "../core/session-manager.ts";
import type { SettingsManager } from "../core/settings-manager.ts";
type SessionsLoader = (onProgress?: SessionListProgress) => Promise<SessionInfo[]>;
export declare function selectSession(currentSessionsLoader: SessionsLoader, allSessionsLoader: SessionsLoader, settingsManager: SettingsManager): Promise<string | null>;
export {};
//# sourceMappingURL=session-picker.d.ts.map