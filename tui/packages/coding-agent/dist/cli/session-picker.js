import { setKeybindings } from "@cortexagent/tui";
import { KeybindingsManager } from "../core/keybindings.js";
import { SessionSelectorComponent } from "../modes/interactive/components/session-selector.js";
import { createStartupTui, startStartupTui } from "./startup-ui.js";
export async function selectSession(currentSessionsLoader, allSessionsLoader, settingsManager) {
    const ui = await createStartupTui(settingsManager);
    return new Promise((resolve) => {
        const keybindings = KeybindingsManager.create();
        setKeybindings(keybindings);
        let resolved = false;
        const selector = new SessionSelectorComponent(currentSessionsLoader, allSessionsLoader, (path) => {
            if (!resolved) {
                resolved = true;
                ui.stop();
                resolve(path);
            }
        }, () => {
            if (!resolved) {
                resolved = true;
                ui.stop();
                resolve(null);
            }
        }, () => {
            ui.stop();
            process.exit(0);
        }, () => ui.requestRender(), { showRenameHint: false, keybindings });
        ui.addChild(selector);
        ui.setFocus(selector.getSessionList());
        startStartupTui(ui, settingsManager);
    });
}
//# sourceMappingURL=session-picker.js.map