import { getKeybindings } from "../keybindings.ts";
import { Loader } from "./loader.ts";

export class CancellableLoader extends Loader {
	private abortController = new AbortController();

	onAbort?: () => void;

	get signal(): AbortSignal {
		return this.abortController.signal;
	}

	get aborted(): boolean {
		return this.abortController.signal.aborted;
	}

	handleInput(data: string): void {
		const kb = getKeybindings();
		if (kb.matches(data, "tui.select.cancel")) {
			this.abortController.abort();
			this.onAbort?.();
		}
	}

	dispose(): void {
		this.stop();
	}
}
