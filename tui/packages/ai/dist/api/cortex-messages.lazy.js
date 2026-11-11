import { lazyApi } from "./lazy.js";
export const piMessagesApi = () => lazyApi(() => import("./cortex-messages.js"));
//# sourceMappingURL=cortex-messages.lazy.js.map