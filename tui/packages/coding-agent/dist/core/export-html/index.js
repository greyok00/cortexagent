import { existsSync, readFileSync, writeFileSync } from "fs";
import { basename, join } from "path";
import { APP_NAME, getExportTemplateDir } from "../../config.js";
import { getResolvedThemeColors, getThemeExportColors } from "../../modes/interactive/theme/theme.js";
import { normalizePath, resolvePath } from "../../utils/paths.js";
import { SessionManager } from "../session-manager.js";
function parseColor(color) {
    const hexMatch = color.match(/^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/);
    if (hexMatch) {
        return {
            r: Number.parseInt(hexMatch[1], 16),
            g: Number.parseInt(hexMatch[2], 16),
            b: Number.parseInt(hexMatch[3], 16),
        };
    }
    const rgbMatch = color.match(/^rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/);
    if (rgbMatch) {
        return {
            r: Number.parseInt(rgbMatch[1], 10),
            g: Number.parseInt(rgbMatch[2], 10),
            b: Number.parseInt(rgbMatch[3], 10),
        };
    }
    return undefined;
}
function getLuminance(r, g, b) {
    const toLinear = (c) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}
function adjustBrightness(color, factor) {
    const parsed = parseColor(color);
    if (!parsed)
        return color;
    const adjust = (c) => Math.min(255, Math.max(0, Math.round(c * factor)));
    return `rgb(${adjust(parsed.r)}, ${adjust(parsed.g)}, ${adjust(parsed.b)})`;
}
function deriveExportColors(baseColor) {
    const parsed = parseColor(baseColor);
    if (!parsed) {
        return {
            pageBg: "rgb(24, 24, 30)",
            cardBg: "rgb(30, 30, 36)",
            infoBg: "rgb(60, 55, 40)",
        };
    }
    const luminance = getLuminance(parsed.r, parsed.g, parsed.b);
    const isLight = luminance > 0.5;
    if (isLight) {
        return {
            pageBg: adjustBrightness(baseColor, 0.96),
            cardBg: baseColor,
            infoBg: `rgb(${Math.min(255, parsed.r + 10)}, ${Math.min(255, parsed.g + 5)}, ${Math.max(0, parsed.b - 20)})`,
        };
    }
    return {
        pageBg: adjustBrightness(baseColor, 0.7),
        cardBg: adjustBrightness(baseColor, 0.85),
        infoBg: `rgb(${Math.min(255, parsed.r + 20)}, ${Math.min(255, parsed.g + 15)}, ${parsed.b})`,
    };
}
function generateThemeVars(themeName) {
    const colors = getResolvedThemeColors(themeName);
    const lines = [];
    for (const [key, value] of Object.entries(colors)) {
        lines.push(`--${key}: ${value};`);
    }
    const themeExport = getThemeExportColors(themeName);
    const userMessageBg = colors.userMessageBg || "#343541";
    const derivedColors = deriveExportColors(userMessageBg);
    lines.push(`--exportPageBg: ${themeExport.pageBg ?? derivedColors.pageBg};`);
    lines.push(`--exportCardBg: ${themeExport.cardBg ?? derivedColors.cardBg};`);
    lines.push(`--exportInfoBg: ${themeExport.infoBg ?? derivedColors.infoBg};`);
    return lines.join("\n      ");
}
function generateHtml(sessionData, themeName) {
    const templateDir = getExportTemplateDir();
    const template = readFileSync(join(templateDir, "template.html"), "utf-8");
    const templateCss = readFileSync(join(templateDir, "template.css"), "utf-8");
    const templateJs = readFileSync(join(templateDir, "template.js"), "utf-8");
    const markedJs = readFileSync(join(templateDir, "vendor", "marked.min.js"), "utf-8");
    const hljsJs = readFileSync(join(templateDir, "vendor", "highlight.min.js"), "utf-8");
    const themeVars = generateThemeVars(themeName);
    const colors = getResolvedThemeColors(themeName);
    const themeExport = getThemeExportColors(themeName);
    const derivedExportColors = deriveExportColors(colors.userMessageBg || "#343541");
    const bodyBg = themeExport.pageBg ?? derivedExportColors.pageBg;
    const containerBg = themeExport.cardBg ?? derivedExportColors.cardBg;
    const infoBg = themeExport.infoBg ?? derivedExportColors.infoBg;
    const sessionDataBase64 = Buffer.from(JSON.stringify(sessionData)).toString("base64");
    const css = templateCss
        .replace("{{THEME_VARS}}", themeVars)
        .replace("{{BODY_BG}}", bodyBg)
        .replace("{{CONTAINER_BG}}", containerBg)
        .replace("{{INFO_BG}}", infoBg);
    return template
        .replace("{{CSS}}", css)
        .replace("{{JS}}", templateJs)
        .replace("{{SESSION_DATA}}", sessionDataBase64)
        .replace("{{MARKED_JS}}", markedJs)
        .replace("{{HIGHLIGHT_JS}}", hljsJs);
}
const TEMPLATE_RENDERED_TOOLS = new Set(["bash", "read", "write", "edit", "ls"]);
function preRenderCustomTools(entries, toolRenderer) {
    const renderedTools = {};
    for (const entry of entries) {
        if (entry.type !== "message")
            continue;
        const msg = entry.message;
        if (msg.role === "assistant" && Array.isArray(msg.content)) {
            for (const block of msg.content) {
                if (block.type === "toolCall" && !TEMPLATE_RENDERED_TOOLS.has(block.name)) {
                    const callHtml = toolRenderer.renderCall(block.id, block.name, block.arguments);
                    if (callHtml) {
                        renderedTools[block.id] = { callHtml };
                    }
                }
            }
        }
        if (msg.role === "toolResult" && msg.toolCallId) {
            const toolName = msg.toolName || "";
            const existing = renderedTools[msg.toolCallId];
            if (existing || !TEMPLATE_RENDERED_TOOLS.has(toolName)) {
                const rendered = toolRenderer.renderResult(msg.toolCallId, toolName, msg.content, msg.details, msg.isError || false);
                if (rendered) {
                    renderedTools[msg.toolCallId] = {
                        ...existing,
                        resultHtmlCollapsed: rendered.collapsed,
                        resultHtmlExpanded: rendered.expanded,
                    };
                }
            }
        }
    }
    return renderedTools;
}
export async function exportSessionToHtml(sm, state, options) {
    const opts = typeof options === "string" ? { outputPath: options } : options || {};
    const sessionFile = sm.getSessionFile();
    if (!sessionFile) {
        throw new Error("Cannot export in-memory session to HTML");
    }
    if (!existsSync(sessionFile)) {
        throw new Error("Nothing to export yet - start a conversation first");
    }
    const entries = sm.getEntries();
    let renderedTools;
    if (opts.toolRenderer) {
        renderedTools = preRenderCustomTools(entries, opts.toolRenderer);
        if (Object.keys(renderedTools).length === 0) {
            renderedTools = undefined;
        }
    }
    const sessionData = {
        header: sm.getHeader(),
        entries,
        leafId: sm.getLeafId(),
        systemPrompt: state?.systemPrompt,
        tools: state?.tools?.map((t) => ({ name: t.name, description: t.description, parameters: t.parameters })),
        renderedTools,
    };
    const html = generateHtml(sessionData, opts.themeName);
    let outputPath = opts.outputPath ? normalizePath(opts.outputPath) : undefined;
    if (!outputPath) {
        const sessionBasename = basename(sessionFile, ".jsonl");
        outputPath = `${APP_NAME}-session-${sessionBasename}.html`;
    }
    writeFileSync(outputPath, html, "utf8");
    return outputPath;
}
export async function exportFromFile(inputPath, options) {
    const opts = typeof options === "string" ? { outputPath: options } : options || {};
    const resolvedInputPath = resolvePath(inputPath);
    if (!existsSync(resolvedInputPath)) {
        throw new Error(`File not found: ${resolvedInputPath}`);
    }
    const sm = SessionManager.open(resolvedInputPath);
    const sessionData = {
        header: sm.getHeader(),
        entries: sm.getEntries(),
        leafId: sm.getLeafId(),
        systemPrompt: undefined,
        tools: undefined,
    };
    const html = generateHtml(sessionData, opts.themeName);
    let outputPath = opts.outputPath ? normalizePath(opts.outputPath) : undefined;
    if (!outputPath) {
        const inputBasename = basename(resolvedInputPath, ".jsonl");
        outputPath = `${APP_NAME}-session-${inputBasename}.html`;
    }
    writeFileSync(outputPath, html, "utf8");
    return outputPath;
}
//# sourceMappingURL=index.js.map