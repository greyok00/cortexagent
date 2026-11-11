var __rewriteRelativeImportExtension = (this && this.__rewriteRelativeImportExtension) || function (path, preserveJsx) {
    if (typeof path === "string" && /^\.\.?\//.test(path)) {
        return path.replace(/\.(tsx)$|((?:\.d)?)((?:\.[^./]+?)?)\.([cm]?)ts$/i, function (m, tsx, d, ext, cm) {
            return tsx ? preserveJsx ? ".jsx" : ".js" : d && (!ext || !cm) ? m : (d + ext + "." + cm.toLowerCase() + "js");
        });
    }
    return path;
};
const importNodeModule = (specifier) => import(__rewriteRelativeImportExtension(specifier));
function getProcessEnv() {
    const proc = globalThis.process;
    return proc?.env;
}
export function defaultProviderAuthContext() {
    return {
        async env(name) {
            const value = getProcessEnv()?.[name];
            return typeof value === "string" && value.trim().length > 0 ? value : undefined;
        },
        async fileExists(path) {
            try {
                const fs = (await importNodeModule("node:fs/promises"));
                let resolved = path;
                if (resolved.startsWith("~")) {
                    const os = (await importNodeModule("node:os"));
                    resolved = os.homedir() + resolved.slice(1);
                }
                await fs.access(resolved);
                return true;
            }
            catch {
                return false;
            }
        },
    };
}
//# sourceMappingURL=context.js.map