import * as fs from "node:fs";
import { createRequire } from "node:module";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as _bundledCortexAgentCore from "@cortexagent/agent-core";
import * as _bundledCortexAiCompat from "@cortexagent/ai/compat";
import * as _bundledCortexAiOauth from "@cortexagent/ai/oauth";
import * as _bundledCortexAiProviders from "@cortexagent/ai/providers/all";
import * as _bundledCortexTui from "@cortexagent/tui";
import { createJiti } from "jiti/static";
import * as _bundledTypebox from "typebox";
import * as _bundledTypeboxCompile from "typebox/compile";
import * as _bundledTypeboxValue from "typebox/value";
import { CONFIG_DIR_NAME, getAgentDir, isBunBinary } from "../../config.js";
import * as _bundledCortexCodingAgent from "../../index.js";
import { resolvePath } from "../../utils/paths.js";
import { readCortexManifest } from "../cortex-manifest.js";
import { createEventBus } from "../event-bus.js";
import { execCommand } from "../exec.js";
import { createSyntheticSourceInfo } from "../source-info.js";
import { time } from "../timings.js";
const VIRTUAL_MODULES = {
    typebox: _bundledTypebox,
    "typebox/compile": _bundledTypeboxCompile,
    "typebox/value": _bundledTypeboxValue,
    "@sinclair/typebox": _bundledTypebox,
    "@sinclair/typebox/compile": _bundledTypeboxCompile,
    "@sinclair/typebox/value": _bundledTypeboxValue,
    "@cortexagent/agent-core": _bundledCortexAgentCore,
    "@cortexagent/tui": _bundledCortexTui,
    "@cortexagent/ai": _bundledCortexAiCompat,
    "@cortexagent/ai/compat": _bundledCortexAiCompat,
    "@cortexagent/ai/oauth": _bundledCortexAiOauth,
    "@cortexagent/ai/providers/all": _bundledCortexAiProviders,
    "@cortexagent/coding-agent": _bundledCortexCodingAgent,
    "@cortex00/cortex-agent-core": _bundledCortexAgentCore,
    "@cortex00/cortex-tui": _bundledCortexTui,
    "@cortex00/cortex-ai": _bundledCortexAiCompat,
    "@cortex00/cortex-ai/compat": _bundledCortexAiCompat,
    "@cortex00/cortex-ai/oauth": _bundledCortexAiOauth,
    "@cortex00/cortex-ai/providers/all": _bundledCortexAiProviders,
    "@cortex00/cortex-coding-agent": _bundledCortexCodingAgent,
};
const require = createRequire(import.meta.url);
const isTypeScriptSourceRuntime = !isBunBinary && path.extname(fileURLToPath(import.meta.url)) === ".ts";
let _aliases = null;
function getAliases() {
    if (_aliases)
        return _aliases;
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    const packageIndex = path.resolve(__dirname, "../..", "index.js");
    const typeboxEntry = require.resolve("typebox");
    const typeboxCompileEntry = require.resolve("typebox/compile");
    const typeboxValueEntry = require.resolve("typebox/value");
    const packagesRoot = path.resolve(__dirname, "../../../../");
    const resolveWorkspaceOrImport = (workspaceRelativePath, specifier) => {
        const workspacePath = path.join(packagesRoot, workspaceRelativePath);
        if (fs.existsSync(workspacePath)) {
            return workspacePath;
        }
        return fileURLToPath(import.meta.resolve(specifier));
    };
    const cortexCodingAgentEntry = packageIndex;
    const cortexAgentCoreEntry = resolveWorkspaceOrImport("agent/dist/index.js", "@cortexagent/agent-core");
    const cortexTuiEntry = resolveWorkspaceOrImport("tui/dist/index.js", "@cortexagent/tui");
    const cortexAiCompatEntry = resolveWorkspaceOrImport("ai/dist/compat.js", "@cortexagent/ai/compat");
    const cortexAiOauthEntry = resolveWorkspaceOrImport("ai/dist/oauth.js", "@cortexagent/ai/oauth");
    const cortexAiProvidersEntry = resolveWorkspaceOrImport("ai/dist/providers/all.js", "@cortexagent/ai/providers/all");
    _aliases = {
        "@cortexagent/coding-agent": cortexCodingAgentEntry,
        "@cortexagent/agent-core": cortexAgentCoreEntry,
        "@cortexagent/tui": cortexTuiEntry,
        "@cortexagent/ai/providers/all": cortexAiProvidersEntry,
        "@cortexagent/ai/compat": cortexAiCompatEntry,
        "@cortexagent/ai/oauth": cortexAiOauthEntry,
        "@cortexagent/ai": cortexAiCompatEntry,
        "@cortex00/cortex-coding-agent": cortexCodingAgentEntry,
        "@cortex00/cortex-agent-core": cortexAgentCoreEntry,
        "@cortex00/cortex-tui": cortexTuiEntry,
        "@cortex00/cortex-ai/providers/all": cortexAiProvidersEntry,
        "@cortex00/cortex-ai/compat": cortexAiCompatEntry,
        "@cortex00/cortex-ai/oauth": cortexAiOauthEntry,
        "@cortex00/cortex-ai": cortexAiCompatEntry,
        typebox: typeboxEntry,
        "typebox/compile": typeboxCompileEntry,
        "typebox/value": typeboxValueEntry,
        "@sinclair/typebox": typeboxEntry,
        "@sinclair/typebox/compile": typeboxCompileEntry,
        "@sinclair/typebox/value": typeboxValueEntry,
    };
    return _aliases;
}
let extensionCacheCwd;
let extensionCacheGeneration = 0;
const extensionCache = new Map();
export function clearExtensionCache() {
    extensionCache.clear();
    extensionCacheCwd = undefined;
    extensionCacheGeneration++;
}
function useExtensionCacheCwd(cwd) {
    const resolvedCwd = resolvePath(cwd);
    if (extensionCacheCwd !== undefined && extensionCacheCwd !== resolvedCwd) {
        clearExtensionCache();
    }
    extensionCacheCwd = resolvedCwd;
    return { cwd: resolvedCwd, generation: extensionCacheGeneration };
}
export function createExtensionRuntime() {
    const notInitialized = () => {
        throw new Error("Extension runtime not initialized. Action methods cannot be called during extension loading.");
    };
    const state = {};
    const eventBusUnsubscribers = new Set();
    const assertActive = () => {
        if (state.staleMessage) {
            throw new Error(state.staleMessage);
        }
    };
    const runtime = {
        sendMessage: notInitialized,
        sendUserMessage: notInitialized,
        appendEntry: notInitialized,
        setSessionName: notInitialized,
        getSessionName: notInitialized,
        setLabel: notInitialized,
        getActiveTools: notInitialized,
        getAllTools: notInitialized,
        setActiveTools: notInitialized,
        refreshTools: () => { },
        getCommands: notInitialized,
        setModel: () => Promise.reject(new Error("Extension runtime not initialized")),
        getThinkingLevel: notInitialized,
        setThinkingLevel: notInitialized,
        flagValues: new Map(),
        pendingProviderRegistrations: [],
        pendingNativeProviderRegistrations: [],
        assertActive,
        invalidate: (message) => {
            if (state.staleMessage)
                return;
            state.staleMessage =
                message ??
                    "This extension ctx is stale after session replacement or reload. Do not use a captured cortex or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload(). For newSession, fork, and switchSession, move post-replacement work into withSession and use the ctx passed to withSession. For reload, do not use the old ctx after await ctx.reload().";
            for (const unsubscribe of eventBusUnsubscribers)
                unsubscribe();
            eventBusUnsubscribers.clear();
        },
        trackEventBusSubscription: (unsubscribe) => {
            let active = true;
            const trackedUnsubscribe = () => {
                if (!active)
                    return;
                active = false;
                eventBusUnsubscribers.delete(trackedUnsubscribe);
                unsubscribe();
            };
            eventBusUnsubscribers.add(trackedUnsubscribe);
            return trackedUnsubscribe;
        },
        registerProvider: (name, config, extensionPath = "<unknown>") => {
            runtime.pendingProviderRegistrations.push({ name, config, extensionPath });
        },
        registerNativeProvider: (provider, extensionPath = "<unknown>") => {
            runtime.pendingNativeProviderRegistrations.push({ provider, extensionPath });
        },
        unregisterProvider: (name) => {
            runtime.pendingProviderRegistrations = runtime.pendingProviderRegistrations.filter((r) => r.name !== name);
            runtime.pendingNativeProviderRegistrations = runtime.pendingNativeProviderRegistrations.filter((r) => r.provider.id !== name);
        },
    };
    return runtime;
}
function createExtensionAPI(extension, runtime, cwd, eventBus) {
    const api = {
        on(event, handler) {
            runtime.assertActive();
            const list = extension.handlers.get(event) ?? [];
            list.push(handler);
            extension.handlers.set(event, list);
        },
        registerTool(tool) {
            runtime.assertActive();
            extension.tools.set(tool.name, {
                definition: tool,
                sourceInfo: extension.sourceInfo,
            });
            runtime.refreshTools();
        },
        registerCommand(name, options) {
            runtime.assertActive();
            extension.commands.set(name, {
                name,
                sourceInfo: extension.sourceInfo,
                ...options,
            });
        },
        registerShortcut(shortcut, options) {
            runtime.assertActive();
            extension.shortcuts.set(shortcut, { shortcut, extensionPath: extension.path, ...options });
        },
        registerFlag(name, options) {
            runtime.assertActive();
            extension.flags.set(name, { name, extensionPath: extension.path, ...options });
            if (options.default !== undefined && !runtime.flagValues.has(name)) {
                runtime.flagValues.set(name, options.default);
            }
        },
        registerMessageRenderer(customType, renderer) {
            runtime.assertActive();
            extension.messageRenderers.set(customType, renderer);
        },
        registerMarkdownTransformer(transformer) {
            runtime.assertActive();
            extension.markdownTransformer = transformer;
        },
        registerEntryRenderer(customType, renderer) {
            runtime.assertActive();
            extension.entryRenderers ??= new Map();
            extension.entryRenderers.set(customType, renderer);
        },
        getFlag(name) {
            runtime.assertActive();
            if (!extension.flags.has(name))
                return undefined;
            return runtime.flagValues.get(name);
        },
        sendMessage(message, options) {
            runtime.assertActive();
            runtime.sendMessage(message, options);
        },
        sendUserMessage(content, options) {
            runtime.assertActive();
            runtime.sendUserMessage(content, options);
        },
        appendEntry(customType, data) {
            runtime.assertActive();
            runtime.appendEntry(customType, data);
        },
        setSessionName(name) {
            runtime.assertActive();
            runtime.setSessionName(name);
        },
        getSessionName() {
            runtime.assertActive();
            return runtime.getSessionName();
        },
        setLabel(entryId, label) {
            runtime.assertActive();
            runtime.setLabel(entryId, label);
        },
        exec(command, args, options) {
            runtime.assertActive();
            return execCommand(command, args, options?.cwd ?? cwd, options);
        },
        getActiveTools() {
            runtime.assertActive();
            return runtime.getActiveTools();
        },
        getAllTools() {
            runtime.assertActive();
            return runtime.getAllTools();
        },
        setActiveTools(toolNames) {
            runtime.assertActive();
            runtime.setActiveTools(toolNames);
        },
        getCommands() {
            runtime.assertActive();
            return runtime.getCommands();
        },
        setModel(model) {
            runtime.assertActive();
            return runtime.setModel(model);
        },
        getThinkingLevel() {
            runtime.assertActive();
            return runtime.getThinkingLevel();
        },
        setThinkingLevel(level) {
            runtime.assertActive();
            runtime.setThinkingLevel(level);
        },
        registerProvider(providerOrName, config) {
            runtime.assertActive();
            if (typeof providerOrName === "string") {
                if (!config)
                    throw new Error("Provider config is required when registering by name");
                runtime.registerProvider(providerOrName, config, extension.path);
                return;
            }
            runtime.registerNativeProvider(providerOrName, extension.path);
        },
        unregisterProvider(name) {
            runtime.assertActive();
            runtime.unregisterProvider(name, extension.path);
        },
        events: {
            emit(channel, data) {
                runtime.assertActive();
                eventBus.emit(channel, data);
            },
            on(channel, handler) {
                runtime.assertActive();
                return runtime.trackEventBusSubscription(eventBus.on(channel, handler));
            },
        },
    };
    return api;
}
function isCurrentCacheToken(cacheToken) {
    return (cacheToken !== undefined &&
        extensionCacheCwd === cacheToken.cwd &&
        extensionCacheGeneration === cacheToken.generation);
}
async function loadExtensionModule(extensionPath, cacheToken) {
    if (isCurrentCacheToken(cacheToken)) {
        const cachedFactory = extensionCache.get(extensionPath);
        if (cachedFactory) {
            return cachedFactory;
        }
    }
    const jiti = createJiti(import.meta.url, {
        moduleCache: false,
        ...(isBunBinary
            ? { virtualModules: VIRTUAL_MODULES, tryNative: false }
            : isTypeScriptSourceRuntime
                ? { virtualModules: VIRTUAL_MODULES, tsconfigPaths: true }
                : { alias: getAliases() }),
    });
    const module = await jiti.import(extensionPath, { default: true });
    const factory = module;
    if (typeof factory !== "function") {
        return undefined;
    }
    if (isCurrentCacheToken(cacheToken)) {
        extensionCache.set(extensionPath, factory);
    }
    return factory;
}
function createExtension(extensionPath, resolvedPath) {
    const source = extensionPath.startsWith("<") && extensionPath.endsWith(">")
        ? extensionPath.slice(1, -1).split(":")[0] || "temporary"
        : "local";
    const baseDir = extensionPath.startsWith("<") ? undefined : path.dirname(resolvedPath);
    return {
        path: extensionPath,
        resolvedPath,
        sourceInfo: createSyntheticSourceInfo(extensionPath, { source, baseDir }),
        handlers: new Map(),
        tools: new Map(),
        messageRenderers: new Map(),
        entryRenderers: new Map(),
        commands: new Map(),
        flags: new Map(),
        shortcuts: new Map(),
    };
}
async function loadExtension(extensionPath, cwd, eventBus, runtime, cacheToken) {
    const resolvedPath = resolvePath(extensionPath, cwd, { normalizeUnicodeSpaces: true });
    try {
        const factory = await loadExtensionModule(resolvedPath, cacheToken);
        time(`${extensionPath} module import`, "extensions");
        if (!factory) {
            return { extension: null, error: `Extension does not export a valid factory function: ${extensionPath}` };
        }
        const extension = createExtension(extensionPath, resolvedPath);
        const api = createExtensionAPI(extension, runtime, cwd, eventBus);
        await factory(api);
        time(`${extensionPath} factory`, "extensions");
        return { extension, error: null };
    }
    catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return { extension: null, error: `Failed to load extension: ${message}` };
    }
}
export async function loadExtensionFromFactory(factory, cwd, eventBus, runtime, extensionPath = "<inline>") {
    const extension = createExtension(extensionPath, extensionPath);
    const resolvedCwd = resolvePath(cwd);
    const api = createExtensionAPI(extension, runtime, resolvedCwd, eventBus);
    await factory(api);
    time(`${extensionPath} factory`, "extensions");
    return extension;
}
async function loadExtensionsInternal(paths, cwd, eventBus, runtime, useCache = false) {
    const extensions = [];
    const errors = [];
    const cacheToken = useCache ? useExtensionCacheCwd(cwd) : undefined;
    const resolvedCwd = cacheToken?.cwd ?? resolvePath(cwd);
    const resolvedEventBus = eventBus ?? createEventBus();
    const resolvedRuntime = runtime ?? createExtensionRuntime();
    for (const extPath of paths) {
        const { extension, error } = await loadExtension(extPath, resolvedCwd, resolvedEventBus, resolvedRuntime, cacheToken);
        if (error) {
            errors.push({ path: extPath, error });
            continue;
        }
        if (extension) {
            extensions.push(extension);
        }
    }
    return {
        extensions,
        errors,
        runtime: resolvedRuntime,
    };
}
export async function loadExtensions(paths, cwd, eventBus, runtime) {
    return loadExtensionsInternal(paths, cwd, eventBus, runtime);
}
export async function loadExtensionsCached(paths, cwd, eventBus, runtime) {
    return loadExtensionsInternal(paths, cwd, eventBus, runtime, true);
}
function isExtensionFile(name) {
    return name.endsWith(".ts") || name.endsWith(".js");
}
function resolveExtensionEntries(dir) {
    const packageJsonPath = path.join(dir, "package.json");
    if (fs.existsSync(packageJsonPath)) {
        const manifest = readCortexManifest(packageJsonPath);
        if (manifest?.extensions?.length) {
            const entries = [];
            for (const extPath of manifest.extensions) {
                const resolvedExtPath = path.resolve(dir, extPath);
                if (fs.existsSync(resolvedExtPath)) {
                    entries.push(resolvedExtPath);
                }
            }
            if (entries.length > 0) {
                return entries;
            }
        }
    }
    const indexTs = path.join(dir, "index.ts");
    const indexJs = path.join(dir, "index.js");
    if (fs.existsSync(indexTs)) {
        return [indexTs];
    }
    if (fs.existsSync(indexJs)) {
        return [indexJs];
    }
    return null;
}
function discoverExtensionsInDir(dir) {
    if (!fs.existsSync(dir)) {
        return [];
    }
    const discovered = [];
    try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
            const entryPath = path.join(dir, entry.name);
            if ((entry.isFile() || entry.isSymbolicLink()) && isExtensionFile(entry.name)) {
                discovered.push(entryPath);
                continue;
            }
            if (entry.isDirectory() || entry.isSymbolicLink()) {
                const entries = resolveExtensionEntries(entryPath);
                if (entries) {
                    discovered.push(...entries);
                }
            }
        }
    }
    catch {
        return [];
    }
    return discovered;
}
export async function discoverAndLoadExtensions(configuredPaths, cwd, agentDir = getAgentDir(), eventBus) {
    const resolvedCwd = resolvePath(cwd);
    const resolvedAgentDir = resolvePath(agentDir);
    const allPaths = [];
    const seen = new Set();
    const addPaths = (paths) => {
        for (const p of paths) {
            const resolved = path.resolve(p);
            if (!seen.has(resolved)) {
                seen.add(resolved);
                allPaths.push(p);
            }
        }
    };
    const localExtDir = path.join(resolvedCwd, CONFIG_DIR_NAME, "extensions");
    addPaths(discoverExtensionsInDir(localExtDir));
    const globalExtDir = path.join(resolvedAgentDir, "extensions");
    addPaths(discoverExtensionsInDir(globalExtDir));
    for (const p of configuredPaths) {
        const resolved = resolvePath(p, resolvedCwd, { normalizeUnicodeSpaces: true });
        if (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory()) {
            const entries = resolveExtensionEntries(resolved);
            if (entries) {
                addPaths(entries);
                continue;
            }
            addPaths(discoverExtensionsInDir(resolved));
            continue;
        }
        addPaths([resolved]);
    }
    return loadExtensions(allPaths, resolvedCwd, eventBus);
}
//# sourceMappingURL=loader.js.map