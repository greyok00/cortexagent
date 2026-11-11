import { Command } from "../command.js";
import { authTokenFileOption, authTokenOption, parseAuth, parseLegacyOptions, transportOption, } from "../command-options.js";
const listenOption = transportOption("--listen");
export const cortexCommand = new Command("cortex")
    .option(listenOption)
    .option(authTokenOption)
    .option(authTokenFileOption)
    .build((input) => {
    const { auth, errors: authErrors } = parseAuth(input);
    const listen = input.values(listenOption);
    const { options, errors: optionErrors } = parseLegacyOptions(input);
    const errors = [...authErrors, ...optionErrors];
    if (options.unknownFlags.has("connect"))
        errors.push("--connect is only valid for client mode");
    if (errors.length > 0)
        return { ok: false, errors };
    return {
        ok: true,
        command: {
            command: "cortex",
            options,
            ...(auth === undefined ? {} : { auth }),
            ...(listen.length === 0 ? {} : { listen }),
        },
    };
})
    .action((command, context) => context.runCortex(command));
//# sourceMappingURL=cortex.js.map