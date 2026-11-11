export interface ColdMemoryEntry {
    id: string;
    topic: string;
    body: string;
    ts: number;
}
export interface RecallOptions {
    prompt?: string;
    limit?: number;
    maxCharsPerEntry?: number;
}
export interface RecallResult {
    entries: ColdMemoryEntry[];
    formatted: string;
    tokens: number;
}
export declare function recallColdMemory(opts?: RecallOptions): RecallResult;
//# sourceMappingURL=cold-memory.d.ts.map