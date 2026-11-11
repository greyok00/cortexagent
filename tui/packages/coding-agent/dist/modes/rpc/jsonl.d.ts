import type { Readable } from "node:stream";
export declare function serializeJsonLine(value: unknown): string;
export declare function attachJsonlLineReader(stream: Readable, onLine: (line: string) => void): () => void;
//# sourceMappingURL=jsonl.d.ts.map