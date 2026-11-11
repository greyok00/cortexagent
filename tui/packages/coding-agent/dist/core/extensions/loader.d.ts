import { type EventBus } from "../event-bus.ts";
import type { Extension, ExtensionFactory, ExtensionRuntime, LoadExtensionsResult } from "./types.ts";
export declare function clearExtensionCache(): void;
export declare function createExtensionRuntime(): ExtensionRuntime;
export declare function loadExtensionFromFactory(factory: ExtensionFactory, cwd: string, eventBus: EventBus, runtime: ExtensionRuntime, extensionPath?: string): Promise<Extension>;
export declare function loadExtensions(paths: string[], cwd: string, eventBus?: EventBus, runtime?: ExtensionRuntime): Promise<LoadExtensionsResult>;
export declare function loadExtensionsCached(paths: string[], cwd: string, eventBus?: EventBus, runtime?: ExtensionRuntime): Promise<LoadExtensionsResult>;
export declare function discoverAndLoadExtensions(configuredPaths: string[], cwd: string, agentDir?: string, eventBus?: EventBus): Promise<LoadExtensionsResult>;
//# sourceMappingURL=loader.d.ts.map