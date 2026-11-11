let procEnvCache = null;
function getBunSandboxEnvValue(name) {
    if (typeof process === "undefined" || !process.versions?.bun || Object.keys(process.env).length > 0) {
        return undefined;
    }
    if (procEnvCache === null) {
        procEnvCache = new Map();
        try {
            const { readFileSync } = require("node:fs");
            const data = readFileSync("/proc/self/environ", "utf-8");
            for (const entry of data.split("\0")) {
                const idx = entry.indexOf("=");
                if (idx > 0) {
                    procEnvCache.set(entry.slice(0, idx), entry.slice(idx + 1));
                }
            }
        }
        catch {
            // /proc/self/environ may not exist or may not be readable.
        }
    }
    return procEnvCache.get(name);
}
export function getProviderEnvValue(name, env) {
    return (env?.[name] ||
        (typeof process !== "undefined" ? process.env[name] : undefined) ||
        getBunSandboxEnvValue(name) ||
        undefined);
}
//# sourceMappingURL=provider-env.js.map