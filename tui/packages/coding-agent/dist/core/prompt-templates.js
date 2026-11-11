import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { basename, dirname, join, resolve, sep } from "path";
import { CONFIG_DIR_NAME } from "../config.js";
import { parseFrontmatter } from "../utils/frontmatter.js";
import { resolvePath } from "../utils/paths.js";
import { createSyntheticSourceInfo } from "./source-info.js";
export function parseCommandArgs(argsString) {
    const args = [];
    let current = "";
    let inQuote = null;
    for (let i = 0; i < argsString.length; i++) {
        const char = argsString[i];
        if (inQuote) {
            if (char === inQuote) {
                inQuote = null;
            }
            else {
                current += char;
            }
        }
        else if (char === '"' || char === "'") {
            inQuote = char;
        }
        else if (/\s/.test(char)) {
            if (current) {
                args.push(current);
                current = "";
            }
        }
        else {
            current += char;
        }
    }
    if (current) {
        args.push(current);
    }
    return args;
}
export function substituteArgs(content, args) {
    const allArgs = args.join(" ");
    return content.replace(/\$\{(\d+|ARGUMENTS|@):-([^}]*)\}|\$\{@:(\d+)(?::(\d+))?\}|\$(ARGUMENTS|@|\d+)/g, (_match, defaultTarget, defaultValue, sliceStart, sliceLength, simple) => {
        if (defaultTarget) {
            const value = defaultTarget === "@" || defaultTarget === "ARGUMENTS" ? allArgs : args[parseInt(defaultTarget, 10) - 1];
            return value ? value : defaultValue;
        }
        if (sliceStart) {
            let start = parseInt(sliceStart, 10) - 1;
            if (start < 0)
                start = 0;
            if (sliceLength) {
                const length = parseInt(sliceLength, 10);
                return args.slice(start, start + length).join(" ");
            }
            return args.slice(start).join(" ");
        }
        if (simple === "ARGUMENTS" || simple === "@") {
            return allArgs;
        }
        const index = parseInt(simple, 10) - 1;
        return args[index] ?? "";
    });
}
function loadTemplateFromFile(filePath, sourceInfo) {
    try {
        const rawContent = readFileSync(filePath, "utf-8");
        const { frontmatter, body } = parseFrontmatter(rawContent);
        const name = basename(filePath).replace(/\.md$/, "");
        let description = frontmatter.description || "";
        if (!description) {
            const firstLine = body.split("\n").find((line) => line.trim());
            if (firstLine) {
                description = firstLine.slice(0, 60);
                if (firstLine.length > 60)
                    description += "...";
            }
        }
        return {
            name,
            description,
            ...(frontmatter["argument-hint"] && { argumentHint: frontmatter["argument-hint"] }),
            content: body,
            sourceInfo,
            filePath,
        };
    }
    catch {
        return null;
    }
}
function loadTemplatesFromDir(dir, getSourceInfo) {
    const templates = [];
    if (!existsSync(dir)) {
        return templates;
    }
    try {
        const entries = readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = join(dir, entry.name);
            let isFile = entry.isFile();
            if (entry.isSymbolicLink()) {
                try {
                    const stats = statSync(fullPath);
                    isFile = stats.isFile();
                }
                catch {
                    continue;
                }
            }
            if (isFile && entry.name.endsWith(".md")) {
                const template = loadTemplateFromFile(fullPath, getSourceInfo(fullPath));
                if (template) {
                    templates.push(template);
                }
            }
        }
    }
    catch {
        return templates;
    }
    return templates;
}
export function loadPromptTemplates(options) {
    const resolvedCwd = resolvePath(options.cwd);
    const resolvedAgentDir = resolvePath(options.agentDir);
    const promptPaths = options.promptPaths;
    const includeDefaults = options.includeDefaults;
    const templates = [];
    const globalPromptsDir = join(resolvedAgentDir, "prompts");
    const projectPromptsDir = resolve(resolvedCwd, CONFIG_DIR_NAME, "prompts");
    const isUnderPath = (target, root) => {
        const normalizedRoot = resolve(root);
        if (target === normalizedRoot) {
            return true;
        }
        const prefix = normalizedRoot.endsWith(sep) ? normalizedRoot : `${normalizedRoot}${sep}`;
        return target.startsWith(prefix);
    };
    const getSourceInfo = (resolvedPath) => {
        if (isUnderPath(resolvedPath, globalPromptsDir)) {
            return createSyntheticSourceInfo(resolvedPath, {
                source: "local",
                scope: "user",
                baseDir: globalPromptsDir,
            });
        }
        if (isUnderPath(resolvedPath, projectPromptsDir)) {
            return createSyntheticSourceInfo(resolvedPath, {
                source: "local",
                scope: "project",
                baseDir: projectPromptsDir,
            });
        }
        return createSyntheticSourceInfo(resolvedPath, {
            source: "local",
            baseDir: statSync(resolvedPath).isDirectory() ? resolvedPath : dirname(resolvedPath),
        });
    };
    if (includeDefaults) {
        templates.push(...loadTemplatesFromDir(globalPromptsDir, getSourceInfo));
        templates.push(...loadTemplatesFromDir(projectPromptsDir, getSourceInfo));
    }
    for (const rawPath of promptPaths) {
        const resolvedPath = resolvePath(rawPath, resolvedCwd, { trim: true });
        if (!existsSync(resolvedPath)) {
            continue;
        }
        try {
            const stats = statSync(resolvedPath);
            if (stats.isDirectory()) {
                templates.push(...loadTemplatesFromDir(resolvedPath, getSourceInfo));
            }
            else if (stats.isFile() && resolvedPath.endsWith(".md")) {
                const template = loadTemplateFromFile(resolvedPath, getSourceInfo(resolvedPath));
                if (template) {
                    templates.push(template);
                }
            }
        }
        catch {
            // Ignore read failures
        }
    }
    return templates;
}
export function expandPromptTemplate(text, templates) {
    if (!text.startsWith("/"))
        return text;
    const match = text.match(/^\/([^\s]+)(?:\s+([\s\S]*))?$/);
    if (!match)
        return text;
    const templateName = match[1];
    const argsString = match[2] ?? "";
    const template = templates.find((t) => t.name === templateName);
    if (template) {
        const args = parseCommandArgs(argsString);
        return substituteArgs(template.content, args);
    }
    return text;
}
//# sourceMappingURL=prompt-templates.js.map