import { Editor, type EditorOptions, type EditorTheme, type TUI } from "@cortexagent/tui";
import type { AppKeybinding, KeybindingsManager } from "../../../core/keybindings.ts";

export class CustomEditor extends Editor {
	private keybindings: KeybindingsManager;
	public actionHandlers: Map<AppKeybinding, () => void> = new Map();

	public onEscape?: () => void;
	public onCtrlD?: () => void;
	public onPasteImage?: () => void;

	public onExtensionShortcut?: (data: string) => boolean;

	// 2026-11-11 (owner: "when i press up it doesnt have any history"): shell-
	// ergonomics law — ↑ on an EMPTY input summons the previous prompt, ↓ walks
	// back forward. With text present, ↑/↓ stay cursor-motion (multiline edits
	// keep working). The editor's history is filled per-prompt at submit time;
	// the extension below also seeds it from the hot memory store so even a
	// FRESH session immediately has the owner's last prompts on ↑.
	private emptyUpDown(data: string): boolean {
		if (this.getText().length !== 0) return false;
		const up =
			this.keybindings.matches(data, "tui.editor.cursorUp") || data === "\x1b[A";
		const down =
			this.keybindings.matches(data, "tui.editor.cursorDown") || data === "\x1b[B";
		if (!up && !down) return false;
		if (this.isShowingAutocomplete()) return false;
		// navigateHistory is private in Editor (historyIndex/historyDraft live
		// there); access through the same-module channel Editor itself uses —
		// a narrow structural cast, not a behavioral override.
		type Nav = { navigateHistory(d: 1 | -1): void };
		(this as unknown as Nav).navigateHistory(down ? 1 : -1);
		return true;
	}

	constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsManager, options?: EditorOptions) {
		super(tui, theme, options);
		this.keybindings = keybindings;
	}

	onAction(action: AppKeybinding, handler: () => void): void {
		this.actionHandlers.set(action, handler);
	}

	handleInput(data: string): void {
		if (this.onExtensionShortcut?.(data)) {
			return;
		}

		if (this.keybindings.matches(data, "app.clipboard.pasteImage")) {
			this.onPasteImage?.();
			return;
		}

		if (this.keybindings.matches(data, "app.interrupt")) {
			if (!this.isShowingAutocomplete()) {
				const handler = this.onEscape ?? this.actionHandlers.get("app.interrupt");
				if (handler) {
					handler();
					return;
				}
			}

			super.handleInput(data);
			return;
		}

		if (this.keybindings.matches(data, "app.exit")) {
			if (this.getText().length === 0) {
				const handler = this.onCtrlD ?? this.actionHandlers.get("app.exit");
				if (handler) handler();
				return;
			}
			// Fall through to editor handling for delete-char-forward when not empty
		}

		if (this.emptyUpDown(data)) {
			return;
		}

		if (
			this.keybindings.matches(data, "tui.editor.historyPrevious") ||
			this.keybindings.matches(data, "tui.editor.historyNext")
		) {
			super.handleInput(data);
			return;
		}

		for (const [action, handler] of this.actionHandlers) {
			if (action !== "app.interrupt" && action !== "app.exit" && this.keybindings.matches(data, action)) {
				handler();
				return;
			}
		}

		super.handleInput(data);
	}
}
