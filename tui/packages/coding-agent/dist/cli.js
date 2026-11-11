#!/usr/bin/env node
import { APP_NAME } from "./config.js";
import { installDisplayRelay } from "./core/display-relay.js";
import { configureHttpDispatcher } from "./core/http-dispatcher.js";
import { main } from "./main.js";
process.title = APP_NAME;
process.env.CORTEX_CODING_AGENT = "true";
process.env.AI_AGENT = "cortex";
process.emitWarning = (() => { });
// 2026-10-26: never write to the pty from this process (X grab = frozen
// terminal = blocked event loop). See core/display-relay.ts.
installDisplayRelay();
configureHttpDispatcher();
main(process.argv.slice(2));
//# sourceMappingURL=cli.js.map