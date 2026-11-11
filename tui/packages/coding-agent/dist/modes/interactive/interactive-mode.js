import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as TuiLayouts from "@cortexagent/tui";
import { CombinedAutocompleteProvider, Container, fuzzyFilter, Markdown, ProcessTerminal, Spacer, setKeybindings, Text, TruncatedText, TuiAltScreen, TuiMainScreen, } from "@cortexagent/tui";
import chalk from "chalk";
import { spawn } from "child_process";
import { APP_NAME, APP_TITLE, CONFIG_DIR_NAME, getAgentDir, VERSION, } from "../../config.js";
import { parseSkillBlock } from "../../core/agent-session.js";
import { SessionImportFileNotFoundError } from "../../core/agent-session-runtime.js";
import { CACHE_TTL_MS, collectCacheMisses, detectCacheMiss, } from "../../core/cache-stats.js";
import { FooterDataProvider } from "../../core/footer-data-provider.js";
import { configureHttpDispatcher, formatHttpIdleTimeoutMs } from "../../core/http-dispatcher.js";
import { KeybindingsManager } from "../../core/keybindings.js";
import { createCompactionSummaryMessage } from "../../core/messages.js";
import { defaultModelPerProvider, } from "../../core/model-resolver.js";
import { DefaultPackageManager } from "../../core/package-manager.js";
import { formatMissingSessionCwdPrompt, MissingSessionCwdError } from "../../core/session-cwd.js";
import { SessionManager, sessionEntryToContextMessages } from "../../core/session-manager.js";
import { selectSession } from "../../cli/session-picker.js";
import { BUILTIN_SLASH_COMMANDS } from "../../core/slash-commands.js";
import { hasTrustRequiringProjectResources, ProjectTrustStore } from "../../core/trust-manager.js";
import { readClipboardText } from "../../utils/clipboard.js";
import { extensionForImageMimeType, readClipboardImage } from "../../utils/clipboard-image.js";
import { parseGitUrl } from "../../utils/git.js";
import { openBrowser } from "../../utils/open-browser.js";
import { getCwdRelativePath } from "../../utils/paths.js";
import { killTrackedDetachedChildren } from "../../utils/shell.js";
import { ensureTool } from "../../utils/tools-manager.js";
import { checkForNewCortexVersion } from "../../utils/version-check.js";
import { AssistantMessageComponent } from "./components/assistant-message.js";
import { BashExecutionComponent } from "./components/bash-execution.js";
import { BranchSummaryMessageComponent } from "./components/branch-summary-message.js";
import { CompactionSummaryMessageComponent } from "./components/compaction-summary-message.js";
import { CustomEditor } from "./components/custom-editor.js";
import { CustomEntryComponent } from "./components/custom-entry.js";
import { CustomMessageComponent } from "./components/custom-message.js";
import { DynamicBorder } from "./components/dynamic-border.js";
import { ExtensionEditorComponent } from "./components/extension-editor.js";
import { ExtensionInputComponent } from "./components/extension-input.js";
import { ExtensionSelectorComponent } from "./components/extension-selector.js";
import { FooterComponent, formatTokens } from "./components/footer.js";
import { formatKeyText, keyDisplayText, keyText } from "./components/keybinding-hints.js";
import { LeftStripComponent, STRIP_COLLAPSED_W, STRIP_EXPANDED_W } from "./components/left-strip.js";
import { createMermaidMarkdownTransformer } from "./components/mermaid.js";
import { formatAuthSelectorProviderType, } from "./components/oauth-selector.js";
import { SettingsSelectorComponent } from "./components/settings-selector.js";
import { SkillInvocationMessageComponent } from "./components/skill-invocation-message.js";
import { BranchSummaryStatusIndicator, CompactionStatusIndicator, IdleStatus, RetryStatusIndicator, WorkingStatusIndicator, } from "./components/status-indicator.js";
import { PANELS_FALLBACK_MS, panelsMayJoinFrame, StatusPanelsComponent } from "./components/status-panels.js";
import { ToolExecutionComponent } from "./components/tool-execution.js";
import { UserMessageComponent } from "./components/user-message.js";
import { setDisplayRelayRecoveryHandler } from "../../core/display-relay.js";
import { editInExternalEditor } from "./external-editor.js";
import { refreshModelCatalogs } from "./model-catalog-refresh.js";
import { getAvailableThemes, getAvailableThemesWithPaths, getEditorTheme, getMarkdownTheme, getThemeByName, onThemeChange, setRegisteredThemes, stopThemeWatcher, Theme, theme, } from "./theme/theme.js";
import { InteractiveThemeController } from "./theme/theme-controller.js";
function isExpandable(obj) {
    return typeof obj === "object" && obj !== null && "setExpanded" in obj && typeof obj.setExpanded === "function";
}
class ExpandableText extends Text {
    getCollapsedText;
    getExpandedText;
    constructor(getCollapsedText, getExpandedText, expanded = false, paddingX = 0, paddingY = 0) {
        super(expanded ? getExpandedText() : getCollapsedText(), paddingX, paddingY);
        this.getCollapsedText = getCollapsedText;
        this.getExpandedText = getExpandedText;
    }
    setExpanded(expanded) {
        this.setText(expanded ? this.getExpandedText() : this.getCollapsedText());
    }
}
function isCustomSessionEntry(item) {
    return "type" in item && item.type === "custom";
}
const DEAD_TERMINAL_ERROR_CODES = new Set(["EIO", "EPIPE", "ENOTCONN"]);
function isDeadTerminalError(error) {
    if (!error || typeof error !== "object" || !("code" in error)) {
        return false;
    }
    const code = error.code;
    return code !== undefined && DEAD_TERMINAL_ERROR_CODES.has(code);
}
const SUBSCRIPTION_AUTH_WARNING = "Vendor subscription auth is active. Third-party harness usage draws from extra usage and is billed separately. Manage extra usage in your provider console. Disable this warning in /settings.";
function isSubscriptionAuthKey(apiKey) {
    return typeof apiKey === "string" && apiKey.startsWith("sk-ant-oat");
}
function isUnknownModel(model) {
    return !!model && model.provider === "unknown" && model.id === "unknown" && model.api === "unknown";
}
function quoteIfNeeded(value) {
    if (value.length > 0 && !/[^a-zA-Z0-9_\-./~:@]/.test(value)) {
        return value;
    }
    return `'${value.replace(/'/g, `'\\''`)}'`;
}
export function formatResumeCommand(sessionManager) {
    if (!process.stdout.isTTY)
        return undefined;
    if (!sessionManager.isPersisted())
        return undefined;
    const sessionFile = sessionManager.getSessionFile();
    if (!sessionFile || !fs.existsSync(sessionFile))
        return undefined;
    const args = [APP_NAME];
    if (!sessionManager.usesDefaultSessionDir()) {
        args.push("--session-dir", quoteIfNeeded(sessionManager.getSessionDir()));
    }
    args.push("--session", sessionManager.getSessionId());
    return args.join(" ");
}
function hasDefaultModelProvider(providerId) {
    return providerId in defaultModelPerProvider;
}
const AUTH_TYPE_ORDER = { oauth: 0, api_key: 1 };
function createFuzzyAutocompleteItems(items, prefix, getSearchText, toAutocompleteItem) {
    const filtered = fuzzyFilter(items, prefix, getSearchText);
    if (filtered.length === 0)
        return null;
    return filtered.map(toAutocompleteItem);
}
function getLoginProviderCompletionOptions(providerOptions) {
    const byId = new Map();
    for (const provider of providerOptions) {
        const existing = byId.get(provider.id);
        if (existing) {
            if (!existing.authTypes.includes(provider.authType)) {
                existing.authTypes.push(provider.authType);
                existing.authTypes.sort((a, b) => AUTH_TYPE_ORDER[a] - AUTH_TYPE_ORDER[b]);
            }
            continue;
        }
        byId.set(provider.id, {
            id: provider.id,
            name: provider.name,
            authTypes: [provider.authType],
        });
    }
    return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
}
function getLoginProviderSearchText(provider) {
    const authTypes = provider.authTypes
        .map((authType) => `${authType} ${formatAuthSelectorProviderType(authType)}`)
        .join(" ");
    return `${provider.id} ${provider.name} ${authTypes}`;
}
function formatLoginProviderCompletionDescription(provider) {
    const authTypes = provider.authTypes.map(formatAuthSelectorProviderType).join("/");
    return provider.name === provider.id ? authTypes : `${provider.name} · ${authTypes}`;
}
export function createInteractiveTui(options) {
    const terminal = options.terminal ?? new ProcessTerminal();
    if (options.tuiMode === "fullscreen") {
        const styleSearchMatch = (text) => theme.bg("searchMatchBg", theme.fg("searchMatchText", text));
        return new TuiAltScreen(terminal, options.showHardwareCursor, options.logDirectory, {
            searchMatchStyle: (text) => theme.underline(styleSearchMatch(text)),
            searchCurrentMatchStyle: (text) => theme.bold(theme.inverse(styleSearchMatch(text))),
            openUrl: openBrowser,
            onRightClickPaste: options.onRightClickPaste,
        });
    }
    return new TuiMainScreen(terminal, options.showHardwareCursor, options.logDirectory);
}
export function createInteractiveTuiReference(getTui) {
    return new Proxy({}, {
        get: (_target, property) => {
            const tui = getTui();
            const value = Reflect.get(tui, property, tui);
            if (typeof value !== "function")
                return value;
            let methodTui = tui;
            let method = value;
            return (...args) => {
                const currentTui = getTui();
                if (currentTui !== methodTui) {
                    const currentMethod = Reflect.get(currentTui, property, currentTui);
                    if (typeof currentMethod !== "function") {
                        throw new TypeError(`TUI property ${String(property)} is not callable`);
                    }
                    methodTui = currentTui;
                    method = currentMethod;
                }
                return Reflect.apply(method, methodTui, args);
            };
        },
        set: (_target, property, value) => {
            const tui = getTui();
            return Reflect.set(tui, property, value, tui);
        },
        has: (_target, property) => Reflect.has(getTui(), property),
        getPrototypeOf: () => Reflect.getPrototypeOf(getTui()),
    });
}
export class InteractiveMode {
    runtimeHost;
    renderer;
    ui;
    mainScreenRenderState;
    loadedResourcesContainer;
    chatContainer;
    documentContainer;
    transcriptScrollView;
    fullscreenLayoutRoot;
    pendingMessagesContainer;
    statusContainer;
    defaultEditor;
    editor;
    editorComponentFactory;
    autocompleteProvider;
    autocompleteProviderWrappers = [];
    fdPath;
    editorContainer;
    activeSelectorToken;
    activeSelectorDispose;
    footer;
    footerContainer;
    footerDataProvider;
    keybindings;
    version;
    isInitialized = false;
    onInputCallback;
    pendingUserInputs = [];
    activeStatusIndicator = undefined;
    idleStatus = new IdleStatus();
    workingMessage = undefined;
    workingVisible = true;
    workingIndicatorOptions = undefined;
    defaultWorkingMessage = "Working...";
    defaultHiddenThinkingLabel = "Thinking...";
    hiddenThinkingLabel = this.defaultHiddenThinkingLabel;
    lastSigintTime = 0;
    lastEscapeTime = 0;
    subscriptionAuthWarningShown = false;
    lastStatusSpacer = undefined;
    lastStatusText = undefined;
    managedToolStatusStarted = false;
    streamingComponent = undefined;
    streamingMessage = undefined;
    pendingTools = new Map();
    // 2026-09-26 owner directive: tool output expanded by default (ctrl+o
    // starts ON; the toggle collapses on demand).
    toolOutputExpanded = true;
    // HARD-CODED: thinking is never shown. Forced true; the toggle is a no-op.
    hideThinkingBlock = true;
    outputPad = 1;
    mermaidMarkdownTransformer = createMermaidMarkdownTransformer({
        getMode: () => this.settingsManager.getMermaidRenderingMode(),
        theme,
    });
    skillCommands = new Map();
    unsubscribe;
    signalCleanupHandlers = [];
    isBashMode = false;
    bashComponent = undefined;
    pendingBashComponents = [];
    autoCompactionEscapeHandler;
    retryEscapeHandler;
    compactionQueuedMessages = [];
    shutdownRequested = false;
    extensionSelector = undefined;
    extensionInput = undefined;
    extensionEditor = undefined;
    extensionTerminalInputSubscriptions = new Set();
    extensionWidgetsAbove = new Map();
    extensionWidgetsBelow = new Map();
    widgetContainerAbove;
    widgetContainerBelow;
    statusPanels = null;
    leftStrip = null;
    leftStripScrollView = null;
    customFooter = undefined;
    headerContainer;
    builtInHeader = undefined;
    customHeader = undefined;
    options;
    onRightClickPaste = () => {
        void this.handleRightClickPaste();
    };
    autoTrustOnReloadCwd;
    themeController;
    get session() {
        return this.runtimeHost.session;
    }
    get agent() {
        return this.session.agent;
    }
    get sessionManager() {
        return this.session.sessionManager;
    }
    get settingsManager() {
        return this.session.settingsManager;
    }
    constructor(runtimeHost, options = {}) {
        this.runtimeHost = runtimeHost;
        const tuiMode = options.tuiMode ?? this.settingsManager.getTuiMode();
        this.options = { ...options, tuiMode };
        this.autoTrustOnReloadCwd = options.autoTrustOnReloadCwd;
        this.runtimeHost.setBeforeSessionInvalidate(() => {
            this.resetExtensionUI();
        });
        this.runtimeHost.setRebindSession(async () => {
            await this.rebindCurrentSession({ renderBeforeBind: true });
            await this.themeController.applyFromSettings();
        });
        this.version = VERSION;
        this.renderer = createInteractiveTui({
            tuiMode,
            showHardwareCursor: this.settingsManager.getShowHardwareCursor(),
            logDirectory: getAgentDir(),
            onRightClickPaste: this.onRightClickPaste,
        });
        this.ui = createInteractiveTuiReference(() => this.renderer);
        // 2026-10-26: if the display relay had to drop frames while the terminal
        // was not reading (X server grab), repaint everything once it drains.
        setDisplayRelayRecoveryHandler(() => this.ui.requestRender(true));
        this.ui.setClearOnShrink(this.settingsManager.getClearOnShrink());
        this.headerContainer = new Container();
        this.loadedResourcesContainer = new Container();
        this.chatContainer = new Container();
        this.documentContainer = new Container();
        this.documentContainer.addChild(this.headerContainer);
        this.documentContainer.addChild(this.loadedResourcesContainer);
        this.documentContainer.addChild(this.chatContainer);
        this.pendingMessagesContainer = new Container();
        this.statusContainer = new Container();
        this.widgetContainerAbove = new Container();
        this.widgetContainerBelow = new Container();
        this.keybindings = KeybindingsManager.create();
        setKeybindings(this.keybindings);
        const editorPaddingX = this.settingsManager.getEditorPaddingX();
        const autocompleteMaxVisible = this.settingsManager.getAutocompleteMaxVisible();
        this.defaultEditor = new CustomEditor(this.ui, getEditorTheme(), this.keybindings, {
            paddingX: editorPaddingX,
            autocompleteMaxVisible,
        });
        this.editor = this.defaultEditor;
        this.editorContainer = new Container();
        this.editorContainer.addChild(this.editor);
        this.footerDataProvider = new FooterDataProvider(this.sessionManager.getCwd());
        this.footer = new FooterComponent(this.session, this.footerDataProvider);
        this.footer.setAutoCompactEnabled(this.session.autoCompactionEnabled);
        this.footerContainer = new Container();
        this.footerContainer.addChild(this.footer);
        this.hideThinkingBlock = this.settingsManager.getHideThinkingBlock();
        this.outputPad = this.settingsManager.getOutputPad();
        setRegisteredThemes(this.session.resourceLoader.getThemes().themes);
        this.themeController = new InteractiveThemeController(this.ui, {
            getSettingsManager: () => this.settingsManager,
            showError: (message) => this.showError(message),
            onChanged: () => this.updateEditorBorderColor(),
            initialThemeSetting: options.initialThemeSetting,
        });
    }
    getAutocompleteSourceTag(sourceInfo) {
        if (!sourceInfo) {
            return undefined;
        }
        const scopePrefix = sourceInfo.scope === "user" ? "u" : sourceInfo.scope === "project" ? "p" : "t";
        const source = sourceInfo.source.trim();
        if (source === "auto" || source === "local" || source === "cli") {
            return scopePrefix;
        }
        if (source.startsWith("npm:")) {
            return `${scopePrefix}:${source}`;
        }
        const gitSource = parseGitUrl(source);
        if (gitSource) {
            const ref = gitSource.ref ? `@${gitSource.ref}` : "";
            return `${scopePrefix}:git:${gitSource.host}/${gitSource.path}${ref}`;
        }
        return scopePrefix;
    }
    prefixAutocompleteDescription(description, sourceInfo) {
        const sourceTag = this.getAutocompleteSourceTag(sourceInfo);
        if (!sourceTag) {
            return description;
        }
        return description ? `[${sourceTag}] ${description}` : `[${sourceTag}]`;
    }
    getBuiltInCommandConflictDiagnostics(extensionRunner) {
        const builtinNames = new Set(BUILTIN_SLASH_COMMANDS.map((command) => command.name));
        return extensionRunner
            .getRegisteredCommands()
            .filter((command) => builtinNames.has(command.name))
            .map((command) => ({
            type: "warning",
            message: command.invocationName === command.name
                ? `Extension command '/${command.name}' conflicts with built-in interactive command. Skipping in autocomplete.`
                : `Extension command '/${command.name}' conflicts with built-in interactive command. Available as '/${command.invocationName}'.`,
            path: command.sourceInfo.path,
        }));
    }
    createBaseAutocompleteProvider() {
        const slashCommands = BUILTIN_SLASH_COMMANDS.map((command) => ({
            name: command.name,
            description: command.description,
            ...(command.argumentHint && { argumentHint: command.argumentHint }),
        }));
        // 2026-10-13 (owner order, ported from cloud fork): /model and /login are
        // disabled — no argument completion adapters for removed commands.
        const templateCommands = this.session.promptTemplates.map((cmd) => ({
            name: cmd.name,
            description: this.prefixAutocompleteDescription(cmd.description, cmd.sourceInfo),
            ...(cmd.argumentHint && { argumentHint: cmd.argumentHint }),
        }));
        const builtinCommandNames = new Set(slashCommands.map((c) => c.name));
        const extensionCommands = this.session.extensionRunner
            .getRegisteredCommands()
            .filter((cmd) => !builtinCommandNames.has(cmd.name))
            .map((cmd) => ({
            name: cmd.invocationName,
            description: this.prefixAutocompleteDescription(cmd.description, cmd.sourceInfo),
            getArgumentCompletions: cmd.getArgumentCompletions,
        }));
        this.skillCommands.clear();
        const skillCommandList = [];
        if (this.settingsManager.getEnableSkillCommands()) {
            for (const skill of this.session.resourceLoader.getSkills().skills) {
                const commandName = `skill:${skill.name}`;
                this.skillCommands.set(commandName, skill.filePath);
                skillCommandList.push({
                    name: commandName,
                    description: this.prefixAutocompleteDescription(skill.description, skill.sourceInfo),
                });
            }
        }
        return new CombinedAutocompleteProvider([...slashCommands, ...templateCommands, ...extensionCommands, ...skillCommandList], this.sessionManager.getCwd(), this.fdPath);
    }
    setupAutocompleteProvider() {
        let provider = this.createBaseAutocompleteProvider();
        const triggerCharacters = [];
        for (const wrapProvider of this.autocompleteProviderWrappers) {
            provider = wrapProvider(provider);
            triggerCharacters.push(...(provider.triggerCharacters ?? []));
        }
        if (triggerCharacters.length > 0) {
            provider.triggerCharacters = [...new Set(triggerCharacters)];
        }
        this.autocompleteProvider = provider;
        this.defaultEditor.setAutocompleteProvider(provider);
        if (this.editor !== this.defaultEditor) {
            this.editor.setAutocompleteProvider?.(provider);
        }
    }
    mountInteractiveTui(tui, components) {
        for (const component of components)
            tui.addChild(component);
        if (TuiLayouts.isViewportTUI(tui)) {
            if (!this.fullscreenLayoutRoot)
                throw new Error("Fullscreen layout is not initialized");
            tui.setLayoutRoot(this.fullscreenLayoutRoot);
        }
    }
    stopInteractiveTui(fullscreenExitOutput) {
        if (this.renderer.mode === "fullscreen" && fullscreenExitOutput === "transcript") {
            while (this.renderer.hasOverlayEntries)
                this.renderer.hideOverlay();
            this.switchTuiMode("regular", false, false);
            this.renderer.renderNow();
        }
        this.ui.stop({ preserveScreen: this.renderer.mode === "fullscreen" });
    }
    switchTuiMode(mode, restoreProgress = true, startRenderer = true) {
        const previousUi = this.renderer;
        if (mode === previousUi.mode)
            return true;
        if (previousUi.hasOverlayEntries)
            return false;
        const components = [...previousUi.children];
        const focus = previousUi.getFocusedComponent();
        const terminal = previousUi.terminal;
        const showHardwareCursor = previousUi.getShowHardwareCursor();
        const clearOnShrink = previousUi.getClearOnShrink();
        const onDebug = previousUi.onDebug;
        if (previousUi instanceof TuiMainScreen) {
            this.mainScreenRenderState = previousUi.captureRenderState();
        }
        previousUi.stop({ preserveScreen: true });
        previousUi.setFocus(null);
        previousUi.clear();
        if (TuiLayouts.isViewportTUI(previousUi))
            previousUi.setLayoutRoot(undefined);
        const nextUi = createInteractiveTui({
            tuiMode: mode,
            showHardwareCursor,
            logDirectory: getAgentDir(),
            terminal,
            onRightClickPaste: this.onRightClickPaste,
        });
        nextUi.setClearOnShrink(clearOnShrink);
        nextUi.onDebug = onDebug;
        if (nextUi instanceof TuiMainScreen && this.mainScreenRenderState) {
            nextUi.restoreRenderState(this.mainScreenRenderState);
        }
        this.renderer = nextUi;
        this.options.tuiMode = mode;
        this.mountInteractiveTui(nextUi, components);
        nextUi.invalidate();
        nextUi.setFocus(focus);
        if (!startRenderer)
            return true;
        nextUi.start();
        this.themeController.rebindTui();
        this.rebindExtensionTerminalInputListeners();
        if (restoreProgress &&
            this.settingsManager.getShowTerminalProgress() &&
            (this.session.isStreaming || this.session.isCompacting)) {
            terminal.setProgress(true);
        }
        return true;
    }
    async init() {
        if (this.isInitialized)
            return;
        this.registerSignalHandlers();
        this.seedEditorHistoryFromHotStore();
        if (this.session.scopedModels.length > 0 && (this.options.verbose || !this.settingsManager.getQuietStartup())) {
            const modelList = this.session.scopedModels
                .map((sm) => {
                const thinkingStr = sm.thinkingLevel ? `:${sm.thinkingLevel}` : "";
                return `${sm.model.id}${thinkingStr}`;
            })
                .join(", ");
            const cycleKeys = this.keybindings.getKeys("app.model.cycleForward");
            const cycleHint = cycleKeys.length > 0
                ? theme.fg("muted", ` (${formatKeyText(cycleKeys.join("/"), { capitalize: true })} to cycle)`)
                : "";
            console.log(theme.fg("dim", `Model scope: ${modelList}${cycleHint}`));
        }
        this.statusPanels = new StatusPanelsComponent(() => this.ui.requestRender(), {
            // 2026-10-24 (owner): Tokens panel shows REAL session usage —
            // the totals the model itself reports per reply, read live.
            getSessionStats: () => this.session.getSessionStats(),
        });
        this.leftStrip = new LeftStripComponent(() => this.ui.requestRender());
        // Wrap the strip's content in a ScrollView so the 5 sections don't
        // overflow the visible height. The strip's render() returns many
        // lines; the ScrollView clips + renders a scrollbar + auto-follows
        // the bottom on new content. User feedback 2026-08-20: "the task
        // list on the left side isn't being populated. should be, I should
        // be able to scroll to left pane."
        this.leftStripScrollView = new TuiLayouts.ScrollView(this.leftStrip, {
            follow: "end",
            primary: false,
            overscroll: "chain",
            scrollbar: this.settingsManager.getFullscreenScrollbar(),
            scrollbarStyle: (text) => theme.bg("scrollbarThumb", text),
        });
        // No right strip in the TUI. The control icons (Esc / Ctrl-C /
        // paperclip / enter) live in the Tkinter frontend, not here.
        this.renderWidgets();
        this.transcriptScrollView = new TuiLayouts.ScrollView(this.documentContainer, {
            follow: "end",
            primary: true,
            overscroll: "chain",
            scrollbar: this.settingsManager.getFullscreenScrollbar(),
            scrollbarStyle: (text) => theme.bg("scrollbarThumb", text),
        });
        const dock = new TuiLayouts.VStack([
            { component: this.pendingMessagesContainer, shrink: 1, minSize: 0 },
            { component: this.statusContainer, shrink: 1, minSize: 0 },
            { component: this.widgetContainerAbove, shrink: 1, minSize: 0 },
            { component: this.editorContainer, shrink: 1, minSize: 3 },
            { component: this.widgetContainerBelow, shrink: 1, minSize: 0 },
            { component: this.footerContainer, shrink: 1, minSize: 1 },
        ]);
        this.fullscreenLayoutRoot = new TuiLayouts.HStack([
            // Left strip wrapper: a ScrollView that contains the
            // LeftStripComponent. ScrollView is the only container that
            // gives us a scrollbar + content clipping + auto-follow. The
            // strip itself still owns the render() output; the ScrollView
            // just decides what to show in the visible height.
            {
                component: this.leftStripScrollView,
                basis: STRIP_COLLAPSED_W,
                grow: 0,
                shrink: 0,
                minSize: STRIP_COLLAPSED_W,
                maxSize: STRIP_EXPANDED_W,
            },
            // Middle: the existing chat VStack (transcript + dock).
            // No right strip — the chat fills the rest of the screen.
            {
                component: new TuiLayouts.VStack([
                    { component: this.transcriptScrollView, basis: 0, grow: 1, shrink: 1, minSize: 1 },
                    { component: dock, basis: "auto", grow: 0, shrink: 1, minSize: 1 },
                ]),
                basis: 0,
                grow: 1,
                shrink: 1,
                minSize: 32,
            },
        ]);
        this.mountInteractiveTui(this.renderer, [
            this.documentContainer,
            this.pendingMessagesContainer,
            this.statusContainer,
            this.widgetContainerAbove,
            this.editorContainer,
            this.widgetContainerBelow,
            this.footerContainer,
        ]);
        this.defaultEditor.onAction("app.clear", () => this.handleCtrlC());
        this.defaultEditor.onCtrlD = () => this.handleCtrlD();
        this.defaultEditor.onSubmit = (text) => this.handleStartupSubmit(text);
        this.ui.setFocus(this.editor);
        this.ui.start();
        this.isInitialized = true;
        await this.themeController.applyFromSettings();
        if (this.options.verbose || !this.settingsManager.getQuietStartup()) {
            // 2026-10-14 (owner order): ALL startup key-hint lines are GONE. quiet
            // startup is hard-locked so this branch is dead in practice (kept for
            // --verbose debugging). The header is only the brand line.
            const logo = theme.bold(theme.fg("accent", APP_NAME)) + theme.fg("accent", ` v${this.version}`);
            this.builtInHeader = new ExpandableText(() => logo, () => logo, this.getStartupExpansionState(), 1, 0);
            this.headerContainer.addChild(new Spacer(1));
            this.headerContainer.addChild(this.builtInHeader);
            this.headerContainer.addChild(new Spacer(1));
        }
        else {
            this.builtInHeader = new Text("", 0, 0);
            this.headerContainer.addChild(this.builtInHeader);
        }
        this.ui.requestRender();
        const [fdPath] = await Promise.all([
            ensureTool("fd", (status) => this.showManagedToolStatus(status)),
            ensureTool("rg", (status) => this.showManagedToolStatus(status)),
        ]);
        this.fdPath = fdPath;
        this.setupKeyHandlers();
        this.setupEditorSubmitHandler();
        this.ui.requestRender();
        await this.rebindCurrentSession();
        this.renderInitialMessages();
        onThemeChange(() => {
            this.ui.invalidate();
            this.updateEditorBorderColor();
            this.ui.requestRender();
        });
        this.footerDataProvider.onBranchChange(() => {
            this.ui.requestRender();
        });
        await this.updateAvailableProviderCount();
    }
    updateTerminalTitle() {
        const cwdBasename = path.basename(this.sessionManager.getCwd());
        const sessionName = this.sessionManager.getSessionName();
        if (sessionName) {
            this.ui.terminal.setTitle(`${APP_TITLE} - ${sessionName} - ${cwdBasename}`);
        }
        else {
            this.ui.terminal.setTitle(`${APP_TITLE} - ${cwdBasename}`);
        }
    }
    async run() {
        await this.init();
        if (!process.env.CORTEX_OFFLINE) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 15_000);
            void refreshModelCatalogs(this.session.modelRuntime, controller.signal)
                .then(() => this.updateAvailableProviderCount())
                .catch(() => { })
                .finally(() => clearTimeout(timeout));
        }
        checkForNewCortexVersion(this.version).then((newRelease) => {
            if (newRelease) {
                this.showNewVersionNotification(newRelease);
            }
        });
        this.checkForPackageUpdates()
            .then((updates) => {
            if (updates.length > 0) {
                this.showPackageUpdateNotification(updates);
            }
        })
            .finally(() => {
            if (process.platform === "win32" && this.isInitialized) {
                this.updateTerminalTitle();
            }
        });
        this.checkTmuxKeyboardSetup().then((warning) => {
            if (warning) {
                this.showWarning(warning);
            }
        });
        const { migratedProviders, modelFallbackMessage, initialMessage, initialImages, initialMessages } = this.options;
        if (migratedProviders && migratedProviders.length > 0) {
            this.showWarning(`Migrated credentials to auth.json: ${migratedProviders.join(", ")}`);
        }
        const modelsJsonError = this.session.modelRuntime.getError();
        if (modelsJsonError) {
            this.showError(`models.json error: ${modelsJsonError}`);
        }
        if (modelFallbackMessage) {
            this.showWarning(modelFallbackMessage);
        }
        void this.maybeWarnAboutSubscriptionAuth();
        if (initialMessage) {
            try {
                await this.session.prompt(initialMessage, { images: initialImages });
            }
            catch (error) {
                const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";
                this.showError(errorMessage);
            }
        }
        if (initialMessages) {
            for (const message of initialMessages) {
                try {
                    await this.session.prompt(message);
                }
                catch (error) {
                    const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";
                    this.showError(errorMessage);
                }
            }
        }
        while (true) {
            const userInput = await this.getUserInput();
            try {
                await this.session.prompt(userInput);
            }
            catch (error) {
                const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";
                this.showError(errorMessage);
            }
        }
    }
    async checkForPackageUpdates() {
        if (process.env.CORTEX_OFFLINE) {
            return [];
        }
        try {
            const packageManager = new DefaultPackageManager({
                cwd: this.sessionManager.getCwd(),
                agentDir: getAgentDir(),
                settingsManager: this.settingsManager,
            });
            const updates = await packageManager.checkForAvailableUpdates();
            return updates.map((update) => update.displayName);
        }
        catch {
            return [];
        }
    }
    async checkTmuxKeyboardSetup() {
        if (!process.env.TMUX)
            return undefined;
        const runTmuxShow = (option) => {
            return new Promise((resolve) => {
                const proc = spawn("tmux", ["show", "-gv", option], {
                    stdio: ["ignore", "pipe", "ignore"],
                });
                let stdout = "";
                const timer = setTimeout(() => {
                    proc.kill();
                    resolve(undefined);
                }, 2000);
                proc.stdout?.on("data", (data) => {
                    stdout += data.toString();
                });
                proc.on("error", () => {
                    clearTimeout(timer);
                    resolve(undefined);
                });
                proc.on("close", (code) => {
                    clearTimeout(timer);
                    resolve(code === 0 ? stdout.trim() : undefined);
                });
            });
        };
        const [extendedKeys, extendedKeysFormat] = await Promise.all([
            runTmuxShow("extended-keys"),
            runTmuxShow("extended-keys-format"),
        ]);
        if (extendedKeys === undefined)
            return undefined;
        if (extendedKeys !== "on" && extendedKeys !== "always") {
            return "tmux extended-keys is off. Modified Enter keys may not work. Add `set -g extended-keys on` to ~/.tmux.conf and restart tmux.";
        }
        if (extendedKeysFormat === "xterm") {
            return "tmux extended-keys-format is xterm. Cortex works best with csi-u. Add `set -g extended-keys-format csi-u` to ~/.tmux.conf and restart tmux.";
        }
        return undefined;
    }
    getMarkdownThemeWithSettings() {
        return {
            ...getMarkdownTheme(),
            codeBlockIndent: this.settingsManager.getCodeBlockIndent(),
        };
    }
    formatDisplayPath(p) {
        const home = os.homedir();
        let result = p;
        if (result.startsWith(home)) {
            result = `~${result.slice(home.length)}`;
        }
        return result;
    }
    formatExtensionDisplayPath(path) {
        let result = this.formatDisplayPath(path);
        result = result.replace(/\/index\.ts$/, "").replace(/\/index\.js$/, "");
        return result;
    }
    formatContextPath(p) {
        const cwd = path.resolve(this.sessionManager.getCwd());
        const absolutePath = path.isAbsolute(p) ? path.resolve(p) : path.resolve(cwd, p);
        const relativePath = getCwdRelativePath(absolutePath, cwd);
        if (relativePath !== undefined) {
            return relativePath;
        }
        return this.formatDisplayPath(absolutePath);
    }
    getStartupExpansionState() {
        return this.options.verbose || this.toolOutputExpanded;
    }
    getShortPath(fullPath, sourceInfo) {
        const normalizedFullPath = fullPath.replace(/\\/g, "/");
        const baseDir = sourceInfo?.baseDir;
        if (baseDir && this.isPackageSource(sourceInfo)) {
            const normalizedBaseDir = baseDir.replace(/\\/g, "/");
            const npmRootMatch = normalizedBaseDir.match(/^(.*\/node_modules)\/(@?[^/]+(?:\/[^/]+)?)$/);
            if (npmRootMatch?.[1] && normalizedFullPath.startsWith(`${npmRootMatch[1]}/`)) {
                return path.posix.relative(normalizedBaseDir, normalizedFullPath);
            }
            const relativePath = path.relative(path.resolve(baseDir), path.resolve(fullPath));
            if (relativePath &&
                relativePath !== "." &&
                !relativePath.startsWith("..") &&
                !relativePath.startsWith(`..${path.sep}`) &&
                !path.isAbsolute(relativePath)) {
                return relativePath.replace(/\\/g, "/");
            }
        }
        const source = sourceInfo?.source ?? "";
        const npmMatch = normalizedFullPath.match(/node_modules\/(@?[^/]+(?:\/[^/]+)?)\/(.*)/);
        if (npmMatch && source.startsWith("npm:")) {
            return npmMatch[2];
        }
        const gitMatch = normalizedFullPath.match(/git\/[^/]+\/[^/]+\/(.*)/);
        if (gitMatch && source.startsWith("git:")) {
            return gitMatch[1];
        }
        return this.formatDisplayPath(fullPath);
    }
    getCompactPathLabel(resourcePath, sourceInfo) {
        const shortPath = this.getShortPath(resourcePath, sourceInfo);
        const normalizedPath = shortPath.replace(/\\/g, "/");
        const segments = normalizedPath.split("/").filter((segment) => segment.length > 0 && segment !== "~");
        if (segments.length > 0) {
            return segments[segments.length - 1];
        }
        return shortPath;
    }
    getCompactPackageSourceLabel(sourceInfo) {
        const source = sourceInfo?.source ?? "";
        if (source.startsWith("npm:")) {
            return source.slice("npm:".length) || source;
        }
        const gitSource = parseGitUrl(source);
        if (gitSource) {
            return gitSource.path || source;
        }
        return source;
    }
    getCompactExtensionLabel(resourcePath, sourceInfo) {
        if (!this.isPackageSource(sourceInfo)) {
            return this.getCompactPathLabel(resourcePath, sourceInfo);
        }
        const sourceLabel = this.getCompactPackageSourceLabel(sourceInfo);
        if (!sourceLabel) {
            return this.getCompactPathLabel(resourcePath, sourceInfo);
        }
        const shortPath = this.getShortPath(resourcePath, sourceInfo).replace(/\\/g, "/");
        const packagePath = shortPath.startsWith("extensions/") ? shortPath.slice("extensions/".length) : shortPath;
        const parsedPath = path.posix.parse(packagePath);
        if (parsedPath.name === "index") {
            return !parsedPath.dir || parsedPath.dir === "." ? sourceLabel : `${sourceLabel}:${parsedPath.dir}`;
        }
        return `${sourceLabel}:${packagePath}`;
    }
    getCompactDisplayPathSegments(resourcePath) {
        return this.formatDisplayPath(resourcePath)
            .replace(/\\/g, "/")
            .split("/")
            .filter((segment) => segment.length > 0 && segment !== "~");
    }
    getCompactNonPackageExtensionLabel(resourcePath, index, allPaths) {
        const segments = allPaths[index]?.segments;
        if (!segments || segments.length === 0) {
            return this.getCompactPathLabel(resourcePath);
        }
        for (let segmentCount = 1; segmentCount <= segments.length; segmentCount += 1) {
            const candidate = segments.slice(-segmentCount).join("/");
            const isUnique = allPaths.every((item, itemIndex) => {
                if (itemIndex === index) {
                    return true;
                }
                return item.segments.slice(-segmentCount).join("/") !== candidate;
            });
            if (isUnique) {
                return candidate;
            }
        }
        return segments.join("/");
    }
    getCompactExtensionLabels(extensions) {
        const nonPackageExtensions = extensions
            .map((extension) => {
            const segments = this.getCompactDisplayPathSegments(extension.path);
            const lastSegment = segments[segments.length - 1];
            if (segments.length > 1 && (lastSegment === "index.ts" || lastSegment === "index.js")) {
                segments.pop();
            }
            return {
                path: extension.path,
                sourceInfo: extension.sourceInfo,
                segments,
            };
        })
            .filter((extension) => !this.isPackageSource(extension.sourceInfo));
        return extensions.map((extension) => {
            if (this.isPackageSource(extension.sourceInfo)) {
                return this.getCompactExtensionLabel(extension.path, extension.sourceInfo);
            }
            const nonPackageIndex = nonPackageExtensions.findIndex((item) => item.path === extension.path);
            if (nonPackageIndex === -1) {
                return this.getCompactPathLabel(extension.path, extension.sourceInfo);
            }
            return this.getCompactNonPackageExtensionLabel(extension.path, nonPackageIndex, nonPackageExtensions);
        });
    }
    getDisplaySourceInfo(sourceInfo) {
        const source = sourceInfo?.source ?? "local";
        const scope = sourceInfo?.scope ?? "project";
        if (source === "local") {
            if (scope === "user") {
                return { label: "user", color: "muted" };
            }
            if (scope === "project") {
                return { label: "project", color: "muted" };
            }
            if (scope === "temporary") {
                return { label: "path", scopeLabel: "temp", color: "muted" };
            }
            return { label: "path", color: "muted" };
        }
        if (source === "cli") {
            return { label: "path", scopeLabel: scope === "temporary" ? "temp" : undefined, color: "muted" };
        }
        const scopeLabel = scope === "user" ? "user" : scope === "project" ? "project" : scope === "temporary" ? "temp" : undefined;
        return { label: source, scopeLabel, color: "accent" };
    }
    getScopeGroup(sourceInfo) {
        const source = sourceInfo?.source ?? "local";
        const scope = sourceInfo?.scope ?? "project";
        if (source === "cli" || scope === "temporary")
            return "path";
        if (scope === "user")
            return "user";
        if (scope === "project")
            return "project";
        return "path";
    }
    isPackageSource(sourceInfo) {
        const source = sourceInfo?.source ?? "";
        return source.startsWith("npm:") || source.startsWith("git:");
    }
    buildScopeGroups(items) {
        const groups = {
            user: { scope: "user", paths: [], packages: new Map() },
            project: { scope: "project", paths: [], packages: new Map() },
            path: { scope: "path", paths: [], packages: new Map() },
        };
        for (const item of items) {
            const groupKey = this.getScopeGroup(item.sourceInfo);
            const group = groups[groupKey];
            const source = item.sourceInfo?.source ?? "local";
            if (this.isPackageSource(item.sourceInfo)) {
                const list = group.packages.get(source) ?? [];
                list.push(item);
                group.packages.set(source, list);
            }
            else {
                group.paths.push(item);
            }
        }
        return [groups.project, groups.user, groups.path].filter((group) => group.paths.length > 0 || group.packages.size > 0);
    }
    formatScopeGroups(groups, options) {
        const lines = [];
        for (const group of groups) {
            lines.push(`  ${theme.fg("accent", group.scope)}`);
            const sortedPaths = [...group.paths].sort((a, b) => a.path.localeCompare(b.path));
            for (const item of sortedPaths) {
                lines.push(theme.fg("dim", `    ${options.formatPath(item)}`));
            }
            const sortedPackages = Array.from(group.packages.entries()).sort(([a], [b]) => a.localeCompare(b));
            for (const [source, items] of sortedPackages) {
                lines.push(`    ${theme.fg("mdLink", source)}`);
                const sortedPackagePaths = [...items].sort((a, b) => a.path.localeCompare(b.path));
                for (const item of sortedPackagePaths) {
                    lines.push(theme.fg("dim", `      ${options.formatPackagePath(item, source)}`));
                }
            }
        }
        return lines.join("\n");
    }
    findSourceInfoForPath(p, sourceInfos) {
        const exact = sourceInfos.get(p);
        if (exact)
            return exact;
        let current = p;
        while (current.includes("/")) {
            current = current.substring(0, current.lastIndexOf("/"));
            const parent = sourceInfos.get(current);
            if (parent)
                return parent;
        }
        return undefined;
    }
    formatPathWithSource(p, sourceInfo) {
        if (sourceInfo) {
            const shortPath = this.getShortPath(p, sourceInfo);
            const { label, scopeLabel } = this.getDisplaySourceInfo(sourceInfo);
            const labelText = scopeLabel ? `${label} (${scopeLabel})` : label;
            return `${labelText} ${shortPath}`;
        }
        return this.formatDisplayPath(p);
    }
    formatDiagnostics(diagnostics, sourceInfos) {
        const lines = [];
        const collisions = new Map();
        const otherDiagnostics = [];
        for (const d of diagnostics) {
            if (d.type === "collision" && d.collision) {
                const list = collisions.get(d.collision.name) ?? [];
                list.push(d);
                collisions.set(d.collision.name, list);
            }
            else {
                otherDiagnostics.push(d);
            }
        }
        for (const [name, collisionList] of collisions) {
            const first = collisionList[0]?.collision;
            if (!first)
                continue;
            lines.push(theme.fg("warning", `  "${name}" collision:`));
            lines.push(theme.fg("dim", `    ${theme.fg("success", "✓")} ${this.formatPathWithSource(first.winnerPath, this.findSourceInfoForPath(first.winnerPath, sourceInfos))}`));
            for (const d of collisionList) {
                if (d.collision) {
                    lines.push(theme.fg("dim", `    ${theme.fg("warning", "✗")} ${this.formatPathWithSource(d.collision.loserPath, this.findSourceInfoForPath(d.collision.loserPath, sourceInfos))} (skipped)`));
                }
            }
        }
        for (const d of otherDiagnostics) {
            if (d.path) {
                const formattedPath = this.formatPathWithSource(d.path, this.findSourceInfoForPath(d.path, sourceInfos));
                lines.push(theme.fg(d.type === "error" ? "error" : "warning", `  ${formattedPath}`));
                lines.push(theme.fg(d.type === "error" ? "error" : "warning", `    ${d.message}`));
            }
            else {
                lines.push(theme.fg(d.type === "error" ? "error" : "warning", `  ${d.message}`));
            }
        }
        return lines.join("\n");
    }
    showLoadedResources(options) {
        this.loadedResourcesContainer.clear();
        // 2026-10-14 (owner steering): the [Context]/[Skills]/… resource listing
        // is REAL UI — always shown at startup. Only the key-hint lists are
        // hard-locked off (elsewhere).
        const showListing = true;
        const showDiagnostics = true;
        if (!showListing && !showDiagnostics) {
            // Nothing will be printed above the panels, so the view is composed
            // as far as the mount guard is concerned.
            this.sessionViewComposed = true;
            return;
        }
        const sectionHeader = (name, color = "mdHeading") => theme.fg(color, `[${name}]`);
        const formatCompactList = (items, options) => {
            const labels = items.map((item) => item.trim()).filter((item) => item.length > 0);
            if (options?.sort !== false) {
                labels.sort((a, b) => a.localeCompare(b));
            }
            return theme.fg("dim", `  ${labels.join(", ")}`);
        };
        const addLoadedSection = (name, collapsedBody, expandedBody = collapsedBody, color = "mdHeading") => {
            const section = new ExpandableText(() => `${sectionHeader(name, color)}\n${collapsedBody}`, () => `${sectionHeader(name, color)}\n${expandedBody}`, this.getStartupExpansionState(), 0, 0);
            this.loadedResourcesContainer.addChild(section);
            this.loadedResourcesContainer.addChild(new Spacer(1));
        };
        const skillsResult = this.session.resourceLoader.getSkills();
        const promptsResult = this.session.resourceLoader.getPrompts();
        const themesResult = this.session.resourceLoader.getThemes();
        const extensions = options?.extensions ??
            this.session.resourceLoader
                .getExtensions()
                .extensions.filter((extension) => !extension.hidden)
                .map((extension) => ({
                path: extension.path,
                sourceInfo: extension.sourceInfo,
            }));
        const sourceInfos = new Map();
        for (const extension of extensions) {
            if (extension.sourceInfo) {
                sourceInfos.set(extension.path, extension.sourceInfo);
            }
        }
        for (const skill of skillsResult.skills) {
            if (skill.sourceInfo) {
                sourceInfos.set(skill.filePath, skill.sourceInfo);
            }
        }
        for (const prompt of promptsResult.prompts) {
            if (prompt.sourceInfo) {
                sourceInfos.set(prompt.filePath, prompt.sourceInfo);
            }
        }
        for (const loadedTheme of themesResult.themes) {
            if (loadedTheme.sourcePath && loadedTheme.sourceInfo) {
                sourceInfos.set(loadedTheme.sourcePath, loadedTheme.sourceInfo);
            }
        }
        if (showListing) {
            const systemPromptSource = this.session.resourceLoader.getSystemPromptSource();
            const contextFiles = [
                ...(systemPromptSource ? [systemPromptSource] : []),
                ...this.session.resourceLoader.getAppendSystemPromptSources(),
                ...this.session.resourceLoader.getAgentsFiles().agentsFiles,
            ];
            if (contextFiles.length > 0) {
                this.loadedResourcesContainer.addChild(new Spacer(1));
                const contextList = contextFiles
                    .map((f) => theme.fg("dim", `  ${this.formatDisplayPath(f.path)}`))
                    .join("\n");
                const contextCompactList = formatCompactList(contextFiles.map((contextFile) => this.formatContextPath(contextFile.path)), { sort: false });
                addLoadedSection("Context", contextCompactList, contextList);
            }
            // Skills hidden from startup — shown only when verbose.
            const showSkills = this.options.verbose;
            const skills = skillsResult.skills;
            if (showSkills && skills.length > 0) {
                const groups = this.buildScopeGroups(skills.map((skill) => ({ path: skill.filePath, sourceInfo: skill.sourceInfo })));
                const skillList = this.formatScopeGroups(groups, {
                    formatPath: (item) => this.formatDisplayPath(item.path),
                    formatPackagePath: (item) => this.getShortPath(item.path, item.sourceInfo),
                });
                const skillCompactList = formatCompactList(skills.map((skill) => skill.name));
                addLoadedSection("Skills", skillCompactList, skillList);
            }
            const templates = this.session.promptTemplates;
            if (templates.length > 0) {
                const groups = this.buildScopeGroups(templates.map((template) => ({ path: template.filePath, sourceInfo: template.sourceInfo })));
                const templateByPath = new Map(templates.map((t) => [t.filePath, t]));
                const templateList = this.formatScopeGroups(groups, {
                    formatPath: (item) => {
                        const template = templateByPath.get(item.path);
                        return template ? `/${template.name}` : this.formatDisplayPath(item.path);
                    },
                    formatPackagePath: (item) => {
                        const template = templateByPath.get(item.path);
                        return template ? `/${template.name}` : this.formatDisplayPath(item.path);
                    },
                });
                const promptCompactList = formatCompactList(templates.map((template) => `/${template.name}`));
                addLoadedSection("Prompts", promptCompactList, templateList);
            }
            // Extensions hidden from startup — shown only when verbose.
            const showExtensions = this.options.verbose;
            if (showExtensions && extensions.length > 0) {
                const groups = this.buildScopeGroups(extensions);
                const extList = this.formatScopeGroups(groups, {
                    formatPath: (item) => this.formatExtensionDisplayPath(item.path),
                    formatPackagePath: (item) => this.formatExtensionDisplayPath(this.getShortPath(item.path, item.sourceInfo)),
                });
                const extensionCompactList = formatCompactList(this.getCompactExtensionLabels(extensions));
                addLoadedSection("Extensions", extensionCompactList, extList, "mdHeading");
            }
            // Themes hidden from startup — shown only when verbose.
            const showThemes = this.options.verbose;
            if (showThemes) {
                const loadedThemes = themesResult.themes;
                const customThemes = loadedThemes.filter((t) => t.sourcePath);
                if (customThemes.length > 0) {
                    const groups = this.buildScopeGroups(customThemes.map((loadedTheme) => ({
                        path: loadedTheme.sourcePath,
                        sourceInfo: loadedTheme.sourceInfo,
                    })));
                    const themeList = this.formatScopeGroups(groups, {
                        formatPath: (item) => this.formatDisplayPath(item.path),
                        formatPackagePath: (item) => this.getShortPath(item.path, item.sourceInfo),
                    });
                    const themeCompactList = formatCompactList(customThemes.map((loadedTheme) => loadedTheme.name ?? this.getCompactPathLabel(loadedTheme.sourcePath, loadedTheme.sourceInfo)));
                    addLoadedSection("Themes", themeCompactList, themeList);
                }
            }
        }
        if (showDiagnostics) {
            const skillDiagnostics = skillsResult.diagnostics;
            if (skillDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(skillDiagnostics, sourceInfos);
                this.loadedResourcesContainer.addChild(new Text(`${theme.fg("warning", "[Skill conflicts]")}\n${warningLines}`, 0, 0));
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }
            const promptDiagnostics = promptsResult.diagnostics;
            if (promptDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(promptDiagnostics, sourceInfos);
                this.loadedResourcesContainer.addChild(new Text(`${theme.fg("warning", "[Prompt conflicts]")}\n${warningLines}`, 0, 0));
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }
            const extensionDiagnostics = [];
            const extensionErrors = this.session.resourceLoader.getExtensions().errors;
            if (extensionErrors.length > 0) {
                for (const error of extensionErrors) {
                    extensionDiagnostics.push({ type: "error", message: error.error, path: error.path });
                }
            }
            const commandDiagnostics = this.session.extensionRunner.getCommandDiagnostics();
            extensionDiagnostics.push(...commandDiagnostics);
            extensionDiagnostics.push(...this.getBuiltInCommandConflictDiagnostics(this.session.extensionRunner));
            const shortcutDiagnostics = this.session.extensionRunner.getShortcutDiagnostics();
            extensionDiagnostics.push(...shortcutDiagnostics);
            if (extensionDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(extensionDiagnostics, sourceInfos);
                this.loadedResourcesContainer.addChild(new Text(`${theme.fg("warning", "[Extension issues]")}\n${warningLines}`, 0, 0));
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }
            const themeDiagnostics = themesResult.diagnostics;
            if (themeDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(themeDiagnostics, sourceInfos);
                this.loadedResourcesContainer.addChild(new Text(`${theme.fg("warning", "[Theme conflicts]")}\n${warningLines}`, 0, 0));
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }
        }
        // The [Context] header and everything else above the panels is on screen
        // now, so the panels may join the next frame.
        this.sessionViewComposed = true;
    }
    async bindCurrentSessionExtensions() {
        const uiContext = this.createExtensionUIContext();
        await this.session.bindExtensions({
            uiContext,
            mode: "tui",
            abortHandler: () => {
                this.restoreQueuedMessagesToEditor({ abort: true });
            },
            commandContextActions: {
                waitForIdle: () => this.session.waitForIdle(),
                newSession: async (options) => {
                    this.clearStatusIndicator();
                    try {
                        return await this.runtimeHost.newSession(options);
                    }
                    catch (error) {
                        return this.handleFatalRuntimeError("Failed to create session", error);
                    }
                },
                fork: async (entryId, options) => {
                    try {
                        const result = await this.runtimeHost.fork(entryId, options);
                        if (!result.cancelled) {
                            this.editor.setText(result.selectedText ?? "");
                            this.showStatus("Forked to new session");
                        }
                        return { cancelled: result.cancelled };
                    }
                    catch (error) {
                        return this.handleFatalRuntimeError("Failed to fork session", error);
                    }
                },
                navigateTree: async (targetId, options) => {
                    const result = await this.session.navigateTree(targetId, {
                        summarize: options?.summarize,
                        customInstructions: options?.customInstructions,
                        replaceInstructions: options?.replaceInstructions,
                        label: options?.label,
                    });
                    if (result.cancelled) {
                        return { cancelled: true };
                    }
                    this.chatContainer.clear();
                    this.renderInitialMessages();
                    if (result.editorText && !this.editor.getText().trim()) {
                        this.editor.setText(result.editorText);
                    }
                    this.showStatus("Navigated to selected point");
                    void this.flushCompactionQueue({ willRetry: false });
                    return { cancelled: false };
                },
                switchSession: async (sessionPath, options) => {
                    return this.handleResumeSession(sessionPath, options);
                },
                reload: async () => {
                    await this.handleReloadCommand();
                },
            },
            shutdownHandler: () => {
                this.shutdownRequested = true;
                if (this.session.isIdle) {
                    void this.shutdown();
                }
            },
            onError: (error) => {
                this.showExtensionError(error.extensionPath, error.error, error.stack);
            },
        });
        setRegisteredThemes(this.session.resourceLoader.getThemes().themes);
        this.setupAutocompleteProvider();
        const extensionRunner = this.session.extensionRunner;
        this.setupExtensionShortcuts(extensionRunner);
        this.showLoadedResources({ force: false, showDiagnosticsWhenQuiet: true });
        // Mount the panels on this frame rather than on whichever unrelated
        // widget update happens to call renderWidgets() next.
        this.renderWidgets();
    }
    applyFullscreenScrollbarSetting() {
        this.transcriptScrollView?.setScrollbar(this.settingsManager.getFullscreenScrollbar());
    }
    applyRuntimeSettings() {
        configureHttpDispatcher(this.settingsManager.getHttpIdleTimeoutMs());
        this.applyFullscreenScrollbarSetting();
        this.footer.setSession(this.session);
        this.footer.setAutoCompactEnabled(this.session.autoCompactionEnabled);
        this.footerDataProvider.setCwd(this.sessionManager.getCwd());
        this.hideThinkingBlock = this.settingsManager.getHideThinkingBlock();
        this.outputPad = this.settingsManager.getOutputPad();
        this.ui.setShowHardwareCursor(this.settingsManager.getShowHardwareCursor());
        const clearOnShrink = this.settingsManager.getClearOnShrink();
        this.ui.setClearOnShrink(clearOnShrink);
        if (!clearOnShrink && !this.activeStatusIndicator) {
            this.statusContainer.clear();
        }
        const editorPaddingX = this.settingsManager.getEditorPaddingX();
        const autocompleteMaxVisible = this.settingsManager.getAutocompleteMaxVisible();
        this.defaultEditor.setPaddingX(editorPaddingX);
        this.defaultEditor.setAutocompleteMaxVisible(autocompleteMaxVisible);
        if (this.editor !== this.defaultEditor) {
            this.editor.setPaddingX?.(editorPaddingX);
            this.editor.setAutocompleteMaxVisible?.(autocompleteMaxVisible);
        }
    }
    async rebindCurrentSession(options = {}) {
        const session = this.session;
        this.unsubscribe?.();
        this.unsubscribe = undefined;
        this.applyRuntimeSettings();
        if (options.renderBeforeBind) {
            this.renderCurrentSessionState();
            this.subscribeToAgent();
        }
        await this.bindCurrentSessionExtensions();
        if (this.session !== session) {
            return;
        }
        if (!options.renderBeforeBind) {
            this.subscribeToAgent();
        }
        await this.updateAvailableProviderCount();
        this.updateEditorBorderColor();
        this.updateTerminalTitle();
    }
    async handleFatalRuntimeError(prefix, error) {
        const message = error instanceof Error ? error.message : String(error);
        this.showError(`${prefix}: ${message}`);
        stopThemeWatcher();
        this.stop("transcript");
        process.exit(1);
    }
    renderCurrentSessionState() {
        this.loadedResourcesContainer.clear();
        this.chatContainer.clear();
        this.pendingMessagesContainer.clear();
        this.compactionQueuedMessages = [];
        this.streamingComponent = undefined;
        this.streamingMessage = undefined;
        this.pendingTools.clear();
        this.renderInitialMessages();
    }
    getRegisteredToolDefinition(toolName) {
        return this.session.getToolDefinition(toolName);
    }
    getMarkdownTransformers() {
        return [this.mermaidMarkdownTransformer, ...this.session.extensionRunner.getMarkdownTransformers()];
    }
    setupExtensionShortcuts(extensionRunner) {
        // 2026-10-13 (owner order, ported from cloud fork): extension key
        // shortcuts are disabled — no extension can grab a key from the kept
        // command set. The extension shortcuts table in the /hotkeys view is
        // likewise suppressed.
        void extensionRunner;
    }
    setExtensionStatus(key, text) {
        this.footerDataProvider.setExtensionStatus(key, text);
        this.ui.requestRender();
    }
    showStatusIndicator(indicator) {
        this.activeStatusIndicator?.dispose();
        this.activeStatusIndicator = indicator;
        this.statusContainer.clear();
        this.statusContainer.addChild(indicator);
    }
    clearStatusIndicator(kind) {
        if (kind && this.activeStatusIndicator?.kind !== kind) {
            return;
        }
        const hadActiveStatusIndicator = this.activeStatusIndicator !== undefined;
        this.activeStatusIndicator?.dispose();
        this.activeStatusIndicator = undefined;
        this.statusContainer.clear();
        if (hadActiveStatusIndicator && this.options.tuiMode === "regular" && this.ui.getClearOnShrink()) {
            this.statusContainer.addChild(this.idleStatus);
        }
    }
    setWorkingVisible(visible) {
        this.workingVisible = visible;
        if (!visible) {
            this.clearStatusIndicator("working");
            this.ui.requestRender();
            return;
        }
        if (this.session.isStreaming && this.activeStatusIndicator?.kind !== "working") {
            this.showStatusIndicator(new WorkingStatusIndicator(this.ui, this.workingMessage ?? this.defaultWorkingMessage, this.workingIndicatorOptions));
        }
        this.ui.requestRender();
    }
    setWorkingIndicator(options) {
        this.workingIndicatorOptions = options;
        if (this.activeStatusIndicator?.kind === "working") {
            this.activeStatusIndicator.setIndicator(options);
        }
        this.ui.requestRender();
    }
    setHiddenThinkingLabel(label) {
        this.hiddenThinkingLabel = label ?? this.defaultHiddenThinkingLabel;
        for (const child of this.chatContainer.children) {
            if (child instanceof AssistantMessageComponent) {
                child.setHiddenThinkingLabel(this.hiddenThinkingLabel);
            }
        }
        if (this.streamingComponent) {
            this.streamingComponent.setHiddenThinkingLabel(this.hiddenThinkingLabel);
        }
        this.ui.requestRender();
    }
    setExtensionWidget(key, content, options) {
        const placement = options?.placement ?? "aboveEditor";
        const removeExisting = (map) => {
            const existing = map.get(key);
            if (existing?.dispose)
                existing.dispose();
            map.delete(key);
        };
        removeExisting(this.extensionWidgetsAbove);
        removeExisting(this.extensionWidgetsBelow);
        if (content === undefined) {
            this.renderWidgets();
            return;
        }
        let component;
        if (Array.isArray(content)) {
            const container = new Container();
            for (const line of content.slice(0, InteractiveMode.MAX_WIDGET_LINES)) {
                container.addChild(new Text(line, 0, 0));
            }
            if (content.length > InteractiveMode.MAX_WIDGET_LINES) {
                container.addChild(new Text(theme.fg("muted", "... (widget truncated)"), 1, 0));
            }
            component = container;
        }
        else {
            component = content(this.ui, theme);
        }
        const targetMap = placement === "belowEditor" ? this.extensionWidgetsBelow : this.extensionWidgetsAbove;
        targetMap.set(key, component);
        this.renderWidgets();
    }
    clearExtensionWidgets() {
        for (const widget of this.extensionWidgetsAbove.values()) {
            widget.dispose?.();
        }
        for (const widget of this.extensionWidgetsBelow.values()) {
            widget.dispose?.();
        }
        this.extensionWidgetsAbove.clear();
        this.extensionWidgetsBelow.clear();
        this.renderWidgets();
    }
    resetExtensionUI() {
        if (this.extensionSelector) {
            this.hideExtensionSelector();
        }
        if (this.extensionInput) {
            this.hideExtensionInput();
        }
        if (this.extensionEditor) {
            this.hideExtensionEditor();
        }
        this.ui.hideOverlay();
        this.clearExtensionTerminalInputListeners();
        this.setExtensionFooter(undefined);
        this.setExtensionHeader(undefined);
        this.clearExtensionWidgets();
        this.footerDataProvider.clearExtensionStatuses();
        this.footer.invalidate();
        this.autocompleteProviderWrappers = [];
        this.setCustomEditorComponent(undefined);
        this.setupAutocompleteProvider();
        this.defaultEditor.onExtensionShortcut = undefined;
        this.updateTerminalTitle();
        this.workingMessage = undefined;
        this.workingVisible = true;
        this.setWorkingIndicator();
        if (this.activeStatusIndicator?.kind === "working") {
            this.activeStatusIndicator.setMessage(`${this.defaultWorkingMessage} (${keyText("app.interrupt")} to interrupt)`);
        }
        this.setHiddenThinkingLabel();
    }
    static MAX_WIDGET_LINES = 10;
    renderWidgets() {
        if (!this.widgetContainerAbove || !this.widgetContainerBelow)
            return;
        this.renderWidgetContainer(this.widgetContainerAbove, this.extensionWidgetsAbove, true, true);
        this.renderWidgetContainer(this.widgetContainerBelow, this.extensionWidgetsBelow, false, false);
        // 2026-09-23: the status panels used to paint into scrollback at the TOP
        // of the session on first launch (before the [Context] header existed the
        // panels were the only content, so the first frame printed them at the
        // top and they stayed there). 2026-09-27: a 2s stopwatch did not hold —
        // extensions, skills, themes and the local model warm-up push the
        // [Context] pass past 2s, and the owner was left looking at a stale
        // Cloud Management / Messenger box above [Context] again. The signal is
        // the composition pass itself (showLoadedResources), with a generous net
        // in case that pass never happens.
        if (this.statusPanels &&
            panelsMayJoinFrame({ sessionViewComposed: this.sessionViewComposed, fallbackAt: this.panelsFallbackAt })) {
            this.widgetContainerAbove.addChild(this.statusPanels);
        }
        this.ui.requestRender();
    }
    /** Set by showLoadedResources: the pass that prints [Context] has run. */
    sessionViewComposed = false;
    panelsFallbackAt = Date.now() + PANELS_FALLBACK_MS;
    renderWidgetContainer(container, widgets, spacerWhenEmpty, leadingSpacer) {
        container.clear();
        if (widgets.size === 0) {
            if (spacerWhenEmpty) {
                container.addChild(new Spacer(1));
            }
            return;
        }
        if (leadingSpacer) {
            container.addChild(new Spacer(1));
        }
        for (const component of widgets.values()) {
            container.addChild(component);
        }
    }
    setExtensionFooter(factory) {
        if (this.customFooter?.dispose) {
            this.customFooter.dispose();
        }
        this.footerContainer.clear();
        if (factory) {
            this.customFooter = factory(this.ui, theme, this.footerDataProvider);
            this.footerContainer.addChild(this.customFooter);
        }
        else {
            this.customFooter = undefined;
            this.footerContainer.addChild(this.footer);
        }
        this.ui.requestRender();
    }
    setExtensionHeader(factory) {
        if (!this.builtInHeader) {
            return;
        }
        if (this.customHeader?.dispose) {
            this.customHeader.dispose();
        }
        const currentHeader = this.customHeader || this.builtInHeader;
        const index = this.headerContainer.children.indexOf(currentHeader);
        if (factory) {
            this.customHeader = factory(this.ui, theme);
            if (isExpandable(this.customHeader)) {
                this.customHeader.setExpanded(this.toolOutputExpanded);
            }
            if (index !== -1) {
                this.headerContainer.children[index] = this.customHeader;
            }
            else {
                this.headerContainer.children.unshift(this.customHeader);
            }
        }
        else {
            this.customHeader = undefined;
            if (isExpandable(this.builtInHeader)) {
                this.builtInHeader.setExpanded(this.toolOutputExpanded);
            }
            if (index !== -1) {
                this.headerContainer.children[index] = this.builtInHeader;
            }
        }
        this.ui.requestRender();
    }
    addExtensionTerminalInputListener(handler) {
        const subscription = { handler, unsubscribe: this.ui.addInputListener(handler) };
        this.extensionTerminalInputSubscriptions.add(subscription);
        return () => {
            subscription.unsubscribe();
            this.extensionTerminalInputSubscriptions.delete(subscription);
        };
    }
    rebindExtensionTerminalInputListeners() {
        for (const subscription of this.extensionTerminalInputSubscriptions) {
            subscription.unsubscribe();
            subscription.unsubscribe = this.ui.addInputListener(subscription.handler);
        }
    }
    clearExtensionTerminalInputListeners() {
        for (const subscription of this.extensionTerminalInputSubscriptions)
            subscription.unsubscribe();
        this.extensionTerminalInputSubscriptions.clear();
    }
    createProjectTrustContext(cwd) {
        const ui = this.createExtensionUIContext();
        return {
            cwd,
            mode: "tui",
            hasUI: true,
            ui: {
                select: ui.select,
                confirm: ui.confirm,
                input: ui.input,
                notify: ui.notify,
            },
        };
    }
    createExtensionUIContext() {
        return {
            select: (title, options, opts) => this.showExtensionSelector(title, options, opts),
            confirm: (title, message, opts) => this.showExtensionConfirm(title, message, opts),
            input: (title, placeholder, opts) => this.showExtensionInput(title, placeholder, opts),
            notify: (message, type) => this.showExtensionNotify(message, type),
            onTerminalInput: (handler) => this.addExtensionTerminalInputListener(handler),
            setStatus: (key, text) => this.setExtensionStatus(key, text),
            setWorkingMessage: (message) => {
                this.workingMessage = message;
                if (this.activeStatusIndicator?.kind === "working") {
                    this.activeStatusIndicator.setMessage(message ?? this.defaultWorkingMessage);
                }
            },
            setWorkingVisible: (visible) => this.setWorkingVisible(visible),
            setWorkingIndicator: (options) => this.setWorkingIndicator(options),
            setHiddenThinkingLabel: (label) => this.setHiddenThinkingLabel(label),
            setWidget: (key, content, options) => this.setExtensionWidget(key, content, options),
            setFooter: (factory) => this.setExtensionFooter(factory),
            setHeader: (factory) => this.setExtensionHeader(factory),
            setTitle: (title) => this.ui.terminal.setTitle(title),
            custom: (factory, options) => this.showExtensionCustom(factory, options),
            pasteToEditor: (text) => this.editor.handleInput(`\x1b[200~${text}\x1b[201~`),
            setEditorText: (text) => this.editor.setText(text),
            getEditorText: () => this.editor.getExpandedText?.() ?? this.editor.getText(),
            editor: (title, prefill) => this.showExtensionEditor(title, prefill),
            addAutocompleteProvider: (factory) => {
                this.autocompleteProviderWrappers.push(factory);
                this.setupAutocompleteProvider();
            },
            setEditorComponent: (factory) => this.setCustomEditorComponent(factory),
            getEditorComponent: () => this.editorComponentFactory,
            get theme() {
                return theme;
            },
            getAllThemes: () => getAvailableThemesWithPaths(),
            getTheme: (name) => getThemeByName(name),
            setTheme: (themeOrName) => {
                if (themeOrName instanceof Theme) {
                    return this.themeController.setThemeInstance(themeOrName);
                }
                const result = this.themeController.setThemeName(themeOrName);
                if (result.success) {
                    if (this.settingsManager.getTheme() !== themeOrName) {
                        this.settingsManager.setTheme(themeOrName);
                    }
                }
                return result;
            },
            getToolsExpanded: () => this.toolOutputExpanded,
            setToolsExpanded: (expanded) => this.setToolsExpanded(expanded),
        };
    }
    showExtensionSelector(title, options, opts) {
        return new Promise((resolve) => {
            if (opts?.signal?.aborted) {
                resolve(undefined);
                return;
            }
            const onAbort = () => {
                this.hideExtensionSelector();
                resolve(undefined);
            };
            opts?.signal?.addEventListener("abort", onAbort, { once: true });
            this.extensionSelector = new ExtensionSelectorComponent(title, options, (option) => {
                opts?.signal?.removeEventListener("abort", onAbort);
                this.hideExtensionSelector();
                resolve(option);
            }, () => {
                opts?.signal?.removeEventListener("abort", onAbort);
                this.hideExtensionSelector();
                resolve(undefined);
            }, { tui: this.ui, timeout: opts?.timeout, onToggleToolsExpanded: () => this.toggleToolOutputExpansion() });
            this.disposeActiveSelector();
            this.editorContainer.clear();
            this.editorContainer.addChild(this.extensionSelector);
            this.ui.setFocus(this.extensionSelector);
            this.ui.requestRender();
        });
    }
    hideExtensionSelector() {
        this.extensionSelector?.dispose();
        this.editorContainer.clear();
        this.editorContainer.addChild(this.editor);
        this.extensionSelector = undefined;
        this.ui.setFocus(this.editor);
        this.ui.requestRender();
    }
    async showExtensionConfirm(title, message, opts) {
        const result = await this.showExtensionSelector(`${title}\n${message}`, ["Yes", "No"], opts);
        return result === "Yes";
    }
    async promptForMissingSessionCwd(error) {
        const confirmed = await this.showExtensionConfirm("Session cwd not found", formatMissingSessionCwdPrompt(error.issue));
        return confirmed ? error.issue.fallbackCwd : undefined;
    }
    showExtensionInput(title, placeholder, opts) {
        return new Promise((resolve) => {
            if (opts?.signal?.aborted) {
                resolve(undefined);
                return;
            }
            const onAbort = () => {
                this.hideExtensionInput();
                resolve(undefined);
            };
            opts?.signal?.addEventListener("abort", onAbort, { once: true });
            this.extensionInput = new ExtensionInputComponent(title, placeholder, (value) => {
                opts?.signal?.removeEventListener("abort", onAbort);
                this.hideExtensionInput();
                resolve(value);
            }, () => {
                opts?.signal?.removeEventListener("abort", onAbort);
                this.hideExtensionInput();
                resolve(undefined);
            }, { tui: this.ui, timeout: opts?.timeout });
            this.disposeActiveSelector();
            this.editorContainer.clear();
            this.editorContainer.addChild(this.extensionInput);
            this.ui.setFocus(this.extensionInput);
            this.ui.requestRender();
        });
    }
    hideExtensionInput() {
        this.extensionInput?.dispose();
        this.editorContainer.clear();
        this.editorContainer.addChild(this.editor);
        this.extensionInput = undefined;
        this.ui.setFocus(this.editor);
        this.ui.requestRender();
    }
    showExtensionEditor(title, prefill) {
        return new Promise((resolve) => {
            this.extensionEditor = new ExtensionEditorComponent(this.ui, this.keybindings, title, prefill, (value) => {
                this.hideExtensionEditor();
                resolve(value);
            }, () => {
                this.hideExtensionEditor();
                resolve(undefined);
            }, undefined, this.settingsManager.getExternalEditorCommand());
            this.disposeActiveSelector();
            this.editorContainer.clear();
            this.editorContainer.addChild(this.extensionEditor);
            this.ui.setFocus(this.extensionEditor);
            this.ui.requestRender();
        });
    }
    hideExtensionEditor() {
        this.editorContainer.clear();
        this.editorContainer.addChild(this.editor);
        this.extensionEditor = undefined;
        this.ui.setFocus(this.editor);
        this.ui.requestRender();
    }
    setCustomEditorComponent(factory) {
        this.editorComponentFactory = factory;
        const currentText = this.editor.getText();
        this.disposeActiveSelector();
        this.editorContainer.clear();
        if (factory) {
            const newEditor = factory(this.ui, getEditorTheme(), this.keybindings);
            newEditor.onSubmit = this.defaultEditor.onSubmit;
            newEditor.onChange = this.defaultEditor.onChange;
            newEditor.setText(currentText);
            if (newEditor.borderColor !== undefined) {
                newEditor.borderColor = this.defaultEditor.borderColor;
            }
            if (newEditor.setPaddingX !== undefined) {
                newEditor.setPaddingX(this.defaultEditor.getPaddingX());
            }
            if (newEditor.setAutocompleteMaxVisible !== undefined) {
                newEditor.setAutocompleteMaxVisible(this.defaultEditor.getAutocompleteMaxVisible());
            }
            if (newEditor.setAutocompleteProvider && this.autocompleteProvider) {
                newEditor.setAutocompleteProvider(this.autocompleteProvider);
            }
            const customEditor = newEditor;
            if ("actionHandlers" in customEditor && customEditor.actionHandlers instanceof Map) {
                if (!customEditor.onEscape) {
                    customEditor.onEscape = () => this.defaultEditor.onEscape?.();
                }
                if (!customEditor.onCtrlD) {
                    customEditor.onCtrlD = () => this.defaultEditor.onCtrlD?.();
                }
                if (!customEditor.onPasteImage) {
                    customEditor.onPasteImage = () => this.defaultEditor.onPasteImage?.();
                }
                if (!customEditor.onExtensionShortcut) {
                    customEditor.onExtensionShortcut = (data) => this.defaultEditor.onExtensionShortcut?.(data);
                }
                for (const [action, handler] of this.defaultEditor.actionHandlers) {
                    customEditor.actionHandlers.set(action, handler);
                }
            }
            this.editor = newEditor;
        }
        else {
            this.defaultEditor.setText(currentText);
            this.editor = this.defaultEditor;
        }
        this.editorContainer.addChild(this.editor);
        this.ui.setFocus(this.editor);
        this.ui.requestRender();
    }
    showExtensionNotify(message, type) {
        if (type === "error") {
            this.showError(message);
        }
        else if (type === "warning") {
            this.showWarning(message);
        }
        else {
            this.showStatus(message);
        }
    }
    async showExtensionCustom(factory, options) {
        const savedText = this.editor.getText();
        const isOverlay = options?.overlay ?? false;
        const restoreEditor = () => {
            this.editorContainer.clear();
            this.editorContainer.addChild(this.editor);
            this.editor.setText(savedText);
            this.ui.setFocus(this.editor);
            this.ui.requestRender();
        };
        return new Promise((resolve, reject) => {
            let component;
            let closed = false;
            const close = (result) => {
                if (closed)
                    return;
                closed = true;
                if (isOverlay)
                    this.ui.hideOverlay();
                else
                    restoreEditor();
                resolve(result);
                try {
                    component?.dispose?.();
                }
                catch {
                    /* ignore dispose errors */
                }
            };
            Promise.resolve(factory(this.ui, theme, this.keybindings, close))
                .then((c) => {
                if (closed)
                    return;
                component = c;
                if (isOverlay) {
                    const resolveOptions = () => {
                        if (options?.overlayOptions) {
                            const opts = typeof options.overlayOptions === "function"
                                ? options.overlayOptions()
                                : options.overlayOptions;
                            return opts;
                        }
                        const w = component.width;
                        return w ? { width: w } : undefined;
                    };
                    const handle = this.ui.showOverlay(component, resolveOptions());
                    options?.onHandle?.(handle);
                }
                else {
                    this.disposeActiveSelector();
                    this.editorContainer.clear();
                    this.editorContainer.addChild(component);
                    this.ui.setFocus(component);
                    this.ui.requestRender();
                }
            })
                .catch((err) => {
                if (closed)
                    return;
                if (!isOverlay)
                    restoreEditor();
                reject(err);
            });
        });
    }
    showExtensionError(extensionPath, error, stack) {
        const errorMsg = `Extension "${extensionPath}" error: ${error}`;
        const errorText = new Text(theme.fg("error", errorMsg), 1, 0);
        this.chatContainer.addChild(errorText);
        if (stack) {
            const stackLines = stack
                .split("\n")
                .slice(1)
                .map((line) => theme.fg("dim", `  ${line.trim()}`))
                .join("\n");
            if (stackLines) {
                this.chatContainer.addChild(new Text(stackLines, 1, 0));
            }
        }
        this.ui.requestRender();
    }
    setupKeyHandlers() {
        this.defaultEditor.onEscape = () => {
            if (this.session.isStreaming) {
                this.restoreQueuedMessagesToEditor({ abort: true });
            }
            else if (this.session.isBashRunning) {
                this.session.abortBash();
            }
            else if (this.isBashMode) {
                this.editor.setText("");
                this.isBashMode = false;
                this.updateEditorBorderColor();
            }
            else if (!this.editor.getText().trim()) {
                // 2026-10-13 (owner order, ported): double-escape action disabled —
                // the double-press still resets timing, nothing opens. Interrupt
                // Escape itself is untouched.
                this.lastEscapeTime = Date.now();
            }
        };
        this.defaultEditor.onAction("app.clear", () => this.handleCtrlC());
        this.defaultEditor.onCtrlD = () => this.handleCtrlD();
        this.defaultEditor.onAction("app.suspend", () => this.handleCtrlZ());
        // 2026-10-13 (owner order, ported from cloud fork): only these commands
        // stay — Escape interrupt, ctrl+c clear, ctrl+d exit, ctrl+z suspend,
        // ctrl+g external editor, ctrl+v/drop paste. Thinking/model/tools cycles
        // and selectors are registered as NO-OP with the keybinding freed (key
        // shows nothing in hints), extensions can't rebind a disabled arm.
        this.defaultEditor.onAction("app.thinking.cycle", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.model.cycleForward", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.model.cycleBackward", () => this.showStatus("Disabled in CortexAgent"));
        this.ui.onDebug = () => this.showStatus("Disabled in CortexAgent");
        this.defaultEditor.onAction("app.model.select", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.tools.expand", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.thinking.toggle", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.leftStrip.toggle", () => {
            if (this.leftStrip) {
                this.leftStrip.toggle();
                this.ui.requestRender();
            }
        });
        this.defaultEditor.onAction("app.editor.external", () => void this.handleOpenExternalEditor());
        this.defaultEditor.onAction("app.message.copy", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.message.followUp", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.message.dequeue", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.session.new", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.session.tree", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.session.fork", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onAction("app.session.resume", () => this.showStatus("Disabled in CortexAgent"));
        this.defaultEditor.onChange = (text) => {
            const wasBashMode = this.isBashMode;
            this.isBashMode = text.trimStart().startsWith("!");
            if (wasBashMode !== this.isBashMode) {
                this.updateEditorBorderColor();
            }
        };
        this.defaultEditor.onPasteImage = () => {
            void this.handleClipboardPaste();
        };
    }
    async handleRightClickPaste() {
        const target = this.renderer.getFocusedComponent();
        const handleInput = target?.handleInput;
        if (!target || !handleInput)
            return;
        try {
            const text = await readClipboardText();
            if (!text || this.renderer.getFocusedComponent() !== target)
                return;
            handleInput.call(target, `\x1b[200~${text}\x1b[201~`);
            this.ui.requestRender();
        }
        catch {
            // Silently ignore clipboard errors (may not have permission, etc.)
        }
    }
    async handleClipboardPaste() {
        try {
            const image = await readClipboardImage();
            if (image) {
                const tmpDir = os.tmpdir();
                const ext = extensionForImageMimeType(image.mimeType) ?? "png";
                const fileName = `cortex-clipboard-${crypto.randomUUID()}.${ext}`;
                const filePath = path.join(tmpDir, fileName);
                fs.writeFileSync(filePath, Buffer.from(image.bytes));
                this.editor.insertTextAtCursor?.(filePath);
                this.ui.requestRender();
                return;
            }
            const text = await readClipboardText();
            if (text) {
                this.editor.insertTextAtCursor?.(text);
                this.ui.requestRender();
            }
        }
        catch {
            // Silently ignore clipboard errors (may not have permission, etc.)
        }
    }
    handleStartupSubmit(text) {
        this.editor.setText(text);
        this.showStatus("Startup is still in progress");
    }
    setupEditorSubmitHandler() {
        this.defaultEditor.onSubmit = async (text) => {
            text = text.trim();
            if (!text)
                return;
            if (text === "/settings") {
                this.showSettingsSelector();
                this.editor.setText("");
                return;
            }
            if (text === "/export" || text.startsWith("/export ")) {
                await this.handleExportCommand(text);
                this.editor.setText("");
                return;
            }
            if (text === "/import" || text.startsWith("/import ")) {
                await this.handleImportCommand(text);
                this.editor.setText("");
                return;
            }
            if (text === "/resume") {
                this.editor.setText("");
                void this.handleResumeCommand();
                return;
            }
            if (text === "/continue") {
                this.editor.setText("");
                void this.handleContinueCommand();
                return;
            }
            if (text === "/share") {
                this.editor.setText("");
                this.showWarning("Command disabled in CortexAgent");
                return;
            }
            if (text === "/copy") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/name" || text.startsWith("/name ")) {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/session") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/hotkeys") {
                this.handleHotkeysCommand();
                this.editor.setText("");
                return;
            }
            if (text === "/fork") {
                // 2026-10-13 (owner order): fork/tree/trust UI is session-management
                // tooling — disabled. Arm stays so the command never falls through
                // to the model as a prompt.
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/clone") {
                this.editor.setText("");
                await this.handleCloneCommand();
                return;
            }
            if (text === "/tree") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/trust") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/login" || text.startsWith("/login ")) {
                this.editor.setText("");
                this.showWarning("Command disabled in CortexAgent");
                return;
            }
            if (text === "/logout") {
                this.editor.setText("");
                this.showWarning("Command disabled in CortexAgent");
                return;
            }
            if (text === "/new") {
                this.editor.setText("");
                await this.handleClearCommand();
                return;
            }
            if (text === "/compact" || text.startsWith("/compact ")) {
                this.editor.setText("");
                // 2026-10-18 (owner order): /compact re-enabled. The threshold
                // auto-compact was broken (the engine reports prompt_tokens as the
                // n_ctx cap, so shouldCompact never fired) — manual compaction is
                // the recovery path until that's fixed upstream.
                const instructions = text.startsWith("/compact ") ? text.slice("/compact ".length).trim() : undefined;
                void this.session.compact(instructions).then(() => this.showStatus("Compacted"), (error) => this.showWarning(error instanceof Error ? error.message : String(error)));
                return;
            }
            if (text === "/reload") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/debug") {
                this.editor.setText("");
                this.showStatus("Command disabled in CortexAgent");
                return;
            }
            if (text === "/resume") {
                this.editor.setText("");
                this.showWarning("Command disabled in CortexAgent");
                return;
            }
            if (text === "/quit") {
                this.editor.setText("");
                await this.shutdown();
                return;
            }
            if (text.startsWith("!")) {
                const isExcluded = text.startsWith("!!");
                const command = isExcluded ? text.slice(2).trim() : text.slice(1).trim();
                if (command) {
                    if (this.session.isBashRunning) {
                        this.showWarning("A bash command is already running. Press Esc to cancel it first.");
                        this.editor.setText(text);
                        return;
                    }
                    this.editor.addToHistory?.(text);
                    await this.handleBashCommand(command, isExcluded);
                    this.isBashMode = false;
                    this.updateEditorBorderColor();
                    return;
                }
            }
            if (this.session.isCompacting) {
                if (this.isExtensionCommand(text)) {
                    this.editor.addToHistory?.(text);
                    this.editor.setText("");
                    await this.session.prompt(text);
                }
                else {
                    this.queueCompactionMessage(text, "steer");
                }
                return;
            }
            if (this.session.isStreaming) {
                // 2026-10-13 (owner order): most slash commands are disabled; steer
                // sends the line to the agent verbatim instead of executing a dead
                // command mid-stream.
                this.editor.addToHistory?.(text);
                this.editor.setText("");
                await this.session.prompt(text, { streamingBehavior: "steer" });
                this.updatePendingMessagesDisplay();
                this.ui.requestRender();
                return;
            }
            this.flushPendingBashComponents();
            if (this.onInputCallback) {
                this.onInputCallback(text);
            }
            else {
                this.pendingUserInputs.push(text);
            }
            this.editor.addToHistory?.(text);
        };
    }
    /**
     * 2026-10-24 (owner: "have it wait on input while the model is loading"):
     * the send is ALREADY queued through the retry ladder (settings.retry),
     * so this is purely display — while :7080 answers 503 "Loading model",
     * the status line says so instead of the user seeing nothing. It polls
     * the server's own /health every 2s (bounded by the loader's own 600s
     * timeout), and reports readiness so the wait has a visible end.
     */
    modelLoadNotifierRunning = false;
    async notifyIfModelLoading() {
        if (this.modelLoadNotifierRunning)
            return;
        this.modelLoadNotifierRunning = true;
        try {
            const healthUrl = process.env.CORTEXENGINE_MODEL_HEALTH_URL ?? "http://127.0.0.1:7080/health";
            let healthy = false;
            for (let poll = 0; poll < 300 && !healthy; poll++) {
                try {
                    const res = await fetch(healthUrl, { signal: AbortSignal.timeout(700) });
                    healthy = res.ok;
                }
                catch {
                    healthy = false;
                }
                if (!healthy) {
                    if (poll === 0) {
                        this.showStatus("⏳ model loading on :7080 — your message is queued and answers when it's ready");
                    }
                    await new Promise((resolve) => setTimeout(resolve, 2000));
                }
            }
            if (healthy) {
                this.showStatus("🟢 model ready — responding");
            }
            else {
                this.showWarning("model did not come up in time — the send may still retry or fail");
            }
        }
        finally {
            this.modelLoadNotifierRunning = false;
        }
    }
    // 2026-11-11 (owner: "when i press up it doesnt have any history"): the hot
    // memory store already records every prompt across ALL sessions — seed the
    // editor's in-memory history from it at startup so ↑ recalls the owner's
    // recent prompts from day zero. Best-effort: missing/locked store = no-op.
    seedEditorHistoryFromHotStore() {
        try {
            const dir = process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory");
            const file = path.join(dir, "hot", "cortexagent.jsonl");
            if (!fs.existsSync(file))
                return;
            const lines = fs.readFileSync(file, "utf-8").trim().split("\n");
            const recent = [];
            for (let i = lines.length - 1; i >= 0 && recent.length < 50; i--) {
                try {
                    const row = JSON.parse(lines[i]);
                    if (row.role === "user" && row.content)
                        recent.push(row.content);
                }
                catch {
                    /* skip malformed rows */
                }
            }
            // addToHistory unshifts and de-dupes the immediate repeat; feed oldest
            // first so the newest prompt sits at index 0 for the first ↑.
            for (let i = recent.length - 1; i >= 0; i--) {
                this.defaultEditor.addToHistory?.(recent[i]);
            }
        }
        catch {
            /* best-effort */
        }
    }
    /**
     * 2026-10-24 (owner): the Memory panel is fed HERE — every user prompt
     * appends to the hot store the panel reads (the same NDJSON rows the
     * old daemon wrote), so "+N recent" and the topic line reflect THIS
     * session instead of a dead daemon's last write. Best-effort: a full
     * disk or a locked store must never break the chat.
     */
    writeHotMemory(message) {
        try {
            if (message.role !== "user")
                return;
            let text = "";
            if (typeof message.content === "string") {
                text = message.content;
            }
            else if (Array.isArray(message.content)) {
                for (const part of message.content) {
                    if (part.type === "text" && typeof part.text === "string")
                        text += part.text;
                }
            }
            text = text.trim();
            if (!text)
                return;
            const dir = process.env.CORTEXAGENT_MEMORY_DIR ?? path.join(os.homedir(), ".cortex-agent", "memory");
            fs.mkdirSync(path.join(dir, "hot"), { recursive: true });
            const line = JSON.stringify({
                role: "user",
                content: text.slice(0, 2000),
                timestamp: new Date().toISOString().slice(0, 19).replace("T", " "),
            });
            fs.appendFileSync(path.join(dir, "hot", "cortexagent.jsonl"), `${line}\n`);
        }
        catch {
            /* best-effort — memory writes must never break the chat */
        }
    }
    subscribeToAgent() {
        this.unsubscribe = this.session.subscribe(async (event) => {
            await this.handleEvent(event);
        });
    }
    async handleEvent(event) {
        if (!this.isInitialized) {
            await this.init();
        }
        this.footer.invalidate();
        switch (event.type) {
            case "agent_start":
                this.statusPanels?.onGenerationState(true);
                void this.notifyIfModelLoading();
                this.pendingTools.clear();
                if (this.settingsManager.getShowTerminalProgress()) {
                    this.ui.terminal.setProgress(true);
                }
                if (this.retryEscapeHandler) {
                    this.defaultEditor.onEscape = this.retryEscapeHandler;
                    this.retryEscapeHandler = undefined;
                }
                if (this.workingVisible) {
                    this.showStatusIndicator(new WorkingStatusIndicator(this.ui, this.workingMessage ?? this.defaultWorkingMessage, this.workingIndicatorOptions));
                }
                else {
                    this.clearStatusIndicator();
                }
                this.ui.requestRender();
                break;
            case "queue_update":
                this.updatePendingMessagesDisplay();
                this.ui.requestRender();
                break;
            case "entry_appended":
                if (event.entry.type === "custom") {
                    this.addCustomEntryToChat(event.entry);
                    this.ui.requestRender();
                }
                break;
            case "session_info_changed":
                this.updateTerminalTitle();
                this.footer.invalidate();
                this.ui.requestRender();
                break;
            case "thinking_level_changed":
                this.footer.invalidate();
                this.updateEditorBorderColor();
                break;
            case "message_start":
                if (event.message.role === "custom") {
                    this.addMessageToChat(event.message);
                    this.ui.requestRender();
                }
                else if (event.message.role === "user") {
                    this.addMessageToChat(event.message);
                    this.writeHotMemory(event.message);
                    this.updatePendingMessagesDisplay();
                    this.ui.requestRender();
                }
                else if (event.message.role === "assistant") {
                    this.streamingComponent = new AssistantMessageComponent(undefined, this.hideThinkingBlock, this.getMarkdownThemeWithSettings(), this.hiddenThinkingLabel, this.outputPad, this.getMarkdownTransformers(), this.settingsManager.getCollapseCodeBlocks());
                    this.streamingMessage = event.message;
                    this.chatContainer.addChild(this.streamingComponent);
                    this.streamingComponent.updateContent(this.streamingMessage, true);
                    this.ui.requestRender();
                }
                break;
            case "message_update":
                // 2026-10-24 (owner): realtime tok/s for the Tokens panel —
                // one text/thinking delta ≈ one generated token.
                {
                    const ame = event.assistantMessageEvent;
                    if (ame && (ame.type === "text_delta" || ame.type === "thinking_delta")) {
                        this.statusPanels?.onStreamDelta();
                    }
                }
                if (this.streamingComponent && event.message.role === "assistant") {
                    this.streamingMessage = event.message;
                    this.streamingComponent.updateContent(this.streamingMessage, true);
                    for (const content of this.streamingMessage.content) {
                        if (content.type === "toolCall") {
                            if (!this.pendingTools.has(content.id)) {
                                const component = new ToolExecutionComponent(content.name, content.id, content.arguments, {
                                    showImages: this.settingsManager.getShowImages(),
                                    imageWidthCells: this.settingsManager.getImageWidthCells(),
                                }, this.getRegisteredToolDefinition(content.name), this.ui, this.sessionManager.getCwd());
                                component.setExpanded(this.toolOutputExpanded);
                                this.chatContainer.addChild(component);
                                this.pendingTools.set(content.id, component);
                            }
                            else {
                                const component = this.pendingTools.get(content.id);
                                if (component) {
                                    component.updateArgs(content.arguments);
                                }
                            }
                        }
                    }
                    this.ui.requestRender();
                }
                break;
            case "message_end":
                if (event.message.role === "user")
                    break;
                if (this.streamingComponent && event.message.role === "assistant") {
                    this.streamingMessage = event.message;
                    let errorMessage;
                    if (this.streamingMessage.stopReason === "aborted") {
                        const retryAttempt = this.session.retryAttempt;
                        errorMessage =
                            retryAttempt > 0
                                ? `Aborted after ${retryAttempt} retry attempt${retryAttempt > 1 ? "s" : ""}`
                                : "Operation aborted";
                        this.streamingMessage.errorMessage = errorMessage;
                    }
                    this.streamingComponent.updateContent(this.streamingMessage, false);
                    if (this.streamingMessage.stopReason === "aborted" || this.streamingMessage.stopReason === "error") {
                        if (!errorMessage) {
                            errorMessage = this.streamingMessage.errorMessage || "Error";
                        }
                        for (const [, component] of this.pendingTools.entries()) {
                            component.updateResult({
                                content: [{ type: "text", text: errorMessage }],
                                isError: true,
                            });
                        }
                        this.pendingTools.clear();
                    }
                    else {
                        for (const [, component] of this.pendingTools.entries()) {
                            component.setArgsComplete();
                        }
                        this.maybeShowCacheMissNotice(this.streamingMessage);
                    }
                    this.streamingComponent = undefined;
                    this.streamingMessage = undefined;
                    this.footer.invalidate();
                }
                this.ui.requestRender();
                break;
            case "bash_execution_update":
                break;
            case "tool_execution_start": {
                let component = this.pendingTools.get(event.toolCallId);
                if (!component) {
                    component = new ToolExecutionComponent(event.toolName, event.toolCallId, event.args, {
                        showImages: this.settingsManager.getShowImages(),
                        imageWidthCells: this.settingsManager.getImageWidthCells(),
                    }, this.getRegisteredToolDefinition(event.toolName), this.ui, this.sessionManager.getCwd());
                    component.setExpanded(this.toolOutputExpanded);
                    this.chatContainer.addChild(component);
                    this.pendingTools.set(event.toolCallId, component);
                }
                component.markExecutionStarted();
                this.ui.requestRender();
                break;
            }
            case "tool_execution_update": {
                const component = this.pendingTools.get(event.toolCallId);
                if (component) {
                    component.updateResult({ ...event.partialResult, isError: false }, true);
                    this.ui.requestRender();
                }
                break;
            }
            case "tool_execution_end": {
                const component = this.pendingTools.get(event.toolCallId);
                if (component) {
                    component.updateResult({ ...event.result, isError: event.isError });
                    this.pendingTools.delete(event.toolCallId);
                    this.ui.requestRender();
                }
                break;
            }
            case "agent_end":
                this.statusPanels?.onGenerationState(false);
                if (this.settingsManager.getShowTerminalProgress()) {
                    this.ui.terminal.setProgress(false);
                }
                this.clearStatusIndicator("working");
                if (this.streamingComponent) {
                    this.chatContainer.removeChild(this.streamingComponent);
                    this.streamingComponent = undefined;
                    this.streamingMessage = undefined;
                }
                this.pendingTools.clear();
                this.ui.requestRender();
                break;
            case "agent_settled":
                await this.checkShutdownRequested();
                break;
            case "compaction_start": {
                if (this.settingsManager.getShowTerminalProgress()) {
                    this.ui.terminal.setProgress(true);
                }
                this.autoCompactionEscapeHandler = this.defaultEditor.onEscape;
                this.defaultEditor.onEscape = () => {
                    this.session.abortCompaction();
                };
                this.showStatusIndicator(new CompactionStatusIndicator(this.ui, event.reason));
                this.ui.requestRender();
                break;
            }
            case "compaction_end": {
                if (this.settingsManager.getShowTerminalProgress()) {
                    this.ui.terminal.setProgress(false);
                }
                if (this.autoCompactionEscapeHandler) {
                    this.defaultEditor.onEscape = this.autoCompactionEscapeHandler;
                    this.autoCompactionEscapeHandler = undefined;
                }
                this.clearStatusIndicator("compaction");
                if (event.aborted) {
                    if (event.reason === "manual") {
                        this.showError("Compaction cancelled");
                    }
                    else {
                        this.showStatus("Auto-compaction cancelled");
                    }
                }
                else if (event.result) {
                    this.chatContainer.clear();
                    this.rebuildChatFromMessages();
                    this.addMessageToChat(createCompactionSummaryMessage(event.result.summary, event.result.tokensBefore, new Date().toISOString()));
                    this.footer.invalidate();
                }
                else if (event.errorMessage) {
                    if (event.reason === "manual") {
                        this.showError(event.errorMessage);
                    }
                    else {
                        this.chatContainer.addChild(new Spacer(1));
                        this.chatContainer.addChild(new Text(theme.fg("error", event.errorMessage), 1, 0));
                    }
                }
                void this.flushCompactionQueue({ willRetry: event.willRetry });
                this.ui.requestRender();
                break;
            }
            case "auto_retry_start": {
                this.retryEscapeHandler = this.defaultEditor.onEscape;
                this.defaultEditor.onEscape = () => {
                    this.session.abortRetry();
                };
                this.showStatusIndicator(new RetryStatusIndicator(this.ui, event.attempt, event.maxAttempts, event.delayMs));
                this.ui.requestRender();
                break;
            }
            case "auto_continue": {
                // 2026-10-26: the turn was truncated and recovery did not land;
                // the harness re-prompts itself instead of idling (see
                // AgentSession._autoContinueAfterStall).
                this.showStatus(`Auto-continued after a truncated turn (${event.attempt}/${event.maxAttempts})`);
                this.ui.requestRender();
                break;
            }
            case "auto_retry_end": {
                if (this.retryEscapeHandler) {
                    this.defaultEditor.onEscape = this.retryEscapeHandler;
                    this.retryEscapeHandler = undefined;
                }
                this.clearStatusIndicator("retry");
                if (!event.success) {
                    this.showError(`Retry failed after ${event.attempt} attempts: ${event.finalError || "Unknown error"}`);
                }
                this.ui.requestRender();
                break;
            }
            case "summarization_retry_scheduled": {
                this.showError(event.errorMessage);
                this.showStatusIndicator(new RetryStatusIndicator(this.ui, event.attempt, event.maxAttempts, event.delayMs));
                this.ui.requestRender();
                break;
            }
            case "summarization_retry_attempt_start": {
                this.clearStatusIndicator("retry");
                if (event.source === "branchSummary") {
                    this.showStatusIndicator(new BranchSummaryStatusIndicator(this.ui));
                }
                else {
                    this.showStatusIndicator(new CompactionStatusIndicator(this.ui, event.reason));
                }
                this.ui.requestRender();
                break;
            }
            case "summarization_retry_finished": {
                this.clearStatusIndicator("retry");
                this.ui.requestRender();
                break;
            }
        }
    }
    getUserMessageText(message) {
        if (message.role !== "user")
            return "";
        const textBlocks = typeof message.content === "string"
            ? [{ type: "text", text: message.content }]
            : message.content.filter((c) => c.type === "text");
        return textBlocks.map((c) => c.text).join("");
    }
    showManagedToolStatus(status) {
        if (!this.managedToolStatusStarted) {
            this.chatContainer.addChild(new Spacer(1));
            this.managedToolStatusStarted = true;
        }
        const message = status.type === "warning" ? `Warning: ${status.message}` : status.message;
        const color = status.type === "warning" ? "warning" : "dim";
        this.chatContainer.addChild(new Text(theme.fg(color, message), 1, 0));
        this.lastStatusSpacer = undefined;
        this.lastStatusText = undefined;
        this.ui.requestRender();
    }
    showStatus(message) {
        const children = this.chatContainer.children;
        const last = children.length > 0 ? children[children.length - 1] : undefined;
        const secondLast = children.length > 1 ? children[children.length - 2] : undefined;
        if (last && secondLast && last === this.lastStatusText && secondLast === this.lastStatusSpacer) {
            this.lastStatusText.setText(theme.fg("dim", message));
            this.ui.requestRender();
            return;
        }
        const spacer = new Spacer(1);
        const text = new Text(theme.fg("dim", message), 1, 0);
        this.chatContainer.addChild(spacer);
        this.chatContainer.addChild(text);
        this.lastStatusSpacer = spacer;
        this.lastStatusText = text;
        this.ui.requestRender();
    }
    addCustomEntryToChat(entry) {
        const renderer = this.session.extensionRunner.getEntryRenderer(entry.customType);
        if (!renderer) {
            return;
        }
        const component = new CustomEntryComponent(entry, renderer);
        component.setExpanded(this.toolOutputExpanded);
        if (!component.hasContent()) {
            return;
        }
        if (this.streamingComponent) {
            const streamingIndex = this.chatContainer.children.indexOf(this.streamingComponent);
            if (streamingIndex >= 0) {
                this.chatContainer.children.splice(streamingIndex, 0, component);
                return;
            }
        }
        this.chatContainer.addChild(component);
    }
    addMessageToChat(message, options) {
        switch (message.role) {
            case "bashExecution": {
                const component = new BashExecutionComponent(message.command, this.ui, message.excludeFromContext);
                if (message.output) {
                    component.appendOutput(message.output);
                }
                component.setComplete(message.exitCode, message.cancelled, message.truncated ? { truncated: true } : undefined, message.fullOutputPath);
                this.chatContainer.addChild(component);
                break;
            }
            case "custom": {
                if (message.display) {
                    const renderer = this.session.extensionRunner.getMessageRenderer(message.customType);
                    const component = new CustomMessageComponent(message, renderer, this.getMarkdownThemeWithSettings(), this.outputPad);
                    component.setExpanded(this.toolOutputExpanded);
                    this.chatContainer.addChild(component);
                }
                break;
            }
            case "compactionSummary": {
                this.chatContainer.addChild(new Spacer(1));
                const component = new CompactionSummaryMessageComponent(message, this.getMarkdownThemeWithSettings());
                component.setExpanded(this.toolOutputExpanded);
                this.chatContainer.addChild(component);
                break;
            }
            case "branchSummary": {
                this.chatContainer.addChild(new Spacer(1));
                const component = new BranchSummaryMessageComponent(message, this.getMarkdownThemeWithSettings());
                component.setExpanded(this.toolOutputExpanded);
                this.chatContainer.addChild(component);
                break;
            }
            case "user": {
                const textContent = this.getUserMessageText(message);
                if (textContent) {
                    if (this.chatContainer.children.length > 0) {
                        this.chatContainer.addChild(new Spacer(1));
                    }
                    const skillBlock = parseSkillBlock(textContent);
                    if (skillBlock) {
                        const component = new SkillInvocationMessageComponent(skillBlock, this.getMarkdownThemeWithSettings());
                        component.setExpanded(this.toolOutputExpanded);
                        this.chatContainer.addChild(component);
                        if (skillBlock.userMessage) {
                            this.chatContainer.addChild(new Spacer(1));
                            const userComponent = new UserMessageComponent(skillBlock.userMessage, this.getMarkdownThemeWithSettings(), this.outputPad, this.getMarkdownTransformers());
                            this.chatContainer.addChild(userComponent);
                        }
                    }
                    else {
                        const userComponent = new UserMessageComponent(textContent, this.getMarkdownThemeWithSettings(), this.outputPad, this.getMarkdownTransformers());
                        this.chatContainer.addChild(userComponent);
                    }
                    if (options?.populateHistory) {
                        this.editor.addToHistory?.(textContent);
                    }
                }
                break;
            }
            case "assistant": {
                const assistantComponent = new AssistantMessageComponent(message, this.hideThinkingBlock, this.getMarkdownThemeWithSettings(), this.hiddenThinkingLabel, this.outputPad, this.getMarkdownTransformers(), this.settingsManager.getCollapseCodeBlocks());
                this.chatContainer.addChild(assistantComponent);
                break;
            }
            case "toolResult": {
                break;
            }
            default: {
                const _exhaustive = message;
            }
        }
    }
    renderSessionItems(items, options = {}) {
        this.pendingTools.clear();
        const renderedPendingTools = new Map();
        const cacheMisses = this.settingsManager.getShowCacheMissNotices()
            ? collectCacheMisses(this.sessionManager.getEntries(), this.session.modelRuntime)
            : new Map();
        if (options.updateFooter) {
            this.footer.invalidate();
            this.updateEditorBorderColor();
        }
        for (const item of items) {
            if (isCustomSessionEntry(item)) {
                this.addCustomEntryToChat(item);
                continue;
            }
            const message = item;
            if (message.role === "assistant") {
                this.addMessageToChat(message);
                for (const content of message.content) {
                    if (content.type === "toolCall") {
                        const component = new ToolExecutionComponent(content.name, content.id, content.arguments, {
                            showImages: this.settingsManager.getShowImages(),
                            imageWidthCells: this.settingsManager.getImageWidthCells(),
                        }, this.getRegisteredToolDefinition(content.name), this.ui, this.sessionManager.getCwd());
                        component.setExpanded(this.toolOutputExpanded);
                        this.chatContainer.addChild(component);
                        if (message.stopReason === "aborted" || message.stopReason === "error") {
                            let errorMessage;
                            if (message.stopReason === "aborted") {
                                const retryAttempt = this.session.retryAttempt;
                                errorMessage =
                                    retryAttempt > 0
                                        ? `Aborted after ${retryAttempt} retry attempt${retryAttempt > 1 ? "s" : ""}`
                                        : "Operation aborted";
                            }
                            else {
                                errorMessage = message.errorMessage || "Error";
                            }
                            component.updateResult({ content: [{ type: "text", text: errorMessage }], isError: true });
                        }
                        else {
                            renderedPendingTools.set(content.id, component);
                        }
                    }
                }
                if (message.stopReason !== "aborted" && message.stopReason !== "error") {
                    const miss = cacheMisses.get(message);
                    if (miss)
                        this.addCacheMissNotice(miss);
                }
            }
            else if (message.role === "toolResult") {
                const component = renderedPendingTools.get(message.toolCallId);
                if (component) {
                    component.updateResult(message);
                    renderedPendingTools.delete(message.toolCallId);
                }
            }
            else {
                this.addMessageToChat(message, options);
            }
        }
        for (const [toolCallId, component] of renderedPendingTools) {
            this.pendingTools.set(toolCallId, component);
        }
        this.ui.requestRender();
    }
    renderSessionEntries(entries, options = {}) {
        const items = entries.flatMap((entry) => {
            if (entry.type === "custom") {
                return [entry];
            }
            return sessionEntryToContextMessages(entry);
        });
        this.renderSessionItems(items, options);
    }
    maybeShowCacheMissNotice(message) {
        if (!this.settingsManager.getShowCacheMissNotices())
            return;
        const miss = detectCacheMiss(this.sessionManager.getEntries(), message, this.session.modelRuntime);
        if (miss)
            this.addCacheMissNotice(miss);
    }
    addCacheMissNotice(miss) {
        if (miss.missedTokens < 20_000 && miss.missedCost < 0.1)
            return;
        const cost = miss.missedCost >= 0.01 ? ` (~$${miss.missedCost.toFixed(2)})` : "";
        const reBilled = `${formatTokens(miss.missedTokens)} tokens re-billed${cost}`;
        let label = "Cache miss";
        if (miss.modelChanged) {
            label = "Cache miss after model switch";
        }
        else if (miss.idleMs >= CACHE_TTL_MS) {
            label = `Cache miss after ${Math.round(miss.idleMs / 60_000)}m idle`;
        }
        const text = theme.fg("warning", `${label}: ${reBilled}`);
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new Text(text, 1, 0));
    }
    renderInitialMessages() {
        const entries = this.sessionManager.buildContextEntries();
        this.renderSessionEntries(entries, {
            updateFooter: true,
            populateHistory: true,
        });
        this.renderProjectTrustWarningIfNeeded();
        const allEntries = this.sessionManager.getEntries();
        const compactionCount = allEntries.filter((e) => e.type === "compaction").length;
        if (compactionCount > 0) {
            const times = compactionCount === 1 ? "1 time" : `${compactionCount} times`;
            this.showStatus(`Session compacted ${times}`);
        }
    }
    renderProjectTrustWarningIfNeeded() {
        if (this.settingsManager.isProjectTrusted() || !hasTrustRequiringProjectResources(this.sessionManager.getCwd())) {
            return;
        }
        if (this.chatContainer.children.length > 0) {
            this.chatContainer.addChild(new Spacer(1));
        }
        this.chatContainer.addChild(new Text(theme.fg("warning", `This project is not trusted. Project ${CONFIG_DIR_NAME} resources and packages are ignored. Use /trust to save a trust decision, then restart cortex.`), 1, 0));
    }
    async getUserInput() {
        const queuedInput = this.pendingUserInputs.shift();
        if (queuedInput !== undefined) {
            return queuedInput;
        }
        return new Promise((resolve) => {
            this.onInputCallback = (text) => {
                this.onInputCallback = undefined;
                resolve(text);
            };
        });
    }
    rebuildChatFromMessages() {
        this.chatContainer.clear();
        this.renderSessionEntries(this.sessionManager.buildContextEntries());
    }
    handleCtrlC() {
        const now = Date.now();
        if (now - this.lastSigintTime < 500) {
            void this.shutdown();
        }
        else {
            this.clearEditor();
            this.lastSigintTime = now;
        }
    }
    handleCtrlD() {
        void this.shutdown();
    }
    isShuttingDown = false;
    async shutdown(options) {
        if (this.isShuttingDown)
            return;
        this.isShuttingDown = true;
        if (options?.fromSignal) {
            await this.runtimeHost.dispose();
            this.themeController.disableAutoSync();
            await this.ui.terminal.drainInput(1000);
            this.stop();
            process.exit(0);
        }
        this.themeController.disableAutoSync();
        await this.ui.terminal.drainInput(1000);
        this.stop();
        await this.runtimeHost.dispose();
        const resumeCommand = formatResumeCommand(this.sessionManager);
        if (resumeCommand) {
            process.stdout.write(`${chalk.dim("To resume this session:")} ${resumeCommand}\n`);
        }
        process.exit(0);
    }
    emergencyTerminalExit() {
        this.isShuttingDown = true;
        this.unregisterSignalHandlers();
        killTrackedDetachedChildren();
        process.exit(129);
    }
    uncaughtCrash(error) {
        if (this.isShuttingDown) {
            process.exit(1);
        }
        this.isShuttingDown = true;
        try {
            this.unregisterSignalHandlers();
        }
        catch { }
        try {
            killTrackedDetachedChildren();
        }
        catch { }
        try {
            this.ui.stop();
        }
        catch { }
        console.error("cortex exiting due to uncaughtException:");
        console.error(error);
        process.exit(1);
    }
    async checkShutdownRequested() {
        if (!this.shutdownRequested)
            return;
        await this.shutdown();
    }
    registerSignalHandlers() {
        this.unregisterSignalHandlers();
        const signals = ["SIGTERM"];
        if (process.platform !== "win32") {
            signals.push("SIGHUP");
        }
        for (const signal of signals) {
            const handler = () => {
                killTrackedDetachedChildren();
                void this.shutdown({ fromSignal: true });
            };
            process.prependListener(signal, handler);
            this.signalCleanupHandlers.push(() => process.off(signal, handler));
        }
        const terminalErrorHandler = (error) => {
            if (isDeadTerminalError(error)) {
                this.emergencyTerminalExit();
            }
            throw error;
        };
        process.stdout.on("error", terminalErrorHandler);
        process.stderr.on("error", terminalErrorHandler);
        this.signalCleanupHandlers.push(() => process.stdout.off("error", terminalErrorHandler));
        this.signalCleanupHandlers.push(() => process.stderr.off("error", terminalErrorHandler));
        const uncaughtExceptionHandler = (error) => this.uncaughtCrash(error);
        process.prependListener("uncaughtException", uncaughtExceptionHandler);
        this.signalCleanupHandlers.push(() => process.off("uncaughtException", uncaughtExceptionHandler));
    }
    unregisterSignalHandlers() {
        for (const cleanup of this.signalCleanupHandlers) {
            cleanup();
        }
        this.signalCleanupHandlers = [];
    }
    handleCtrlZ() {
        if (process.platform === "win32") {
            this.showStatus("Suspend to background is not supported on Windows");
            return;
        }
        const suspendKeepAlive = setInterval(() => { }, 2 ** 30);
        const ignoreSigint = () => { };
        process.on("SIGINT", ignoreSigint);
        process.once("SIGCONT", () => {
            clearInterval(suspendKeepAlive);
            process.removeListener("SIGINT", ignoreSigint);
            this.ui.start();
            this.ui.requestRender(true);
        });
        try {
            this.ui.stop();
            process.kill(0, "SIGTSTP");
        }
        catch (error) {
            clearInterval(suspendKeepAlive);
            process.removeListener("SIGINT", ignoreSigint);
            throw error;
        }
    }
    updateEditorBorderColor() {
        if (this.isBashMode) {
            this.editor.borderColor = theme.getBashModeBorderColor();
        }
        else {
            const level = this.session.thinkingLevel || "off";
            this.editor.borderColor = theme.getThinkingBorderColor(level);
        }
        this.ui.requestRender();
    }
    toggleToolOutputExpansion() {
        this.setToolsExpanded(!this.toolOutputExpanded);
    }
    setToolsExpanded(expanded) {
        if (expanded === this.toolOutputExpanded)
            return;
        this.toolOutputExpanded = expanded;
        const activeHeader = this.customHeader ?? this.builtInHeader;
        if (isExpandable(activeHeader)) {
            activeHeader.setExpanded(expanded);
        }
        for (const container of [this.loadedResourcesContainer, this.chatContainer]) {
            for (const child of container.children) {
                if (isExpandable(child)) {
                    child.setExpanded(expanded);
                }
            }
        }
        this.showStatus(`Tool output: ${expanded ? "expanded" : "collapsed"}`);
    }
    toggleThinkingBlockVisibility() {
        // HARD-CODED: thinking is never shown. The toggle is a no-op so the
        // user can't flip it back on.
        this.hideThinkingBlock = true;
        this.settingsManager.setHideThinkingBlock(true);
        this.showStatus("Thinking blocks: hidden (hard-coded)");
    }
    async handleOpenExternalEditor() {
        const editorCmd = this.settingsManager.getExternalEditorCommand();
        const content = this.editor.getExpandedText?.() ?? this.editor.getText();
        this.ui.stop();
        try {
            const result = await editInExternalEditor({
                command: editorCmd,
                content,
            });
            if (result.status === "complete") {
                this.editor.setText(result.content);
            }
        }
        finally {
            this.ui.start();
            this.ui.requestRender(true);
        }
    }
    clearEditor() {
        this.editor.setText("");
        this.ui.requestRender();
    }
    showError(errorMessage) {
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new Text(theme.fg("error", `Error: ${errorMessage}`), this.outputPad, 0));
        this.ui.requestRender();
    }
    showWarning(warningMessage) {
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new Text(theme.fg("warning", `Warning: ${warningMessage}`), 1, 0));
        this.ui.requestRender();
    }
    showNewVersionNotification(release) {
        const action = theme.fg("accent", `${APP_NAME} update`);
        const updateInstruction = theme.fg("muted", `New version ${release.version} is available. Run `) + action;
        const note = release.note?.trim();
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new DynamicBorder((text) => theme.fg("warning", text)));
        this.chatContainer.addChild(new Text(`${theme.bold(theme.fg("warning", "Update Available"))}\n${updateInstruction}`, 1, 0));
        if (note) {
            this.chatContainer.addChild(new Spacer(1));
            this.chatContainer.addChild(new Markdown(note, 1, 0, this.getMarkdownThemeWithSettings(), {
                color: (text) => theme.fg("muted", text),
            }));
            this.chatContainer.addChild(new Spacer(1));
        }
        this.chatContainer.addChild(new DynamicBorder((text) => theme.fg("warning", text)));
        this.ui.requestRender();
    }
    showPackageUpdateNotification(packages) {
        const action = theme.fg("accent", `${APP_NAME} update --extensions`);
        const updateInstruction = theme.fg("muted", "Package updates are available. Run ") + action;
        const packageLines = packages.map((pkg) => `- ${pkg}`).join("\n");
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new DynamicBorder((text) => theme.fg("warning", text)));
        this.chatContainer.addChild(new Text(`${theme.bold(theme.fg("warning", "Package Updates Available"))}\n${updateInstruction}\n${theme.fg("muted", "Packages:")}\n${packageLines}`, 1, 0));
        this.chatContainer.addChild(new DynamicBorder((text) => theme.fg("warning", text)));
        this.ui.requestRender();
    }
    getAllQueuedMessages() {
        return {
            steering: [
                ...this.session.getSteeringMessages(),
                ...this.compactionQueuedMessages.filter((msg) => msg.mode === "steer").map((msg) => msg.text),
            ],
            followUp: [
                ...this.session.getFollowUpMessages(),
                ...this.compactionQueuedMessages.filter((msg) => msg.mode === "followUp").map((msg) => msg.text),
            ],
        };
    }
    clearAllQueues() {
        const { steering, followUp } = this.session.clearQueue();
        const compactionSteering = this.compactionQueuedMessages
            .filter((msg) => msg.mode === "steer")
            .map((msg) => msg.text);
        const compactionFollowUp = this.compactionQueuedMessages
            .filter((msg) => msg.mode === "followUp")
            .map((msg) => msg.text);
        this.compactionQueuedMessages = [];
        return {
            steering: [...steering, ...compactionSteering],
            followUp: [...followUp, ...compactionFollowUp],
        };
    }
    updatePendingMessagesDisplay() {
        this.pendingMessagesContainer.clear();
        const { steering: steeringMessages, followUp: followUpMessages } = this.getAllQueuedMessages();
        if (steeringMessages.length > 0 || followUpMessages.length > 0) {
            this.pendingMessagesContainer.addChild(new Spacer(1));
            for (const message of steeringMessages) {
                const text = theme.fg("dim", `Steering: ${message}`);
                this.pendingMessagesContainer.addChild(new TruncatedText(text, 1, 0));
            }
            for (const message of followUpMessages) {
                const text = theme.fg("dim", `Follow-up: ${message}`);
                this.pendingMessagesContainer.addChild(new TruncatedText(text, 1, 0));
            }
            const dequeueHint = this.getAppKeyDisplay("app.message.dequeue");
            const hintText = theme.fg("dim", `↳ ${dequeueHint} to edit all queued messages`);
            this.pendingMessagesContainer.addChild(new TruncatedText(hintText, 1, 0));
        }
    }
    restoreQueuedMessagesToEditor(options) {
        const { steering, followUp } = this.clearAllQueues();
        const allQueued = [...steering, ...followUp];
        if (allQueued.length === 0) {
            this.updatePendingMessagesDisplay();
            if (options?.abort) {
                this.agent.abort();
            }
            return 0;
        }
        const queuedText = allQueued.join("\n\n");
        const currentText = options?.currentText ?? this.editor.getText();
        const combinedText = [queuedText, currentText].filter((t) => t.trim()).join("\n\n");
        this.editor.setText(combinedText);
        this.updatePendingMessagesDisplay();
        if (options?.abort) {
            this.agent.abort();
        }
        return allQueued.length;
    }
    queueCompactionMessage(text, mode) {
        this.compactionQueuedMessages.push({ text, mode });
        this.editor.addToHistory?.(text);
        this.editor.setText("");
        this.updatePendingMessagesDisplay();
        this.showStatus("Queued message for after compaction");
    }
    isExtensionCommand(text) {
        if (!text.startsWith("/"))
            return false;
        const extensionRunner = this.session.extensionRunner;
        const spaceIndex = text.indexOf(" ");
        const commandName = spaceIndex === -1 ? text.slice(1) : text.slice(1, spaceIndex);
        return !!extensionRunner.getCommand(commandName);
    }
    async flushCompactionQueue(options) {
        if (this.compactionQueuedMessages.length === 0) {
            return;
        }
        const queuedMessages = [...this.compactionQueuedMessages];
        this.compactionQueuedMessages = [];
        this.updatePendingMessagesDisplay();
        const restoreQueue = (error) => {
            this.session.clearQueue();
            this.compactionQueuedMessages = queuedMessages;
            this.updatePendingMessagesDisplay();
            this.showError(`Failed to send queued message${queuedMessages.length > 1 ? "s" : ""}: ${error instanceof Error ? error.message : String(error)}`);
        };
        try {
            if (options?.willRetry) {
                for (const message of queuedMessages) {
                    if (this.isExtensionCommand(message.text)) {
                        await this.session.prompt(message.text);
                    }
                    else if (message.mode === "followUp") {
                        await this.session.followUp(message.text);
                    }
                    else {
                        await this.session.steer(message.text);
                    }
                }
                this.updatePendingMessagesDisplay();
                return;
            }
            const firstPromptIndex = queuedMessages.findIndex((message) => !this.isExtensionCommand(message.text));
            if (firstPromptIndex === -1) {
                for (const message of queuedMessages) {
                    await this.session.prompt(message.text);
                }
                return;
            }
            const preCommands = queuedMessages.slice(0, firstPromptIndex);
            const firstPrompt = queuedMessages[firstPromptIndex];
            const rest = queuedMessages.slice(firstPromptIndex + 1);
            for (const message of preCommands) {
                await this.session.prompt(message.text);
            }
            const promptPromise = this.session
                .prompt(firstPrompt.text, { streamingBehavior: firstPrompt.mode })
                .catch((error) => {
                restoreQueue(error);
            });
            for (const message of rest) {
                if (this.isExtensionCommand(message.text)) {
                    await this.session.prompt(message.text);
                }
                else if (message.mode === "followUp") {
                    await this.session.followUp(message.text);
                }
                else {
                    await this.session.steer(message.text);
                }
            }
            this.updatePendingMessagesDisplay();
            void promptPromise;
        }
        catch (error) {
            restoreQueue(error);
        }
    }
    flushPendingBashComponents() {
        for (const component of this.pendingBashComponents) {
            this.pendingMessagesContainer.removeChild(component);
            this.chatContainer.addChild(component);
        }
        this.pendingBashComponents = [];
    }
    disposeActiveSelector() {
        const dispose = this.activeSelectorDispose;
        this.activeSelectorToken = undefined;
        this.activeSelectorDispose = undefined;
        dispose?.();
    }
    showSelector(create) {
        const token = {};
        let dispose;
        const done = () => {
            dispose?.();
            if (this.activeSelectorToken !== token)
                return;
            this.activeSelectorToken = undefined;
            this.activeSelectorDispose = undefined;
            this.editorContainer.clear();
            this.editorContainer.addChild(this.editor);
            this.ui.setFocus(this.editor);
        };
        const created = create(done);
        dispose = created.dispose;
        this.disposeActiveSelector();
        this.activeSelectorToken = token;
        this.activeSelectorDispose = dispose;
        this.editorContainer.clear();
        this.editorContainer.addChild(created.component);
        this.ui.setFocus(created.focus);
        this.ui.requestRender();
    }
    showSettingsSelector() {
        this.showSelector((done) => {
            let selector;
            selector = new SettingsSelectorComponent({
                autoCompact: this.session.autoCompactionEnabled,
                showImages: this.settingsManager.getShowImages(),
                imageWidthCells: this.settingsManager.getImageWidthCells(),
                autoResizeImages: this.settingsManager.getImageAutoResize(),
                blockImages: this.settingsManager.getBlockImages(),
                enableSkillCommands: this.settingsManager.getEnableSkillCommands(),
                steeringMode: this.session.steeringMode,
                followUpMode: this.session.followUpMode,
                transport: this.settingsManager.getTransport(),
                httpIdleTimeoutMs: this.settingsManager.getHttpIdleTimeoutMs(),
                thinkingLevel: this.session.thinkingLevel,
                availableThinkingLevels: this.session.getAvailableThinkingLevels(),
                currentTheme: this.themeController.getThemeSelection() || "dark",
                terminalTheme: this.themeController.getTerminalTheme(),
                availableThemes: getAvailableThemes(),
                hideThinkingBlock: this.hideThinkingBlock,
                collapseCodeBlocks: this.settingsManager.getCollapseCodeBlocks(),
                mermaidRenderingMode: this.settingsManager.getMermaidRenderingMode(),
                enableInstallTelemetry: this.settingsManager.getEnableInstallTelemetry(),
                doubleEscapeAction: this.settingsManager.getDoubleEscapeAction(),
                treeFilterMode: this.settingsManager.getTreeFilterMode(),
                showHardwareCursor: this.settingsManager.getShowHardwareCursor(),
                showCacheMissNotices: this.settingsManager.getShowCacheMissNotices(),
                defaultProjectTrust: this.settingsManager.getDefaultProjectTrust(),
                editorPaddingX: this.settingsManager.getEditorPaddingX(),
                outputPad: this.settingsManager.getOutputPad(),
                autocompleteMaxVisible: this.settingsManager.getAutocompleteMaxVisible(),
                quietStartup: this.settingsManager.getQuietStartup(),
                clearOnShrink: this.settingsManager.getClearOnShrink(),
                showTerminalProgress: this.settingsManager.getShowTerminalProgress(),
                tuiMode: this.ui.mode,
                fullscreenExitOutput: this.settingsManager.getFullscreenExitOutput(),
                fullscreenScrollbar: this.settingsManager.getFullscreenScrollbar(),
                warnings: this.settingsManager.getWarnings(),
            }, {
                onAutoCompactChange: (enabled) => {
                    this.session.setAutoCompactionEnabled(enabled);
                    this.footer.setAutoCompactEnabled(enabled);
                },
                onShowImagesChange: (enabled) => {
                    this.settingsManager.setShowImages(enabled);
                    for (const child of this.chatContainer.children) {
                        if (child instanceof ToolExecutionComponent) {
                            child.setShowImages(enabled);
                        }
                    }
                },
                onImageWidthCellsChange: (width) => {
                    this.settingsManager.setImageWidthCells(width);
                    for (const child of this.chatContainer.children) {
                        if (child instanceof ToolExecutionComponent) {
                            child.setImageWidthCells(width);
                        }
                    }
                },
                onAutoResizeImagesChange: (enabled) => {
                    this.settingsManager.setImageAutoResize(enabled);
                },
                onBlockImagesChange: (blocked) => {
                    this.settingsManager.setBlockImages(blocked);
                },
                onEnableSkillCommandsChange: (enabled) => {
                    this.settingsManager.setEnableSkillCommands(enabled);
                    this.setupAutocompleteProvider();
                },
                onSteeringModeChange: (mode) => {
                    this.session.setSteeringMode(mode);
                },
                onFollowUpModeChange: (mode) => {
                    this.session.setFollowUpMode(mode);
                },
                onTransportChange: (transport) => {
                    this.settingsManager.setTransport(transport);
                    this.session.agent.transport = transport;
                },
                onHttpIdleTimeoutMsChange: (timeoutMs) => {
                    this.settingsManager.setHttpIdleTimeoutMs(timeoutMs);
                    configureHttpDispatcher(timeoutMs);
                    this.showStatus(`HTTP idle timeout: ${formatHttpIdleTimeoutMs(timeoutMs)}`);
                },
                onThinkingLevelChange: (level) => {
                    this.session.setThinkingLevel(level);
                    this.footer.invalidate();
                    this.updateEditorBorderColor();
                },
                onThemeChange: (themeSetting) => {
                    this.settingsManager.setTheme(themeSetting);
                    void this.themeController.setThemeSetting(themeSetting);
                },
                onThemePreview: (themeName) => this.themeController.preview(themeName),
                onCollapseCodeBlocksChange: (collapse) => {
                    this.settingsManager.setCollapseCodeBlocks(collapse);
                },
                onHideThinkingBlockChange: (hidden) => {
                    this.hideThinkingBlock = hidden;
                    this.settingsManager.setHideThinkingBlock(hidden);
                    for (const child of this.chatContainer.children) {
                        if (child instanceof AssistantMessageComponent) {
                            child.setHideThinkingBlock(hidden);
                        }
                    }
                    this.chatContainer.clear();
                    this.rebuildChatFromMessages();
                },
                onMermaidRenderingModeChange: (mode) => {
                    this.settingsManager.setMermaidRenderingMode(mode);
                    this.chatContainer.invalidate();
                    this.ui.requestRender();
                },
                onShowCacheMissNoticesChange: (shown) => {
                    this.settingsManager.setShowCacheMissNotices(shown);
                    this.rebuildChatFromMessages();
                },
                onEnableInstallTelemetryChange: (enabled) => {
                    this.settingsManager.setEnableInstallTelemetry(enabled);
                },
                // 2026-10-14 (owner order): onQuietStartupChange removed — quiet
                // startup is hard-locked, nothing may flip it.
                onDefaultProjectTrustChange: (defaultProjectTrust) => {
                    this.settingsManager.setDefaultProjectTrust(defaultProjectTrust);
                },
                onDoubleEscapeActionChange: (action) => {
                    this.settingsManager.setDoubleEscapeAction(action);
                },
                onTreeFilterModeChange: (mode) => {
                    this.settingsManager.setTreeFilterMode(mode);
                },
                onShowHardwareCursorChange: (enabled) => {
                    this.settingsManager.setShowHardwareCursor(enabled);
                    this.ui.setShowHardwareCursor(enabled);
                },
                onEditorPaddingXChange: (padding) => {
                    this.settingsManager.setEditorPaddingX(padding);
                    this.defaultEditor.setPaddingX(padding);
                    if (this.editor !== this.defaultEditor && this.editor.setPaddingX !== undefined) {
                        this.editor.setPaddingX(padding);
                    }
                },
                onOutputPadChange: (padding) => {
                    this.settingsManager.setOutputPad(padding);
                    this.outputPad = padding;
                    if (this.streamingComponent || this.session.isStreaming) {
                        for (const child of this.chatContainer.children) {
                            if (child instanceof AssistantMessageComponent ||
                                child instanceof CustomMessageComponent ||
                                child instanceof UserMessageComponent) {
                                child.setOutputPad(padding);
                            }
                        }
                        if (this.streamingComponent) {
                            this.streamingComponent.setOutputPad(padding);
                        }
                        this.ui.requestRender();
                        return;
                    }
                    this.rebuildChatFromMessages();
                },
                onAutocompleteMaxVisibleChange: (maxVisible) => {
                    this.settingsManager.setAutocompleteMaxVisible(maxVisible);
                    this.defaultEditor.setAutocompleteMaxVisible(maxVisible);
                    if (this.editor !== this.defaultEditor && this.editor.setAutocompleteMaxVisible !== undefined) {
                        this.editor.setAutocompleteMaxVisible(maxVisible);
                    }
                },
                onClearOnShrinkChange: (enabled) => {
                    this.settingsManager.setClearOnShrink(enabled);
                    this.ui.setClearOnShrink(enabled);
                    if (!enabled && !this.activeStatusIndicator) {
                        this.statusContainer.clear();
                    }
                },
                onShowTerminalProgressChange: (enabled) => {
                    this.settingsManager.setShowTerminalProgress(enabled);
                },
                onTuiModeChange: (mode) => {
                    if (!this.switchTuiMode(mode)) {
                        selector?.getSettingsList().updateValue("tui-mode", this.ui.mode);
                        this.showStatus("Close active overlays before changing TUI mode");
                        return;
                    }
                    this.settingsManager.setTuiMode(mode);
                    if (!this.activeStatusIndicator)
                        this.statusContainer.clear();
                    this.showStatus(`TUI mode: ${mode}`);
                },
                onFullscreenExitOutputChange: (output) => {
                    this.settingsManager.setFullscreenExitOutput(output);
                },
                onFullscreenScrollbarChange: (mode) => {
                    this.settingsManager.setFullscreenScrollbar(mode);
                    this.applyFullscreenScrollbarSetting();
                },
                onWarningsChange: (warnings) => {
                    this.settingsManager.setWarnings(warnings);
                },
                onCancel: () => {
                    done();
                    this.ui.requestRender();
                },
            });
            return { component: selector, focus: selector.getSettingsList() };
        });
    }
    updateAvailableProviderCount() {
        const models = this.session.scopedModels.length > 0
            ? this.session.scopedModels.map((scoped) => scoped.model)
            : this.session.modelRuntime.getAvailableSnapshot();
        const uniqueProviders = new Set(models.map((model) => model.provider));
        this.footerDataProvider.setAvailableProviderCount(uniqueProviders.size);
    }
    async maybeWarnAboutSubscriptionAuth(model = this.session.model) {
        if (this.settingsManager.getWarnings().subscriptionExtraUsage === false) {
            return;
        }
        if (this.subscriptionAuthWarningShown) {
            return;
        }
        if (!model || model.provider !== "anthropic") {
            return;
        }
        try {
            if ((await this.session.modelRuntime.checkAuth("anthropic"))?.type === "oauth") {
                this.subscriptionAuthWarningShown = true;
                this.showWarning(SUBSCRIPTION_AUTH_WARNING);
                return;
            }
            const apiKey = (await this.session.modelRuntime.getAuth(model.provider))?.auth.apiKey;
            if (!isSubscriptionAuthKey(apiKey)) {
                return;
            }
            this.subscriptionAuthWarningShown = true;
            this.showWarning(SUBSCRIPTION_AUTH_WARNING);
        }
        catch {
            // Ignore auth lookup failures for warning-only checks.
        }
    }
    maybeSaveImplicitProjectTrustAfterReload() {
        const cwd = this.sessionManager.getCwd();
        if (this.autoTrustOnReloadCwd !== cwd) {
            return false;
        }
        if (!this.settingsManager.isProjectTrusted() || !hasTrustRequiringProjectResources(cwd)) {
            return false;
        }
        const trustStore = new ProjectTrustStore(this.runtimeHost.services.agentDir);
        try {
            if (trustStore.get(cwd) !== null) {
                this.autoTrustOnReloadCwd = undefined;
                return false;
            }
            trustStore.set(cwd, true);
            this.autoTrustOnReloadCwd = undefined;
            return true;
        }
        catch (error) {
            this.showWarning(`Could not save project trust after reload: ${error instanceof Error ? error.message : String(error)}`);
            return false;
        }
    }
    async handleCloneCommand() {
        const leafId = this.sessionManager.getLeafId();
        if (!leafId) {
            this.showStatus("Nothing to clone yet");
            return;
        }
        try {
            const result = await this.runtimeHost.fork(leafId, { position: "at" });
            if (result.cancelled) {
                this.ui.requestRender();
                return;
            }
            this.editor.setText("");
            this.showStatus("Cloned to new session");
        }
        catch (error) {
            this.showError(error instanceof Error ? error.message : String(error));
        }
    }
    async handleResumeSession(sessionPath, options) {
        this.clearStatusIndicator();
        try {
            const result = await this.runtimeHost.switchSession(sessionPath, {
                withSession: options?.withSession,
                projectTrustContextFactory: (cwd) => this.createProjectTrustContext(cwd),
            });
            if (result.cancelled) {
                return result;
            }
            this.showStatus("Resumed session");
            return result;
        }
        catch (error) {
            if (error instanceof MissingSessionCwdError) {
                const selectedCwd = await this.promptForMissingSessionCwd(error);
                if (!selectedCwd) {
                    this.showStatus("Resume cancelled");
                    return { cancelled: true };
                }
                const result = await this.runtimeHost.switchSession(sessionPath, {
                    cwdOverride: selectedCwd,
                    withSession: options?.withSession,
                    projectTrustContextFactory: (cwd) => this.createProjectTrustContext(cwd),
                });
                if (result.cancelled) {
                    return result;
                }
                this.showStatus("Resumed session in current cwd");
                return result;
            }
            return this.handleFatalRuntimeError("Failed to resume session", error);
        }
    }
    async handleReloadCommand() {
        // 2026-10-13 (owner order, ported from cloud fork): command disabled —
        // nothing reloads. The extension "reload" plumbing still calls this; it
        // only warns now.
        this.showWarning("Command disabled in CortexAgent");
    }
    async handleExportCommand(text) {
        const outputPath = this.getPathCommandArgument(text, "/export");
        try {
            if (outputPath?.endsWith(".jsonl")) {
                const filePath = this.session.exportToJsonl(outputPath);
                this.showStatus(`Session exported to: ${filePath}`);
            }
            else {
                const filePath = await this.session.exportToHtml(outputPath, {
                    themeName: theme.name,
                });
                this.showStatus(`Session exported to: ${filePath}`);
            }
        }
        catch (error) {
            this.showError(`Failed to export session: ${error instanceof Error ? error.message : "Unknown error"}`);
        }
    }
    getPathCommandArgument(text, command) {
        if (text === command) {
            return undefined;
        }
        if (!text.startsWith(`${command} `)) {
            return undefined;
        }
        const argsString = text.slice(command.length + 1).trimStart();
        if (!argsString) {
            return undefined;
        }
        const firstChar = argsString[0];
        if (firstChar === '"' || firstChar === "'") {
            const closingQuoteIndex = argsString.indexOf(firstChar, 1);
            if (closingQuoteIndex < 0) {
                return undefined;
            }
            return argsString.slice(1, closingQuoteIndex);
        }
        const firstWhitespaceIndex = argsString.search(/\s/);
        if (firstWhitespaceIndex < 0) {
            return argsString;
        }
        return argsString.slice(0, firstWhitespaceIndex);
    }
    // 2026-11-11 (owner: "no /resume"): the two session-reentry commands, wired
    // to the runtime's own switchSession path (same teardown → session_start
    // resume flow the CLI --continue/--resume flags use).
    async handleResumeCommand() {
        try {
            const cwd = this.sessionManager.getCwd();
            const selectedPath = await selectSession((onProgress) => SessionManager.list(cwd, undefined, onProgress), (onProgress) => SessionManager.listAll(undefined, onProgress), this.settingsManager);
            if (!selectedPath) {
                this.showStatus("Resume cancelled");
                return;
            }
            const result = await this.runtimeHost.switchSession(selectedPath);
            if (!result.cancelled)
                this.showStatus("Session resumed");
        }
        catch (error) {
            this.showError(`Resume failed: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
    async handleContinueCommand() {
        try {
            const cwd = this.sessionManager.getCwd();
            const sessions = await SessionManager.list(cwd);
            const latest = sessions[0];
            if (!latest) {
                this.showStatus("No previous session to continue");
                return;
            }
            if (latest.path === this.sessionManager.getSessionFile()) {
                this.showStatus("Already in the latest session");
                return;
            }
            const result = await this.runtimeHost.switchSession(latest.path);
            if (!result.cancelled)
                this.showStatus(`Continued: ${latest.path.split("/").pop()}`);
        }
        catch (error) {
            this.showError(`Continue failed: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
    async handleImportCommand(text) {
        const inputPath = this.getPathCommandArgument(text, "/import");
        if (!inputPath) {
            this.showError("Usage: /import <path.jsonl>");
            return;
        }
        const confirmed = await this.showExtensionConfirm("Import session", `Replace current session with ${inputPath}?`);
        if (!confirmed) {
            this.showStatus("Import cancelled");
            return;
        }
        try {
            this.clearStatusIndicator();
            const result = await this.runtimeHost.importFromJsonl(inputPath);
            if (result.cancelled) {
                this.showStatus("Import cancelled");
                return;
            }
            this.showStatus(`Session imported from: ${inputPath}`);
        }
        catch (error) {
            if (error instanceof MissingSessionCwdError) {
                const selectedCwd = await this.promptForMissingSessionCwd(error);
                if (!selectedCwd) {
                    this.showStatus("Import cancelled");
                    return;
                }
                const result = await this.runtimeHost.importFromJsonl(inputPath, selectedCwd);
                if (result.cancelled) {
                    this.showStatus("Import cancelled");
                    return;
                }
                this.showStatus(`Session imported from: ${inputPath}`);
                return;
            }
            if (error instanceof SessionImportFileNotFoundError) {
                this.showError(`Failed to import session: ${error.message}`);
                return;
            }
            await this.handleFatalRuntimeError("Failed to import session", error);
        }
    }
    getAppKeyDisplay(action) {
        return keyDisplayText(action);
    }
    getEditorKeyDisplay(action) {
        return keyDisplayText(action);
    }
    handleHotkeysCommand() {
        const cursorUp = this.getEditorKeyDisplay("tui.editor.cursorUp");
        const cursorDown = this.getEditorKeyDisplay("tui.editor.cursorDown");
        const cursorLeft = this.getEditorKeyDisplay("tui.editor.cursorLeft");
        const cursorRight = this.getEditorKeyDisplay("tui.editor.cursorRight");
        const cursorWordLeft = this.getEditorKeyDisplay("tui.editor.cursorWordLeft");
        const cursorWordRight = this.getEditorKeyDisplay("tui.editor.cursorWordRight");
        const cursorLineStart = this.getEditorKeyDisplay("tui.editor.cursorLineStart");
        const cursorLineEnd = this.getEditorKeyDisplay("tui.editor.cursorLineEnd");
        const jumpForward = this.getEditorKeyDisplay("tui.editor.jumpForward");
        const jumpBackward = this.getEditorKeyDisplay("tui.editor.jumpBackward");
        const pageUp = this.getEditorKeyDisplay("tui.editor.pageUp");
        const pageDown = this.getEditorKeyDisplay("tui.editor.pageDown");
        const submit = this.getEditorKeyDisplay("tui.input.submit");
        const newLine = this.getEditorKeyDisplay("tui.input.newLine");
        const deleteWordBackward = this.getEditorKeyDisplay("tui.editor.deleteWordBackward");
        const deleteWordForward = this.getEditorKeyDisplay("tui.editor.deleteWordForward");
        const deleteToLineStart = this.getEditorKeyDisplay("tui.editor.deleteToLineStart");
        const deleteToLineEnd = this.getEditorKeyDisplay("tui.editor.deleteToLineEnd");
        const yank = this.getEditorKeyDisplay("tui.editor.yank");
        const yankPop = this.getEditorKeyDisplay("tui.editor.yankPop");
        const undo = this.getEditorKeyDisplay("tui.editor.undo");
        const tab = this.getEditorKeyDisplay("tui.input.tab");
        const interrupt = this.getAppKeyDisplay("app.interrupt");
        const clear = this.getAppKeyDisplay("app.clear");
        const exit = this.getAppKeyDisplay("app.exit");
        const suspend = this.getAppKeyDisplay("app.suspend");
        const externalEditor = this.getAppKeyDisplay("app.editor.external");
        const pasteImage = this.getAppKeyDisplay("app.clipboard.pasteImage");
        // 2026-10-13 (owner order, ported): thinking/model/tools/copy/queue
        // displays dropped — those shortcuts are disabled (empty keys).
        let hotkeys = `
**Navigation**
| Key | Action |
|-----|--------|
| \`${cursorUp}\` / \`${cursorDown}\` / \`${cursorLeft}\` / \`${cursorRight}\` | Move cursor / browse history |
| \`${cursorWordLeft}\` / \`${cursorWordRight}\` | Move by word |
| \`${cursorLineStart}\` | Start of line |
| \`${cursorLineEnd}\` | End of line |
| \`${jumpForward}\` | Jump forward to character |
| \`${jumpBackward}\` | Jump backward to character |
| \`${pageUp}\` / \`${pageDown}\` | Scroll by page |

**Editing**
| Key | Action |
|-----|--------|
| \`${submit}\` | Send message |
| \`${newLine}\` | New line${process.platform === "win32" ? " (Ctrl+Enter on Windows Terminal)" : ""} |
| \`${deleteWordBackward}\` | Delete word backwards |
| \`${deleteWordForward}\` | Delete word forwards |
| \`${deleteToLineStart}\` | Delete to start of line |
| \`${deleteToLineEnd}\` | Delete to end of line |
| \`${yank}\` | Paste the most-recently-deleted text |
| \`${yankPop}\` | Cycle through the deleted text after pasting |
| \`${undo}\` | Undo |

**Other**
| Key | Action |
|-----|--------|
| \`${tab}\` | Path completion / accept autocomplete |
| \`${interrupt}\` | Cancel autocomplete / abort streaming |
| \`${clear}\` | Clear editor (first) / exit (second) |
| \`${exit}\` | Exit (when editor is empty) |
| \`${suspend}\` | Suspend to background |
| \`${externalEditor}\` | Edit message in external editor |
| \`${pasteImage}\` | Paste image or text from clipboard |
| \`/\` | Slash commands |
| \`!\` | Run bash command |
| \`!!\` | Run bash command (excluded from context) |
`;
        const extensionRunner = this.session.extensionRunner;
        const shortcuts = extensionRunner.getShortcuts(this.keybindings.getEffectiveConfig());
        if (shortcuts.size > 0) {
            hotkeys += `
**Extensions**
| Key | Action |
|-----|--------|
`;
            for (const [key, shortcut] of shortcuts) {
                const description = shortcut.description ?? shortcut.extensionPath;
                const keyDisplay = formatKeyText(key, { capitalize: true });
                hotkeys += `| \`${keyDisplay}\` | ${description} |\n`;
            }
        }
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new DynamicBorder());
        this.chatContainer.addChild(new Text(theme.bold(theme.fg("accent", "Keyboard Shortcuts")), 1, 0));
        this.chatContainer.addChild(new Spacer(1));
        this.chatContainer.addChild(new Markdown(hotkeys.trim(), 1, 1, this.getMarkdownThemeWithSettings()));
        this.chatContainer.addChild(new DynamicBorder());
        this.ui.requestRender();
    }
    async handleClearCommand() {
        this.clearStatusIndicator();
        try {
            const result = await this.runtimeHost.newSession();
            if (result.cancelled) {
                return;
            }
            this.chatContainer.addChild(new Spacer(1));
            this.chatContainer.addChild(new Text(`${theme.fg("accent", "✓ New session started")}`, 1, 1));
            this.ui.requestRender();
        }
        catch (error) {
            await this.handleFatalRuntimeError("Failed to create session", error);
        }
    }
    async handleBashCommand(command, excludeFromContext = false) {
        const extensionRunner = this.session.extensionRunner;
        const eventResult = await extensionRunner.emitUserBash({
            type: "user_bash",
            command,
            excludeFromContext,
            cwd: this.sessionManager.getCwd(),
        });
        if (eventResult?.result) {
            const result = eventResult.result;
            this.bashComponent = new BashExecutionComponent(command, this.ui, excludeFromContext);
            if (this.session.isStreaming) {
                this.pendingMessagesContainer.addChild(this.bashComponent);
                this.pendingBashComponents.push(this.bashComponent);
            }
            else {
                this.chatContainer.addChild(this.bashComponent);
            }
            if (result.output) {
                this.bashComponent.appendOutput(result.output);
            }
            this.bashComponent.setComplete(result.exitCode, result.cancelled, result.truncated ? { truncated: true, content: result.output } : undefined, result.fullOutputPath);
            this.session.recordBashResult(command, result, { excludeFromContext });
            this.bashComponent = undefined;
            this.ui.requestRender();
            return;
        }
        const isDeferred = this.session.isStreaming;
        this.bashComponent = new BashExecutionComponent(command, this.ui, excludeFromContext);
        if (isDeferred) {
            this.pendingMessagesContainer.addChild(this.bashComponent);
            this.pendingBashComponents.push(this.bashComponent);
        }
        else {
            this.chatContainer.addChild(this.bashComponent);
        }
        this.ui.requestRender();
        try {
            const result = await this.session.executeBash(command, (chunk) => {
                if (this.bashComponent) {
                    this.bashComponent.appendOutput(chunk);
                    this.ui.requestRender();
                }
            }, { excludeFromContext, operations: eventResult?.operations });
            if (this.bashComponent) {
                this.bashComponent.setComplete(result.exitCode, result.cancelled, result.truncated ? { truncated: true, content: result.output } : undefined, result.fullOutputPath);
            }
        }
        catch (error) {
            if (this.bashComponent) {
                this.bashComponent.setComplete(undefined, false);
            }
            this.showError(`Bash command failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        }
        this.bashComponent = undefined;
        this.ui.requestRender();
    }
    stop(fullscreenExitOutput = this.settingsManager.getFullscreenExitOutput()) {
        this.disposeActiveSelector();
        if (this.settingsManager.getShowTerminalProgress()) {
            this.ui.terminal.setProgress(false);
        }
        this.clearStatusIndicator();
        this.themeController.disableAutoSync();
        this.clearExtensionTerminalInputListeners();
        this.footer.dispose();
        this.footerDataProvider.dispose();
        if (this.unsubscribe) {
            this.unsubscribe();
        }
        if (this.isInitialized) {
            this.stopInteractiveTui(fullscreenExitOutput);
            this.isInitialized = false;
        }
        this.unregisterSignalHandlers();
    }
}
//# sourceMappingURL=interactive-mode.js.map