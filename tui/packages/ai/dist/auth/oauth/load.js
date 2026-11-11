var __rewriteRelativeImportExtension = (this && this.__rewriteRelativeImportExtension) || function (path, preserveJsx) {
    if (typeof path === "string" && /^\.\.?\//.test(path)) {
        return path.replace(/\.(tsx)$|((?:\.d)?)((?:\.[^./]+?)?)\.([cm]?)ts$/i, function (m, tsx, d, ext, cm) {
            return tsx ? preserveJsx ? ".jsx" : ".js" : d && (!ext || !cm) ? m : (d + ext + "." + cm.toLowerCase() + "js");
        });
    }
    return path;
};
const importOAuthModule = (specifier) => {
    const runtimeSpecifier = import.meta.url.endsWith(".js") ? specifier.replace(/\.ts$/, ".js") : specifier;
    return import(__rewriteRelativeImportExtension(runtimeSpecifier));
};
let bundledLoaders;
export function registerBundledOAuthFlowLoaders(loaders) {
    bundledLoaders = loaders;
}
export const loadOpenAICodexOAuth = async () => {
    if (bundledLoaders)
        return bundledLoaders.openaiCodex();
    return (await importOAuthModule("./openai-codex.ts")).openaiCodexOAuth;
};
export const loadOpenRouterOAuth = async () => {
    if (bundledLoaders)
        return bundledLoaders.openrouter();
    return (await importOAuthModule("./openrouter.ts")).openRouterOAuth;
};
export const loadRadiusOAuth = async (options) => {
    if (bundledLoaders)
        return bundledLoaders.radius(options);
    return (await importOAuthModule("./radius.ts")).createRadiusOAuth(options);
};
//# sourceMappingURL=load.js.map