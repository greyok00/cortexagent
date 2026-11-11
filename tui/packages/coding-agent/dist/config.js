import { accessSync, constants, existsSync, readFileSync, realpathSync } from "fs";
import { homedir } from "os";
import { basename, dirname, join, resolve, sep, win32 } from "path";
import { fileURLToPath } from "url";
import { spawnProcessSync } from "./utils/child-process.js";
import { normalizePath } from "./utils/paths.js";
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
export const isBunBinary = import.meta.url.includes("$bunfs") || import.meta.url.includes("~BUN") || import.meta.url.includes("%7EBUN");
export const isBunRuntime = !!process.versions.bun;
function normalizeSelfUpdatePackageTarget(target) {
    if (typeof target === "string") {
        return { packageName: target, installSpec: target };
    }
    return { packageName: target.packageName, installSpec: target.installSpec ?? target.packageName };
}
function makeSelfUpdateCommand(installStep, uninstallStep) {
    if (!uninstallStep)
        return installStep;
    return {
        ...installStep,
        display: `${uninstallStep.display} && ${installStep.display}`,
        steps: [uninstallStep, installStep],
    };
}
function makeSelfUpdateCommandStep(command, args) {
    return {
        command,
        args,
        display: [command, ...args].map((arg) => (/\s/.test(arg) ? `"${arg}"` : arg)).join(" "),
    };
}
export function detectInstallMethod() {
    if (isBunBinary) {
        return "bun-binary";
    }
    const resolvedPath = `${__dirname}\0${process.execPath || ""}`.toLowerCase().replace(/\\/g, "/");
    if (resolvedPath.includes("/pnpm/") || resolvedPath.includes("/.pnpm/")) {
        return "pnpm";
    }
    if (resolvedPath.includes("/yarn/") || resolvedPath.includes("/.yarn/")) {
        return "yarn";
    }
    if (isBunRuntime || resolvedPath.includes("/install/global/node_modules/")) {
        return "bun";
    }
    if (resolvedPath.includes("/npm/") || resolvedPath.includes("/node_modules/")) {
        return "npm";
    }
    return "unknown";
}
function getInferredNpmInstall() {
    const packageDir = getPackageDir();
    const path = process.platform === "win32" || packageDir.includes("\\") ? win32 : { basename, dirname };
    const parent = path.dirname(packageDir);
    let root;
    if (path.basename(parent).startsWith("@") && path.basename(path.dirname(parent)) === "node_modules") {
        root = path.dirname(parent);
    }
    else if (path.basename(parent) === "node_modules") {
        root = parent;
    }
    if (!root)
        return undefined;
    const rootParent = path.dirname(root);
    if (path.basename(rootParent) === "lib")
        return { root, prefix: path.dirname(rootParent) };
    return undefined;
}
function getSelfUpdateCommandForMethod(method, installedPackageName, updatePackageTarget = installedPackageName, npmCommand) {
    const target = normalizeSelfUpdatePackageTarget(updatePackageTarget);
    switch (method) {
        case "bun-binary":
            return undefined;
        case "pnpm": {
            const match = readCommandOutput("pnpm", ["root", "-g"])
                ? undefined
                : /^(.*[\\/]global[\\/][^\\/]+)[\\/]\.pnpm[\\/]/.exec(getPackageDir());
            const binDirArgs = match
                ? [`--config.global-bin-dir=${process.env.PNPM_HOME || dirname(dirname(match[1]))}`]
                : [];
            return makeSelfUpdateCommand(makeSelfUpdateCommandStep("pnpm", [
                "install",
                "-g",
                "--ignore-scripts",
                "--config.minimumReleaseAge=0",
                ...binDirArgs,
                target.installSpec,
            ]), target.packageName === installedPackageName
                ? undefined
                : makeSelfUpdateCommandStep("pnpm", ["remove", "-g", ...binDirArgs, installedPackageName]));
        }
        case "yarn":
            return makeSelfUpdateCommand(makeSelfUpdateCommandStep("yarn", ["global", "add", "--ignore-scripts", target.installSpec]), target.packageName === installedPackageName
                ? undefined
                : makeSelfUpdateCommandStep("yarn", ["global", "remove", installedPackageName]));
        case "bun":
            return makeSelfUpdateCommand(makeSelfUpdateCommandStep("bun", [
                "install",
                "-g",
                "--ignore-scripts",
                "--minimum-release-age=0",
                target.installSpec,
            ]), target.packageName === installedPackageName
                ? undefined
                : makeSelfUpdateCommandStep("bun", ["uninstall", "-g", installedPackageName]));
        case "npm": {
            const [command = "npm", ...npmArgs] = npmCommand ?? [];
            const inferred = npmCommand?.length ? undefined : getInferredNpmInstall();
            const prefixArgs = [...npmArgs, ...(inferred ? ["--prefix", inferred.prefix] : [])];
            const installStep = makeSelfUpdateCommandStep(command, [
                ...prefixArgs,
                "install",
                "-g",
                "--ignore-scripts",
                "--min-release-age=0",
                target.installSpec,
            ]);
            const uninstallStep = target.packageName === installedPackageName
                ? undefined
                : makeSelfUpdateCommandStep(command, [...prefixArgs, "uninstall", "-g", installedPackageName]);
            return makeSelfUpdateCommand(installStep, uninstallStep);
        }
        case "unknown":
            return undefined;
    }
}
function readCommandOutput(command, args, options = {}) {
    const result = spawnProcessSync(command, args, {
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "pipe"],
    });
    if (result.status === 0)
        return result.stdout.trim() || undefined;
    if (options.requireSuccess) {
        const reason = result.error?.message || result.stderr.trim() || `exit code ${result.status ?? "unknown"}`;
        throw new Error(`Failed to run ${[command, ...args].join(" ")}: ${reason}`);
    }
    return undefined;
}
function getGlobalPackageRoots(method, _packageName, npmCommand) {
    switch (method) {
        case "npm": {
            const configured = !!npmCommand?.length;
            const [command = "npm", ...npmArgs] = npmCommand ?? [];
            if (configured && command === "bun") {
                const bunBin = readCommandOutput(command, [...npmArgs, "pm", "bin", "-g"], {
                    requireSuccess: true,
                });
                const roots = [join(homedir(), ".bun", "install", "global", "node_modules")];
                if (bunBin) {
                    roots.push(join(dirname(bunBin), "install", "global", "node_modules"));
                }
                return roots;
            }
            const root = readCommandOutput(command, [...npmArgs, "root", "-g"], {
                requireSuccess: configured,
            });
            const inferred = configured ? undefined : getInferredNpmInstall();
            return [root, inferred?.root].filter((x) => !!x);
        }
        case "pnpm": {
            const root = readCommandOutput("pnpm", ["root", "-g"]);
            if (root)
                return [root, dirname(root)];
            const match = /^(.*[\\/]global[\\/][^\\/]+)[\\/]\.pnpm[\\/]/.exec(getPackageDir());
            return match ? [match[1]] : [];
        }
        case "yarn": {
            const dir = readCommandOutput("yarn", ["global", "dir"]);
            return dir ? [dir, join(dir, "node_modules")] : [];
        }
        case "bun": {
            const bunBin = readCommandOutput("bun", ["pm", "bin", "-g"]);
            const roots = [join(homedir(), ".bun", "install", "global", "node_modules")];
            if (bunBin) {
                roots.push(join(dirname(bunBin), "install", "global", "node_modules"));
            }
            return roots;
        }
        case "bun-binary":
        case "unknown":
            return [];
    }
}
function normalizeExistingPathForComparison(path, resolveSymlinks) {
    const resolvedPath = resolve(path);
    if (!existsSync(resolvedPath)) {
        return undefined;
    }
    let normalizedPath = resolvedPath;
    if (resolveSymlinks) {
        try {
            normalizedPath = realpathSync(resolvedPath);
        }
        catch {
            return undefined;
        }
    }
    if (process.platform === "win32") {
        normalizedPath = normalizedPath.toLowerCase();
    }
    return normalizedPath;
}
function getPathComparisonCandidates(path) {
    return Array.from(new Set([normalizeExistingPathForComparison(path, false), normalizeExistingPathForComparison(path, true)].filter((candidate) => !!candidate)));
}
function getEntrypointPackageDir() {
    const entrypoint = process.argv[1];
    if (!entrypoint)
        return undefined;
    let dir = dirname(entrypoint);
    while (dir !== dirname(dir)) {
        if (existsSync(join(dir, "package.json"))) {
            return dir;
        }
        dir = dirname(dir);
    }
    return undefined;
}
function isSelfUpdatePathWritable() {
    const packageDir = getPackageDir();
    try {
        accessSync(packageDir, constants.W_OK);
        accessSync(dirname(packageDir), constants.W_OK);
        return true;
    }
    catch {
        return false;
    }
}
function isManagedByGlobalPackageManager(method, packageName, npmCommand) {
    const packageDirs = [getPackageDir(), getEntrypointPackageDir()].filter((dir) => !!dir);
    const packageDirCandidates = packageDirs.flatMap((dir) => getPathComparisonCandidates(dir));
    return getGlobalPackageRoots(method, packageName, npmCommand).some((root) => {
        return getPathComparisonCandidates(root).some((normalizedRoot) => {
            const rootPrefix = normalizedRoot.endsWith(sep) ? normalizedRoot : `${normalizedRoot}${sep}`;
            return packageDirCandidates.some((packageDir) => packageDir.startsWith(rootPrefix));
        });
    });
}
export function getSelfUpdateCommand(packageName, npmCommand, updatePackageTarget = packageName) {
    const method = detectInstallMethod();
    const command = getSelfUpdateCommandForMethod(method, packageName, updatePackageTarget, npmCommand);
    if (!command || !isManagedByGlobalPackageManager(method, packageName, npmCommand) || !isSelfUpdatePathWritable()) {
        return undefined;
    }
    return command;
}
export function getSelfUpdateUnavailableInstruction(packageName, npmCommand, updatePackageTarget = packageName) {
    const method = detectInstallMethod();
    const target = normalizeSelfUpdatePackageTarget(updatePackageTarget);
    if (method === "bun-binary") {
        return `Download from: https://github.com/cortex/mono/releases/latest`;
    }
    const command = getSelfUpdateCommandForMethod(method, packageName, target, npmCommand);
    if (command) {
        if (isManagedByGlobalPackageManager(method, packageName, npmCommand) && !isSelfUpdatePathWritable()) {
            return `This installation is managed by a global ${method} install, but the install path is not writable. Update it yourself with: ${command.display}`;
        }
        return `This installation is not managed by a global ${method} install. Update it with the package manager, wrapper, or source checkout that provides it.`;
    }
    return `Update ${target.installSpec} using the package manager, wrapper, or source checkout that provides this installation.`;
}
export function getUpdateInstruction(packageName) {
    const method = detectInstallMethod();
    const command = getSelfUpdateCommandForMethod(method, packageName);
    if (command) {
        return `Run: ${command.display}`;
    }
    return getSelfUpdateUnavailableInstruction(packageName);
}
export function getPackageDir() {
    const envDir = process.env.CORTEX_PACKAGE_DIR;
    if (envDir) {
        return normalizePath(envDir);
    }
    if (isBunBinary) {
        return dirname(process.execPath);
    }
    // Walk up from __dirname until we find the package root. Skip build-output
    // dirs (dist/) that carry a copied package.json but no src/ or dist/ subdir —
    // those are the package root's children, not the root itself.
    let dir = __dirname;
    while (dir !== dirname(dir)) {
        if (existsSync(join(dir, "package.json")) && (existsSync(join(dir, "src")) || existsSync(join(dir, "dist")))) {
            return dir;
        }
        dir = dirname(dir);
    }
    return __dirname;
}
export function getThemesDir() {
    if (isBunBinary) {
        return join(getPackageDir(), "theme");
    }
    const packageDir = getPackageDir();
    const srcOrDist = existsSync(join(packageDir, "src")) ? "src" : "dist";
    return join(packageDir, srcOrDist, "modes", "interactive", "theme");
}
export function getExportTemplateDir() {
    if (isBunBinary) {
        return join(getPackageDir(), "export-html");
    }
    const packageDir = getPackageDir();
    const srcOrDist = existsSync(join(packageDir, "src")) ? "src" : "dist";
    return join(packageDir, srcOrDist, "core", "export-html");
}
export function getPackageJsonPath() {
    return join(getPackageDir(), "package.json");
}
export function getExamplesPath() {
    return resolve(join(getPackageDir(), "examples"));
}
export function getInteractiveAssetsDir() {
    if (isBunBinary) {
        return join(getPackageDir(), "assets");
    }
    const packageDir = getPackageDir();
    const srcOrDist = existsSync(join(packageDir, "src")) ? "src" : "dist";
    return join(packageDir, srcOrDist, "modes", "interactive", "assets");
}
export function getBundledInteractiveAssetPath(name) {
    return join(getInteractiveAssetsDir(), name);
}
let pkg = {};
try {
    pkg = JSON.parse(readFileSync(getPackageJsonPath(), "utf-8"));
}
catch (e) {
    const err = e;
    if (err.code !== "ENOENT")
        throw e;
}
const cortexConfigName = pkg.cortexConfig?.name;
export const PACKAGE_NAME = pkg.name || "@cortexagent/coding-agent";
export const APP_NAME = cortexConfigName || "cortex";
export const APP_TITLE = cortexConfigName ? APP_NAME : "cortex";
export const CONFIG_DIR_NAME = pkg.cortexConfig?.configDir || ".cortex";
export const VERSION = pkg.version || "0.0.0";
export const ENV_AGENT_DIR = `${APP_NAME.toUpperCase()}_CODING_AGENT_DIR`;
export const ENV_SESSION_DIR = `${APP_NAME.toUpperCase()}_CODING_AGENT_SESSION_DIR`;
export function expandTildePath(path) {
    return normalizePath(path);
}
const DEFAULT_SHARE_VIEWER_URL = "http://127.0.0.1/session/";
export function getShareViewerUrl(gistId) {
    const baseUrl = process.env.CORTEX_SHARE_VIEWER_URL || DEFAULT_SHARE_VIEWER_URL;
    return `${baseUrl}#${gistId}`;
}
export function getAgentDir() {
    const envDir = process.env[ENV_AGENT_DIR];
    if (envDir) {
        return expandTildePath(envDir);
    }
    return join(homedir(), CONFIG_DIR_NAME, "agent");
}
export function getCustomThemesDir() {
    return join(getAgentDir(), "themes");
}
export function getModelsPath() {
    return join(getAgentDir(), "models.json");
}
export function getAuthPath() {
    return join(getAgentDir(), "auth.json");
}
export function getSettingsPath() {
    return join(getAgentDir(), "settings.json");
}
export function getToolsDir() {
    return join(getAgentDir(), "tools");
}
export function getBinDir() {
    return join(getAgentDir(), "bin");
}
export function getPromptsDir() {
    return join(getAgentDir(), "prompts");
}
export function getSessionsDir() {
    return join(getAgentDir(), "sessions");
}
export function getDebugLogPath() {
    return join(getAgentDir(), `${APP_NAME}-debug.log`);
}
//# sourceMappingURL=config.js.map