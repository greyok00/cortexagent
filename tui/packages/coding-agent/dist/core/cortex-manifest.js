import { readFileSync } from "node:fs";
const RESOURCE_FIELDS = ["extensions", "skills", "prompts", "themes"];
function isObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
export function readCortexManifest(packageJsonPath) {
    try {
        const pkg = JSON.parse(readFileSync(packageJsonPath, "utf-8"));
        if (!isObject(pkg) || !isObject(pkg.cortex)) {
            return null;
        }
        const manifest = {};
        for (const field of RESOURCE_FIELDS) {
            const entries = pkg.cortex[field];
            if (Array.isArray(entries) && entries.every((entry) => typeof entry === "string")) {
                manifest[field] = entries;
            }
        }
        return manifest;
    }
    catch {
        return null;
    }
}
//# sourceMappingURL=cortex-manifest.js.map