import { type ClientCommandContext } from "./commands/client.ts";
import { type CortexCommandContext } from "./commands/cortex.ts";
import { type ServerCommandContext } from "./commands/server.ts";
export type ExperimentalCliContext = CortexCommandContext & ServerCommandContext & ClientCommandContext;
export declare const experimentalCli: import("./command.ts").Command<import("./commands/cortex.ts").CortexCommand, CortexCommandContext & ServerCommandContext & ClientCommandContext, import("./commands/client.ts").ClientCommand | import("./commands/cortex.ts").CortexCommand | import("./commands/server.ts").ServerCommand>;
//# sourceMappingURL=cli.d.ts.map