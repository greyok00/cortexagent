import { Container, getKeybindings, Spacer, Text } from "@cortexagent/tui";
import { APP_NAME } from "../../../config.js";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { keyHint, rawKeyHint } from "./keybinding-hints.js";
const THEME_OPTIONS = [
    { value: "dark", label: "Dark" },
    { value: "light", label: "Light" },
];
const SETUP_LOGO_LINES = [
    " ██████╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗",
    "██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝",
    "██║     ██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ ",
    "██║     ██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ ",
    "╚██████╗╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗",
    " ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝",
];
export class FirstTimeSetupComponent extends Container {
    themeIndex;
    options;
    constructor(options) {
        super();
        this.options = options;
        this.themeIndex = Math.max(0, THEME_OPTIONS.findIndex((option) => option.value === options.detectedTheme));
        this.update();
    }
    update() {
        this.clear();
        this.addChild(new DynamicBorder());
        this.addChild(new Spacer(1));
        this.addChild(new Text(theme.fg("accent", SETUP_LOGO_LINES.join("\n")), 1, 0));
        this.addChild(new Spacer(1));
        this.addChild(new Text(theme.fg("accent", theme.bold(`Welcome to ${APP_NAME} — fully offline, air-gapped.`)), 1, 0));
        this.addChild(new Spacer(1));
        this.addChild(new Text(theme.fg("text", "Pick a theme."), 1, 0));
        this.addChild(new Text(theme.fg("muted", `Detected system appearance: ${this.options.detectedTheme}`), 1, 0));
        this.addChild(new Spacer(1));
        this.addOptionList(THEME_OPTIONS.map((option) => option.label), this.themeIndex);
        this.addChild(new Spacer(1));
        this.addChild(new Text(rawKeyHint("↑↓", "navigate") +
            "  " +
            keyHint("tui.select.confirm", "finish") +
            "  " +
            keyHint("tui.select.cancel", "skip setup"), 1, 0));
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder());
    }
    addOptionList(labels, selectedIndex) {
        for (let i = 0; i < labels.length; i++) {
            const isSelected = i === selectedIndex;
            const prefix = isSelected ? theme.fg("accent", "→ ") : "  ";
            const label = isSelected ? theme.fg("accent", labels[i]) : theme.fg("text", labels[i]);
            this.addChild(new Text(`${prefix}${label}`, 1, 0));
        }
    }
    moveSelection(delta) {
        const next = Math.max(0, Math.min(THEME_OPTIONS.length - 1, this.themeIndex + delta));
        if (next !== this.themeIndex) {
            this.themeIndex = next;
            this.options.onThemePreview(THEME_OPTIONS[this.themeIndex].value);
        }
        this.update();
    }
    handleInput(keyData) {
        const kb = getKeybindings();
        if (kb.matches(keyData, "tui.select.up") || keyData === "k") {
            this.moveSelection(-1);
        }
        else if (kb.matches(keyData, "tui.select.down") || keyData === "j") {
            this.moveSelection(1);
        }
        else if (kb.matches(keyData, "tui.select.confirm") || keyData === "\n") {
            this.options.onSubmit({
                theme: THEME_OPTIONS[this.themeIndex].value,
                shareAnalytics: false,
            });
        }
        else if (kb.matches(keyData, "tui.select.cancel")) {
            this.options.onCancel();
        }
    }
}
//# sourceMappingURL=first-time-setup.js.map