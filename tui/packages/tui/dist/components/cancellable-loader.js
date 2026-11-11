import { getKeybindings } from "../keybindings.js";
import { Loader } from "./loader.js";
export class CancellableLoader extends Loader {
    abortController = new AbortController();
    onAbort;
    get signal() {
        return this.abortController.signal;
    }
    get aborted() {
        return this.abortController.signal.aborted;
    }
    handleInput(data) {
        const kb = getKeybindings();
        if (kb.matches(data, "tui.select.cancel")) {
            this.abortController.abort();
            this.onAbort?.();
        }
    }
    dispose() {
        this.stop();
    }
}
//# sourceMappingURL=cancellable-loader.js.map