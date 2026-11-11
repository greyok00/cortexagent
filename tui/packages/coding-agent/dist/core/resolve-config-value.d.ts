export declare function getConfigValueEnvVarName(config: string): string | undefined;
export declare function getConfigValueEnvVarNames(config: string): string[];
export declare function getMissingConfigValueEnvVarNames(config: string, env?: Record<string, string>): string[];
export declare function isCommandConfigValue(config: string): boolean;
export declare function isConfigValueConfigured(config: string, env?: Record<string, string>): boolean;
export declare function resolveConfigValue(config: string, env?: Record<string, string>): string | undefined;
export declare function resolveConfigValueUncached(config: string, env?: Record<string, string>): string | undefined;
export declare function resolveConfigValueOrThrow(config: string, description: string, env?: Record<string, string>): string;
export declare function resolveHeaders(headers: Record<string, string> | undefined, env?: Record<string, string>): Record<string, string> | undefined;
export declare function resolveHeadersOrThrow(headers: Record<string, string> | undefined, description: string, env?: Record<string, string>): Record<string, string> | undefined;
export declare function clearConfigValueCache(): void;
//# sourceMappingURL=resolve-config-value.d.ts.map