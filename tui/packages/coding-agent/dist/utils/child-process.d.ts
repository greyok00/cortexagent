import { type ChildProcess, type ChildProcessByStdio, type SpawnOptions, type SpawnOptionsWithStdioTuple, type SpawnSyncOptionsWithStringEncoding, type SpawnSyncReturns, type StdioNull, type StdioPipe } from "node:child_process";
import type { Readable } from "node:stream";
export declare function spawnProcess(command: string, args: string[], options: SpawnOptionsWithStdioTuple<StdioNull, StdioPipe, StdioPipe>): ChildProcessByStdio<null, Readable, Readable>;
export declare function spawnProcess(command: string, args: string[], options: SpawnOptions): ChildProcess;
export declare function spawnProcessSync(command: string, args: string[], options: SpawnSyncOptionsWithStringEncoding): SpawnSyncReturns<string>;
export declare function waitForChildProcess(child: ChildProcess): Promise<number | null>;
//# sourceMappingURL=child-process.d.ts.map