#!/usr/bin/env node

import { APP_NAME } from "./config.ts";
import { installDisplayRelay } from "./core/display-relay.ts";
import { configureHttpDispatcher } from "./core/http-dispatcher.ts";
import { main } from "./main.ts";

process.title = APP_NAME;
process.env.CORTEX_CODING_AGENT = "true";
process.env.AI_AGENT = "cortex";
process.emitWarning = (() => {}) as typeof process.emitWarning;

// 2026-10-26: never write to the pty from this process (X grab = frozen
// terminal = blocked event loop). See core/display-relay.ts.
installDisplayRelay();
configureHttpDispatcher();

main(process.argv.slice(2));
