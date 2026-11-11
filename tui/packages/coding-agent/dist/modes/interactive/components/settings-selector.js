import { Container, getCapabilities, SelectList, SettingsList, Spacer, Text, } from "@cortexagent/tui";
import { formatHttpIdleTimeoutMs, HTTP_IDLE_TIMEOUT_CHOICES } from "../../../core/http-dispatcher.js";
import { getSelectListTheme, getSettingsListTheme, parseAutoThemeSetting, theme, } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { keyDisplayText } from "./keybinding-hints.js";
const SETTINGS_SUBMENU_SELECT_LIST_LAYOUT = {
    minPrimaryColumnWidth: 12,
    maxPrimaryColumnWidth: 32,
};
const THINKING_DESCRIPTIONS = {
    off: "No reasoning",
    minimal: "Very brief reasoning (~1k tokens)",
    low: "Light reasoning (~2k tokens)",
    medium: "Moderate reasoning (~8k tokens)",
    high: "Deep reasoning (~16k tokens)",
    xhigh: "Extra-high reasoning (~32k tokens)",
    max: "Maximum reasoning",
};
const DEFAULT_PROJECT_TRUST_LABELS = {
    ask: "Ask",
    always: "Always trust",
    never: "Never trust",
};
const DEFAULT_PROJECT_TRUST_BY_LABEL = new Map(Object.entries(DEFAULT_PROJECT_TRUST_LABELS).map(([value, label]) => [label, value]));
class WarningSettingsSubmenu extends Container {
    settingsList;
    state;
    constructor(warnings, onChange, onCancel) {
        super();
        this.state = { ...warnings };
        const items = [
            {
                id: "vendor-extra-usage",
                label: "Vendor extra usage",
                description: "Warn when vendor subscription auth may use paid extra usage",
                currentValue: (this.state.subscriptionExtraUsage ?? true) ? "true" : "false",
                values: ["true", "false"],
            },
        ];
        this.settingsList = new SettingsList(items, Math.min(items.length, 10), getSettingsListTheme(), (id, newValue) => {
            switch (id) {
                case "vendor-extra-usage":
                    this.state = { ...this.state, subscriptionExtraUsage: newValue === "true" };
                    onChange({ ...this.state });
                    break;
            }
        }, onCancel);
        this.addChild(this.settingsList);
    }
    handleInput(data) {
        this.settingsList.handleInput(data);
    }
}
class SelectSubmenu extends Container {
    selectList;
    constructor(title, description, options, currentValue, onSelect, onCancel, onSelectionChange) {
        super();
        this.addChild(new Text(theme.bold(theme.fg("accent", title)), 0, 0));
        if (description) {
            this.addChild(new Spacer(1));
            this.addChild(new Text(theme.fg("muted", description), 0, 0));
        }
        this.addChild(new Spacer(1));
        this.selectList = new SelectList(options, Math.min(options.length, 10), getSelectListTheme(), SETTINGS_SUBMENU_SELECT_LIST_LAYOUT);
        const currentIndex = options.findIndex((o) => o.value === currentValue);
        if (currentIndex !== -1) {
            this.selectList.setSelectedIndex(currentIndex);
        }
        this.selectList.onSelect = (item) => {
            onSelect(item.value);
        };
        this.selectList.onCancel = onCancel;
        if (onSelectionChange) {
            this.selectList.onSelectionChange = (item) => {
                onSelectionChange(item.value);
            };
        }
        this.addChild(this.selectList);
        this.addChild(new Spacer(1));
        this.addChild(new Text(theme.fg("dim", "  Enter to select · Esc to go back"), 0, 0));
    }
    handleInput(data) {
        this.selectList.handleInput(data);
    }
}
function themeItems(availableThemes) {
    return availableThemes.map((name) => ({ value: name, label: name }));
}
const AUTOMATIC_THEME_VALUE = "/";
function singleModeThemeItems(availableThemes) {
    return [
        {
            value: AUTOMATIC_THEME_VALUE,
            label: "Automatic",
            description: "Use separate themes for light and dark terminal appearance",
        },
        ...themeItems(availableThemes),
    ];
}
function preferredTheme(availableThemes, preferred, fallback) {
    if (preferred && availableThemes.includes(preferred))
        return preferred;
    if (availableThemes.includes(fallback))
        return fallback;
    return availableThemes[0] ?? fallback;
}
function defaultAutomaticThemes(currentThemeSetting, availableThemes) {
    const autoTheme = parseAutoThemeSetting(currentThemeSetting);
    if (autoTheme)
        return autoTheme;
    const currentFixedTheme = currentThemeSetting.includes("/") ? undefined : currentThemeSetting;
    const themeName = preferredTheme(availableThemes, currentFixedTheme, "dark");
    return { lightTheme: themeName, darkTheme: themeName };
}
class ThemeSubmenu extends Container {
    inputComponent;
    callbacks;
    availableThemes;
    terminalTheme;
    onDone;
    originalThemeSetting;
    mode;
    singleTheme;
    lightTheme;
    darkTheme;
    constructor(currentThemeSetting, terminalTheme, availableThemes, callbacks, onDone) {
        super();
        this.callbacks = callbacks;
        this.availableThemes = availableThemes;
        this.terminalTheme = terminalTheme;
        this.onDone = onDone;
        this.originalThemeSetting = currentThemeSetting;
        const autoTheme = parseAutoThemeSetting(currentThemeSetting);
        const automaticThemes = defaultAutomaticThemes(currentThemeSetting, availableThemes);
        const fixedTheme = autoTheme || currentThemeSetting.includes("/") ? undefined : currentThemeSetting;
        this.mode = autoTheme ? "automatic" : "single";
        this.lightTheme = automaticThemes.lightTheme;
        this.darkTheme = automaticThemes.darkTheme;
        this.singleTheme = preferredTheme(availableThemes, fixedTheme ?? (autoTheme ? this.getActiveAutomaticTheme() : undefined), "dark");
        if (this.mode === "automatic") {
            this.showAutomaticMenu();
        }
        else {
            this.showSingleMenu();
        }
    }
    handleInput(data) {
        this.inputComponent?.handleInput?.(data);
    }
    setContent(renderComponent, inputComponent = renderComponent) {
        this.clear();
        this.addChild(renderComponent);
        this.inputComponent = inputComponent;
    }
    showSingleMenu() {
        this.mode = "single";
        const menu = new SelectSubmenu("Theme", "Select a theme, or choose Automatic to follow terminal appearance.", singleModeThemeItems(this.availableThemes), this.singleTheme, (value) => {
            if (value === AUTOMATIC_THEME_VALUE) {
                this.mode = "automatic";
                this.callbacks.onThemePreview?.(this.getThemeSetting());
                this.showAutomaticMenu();
                return;
            }
            this.singleTheme = value;
            this.apply(value);
        }, () => this.cancel(), (value) => {
            this.callbacks.onThemePreview?.(value === AUTOMATIC_THEME_VALUE ? this.getAutomaticThemeSetting() : value);
        });
        this.setContent(menu);
    }
    showAutomaticMenu() {
        this.mode = "automatic";
        const content = new Container();
        content.addChild(new Text(theme.bold(theme.fg("accent", "Automatic Theme")), 0, 0));
        content.addChild(new Spacer(1));
        content.addChild(new Text(theme.fg("muted", "Choose themes for terminal light and dark appearance."), 0, 0));
        content.addChild(new Text(theme.fg("muted", "Light/dark detection requires terminal support."), 0, 0));
        content.addChild(new Spacer(1));
        const items = [
            {
                id: "light-theme",
                label: "Light theme",
                description: "Theme to use in automatic mode when the terminal is light",
                currentValue: this.lightTheme,
                submenu: (currentValue, done) => this.createThemeSelect("Light Theme", "Select the theme to use for light terminal appearance", currentValue, done, (value) => {
                    this.lightTheme = value;
                    this.callbacks.onThemePreview?.(this.getThemeSetting());
                    done(value);
                }),
            },
            {
                id: "dark-theme",
                label: "Dark theme",
                description: "Theme to use in automatic mode when the terminal is dark",
                currentValue: this.darkTheme,
                submenu: (currentValue, done) => this.createThemeSelect("Dark Theme", "Select the theme to use for dark terminal appearance", currentValue, done, (value) => {
                    this.darkTheme = value;
                    this.callbacks.onThemePreview?.(this.getThemeSetting());
                    done(value);
                }),
            },
            {
                id: "apply",
                label: "Apply",
                description: "Save and go back",
                currentValue: "save and go back",
                values: ["save and go back"],
            },
            {
                id: "single-mode",
                label: "Change mode",
                description: "Switch to one theme for light and dark",
                currentValue: "switch to single theme",
                values: ["switch to single theme"],
            },
        ];
        const settingsList = new SettingsList(items, Math.min(items.length, 10), getSettingsListTheme(), (id) => {
            switch (id) {
                case "single-mode":
                    this.mode = "single";
                    this.singleTheme = this.getActiveAutomaticTheme();
                    this.callbacks.onThemePreview?.(this.singleTheme);
                    this.showSingleMenu();
                    break;
                case "apply":
                    this.apply(this.getAutomaticThemeSetting());
                    break;
            }
        }, () => this.cancel());
        content.addChild(settingsList);
        this.setContent(content, settingsList);
    }
    createThemeSelect(title, description, currentValue, done, onSelect) {
        return new SelectSubmenu(title, description, themeItems(this.availableThemes), currentValue, onSelect, () => {
            this.callbacks.onThemePreview?.(this.getThemeSetting());
            done();
        }, (value) => this.callbacks.onThemePreview?.(value));
    }
    getThemeSetting() {
        return this.mode === "automatic" ? this.getAutomaticThemeSetting() : this.singleTheme;
    }
    getActiveAutomaticTheme() {
        return this.terminalTheme === "light" ? this.lightTheme : this.darkTheme;
    }
    getAutomaticThemeSetting() {
        return `${this.lightTheme}/${this.darkTheme}`;
    }
    apply(themeSetting) {
        this.onDone(themeSetting);
    }
    cancel() {
        this.callbacks.onThemePreview?.(this.originalThemeSetting);
        this.onDone();
    }
}
export class SettingsSelectorComponent extends Container {
    settingsList;
    constructor(config, callbacks) {
        super();
        const supportsImages = getCapabilities().images;
        const followUpKey = keyDisplayText("app.message.followUp");
        let currentWarnings = { ...config.warnings };
        const items = [
            // 2026-10-13 (owner order, ported): autocompact row removed.
            {
                id: "steering-mode",
                label: "Steering mode",
                description: "Enter while streaming queues steering messages. 'one-at-a-time': deliver one, wait for response. 'all': deliver all at once.",
                currentValue: config.steeringMode,
                values: ["one-at-a-time", "all"],
            },
            {
                id: "follow-up-mode",
                label: "Follow-up mode",
                description: `${followUpKey} queues follow-up messages until agent stops. 'one-at-a-time': deliver one, wait for response. 'all': deliver all at once.`,
                currentValue: config.followUpMode,
                values: ["one-at-a-time", "all"],
            },
            {
                id: "transport",
                label: "Transport",
                description: "Preferred transport for providers that support multiple transports",
                currentValue: config.transport,
                values: ["sse", "websocket", "websocket-cached", "auto"],
            },
            {
                id: "http-idle-timeout",
                label: "HTTP idle timeout",
                description: "Maximum idle gap while waiting for HTTP headers or body chunks. Disable for local models that pause longer than five minutes.",
                currentValue: formatHttpIdleTimeoutMs(config.httpIdleTimeoutMs),
                values: HTTP_IDLE_TIMEOUT_CHOICES.map((choice) => choice.label),
            },
            {
                id: "hide-thinking",
                label: "Hide thinking",
                description: "Hide thinking blocks in assistant responses",
                currentValue: config.hideThinkingBlock ? "true" : "false",
                values: ["true", "false"],
            },
            {
                id: "collapse-code-blocks",
                label: "Collapse code blocks",
                description: "Show code blocks as collapsed placeholders in assistant responses",
                currentValue: config.collapseCodeBlocks ? "true" : "false",
                values: ["true", "false"],
            },
            {
                id: "mermaid-rendering",
                label: "Mermaid diagrams",
                description: "Render Mermaid code blocks as Unicode diagrams",
                currentValue: config.mermaidRenderingMode,
                values: ["off", "final", "streaming"],
            },
            {
                id: "cache-miss-notices",
                label: "Cache miss notices",
                description: "Show transcript notices for significant prompt-cache misses",
                currentValue: config.showCacheMissNotices ? "true" : "false",
                values: ["true", "false"],
            },
            {
                id: "install-telemetry",
                label: "Install telemetry",
                description: "Send an anonymous version/update ping",
                currentValue: config.enableInstallTelemetry ? "true" : "false",
                values: ["true", "false"],
            },
            {
                id: "default-project-trust",
                label: "Default project trust",
                description: "Fallback behavior when no extension or saved trust decision decides project trust",
                currentValue: DEFAULT_PROJECT_TRUST_LABELS[config.defaultProjectTrust],
                values: Object.values(DEFAULT_PROJECT_TRUST_LABELS),
            },
            // 2026-10-13 (owner order, ported): double-escape row removed — the
            // double-escape action is disabled (no tree/fork pickers).
            {
                id: "tree-filter-mode",
                label: "Tree filter mode",
                description: "Default filter when opening /tree",
                currentValue: config.treeFilterMode,
                values: ["default", "no-tools", "user-only", "labeled-only", "all"],
            },
            {
                id: "warnings",
                label: "Warnings",
                description: "Enable or disable individual warnings",
                currentValue: "configure",
                submenu: (_currentValue, done) => new WarningSettingsSubmenu(currentWarnings, (warnings) => {
                    currentWarnings = warnings;
                    callbacks.onWarningsChange(warnings);
                }, () => done()),
            },
            // 2026-10-13 (owner order, ported): thinking-level picker removed —
            // thinking display is hard-pinned hidden and level cycling is disabled.
            {
                id: "tui-mode",
                label: "TUI mode",
                description: "Interface layout; fullscreen mode is experimental",
                currentValue: config.tuiMode,
                values: ["regular", "fullscreen"],
            },
            {
                id: "fullscreen-exit-output",
                label: "Fullscreen exit output",
                description: "Print the transcript or only a session resume hint when exiting fullscreen mode",
                currentValue: config.fullscreenExitOutput,
                values: ["transcript", "resume-hint"],
            },
            {
                id: "fullscreen-scrollbar",
                label: "Fullscreen scrollbar",
                description: "Scrollbar behavior in fullscreen mode; has no effect in regular mode",
                currentValue: config.fullscreenScrollbar,
                values: ["auto", "always", "hidden"],
            },
            {
                id: "theme",
                label: "Theme",
                description: "Color theme for the interface",
                currentValue: config.currentTheme,
                submenu: (currentValue, done) => new ThemeSubmenu(currentValue, config.terminalTheme, config.availableThemes, callbacks, done),
            },
        ];
        if (supportsImages) {
            items.splice(1, 0, {
                id: "show-images",
                label: "Show images",
                description: "Render images inline in terminal",
                currentValue: config.showImages ? "true" : "false",
                values: ["true", "false"],
            });
            items.splice(2, 0, {
                id: "image-width-cells",
                label: "Image width",
                description: "Preferred inline image width in terminal cells",
                currentValue: String(config.imageWidthCells),
                values: ["60", "80", "120"],
            });
        }
        items.splice(supportsImages ? 3 : 1, 0, {
            id: "auto-resize-images",
            label: "Auto-resize images",
            description: "Resize large images to 2000x2000 max for better model compatibility",
            currentValue: config.autoResizeImages ? "true" : "false",
            values: ["true", "false"],
        });
        const autoResizeIndex = items.findIndex((item) => item.id === "auto-resize-images");
        items.splice(autoResizeIndex + 1, 0, {
            id: "block-images",
            label: "Block images",
            description: "Prevent images from being sent to LLM providers",
            currentValue: config.blockImages ? "true" : "false",
            values: ["true", "false"],
        });
        const blockImagesIndex = items.findIndex((item) => item.id === "block-images");
        items.splice(blockImagesIndex + 1, 0, {
            id: "skill-commands",
            label: "Skill commands",
            description: "Register skills as /skill:name commands",
            currentValue: config.enableSkillCommands ? "true" : "false",
            values: ["true", "false"],
        });
        const skillCommandsIndex = items.findIndex((item) => item.id === "skill-commands");
        items.splice(skillCommandsIndex + 1, 0, {
            id: "show-hardware-cursor",
            label: "Show hardware cursor",
            description: "Show the terminal cursor while still positioning it for IME support",
            currentValue: config.showHardwareCursor ? "true" : "false",
            values: ["true", "false"],
        });
        const hardwareCursorIndex = items.findIndex((item) => item.id === "show-hardware-cursor");
        items.splice(hardwareCursorIndex + 1, 0, {
            id: "editor-padding",
            label: "Editor padding",
            description: "Horizontal padding for input editor (0-3)",
            currentValue: String(config.editorPaddingX),
            values: ["0", "1", "2", "3"],
        });
        const editorPaddingIndex = items.findIndex((item) => item.id === "editor-padding");
        items.splice(editorPaddingIndex + 1, 0, {
            id: "output-padding",
            label: "Output padding",
            description: "Horizontal padding for user messages, assistant messages, and thinking",
            currentValue: String(config.outputPad),
            values: ["0", "1"],
        });
        const outputPaddingIndex = items.findIndex((item) => item.id === "output-padding");
        items.splice(outputPaddingIndex + 1, 0, {
            id: "autocomplete-max-visible",
            label: "Autocomplete max items",
            description: "Max visible items in autocomplete dropdown (3-20)",
            currentValue: String(config.autocompleteMaxVisible),
            values: ["3", "5", "7", "10", "15", "20"],
        });
        const autocompleteIndex = items.findIndex((item) => item.id === "autocomplete-max-visible");
        items.splice(autocompleteIndex + 1, 0, {
            id: "clear-on-shrink",
            label: "Clear on shrink",
            description: "Clear empty rows when content shrinks (may cause flicker)",
            currentValue: config.clearOnShrink ? "true" : "false",
            values: ["true", "false"],
        });
        const clearOnShrinkIndex = items.findIndex((item) => item.id === "clear-on-shrink");
        items.splice(clearOnShrinkIndex + 1, 0, {
            id: "terminal-progress",
            label: "Terminal progress",
            description: "Show OSC 9;4 progress indicators in the terminal tab bar",
            currentValue: config.showTerminalProgress ? "true" : "false",
            values: ["true", "false"],
        });
        this.addChild(new DynamicBorder());
        this.settingsList = new SettingsList(items, 10, getSettingsListTheme(), (id, newValue) => {
            switch (id) {
                // 2026-10-14 (owner order): autocompact and double-escape-action
                // cases removed — those settings rows are gone from this agent.
                case "show-images":
                    callbacks.onShowImagesChange(newValue === "true");
                    break;
                case "image-width-cells":
                    callbacks.onImageWidthCellsChange(parseInt(newValue, 10));
                    break;
                case "auto-resize-images":
                    callbacks.onAutoResizeImagesChange(newValue === "true");
                    break;
                case "block-images":
                    callbacks.onBlockImagesChange(newValue === "true");
                    break;
                case "skill-commands":
                    callbacks.onEnableSkillCommandsChange(newValue === "true");
                    break;
                case "steering-mode":
                    callbacks.onSteeringModeChange(newValue);
                    break;
                case "follow-up-mode":
                    callbacks.onFollowUpModeChange(newValue);
                    break;
                case "transport":
                    callbacks.onTransportChange(newValue);
                    break;
                case "http-idle-timeout": {
                    const choice = HTTP_IDLE_TIMEOUT_CHOICES.find((item) => item.label === newValue);
                    if (choice) {
                        callbacks.onHttpIdleTimeoutMsChange(choice.timeoutMs);
                    }
                    break;
                }
                case "hide-thinking":
                    callbacks.onHideThinkingBlockChange(newValue === "true");
                    break;
                case "collapse-code-blocks":
                    callbacks.onCollapseCodeBlocksChange(newValue === "true");
                    break;
                case "mermaid-rendering":
                    callbacks.onMermaidRenderingModeChange(newValue);
                    break;
                case "cache-miss-notices":
                    callbacks.onShowCacheMissNoticesChange(newValue === "true");
                    break;
                // 2026-10-14 (owner order): quiet-startup case removed — the setting
                // is hard-locked, nothing may flip it back on.
                case "install-telemetry":
                    callbacks.onEnableInstallTelemetryChange(newValue === "true");
                    break;
                case "default-project-trust": {
                    const defaultProjectTrust = DEFAULT_PROJECT_TRUST_BY_LABEL.get(newValue);
                    if (defaultProjectTrust) {
                        callbacks.onDefaultProjectTrustChange(defaultProjectTrust);
                    }
                    break;
                }
                // 2026-10-14 (owner order): double-escape-action case removed.
                case "tree-filter-mode":
                    callbacks.onTreeFilterModeChange(newValue);
                    break;
                case "show-hardware-cursor":
                    callbacks.onShowHardwareCursorChange(newValue === "true");
                    break;
                case "editor-padding":
                    callbacks.onEditorPaddingXChange(parseInt(newValue, 10));
                    break;
                case "output-padding":
                    callbacks.onOutputPadChange(newValue === "0" ? 0 : 1);
                    break;
                case "autocomplete-max-visible":
                    callbacks.onAutocompleteMaxVisibleChange(parseInt(newValue, 10));
                    break;
                case "clear-on-shrink":
                    callbacks.onClearOnShrinkChange(newValue === "true");
                    break;
                case "terminal-progress":
                    callbacks.onShowTerminalProgressChange(newValue === "true");
                    break;
                case "tui-mode":
                    callbacks.onTuiModeChange(newValue);
                    break;
                case "fullscreen-exit-output":
                    callbacks.onFullscreenExitOutputChange(newValue);
                    break;
                case "fullscreen-scrollbar":
                    callbacks.onFullscreenScrollbarChange(newValue);
                    break;
                case "theme":
                    callbacks.onThemeChange(newValue);
                    break;
            }
        }, callbacks.onCancel, { enableSearch: true });
        this.addChild(this.settingsList);
        this.addChild(new DynamicBorder());
    }
    getSettingsList() {
        return this.settingsList;
    }
}
//# sourceMappingURL=settings-selector.js.map