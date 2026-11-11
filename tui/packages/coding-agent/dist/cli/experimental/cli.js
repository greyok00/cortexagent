import { clientCommand } from "./commands/client.js";
import { cortexCommand } from "./commands/cortex.js";
import { serverCommand } from "./commands/server.js";
export const experimentalCli = cortexCommand.command(serverCommand).command(clientCommand);
//# sourceMappingURL=cli.js.map