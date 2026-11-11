import type { SessionInfo } from "../../../core/session-manager.ts";
export type SortMode = "threaded" | "recent" | "relevance";
export type NameFilter = "all" | "named";
export interface ParsedSearchQuery {
    mode: "tokens" | "regex";
    tokens: {
        kind: "fuzzy" | "phrase";
        value: string;
    }[];
    regex: RegExp | null;
    error?: string;
}
export interface MatchResult {
    matches: boolean;
    score: number;
}
export declare function hasSessionName(session: SessionInfo): boolean;
export declare function parseSearchQuery(query: string): ParsedSearchQuery;
export declare function matchSession(session: SessionInfo, parsed: ParsedSearchQuery): MatchResult;
export declare function filterAndSortSessions(sessions: SessionInfo[], query: string, sortMode: SortMode, nameFilter?: NameFilter): SessionInfo[];
//# sourceMappingURL=session-selector-search.d.ts.map