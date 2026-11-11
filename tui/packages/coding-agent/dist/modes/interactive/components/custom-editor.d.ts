import { Editor, type EditorOptions, type EditorTheme, type TUI } from "@cortexagent/tui";
import type { AppKeybinding, KeybindingsManager } from "../../../core/keybindings.ts";
export declare class CustomEditor extends Editor {
    private keybindings;
    actionHandlers: Map<AppKeybinding, () => void>;
    onEscape?: () => void;
    onCtrlD?: () => void;
    onPasteImage?: () => void;
    onExtensionShortcut?: (data: string) => boolean;
    private emptyUpDown;
    constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsManager, options?: EditorOptions);
    onAction(action: AppKeybinding, handler: () => void): void;
    handleInput(data: string): void;
}
//# sourceMappingURL=custom-editor.d.ts.map