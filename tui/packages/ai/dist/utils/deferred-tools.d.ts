import type { Context, Tool } from "../types.ts";
type ToolNameNormalizer = (name: string) => string;
export declare function splitDeferredTools(context: Context, enabled: boolean, normalizeName?: ToolNameNormalizer): {
    immediate: Tool[];
    deferred: Map<string, Tool>;
};
export {};
//# sourceMappingURL=deferred-tools.d.ts.map