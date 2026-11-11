import { createInterface } from "node:readline";
import { modelsAreEqual } from "@cortexagent/ai";
import chalk from "chalk";
import { parseArgs, printHelp } from "./cli/args.js";
import { checkProviderAuth, createAuthCheckModelRuntime, getProviderCredential, } from "./cli/auth-check.js";
import { AuthCommandError, getAuthCommandName, getAuthCommandUsage, isAuthCommandHelp, parseAuthCommand, printAuthCommandHelp, validateAuthCommandArgs, } from "./cli/auth-command.js";
import { resolveCredentialForPrint } from "./cli/credential-print.js";
import { processFileArguments } from "./cli/file-processor.js";
import { buildInitialMessage } from "./cli/initial-message.js";
import { listModels } from "./cli/list-models.js";
import { createProjectTrustContext } from "./cli/project-trust.js";
import { selectSession } from "./cli/session-picker.js";
import { shouldRunFirstTimeSetup, showFirstTimeSetup, showStartupSelector } from "./cli/startup-ui.js";
import { APP_NAME, ENV_SESSION_DIR, expandTildePath, getAgentDir, getPackageDir, VERSION } from "./config.js";
import { createAgentSessionRuntime } from "./core/agent-session-runtime.js";
import { createAgentSessionFromServices, createAgentSessionServices, } from "./core/agent-session-services.js";
import { formatNoModelsAvailableMessage } from "./core/auth-guidance.js";
import { AuthStorage, ReadOnlyAuthStorage } from "./core/auth-storage.js";
import { exportFromFile } from "./core/export-html/index.js";
import { applyHttpProxySettings, configureHttpDispatcher } from "./core/http-dispatcher.js";
import { resolveCliModel, resolveModelScope } from "./core/model-resolver.js";
import { ModelRuntime } from "./core/model-runtime.js";
import { restoreStdout, takeOverStdout } from "./core/output-guard.js";
import { resolveProjectTrusted } from "./core/project-trust.js";
import { formatMissingSessionCwdPrompt, getMissingSessionCwdIssue, MissingSessionCwdError, } from "./core/session-cwd.js";
import { assertValidSessionId, SessionManager } from "./core/session-manager.js";
import { SettingsManager } from "./core/settings-manager.js";
import { printTimings, resetTimings, time } from "./core/timings.js";
import { hasTrustRequiringProjectResources, ProjectTrustStore } from "./core/trust-manager.js";
import { builtInExtensions } from "./extensions/index.js";
import { runMigrations, showDeprecationWarnings } from "./migrations.js";
import { InteractiveMode, runPrintMode, runRpcMode } from "./modes/index.js";
import { initTheme, stopThemeWatcher } from "./modes/interactive/theme/theme.js";
import { handleConfigCommand, handlePackageCommand } from "./package-manager-cli.js";
import { isLocalPath, normalizePath, resolvePath } from "./utils/paths.js";
import { cleanupWindowsSelfUpdateQuarantine } from "./utils/windows-self-update.js";
const EXTENSION_LOAD_FAILURE_HINT = 'Hint: Start without extensions using "cortex -ne".';
async function readPipedStdin() {
    if (process.stdin.isTTY) {
        return undefined;
    }
    return new Promise((resolve) => {
        let data = "";
        process.stdin.setEncoding("utf8");
        process.stdin.on("data", (chunk) => {
            data += chunk;
        });
        process.stdin.on("end", () => {
            resolve(data.trim() || undefined);
        });
        process.stdin.resume();
    });
}
function collectSettingsDiagnostics(settingsManager, context) {
    return settingsManager.drainErrors().map(({ scope, error }) => ({
        type: "warning",
        message: `(${context}, ${scope} settings) ${error.message}`,
    }));
}
function reportDiagnostics(diagnostics) {
    for (const diagnostic of diagnostics) {
        const color = diagnostic.type === "error" ? chalk.red : diagnostic.type === "warning" ? chalk.yellow : chalk.dim;
        const prefix = diagnostic.type === "error" ? "Error: " : diagnostic.type === "warning" ? "Warning: " : "";
        console.error(color(`${prefix}${diagnostic.message}`));
    }
}
function isTruthyEnvFlag(value) {
    if (!value)
        return false;
    return value === "1" || value.toLowerCase() === "true" || value.toLowerCase() === "yes";
}
function resolveAppMode(parsed, stdinIsTTY, stdoutIsTTY) {
    if (parsed.mode === "rpc") {
        return "rpc";
    }
    if (parsed.mode === "json") {
        return "json";
    }
    if (parsed.print || !stdinIsTTY || !stdoutIsTTY) {
        return "print";
    }
    return "interactive";
}
function toPrintOutputMode(appMode) {
    return appMode === "json" ? "json" : "text";
}
function isPlainRuntimeMetadataCommand(parsed) {
    return !parsed.print && parsed.mode === undefined && (parsed.help === true || parsed.listModels !== undefined);
}
async function runAuthCommand(args) {
    if (isAuthCommandHelp(args)) {
        printAuthCommandHelp();
        return true;
    }
    let command;
    try {
        command = parseAuthCommand(args);
    }
    catch (error) {
        const message = error instanceof AuthCommandError ? error.message : "Failed to parse auth command";
        console.error(chalk.red(`Error: ${message}`));
        process.exitCode = 1;
        return true;
    }
    if (!command)
        return false;
    const parsed = parseArgs(command.args);
    if (parsed.unknownFlags.size > 0) {
        const option = parsed.unknownFlags.keys().next().value;
        console.error(chalk.red(`Unknown option --${option} for "${getAuthCommandName(command.kind)}".`));
        console.error(chalk.dim(`Use "${APP_NAME} --help" or "${getAuthCommandUsage(command.kind)}".`));
        process.exitCode = 1;
        return true;
    }
    try {
        if (parsed.diagnostics.length > 0) {
            throw new AuthCommandError(parsed.diagnostics.map((diagnostic) => diagnostic.message).join("\n"));
        }
        if (command.kind !== "check") {
            const signal = AbortSignal.timeout(15_000);
            const modelRuntime = await ModelRuntime.create({ allowModelNetwork: false, signal });
            const credential = await resolveCredentialForPrint(parsed, modelRuntime, command.kind, command.minExpiryMs, signal);
            process.stdout.write(`${credential}\n`);
            return true;
        }
        const requestedAuth = validateAuthCommandArgs(parsed, command.kind);
        let result;
        let credential;
        try {
            const credentials = command.noRefresh ? new ReadOnlyAuthStorage() : AuthStorage.create();
            const modelRuntime = await createAuthCheckModelRuntime(credentials);
            result = await checkProviderAuth(parsed, modelRuntime, { refresh: !command.noRefresh });
            if (command.credentials && result.status === "ready") {
                credential = await getProviderCredential(result.provider, modelRuntime, credentials, {
                    refresh: !command.noRefresh,
                });
                if (!credential) {
                    result = { status: "not_ready", provider: result.provider, reason: "credential_not_available" };
                }
            }
        }
        catch {
            result = {
                status: "invalid",
                provider: requestedAuth.provider ?? requestedAuth.model,
                reason: "invalid_state",
            };
        }
        const output = command.json
            ? JSON.stringify({ ...result, ...(credential ? { credentials: credential } : {}) })
            : (credential ?? result.status);
        process.stdout.write(`${output}\n`);
        process.exitCode = result.status === "ready" ? 0 : result.status === "not_ready" ? 1 : 2;
    }
    catch (error) {
        const message = error instanceof AuthCommandError ? error.message : "Failed to resolve credential";
        console.error(chalk.red(`Error: ${message}`));
        process.exitCode = command.kind === "check" ? 2 : 1;
    }
    return true;
}
async function prepareInitialMessage(parsed, autoResizeImages, stdinContent) {
    if (parsed.fileArgs.length === 0) {
        return buildInitialMessage({ parsed, stdinContent });
    }
    const { text, images } = await processFileArguments(parsed.fileArgs, { autoResizeImages });
    return buildInitialMessage({
        parsed,
        fileText: text,
        fileImages: images,
        stdinContent,
    });
}
async function findLocalSessionByExactId(sessionId, cwd, sessionDir) {
    const localSessions = await SessionManager.list(cwd, sessionDir);
    const localMatch = localSessions.find((s) => s.id === sessionId);
    return localMatch ? { type: "local", path: localMatch.path } : undefined;
}
async function resolveSessionPath(sessionArg, cwd, sessionDir) {
    if (sessionArg.includes("/") || sessionArg.includes("\\") || sessionArg.endsWith(".jsonl")) {
        return { type: "path", path: resolvePath(sessionArg, cwd) };
    }
    const localSessions = await SessionManager.list(cwd, sessionDir);
    const localMatch = localSessions.find((s) => s.id === sessionArg) ?? localSessions.find((s) => s.id.startsWith(sessionArg));
    if (localMatch) {
        return { type: "local", path: localMatch.path };
    }
    const allSessions = await SessionManager.listAll(sessionDir);
    const globalMatch = allSessions.find((s) => s.id === sessionArg) ?? allSessions.find((s) => s.id.startsWith(sessionArg));
    if (globalMatch) {
        return { type: "global", path: globalMatch.path, cwd: globalMatch.cwd };
    }
    return { type: "not_found", arg: sessionArg };
}
async function promptConfirm(message) {
    return new Promise((resolve) => {
        const rl = createInterface({
            input: process.stdin,
            output: process.stdout,
        });
        rl.question(`${message} [y/N] `, (answer) => {
            rl.close();
            resolve(answer.toLowerCase() === "y" || answer.toLowerCase() === "yes");
        });
    });
}
function validateForkFlags(parsed) {
    if (!parsed.fork)
        return;
    const conflictingFlags = [
        parsed.session ? "--session" : undefined,
        parsed.continue ? "--continue" : undefined,
        parsed.resume ? "--resume" : undefined,
        parsed.noSession ? "--no-session" : undefined,
    ].filter((flag) => flag !== undefined);
    if (conflictingFlags.length > 0) {
        console.error(chalk.red(`Error: --fork cannot be combined with ${conflictingFlags.join(", ")}`));
        process.exit(1);
    }
}
function validateSessionIdFlags(parsed) {
    if (parsed.sessionId === undefined)
        return;
    const conflictingFlags = [
        parsed.session ? "--session" : undefined,
        parsed.continue ? "--continue" : undefined,
        parsed.resume ? "--resume" : undefined,
    ].filter((flag) => flag !== undefined);
    if (conflictingFlags.length > 0) {
        console.error(chalk.red(`Error: --session-id cannot be combined with ${conflictingFlags.join(", ")}`));
        process.exit(1);
    }
    try {
        assertValidSessionId(parsed.sessionId);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error(chalk.red(`Error: ${message}`));
        process.exit(1);
    }
}
function openSessionOrExit(path, sessionDir) {
    try {
        return SessionManager.open(path, sessionDir);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error(chalk.red(`Error: ${message}`));
        process.exit(1);
    }
}
function forkSessionOrExit(sourcePath, cwd, sessionDir, sessionId) {
    try {
        return SessionManager.forkFrom(sourcePath, cwd, sessionDir, { id: sessionId });
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error(chalk.red(`Error: ${message}`));
        process.exit(1);
    }
}
async function createSessionManager(parsed, cwd, sessionDir, settingsManager) {
    if (parsed.noSession || parsed.help || parsed.listModels !== undefined) {
        return SessionManager.inMemory(cwd, parsed.sessionId !== undefined ? { id: parsed.sessionId } : undefined);
    }
    if (parsed.fork) {
        if (parsed.sessionId) {
            const existingTarget = await findLocalSessionByExactId(parsed.sessionId, cwd, sessionDir);
            if (existingTarget) {
                console.error(chalk.red(`Session already exists with id '${parsed.sessionId}'`));
                process.exit(1);
            }
        }
        const resolved = await resolveSessionPath(parsed.fork, cwd, sessionDir);
        switch (resolved.type) {
            case "path":
            case "local":
            case "global":
                return forkSessionOrExit(resolved.path, cwd, sessionDir, parsed.sessionId);
            case "not_found":
                console.error(chalk.red(`No session found matching '${resolved.arg}'`));
                process.exit(1);
        }
    }
    if (parsed.session) {
        const resolved = await resolveSessionPath(parsed.session, cwd, sessionDir);
        switch (resolved.type) {
            case "path":
            case "local":
                return openSessionOrExit(resolved.path, sessionDir);
            case "global": {
                console.log(chalk.yellow(`Session found in different project: ${resolved.cwd}`));
                const shouldFork = await promptConfirm("Fork this session into current directory?");
                if (!shouldFork) {
                    console.log(chalk.dim("Aborted."));
                    process.exit(0);
                }
                return forkSessionOrExit(resolved.path, cwd, sessionDir);
            }
            case "not_found":
                console.error(chalk.red(`No session found matching '${resolved.arg}'`));
                process.exit(1);
        }
    }
    if (parsed.resume) {
        try {
            const selectedPath = await selectSession((onProgress) => SessionManager.list(cwd, sessionDir, onProgress), (onProgress) => SessionManager.listAll(sessionDir, onProgress), settingsManager);
            if (!selectedPath) {
                console.log(chalk.dim("No session selected"));
                process.exit(0);
            }
            return SessionManager.open(selectedPath, sessionDir);
        }
        finally {
            stopThemeWatcher();
        }
    }
    if (parsed.continue) {
        return SessionManager.continueRecent(cwd, sessionDir);
    }
    if (parsed.sessionId) {
        const existingSession = await findLocalSessionByExactId(parsed.sessionId, cwd, sessionDir);
        if (existingSession) {
            return SessionManager.open(existingSession.path, sessionDir);
        }
        console.error(chalk.yellow(`Warning: No project session found with id '${parsed.sessionId}'; creating a new session with that id.`));
    }
    return SessionManager.create(cwd, sessionDir, { id: parsed.sessionId });
}
function buildSessionOptions(parsed, scopedModels, hasExistingSession, modelRuntime, settingsManager) {
    const options = {};
    const diagnostics = [];
    let cliThinkingFromModel = false;
    if (parsed.model) {
        const resolved = resolveCliModel({
            cliProvider: parsed.provider,
            cliModel: parsed.model,
            cliThinking: parsed.thinking,
            modelRuntime,
        });
        if (resolved.warning) {
            diagnostics.push({ type: "warning", message: resolved.warning });
        }
        if (resolved.error) {
            diagnostics.push({ type: "error", message: resolved.error });
        }
        if (resolved.model) {
            options.model = resolved.model;
            if (!parsed.thinking && resolved.thinkingLevel) {
                options.thinkingLevel = resolved.thinkingLevel;
                cliThinkingFromModel = true;
            }
        }
    }
    if (!options.model && scopedModels.length > 0 && !hasExistingSession) {
        const savedProvider = settingsManager.getDefaultProvider();
        const savedModelId = settingsManager.getDefaultModel();
        const savedModel = savedProvider && savedModelId ? modelRuntime.getModel(savedProvider, savedModelId) : undefined;
        const savedInScope = savedModel ? scopedModels.find((sm) => modelsAreEqual(sm.model, savedModel)) : undefined;
        if (savedInScope) {
            options.model = savedInScope.model;
            if (!parsed.thinking && savedInScope.thinkingLevel) {
                options.thinkingLevel = savedInScope.thinkingLevel;
            }
        }
        else {
            options.model = scopedModels[0].model;
            if (!parsed.thinking && scopedModels[0].thinkingLevel) {
                options.thinkingLevel = scopedModels[0].thinkingLevel;
            }
        }
    }
    if (parsed.thinking) {
        options.thinkingLevel = parsed.thinking;
    }
    if (scopedModels.length > 0) {
        options.scopedModels = scopedModels.map((sm) => ({
            model: sm.model,
            thinkingLevel: sm.thinkingLevel,
        }));
    }
    if (parsed.noTools) {
        options.noTools = "all";
    }
    else if (parsed.noBuiltinTools) {
        options.noTools = "builtin";
    }
    if (parsed.tools) {
        options.tools = [...parsed.tools];
    }
    if (parsed.excludeTools) {
        options.excludeTools = [...parsed.excludeTools];
    }
    return { options, cliThinkingFromModel, diagnostics };
}
function resolveCliPaths(cwd, paths) {
    return paths?.map((value) => (isLocalPath(value) ? resolvePath(value, cwd) : value));
}
async function promptForMissingSessionCwd(issue, settingsManager) {
    return showStartupSelector(settingsManager, formatMissingSessionCwdPrompt(issue), [
        { label: "Continue", value: issue.fallbackCwd },
        { label: "Cancel", value: undefined },
    ]);
}
export async function main(args, options) {
    resetTimings();
    const extensionFactories = [...builtInExtensions, ...(options?.extensionFactories ?? [])];
    const offlineMode = args.includes("--offline") || isTruthyEnvFlag(process.env.CORTEX_OFFLINE);
    if (offlineMode) {
        process.env.CORTEX_OFFLINE = "1";
        process.env.CORTEX_SKIP_VERSION_CHECK = "1";
    }
    if (await runAuthCommand(args)) {
        return;
    }
    if (process.platform === "win32") {
        cleanupWindowsSelfUpdateQuarantine(getPackageDir());
    }
    const cwd = process.cwd();
    const agentDir = getAgentDir();
    const bootstrapSettingsManager = SettingsManager.create(cwd, agentDir, { projectTrusted: false });
    applyHttpProxySettings(bootstrapSettingsManager.getGlobalSettings().httpProxy);
    configureHttpDispatcher();
    if (await handlePackageCommand(args, { extensionFactories })) {
        const exitCode = process.exitCode ?? 0;
        if (process.platform === "win32" && exitCode === 0 && args[0] === "update") {
            return;
        }
        process.exit(exitCode);
        return;
    }
    if (await handleConfigCommand(args, { extensionFactories })) {
        return;
    }
    const parsed = parseArgs(args);
    if (parsed.diagnostics.length > 0) {
        for (const d of parsed.diagnostics) {
            const color = d.type === "error" ? chalk.red : chalk.yellow;
            console.error(color(`${d.type === "error" ? "Error" : "Warning"}: ${d.message}`));
        }
        if (parsed.diagnostics.some((d) => d.type === "error")) {
            process.exit(1);
        }
    }
    time("parseArgs");
    if (parsed.version) {
        console.log(VERSION);
        process.exit(0);
    }
    if (parsed.export) {
        let result;
        try {
            const outputPath = parsed.messages.length > 0 ? parsed.messages[0] : undefined;
            result = await exportFromFile(parsed.export, outputPath);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : "Failed to export session";
            console.error(chalk.red(`Error: ${message}`));
            process.exit(1);
        }
        console.log(`Exported to: ${result}`);
        process.exit(0);
    }
    let appMode = resolveAppMode(parsed, process.stdin.isTTY, process.stdout.isTTY);
    const shouldTakeOverStdout = appMode !== "interactive" && !isPlainRuntimeMetadataCommand(parsed);
    if (shouldTakeOverStdout) {
        takeOverStdout();
    }
    if (parsed.mode === "rpc" && parsed.fileArgs.length > 0) {
        console.error(chalk.red("Error: @file arguments are not supported in RPC mode"));
        process.exit(1);
    }
    validateForkFlags(parsed);
    validateSessionIdFlags(parsed);
    const { migratedAuthProviders: migratedProviders, deprecationWarnings } = runMigrations(cwd);
    time("runMigrations");
    const startupSettingsManager = SettingsManager.create(cwd, agentDir);
    reportDiagnostics(collectSettingsDiagnostics(startupSettingsManager, "startup session lookup"));
    if (appMode === "interactive" && !parsed.help && parsed.listModels === undefined && shouldRunFirstTimeSetup()) {
        await showFirstTimeSetup(startupSettingsManager);
        time("firstTimeSetup");
    }
    if (appMode === "interactive" && parsed.useTheme !== undefined) {
        startupSettingsManager.applyOverrides({ theme: parsed.useTheme });
    }
    const envSessionDir = process.env[ENV_SESSION_DIR];
    const sessionDir = (parsed.sessionDir ? normalizePath(parsed.sessionDir) : undefined) ??
        (envSessionDir ? expandTildePath(envSessionDir) : undefined) ??
        startupSettingsManager.getSessionDir();
    let sessionManager = await createSessionManager(parsed, cwd, sessionDir, startupSettingsManager);
    const missingSessionCwdIssue = getMissingSessionCwdIssue(sessionManager, cwd);
    if (missingSessionCwdIssue) {
        if (appMode === "interactive") {
            const selectedCwd = await promptForMissingSessionCwd(missingSessionCwdIssue, startupSettingsManager);
            if (!selectedCwd) {
                process.exit(0);
            }
            sessionManager = SessionManager.open(missingSessionCwdIssue.sessionFile, sessionDir, selectedCwd);
        }
        else {
            console.error(chalk.red(new MissingSessionCwdError(missingSessionCwdIssue).message));
            process.exit(1);
        }
    }
    if (parsed.name !== undefined) {
        const name = parsed.name.trim();
        if (!name) {
            console.error(chalk.red("Error: --name requires a non-empty value"));
            process.exit(1);
        }
        sessionManager.appendSessionInfo(name);
    }
    time("createSessionManager");
    const trustStore = new ProjectTrustStore(agentDir);
    const sessionCwd = sessionManager.getCwd();
    const autoTrustOnReloadCwd = parsed.projectTrustOverride === undefined && !hasTrustRequiringProjectResources(sessionCwd)
        ? sessionCwd
        : undefined;
    const trustPromptMode = parsed.help || parsed.listModels !== undefined ? "print" : appMode;
    const projectTrustByCwd = new Map();
    const resolvedExtensionPaths = resolveCliPaths(cwd, parsed.extensions);
    const resolvedSkillPaths = resolveCliPaths(cwd, parsed.skills);
    const resolvedPromptTemplatePaths = resolveCliPaths(cwd, parsed.promptTemplates);
    const resolvedThemePaths = resolveCliPaths(cwd, parsed.themes);
    const createRuntime = async ({ cwd, agentDir, sessionManager, sessionStartEvent, projectTrustContext, }) => {
        const isInitialRuntime = sessionStartEvent === undefined;
        const projectTrustDiagnostics = [];
        const cachedProjectTrust = projectTrustByCwd.get(cwd);
        const hasTrustRequiringResources = hasTrustRequiringProjectResources(cwd);
        const shouldResolveProjectTrust = parsed.projectTrustOverride === undefined && cachedProjectTrust === undefined && hasTrustRequiringResources;
        const projectTrusted = shouldResolveProjectTrust
            ? false
            : (cachedProjectTrust ??
                parsed.projectTrustOverride ??
                (!hasTrustRequiringResources || trustStore.get(cwd) === true));
        const runtimeSettingsManager = SettingsManager.create(cwd, agentDir, { projectTrusted });
        const services = await createAgentSessionServices({
            cwd,
            agentDir,
            settingsManager: runtimeSettingsManager,
            modelRuntimeSignal: AbortSignal.timeout(15_000),
            extensionFlagValues: parsed.unknownFlags,
            resourceLoaderReloadOptions: shouldResolveProjectTrust
                ? {
                    resolveProjectTrust: async ({ extensionsResult }) => {
                        const trusted = await resolveProjectTrusted({
                            cwd,
                            trustStore,
                            trustOverride: parsed.projectTrustOverride,
                            defaultProjectTrust: startupSettingsManager.getDefaultProjectTrust(),
                            extensionsResult,
                            projectTrustContext: projectTrustContext ??
                                createProjectTrustContext({
                                    cwd,
                                    mode: isInitialRuntime ? trustPromptMode : appMode,
                                    settingsManager: startupSettingsManager,
                                    hasUI: isInitialRuntime && trustPromptMode === "interactive",
                                }),
                            onExtensionError: (message) => projectTrustDiagnostics.push({ type: "warning", message }),
                        });
                        projectTrustByCwd.set(cwd, trusted);
                        return trusted;
                    },
                }
                : undefined,
            resourceLoaderOptions: {
                additionalExtensionPaths: resolvedExtensionPaths,
                additionalSkillPaths: resolvedSkillPaths,
                additionalPromptTemplatePaths: resolvedPromptTemplatePaths,
                additionalThemePaths: resolvedThemePaths,
                noExtensions: parsed.noExtensions,
                noSkills: parsed.noSkills,
                noPromptTemplates: parsed.noPromptTemplates,
                noThemes: parsed.noThemes,
                noContextFiles: parsed.noContextFiles,
                systemPrompt: parsed.systemPrompt,
                appendSystemPrompt: parsed.appendSystemPrompt,
                extensionFactories,
            },
        });
        const { settingsManager, modelRuntime, resourceLoader } = services;
        const diagnostics = [
            ...projectTrustDiagnostics,
            ...services.diagnostics,
            ...collectSettingsDiagnostics(settingsManager, "runtime creation"),
            ...resourceLoader.getExtensions().errors.map(({ path, error }) => ({
                type: "error",
                message: `Failed to load extension "${path}": ${error}`,
            })),
        ];
        const modelPatterns = parsed.models ?? settingsManager.getEnabledModels();
        const scopedModels = modelPatterns && modelPatterns.length > 0
            ? await resolveModelScope(modelPatterns, modelRuntime, { signal: AbortSignal.timeout(15_000) })
            : [];
        const { options: sessionOptions, cliThinkingFromModel, diagnostics: sessionOptionDiagnostics, } = buildSessionOptions(parsed, scopedModels, sessionManager.buildSessionContext().messages.length > 0, modelRuntime, settingsManager);
        diagnostics.push(...sessionOptionDiagnostics);
        if (parsed.apiKey) {
            if (!sessionOptions.model) {
                diagnostics.push({
                    type: "error",
                    message: "--api-key requires a model to be specified via --model, --provider/--model, or --models",
                });
            }
            else {
                await modelRuntime.setRuntimeApiKey(sessionOptions.model.provider, parsed.apiKey);
            }
        }
        const created = await createAgentSessionFromServices({
            services,
            sessionManager,
            sessionStartEvent,
            model: sessionOptions.model,
            thinkingLevel: sessionOptions.thinkingLevel,
            scopedModels: sessionOptions.scopedModels,
            tools: sessionOptions.tools,
            excludeTools: sessionOptions.excludeTools,
            noTools: sessionOptions.noTools,
            customTools: sessionOptions.customTools,
        });
        const cliThinkingOverride = parsed.thinking !== undefined || cliThinkingFromModel;
        if (created.session.model && cliThinkingOverride) {
            created.session.setThinkingLevel(created.session.thinkingLevel);
        }
        return {
            ...created,
            services,
            diagnostics,
        };
    };
    time("createRuntime");
    const runtime = await createAgentSessionRuntime(createRuntime, {
        cwd: sessionManager.getCwd(),
        agentDir,
        sessionManager,
    });
    time("createAgentSessionRuntime");
    const { services, session, modelFallbackMessage } = runtime;
    const { settingsManager, modelRuntime, resourceLoader } = services;
    applyHttpProxySettings(settingsManager.getGlobalSettings().httpProxy);
    configureHttpDispatcher(settingsManager.getHttpIdleTimeoutMs());
    if (parsed.help) {
        const extensionFlags = resourceLoader
            .getExtensions()
            .extensions.flatMap((extension) => Array.from(extension.flags.values()));
        printHelp(extensionFlags);
        process.exit(0);
    }
    if (parsed.listModels !== undefined) {
        const searchPattern = typeof parsed.listModels === "string" ? parsed.listModels : undefined;
        await listModels(modelRuntime, searchPattern, AbortSignal.timeout(15_000));
        process.exit(0);
    }
    let stdinContent;
    if (appMode !== "rpc") {
        stdinContent = await readPipedStdin();
        if (stdinContent !== undefined && appMode === "interactive") {
            appMode = "print";
        }
    }
    time("readPipedStdin");
    const { initialMessage, initialImages } = await prepareInitialMessage(parsed, settingsManager.getImageAutoResize(), stdinContent);
    time("prepareInitialMessage");
    initTheme(settingsManager.getTheme(), appMode === "interactive");
    time("initTheme");
    if (appMode === "interactive" && deprecationWarnings.length > 0) {
        await showDeprecationWarnings(deprecationWarnings);
    }
    time("resolveModelScope");
    reportDiagnostics(runtime.diagnostics);
    if (runtime.diagnostics.some((diagnostic) => diagnostic.type === "error")) {
        if (runtime.diagnostics.some((diagnostic) => diagnostic.message.includes("Failed to load extension"))) {
            console.error(chalk.yellow(EXTENSION_LOAD_FAILURE_HINT));
        }
        process.exit(1);
    }
    time("createAgentSession");
    if (appMode !== "interactive" && !session.model) {
        console.error(chalk.red(formatNoModelsAvailableMessage()));
        process.exit(1);
    }
    const startupBenchmark = isTruthyEnvFlag(process.env.CORTEX_STARTUP_BENCHMARK);
    if (startupBenchmark && appMode !== "interactive") {
        console.error(chalk.red("Error: CORTEX_STARTUP_BENCHMARK only supports interactive mode"));
        process.exit(1);
    }
    if (!offlineMode && appMode === "rpc") {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15_000);
        void modelRuntime
            .refresh({ signal: controller.signal })
            .catch(() => { })
            .finally(() => clearTimeout(timeout));
    }
    if (appMode === "rpc") {
        printTimings();
        await runRpcMode(runtime);
    }
    else if (appMode === "interactive") {
        const interactiveMode = new InteractiveMode(runtime, {
            migratedProviders,
            modelFallbackMessage,
            autoTrustOnReloadCwd,
            initialMessage,
            initialImages,
            initialMessages: parsed.messages,
            verbose: parsed.verbose,
            tuiMode: parsed.tuiMode,
            initialThemeSetting: parsed.useTheme,
        });
        if (startupBenchmark) {
            await interactiveMode.init();
            time("interactiveMode.init");
            await new Promise((resolve) => setTimeout(resolve, 150));
            interactiveMode.stop();
            stopThemeWatcher();
            printTimings();
            if (process.stdout.writableLength > 0) {
                await new Promise((resolve) => process.stdout.once("drain", resolve));
            }
            if (process.stderr.writableLength > 0) {
                await new Promise((resolve) => process.stderr.once("drain", resolve));
            }
            return;
        }
        printTimings();
        await interactiveMode.run();
    }
    else {
        printTimings();
        const exitCode = await runPrintMode(runtime, {
            mode: toPrintOutputMode(appMode),
            messages: parsed.messages,
            initialMessage,
            initialImages,
        });
        stopThemeWatcher();
        restoreStdout();
        if (exitCode !== 0) {
            process.exitCode = exitCode;
        }
        return;
    }
}
//# sourceMappingURL=main.js.map