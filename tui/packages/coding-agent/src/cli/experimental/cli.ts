import { type ClientCommandContext, clientCommand } from "./commands/client.ts";
import { type CortexCommandContext, cortexCommand } from "./commands/cortex.ts";
import { type ServerCommandContext, serverCommand } from "./commands/server.ts";

export type ExperimentalCliContext = CortexCommandContext & ServerCommandContext & ClientCommandContext;

export const experimentalCli = cortexCommand.command(serverCommand).command(clientCommand);
