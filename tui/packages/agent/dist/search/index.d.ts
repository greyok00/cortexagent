import type { Entry } from "../harness/session/types.ts";
export type { ScanningReadable, ScanningReadableOptions, ScanningReadableSource, ScanningSearchTextProjector, ScanningSessionSearchHit, ScanningSessionSearchOptions, SessionSearchCandidate, } from "./scanning.ts";
export { createScanningSessionSearch, scanningEntries } from "./scanning.ts";
export interface SessionSearchOptions {
    readonly entryTypes?: readonly Entry["type"][];
    readonly limit?: number;
    readonly signal?: AbortSignal;
}
export interface SessionSearchHit {
    readonly sessionId: string;
    readonly entryId: string;
}
export interface SessionSearch<T extends SessionSearchHit = SessionSearchHit> {
    search(text: string, options?: SessionSearchOptions): AsyncIterable<T>;
}
//# sourceMappingURL=index.d.ts.map