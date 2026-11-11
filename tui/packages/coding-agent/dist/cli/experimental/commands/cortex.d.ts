import type { Args } from "../../args.ts";
import type { AuthInput } from "../auth.ts";
import { Command } from "../command.ts";
import type { TransportAddress } from "../transport-address.ts";
export interface CortexCommand {
    readonly command: "cortex";
    readonly auth?: AuthInput;
    readonly options: Args;
    readonly listen?: readonly TransportAddress[];
}
export interface CortexCommandContext {
    runCortex(command: CortexCommand): void | Promise<void>;
}
export declare const cortexCommand: Command<CortexCommand, CortexCommandContext, CortexCommand>;
//# sourceMappingURL=cortex.d.ts.map