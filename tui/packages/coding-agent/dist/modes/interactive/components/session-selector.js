import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { unlink } from "node:fs/promises";
import * as os from "node:os";
import { Container, getKeybindings, Input, Spacer, Text, truncateToWidth, visibleWidth, } from "@cortexagent/tui";
import { KeybindingsManager } from "../../../core/keybindings.js";
import { canonicalizePath as _canonicalizePath } from "../../../utils/paths.js";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { keyHint, keyText } from "./keybinding-hints.js";
import { filterAndSortSessions, hasSessionName } from "./session-selector-search.js";
function shortenPath(path) {
    const home = os.homedir();
    if (!path)
        return path;
    if (path.startsWith(home)) {
        return `~${path.slice(home.length)}`;
    }
    return path;
}
function formatSessionDate(date) {
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1)
        return "now";
    if (diffMins < 60)
        return `${diffMins}m`;
    if (diffHours < 24)
        return `${diffHours}h`;
    if (diffDays < 7)
        return `${diffDays}d`;
    if (diffDays < 30)
        return `${Math.floor(diffDays / 7)}w`;
    if (diffDays < 365)
        return `${Math.floor(diffDays / 30)}mo`;
    return `${Math.floor(diffDays / 365)}y`;
}
function canonicalizePath(path) {
    if (!path)
        return path;
    return _canonicalizePath(path);
}
class SessionSelectorHeader {
    scope;
    sortMode;
    nameFilter;
    requestRender;
    loading = false;
    loadProgress = null;
    showPath = false;
    confirmingDeletePath = null;
    statusMessage = null;
    statusTimeout = null;
    showRenameHint = false;
    constructor(scope, sortMode, nameFilter, requestRender) {
        this.scope = scope;
        this.sortMode = sortMode;
        this.nameFilter = nameFilter;
        this.requestRender = requestRender;
    }
    setScope(scope) {
        this.scope = scope;
    }
    setSortMode(sortMode) {
        this.sortMode = sortMode;
    }
    setNameFilter(nameFilter) {
        this.nameFilter = nameFilter;
    }
    setLoading(loading) {
        this.loading = loading;
        this.loadProgress = null;
    }
    setProgress(loaded, total) {
        this.loadProgress = { loaded, total };
    }
    setShowPath(showPath) {
        this.showPath = showPath;
    }
    setShowRenameHint(show) {
        this.showRenameHint = show;
    }
    setConfirmingDeletePath(path) {
        this.confirmingDeletePath = path;
    }
    clearStatusTimeout() {
        if (!this.statusTimeout)
            return;
        clearTimeout(this.statusTimeout);
        this.statusTimeout = null;
    }
    setStatusMessage(msg, autoHideMs) {
        this.clearStatusTimeout();
        this.statusMessage = msg;
        if (!msg || !autoHideMs)
            return;
        this.statusTimeout = setTimeout(() => {
            this.statusMessage = null;
            this.statusTimeout = null;
            this.requestRender();
        }, autoHideMs);
    }
    invalidate() { }
    render(width) {
        const title = this.scope === "current" ? "Resume Session (Current Folder)" : "Resume Session (All)";
        const leftText = theme.bold(title);
        const sortLabel = this.sortMode === "threaded" ? "Threaded" : this.sortMode === "recent" ? "Recent" : "Fuzzy";
        const sortText = theme.fg("muted", "Sort: ") + theme.fg("accent", sortLabel);
        const nameLabel = this.nameFilter === "all" ? "All" : "Named";
        const nameText = theme.fg("muted", "Name: ") + theme.fg("accent", nameLabel);
        let scopeText;
        if (this.loading) {
            const progressText = this.loadProgress ? `${this.loadProgress.loaded}/${this.loadProgress.total}` : "...";
            scopeText = `${theme.fg("muted", "○ Current Folder | ")}${theme.fg("accent", `Loading ${progressText}`)}`;
        }
        else if (this.scope === "current") {
            scopeText = `${theme.fg("accent", "◉ Current Folder")}${theme.fg("muted", " | ○ All")}`;
        }
        else {
            scopeText = `${theme.fg("muted", "○ Current Folder | ")}${theme.fg("accent", "◉ All")}`;
        }
        const rightText = truncateToWidth(`${scopeText}  ${nameText}  ${sortText}`, width, "");
        const availableLeft = Math.max(0, width - visibleWidth(rightText) - 1);
        const left = truncateToWidth(leftText, availableLeft, "");
        const spacing = Math.max(0, width - visibleWidth(left) - visibleWidth(rightText));
        let hintLine1;
        let hintLine2;
        if (this.confirmingDeletePath !== null) {
            const confirmHint = `Delete session? ${keyHint("tui.select.confirm", "confirm")} · ${keyHint("tui.select.cancel", "cancel")}`;
            hintLine1 = theme.fg("error", truncateToWidth(confirmHint, width, "…"));
            hintLine2 = "";
        }
        else if (this.statusMessage) {
            const color = this.statusMessage.type === "error" ? "error" : "accent";
            hintLine1 = theme.fg(color, truncateToWidth(this.statusMessage.message, width, "…"));
            hintLine2 = "";
        }
        else {
            const pathState = this.showPath ? "(on)" : "(off)";
            const sep = theme.fg("muted", " · ");
            const hint1 = keyHint("tui.input.tab", "scope") + sep + theme.fg("muted", 're:<pattern> regex · "phrase" exact');
            const hint2Parts = [
                keyHint("app.session.toggleSort", "sort"),
                keyHint("app.session.toggleNamedFilter", "named"),
                // 2026-10-13 (owner order, ported): delete/rename hints removed —
                // those arms are disabled in CortexAgent.
                keyHint("app.session.togglePath", `path ${pathState}`),
            ];
            const hint2 = hint2Parts.join(sep);
            hintLine1 = truncateToWidth(hint1, width, "…");
            hintLine2 = truncateToWidth(hint2, width, "…");
        }
        return [`${left}${" ".repeat(spacing)}${rightText}`, hintLine1, hintLine2];
    }
}
function buildSessionTree(sessions) {
    const byPath = new Map();
    for (const session of sessions) {
        const sessionPath = canonicalizePath(session.path) ?? session.path;
        byPath.set(sessionPath, { session, children: [], latestActivity: session.modified.getTime() });
    }
    const roots = [];
    for (const session of sessions) {
        const sessionPath = canonicalizePath(session.path) ?? session.path;
        const node = byPath.get(sessionPath);
        const parentPath = canonicalizePath(session.parentSessionPath);
        if (parentPath && byPath.has(parentPath)) {
            byPath.get(parentPath).children.push(node);
        }
        else {
            roots.push(node);
        }
    }
    const updateLatestActivity = (node) => {
        let latestActivity = node.session.modified.getTime();
        for (const child of node.children) {
            latestActivity = Math.max(latestActivity, updateLatestActivity(child));
        }
        node.latestActivity = latestActivity;
        return latestActivity;
    };
    for (const root of roots) {
        updateLatestActivity(root);
    }
    const sortNodes = (nodes) => {
        nodes.sort((a, b) => b.latestActivity - a.latestActivity);
        for (const node of nodes) {
            sortNodes(node.children);
        }
    };
    sortNodes(roots);
    return roots;
}
function flattenSessionTree(roots) {
    const result = [];
    const walk = (node, depth, ancestorContinues, isLast) => {
        result.push({ session: node.session, depth, isLast, ancestorContinues });
        for (let i = 0; i < node.children.length; i++) {
            const childIsLast = i === node.children.length - 1;
            const continues = depth > 0 ? !isLast : false;
            walk(node.children[i], depth + 1, [...ancestorContinues, continues], childIsLast);
        }
    };
    for (let i = 0; i < roots.length; i++) {
        walk(roots[i], 0, [], i === roots.length - 1);
    }
    return result;
}
class SessionList {
    getSelectedSessionPath() {
        const selected = this.filteredSessions[this.selectedIndex];
        return selected?.session.path;
    }
    allSessions = [];
    filteredSessions = [];
    selectedIndex = 0;
    searchInput;
    showCwd = false;
    sortMode = "threaded";
    nameFilter = "all";
    keybindings;
    showPath = false;
    confirmingDeletePath = null;
    currentSessionCanonicalPath;
    onSelect;
    onCancel;
    onExit = () => { };
    onToggleScope;
    onToggleSort;
    onToggleNameFilter;
    onTogglePath;
    onDeleteConfirmationChange;
    onDeleteSession;
    onRenameSession;
    onError;
    maxVisible = 10;
    _focused = false;
    get focused() {
        return this._focused;
    }
    set focused(value) {
        this._focused = value;
        this.searchInput.focused = value;
    }
    constructor(sessions, showCwd, sortMode, nameFilter, keybindings, currentSessionFilePath) {
        this.allSessions = sessions;
        this.filteredSessions = [];
        this.searchInput = new Input();
        this.showCwd = showCwd;
        this.sortMode = sortMode;
        this.nameFilter = nameFilter;
        this.keybindings = keybindings;
        this.currentSessionCanonicalPath = canonicalizePath(currentSessionFilePath);
        this.filterSessions("");
        this.searchInput.onSubmit = () => {
            if (this.filteredSessions[this.selectedIndex]) {
                const selected = this.filteredSessions[this.selectedIndex];
                if (this.onSelect) {
                    this.onSelect(selected.session.path);
                }
            }
        };
    }
    setSortMode(sortMode) {
        this.sortMode = sortMode;
        this.filterSessions(this.searchInput.getValue());
    }
    setNameFilter(nameFilter) {
        this.nameFilter = nameFilter;
        this.filterSessions(this.searchInput.getValue());
    }
    setSessions(sessions, showCwd) {
        this.allSessions = sessions;
        this.showCwd = showCwd;
        this.filterSessions(this.searchInput.getValue());
    }
    filterSessions(query) {
        const trimmed = query.trim();
        const nameFiltered = this.nameFilter === "all" ? this.allSessions : this.allSessions.filter((session) => hasSessionName(session));
        if (this.sortMode === "threaded" && !trimmed) {
            const roots = buildSessionTree(nameFiltered);
            this.filteredSessions = flattenSessionTree(roots);
        }
        else {
            const filtered = filterAndSortSessions(nameFiltered, query, this.sortMode, "all");
            this.filteredSessions = filtered.map((session) => ({
                session,
                depth: 0,
                isLast: true,
                ancestorContinues: [],
            }));
        }
        this.selectedIndex = Math.min(this.selectedIndex, Math.max(0, this.filteredSessions.length - 1));
    }
    setConfirmingDeletePath(path) {
        this.confirmingDeletePath = path;
        this.onDeleteConfirmationChange?.(path);
    }
    startDeleteConfirmationForSelectedSession() {
        const selected = this.filteredSessions[this.selectedIndex];
        if (!selected)
            return;
        if (this.isCurrentSessionPath(selected.session.path)) {
            this.onError?.("Cannot delete the currently active session");
            return;
        }
        this.setConfirmingDeletePath(selected.session.path);
    }
    isCurrentSessionPath(path) {
        if (!this.currentSessionCanonicalPath)
            return false;
        return (canonicalizePath(path) ?? path) === this.currentSessionCanonicalPath;
    }
    invalidate() { }
    render(width) {
        const lines = [];
        lines.push(...this.searchInput.render(width));
        lines.push("");
        if (this.filteredSessions.length === 0) {
            let emptyMessage;
            if (this.nameFilter === "named") {
                const toggleKey = keyText("app.session.toggleNamedFilter");
                if (this.showCwd) {
                    emptyMessage = `  No named sessions found. Press ${toggleKey} to show all.`;
                }
                else {
                    emptyMessage = `  No named sessions in current folder. Press ${toggleKey} to show all, or Tab to view all.`;
                }
            }
            else if (this.showCwd) {
                emptyMessage = "  No sessions found";
            }
            else {
                emptyMessage = "  No sessions in current folder. Press Tab to view all.";
            }
            lines.push(theme.fg("muted", truncateToWidth(emptyMessage, width, "…")));
            return lines;
        }
        const startIndex = Math.max(0, Math.min(this.selectedIndex - Math.floor(this.maxVisible / 2), this.filteredSessions.length - this.maxVisible));
        const endIndex = Math.min(startIndex + this.maxVisible, this.filteredSessions.length);
        for (let i = startIndex; i < endIndex; i++) {
            const node = this.filteredSessions[i];
            const session = node.session;
            const isSelected = i === this.selectedIndex;
            const isConfirmingDelete = session.path === this.confirmingDeletePath;
            const isCurrent = this.isCurrentSessionPath(session.path);
            const prefix = this.buildTreePrefix(node);
            const hasName = !!session.name;
            const displayText = session.name ?? session.firstMessage;
            const normalizedMessage = displayText.replace(/[\x00-\x1f\x7f]/g, " ").trim();
            const age = formatSessionDate(session.modified);
            const msgCount = String(session.messageCount);
            let rightPart = `${msgCount} ${age}`;
            if (this.showCwd && session.cwd) {
                rightPart = `${shortenPath(session.cwd)} ${rightPart}`;
            }
            if (this.showPath) {
                rightPart = `${shortenPath(session.path)} ${rightPart}`;
            }
            const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
            const prefixWidth = visibleWidth(prefix);
            const rightWidth = visibleWidth(rightPart) + 2;
            const availableForMsg = width - 2 - prefixWidth - rightWidth;
            const truncatedMsg = truncateToWidth(normalizedMessage, Math.max(10, availableForMsg), "…");
            let messageColor = null;
            if (isConfirmingDelete) {
                messageColor = "error";
            }
            else if (isCurrent) {
                messageColor = "accent";
            }
            else if (hasName) {
                messageColor = "warning";
            }
            let styledMsg = messageColor ? theme.fg(messageColor, truncatedMsg) : truncatedMsg;
            if (isSelected) {
                styledMsg = theme.bold(styledMsg);
            }
            const leftPart = cursor + theme.fg("dim", prefix) + styledMsg;
            const leftWidth = visibleWidth(leftPart);
            const spacing = Math.max(1, width - leftWidth - visibleWidth(rightPart));
            const styledRight = theme.fg(isConfirmingDelete ? "error" : "dim", rightPart);
            let line = leftPart + " ".repeat(spacing) + styledRight;
            if (isSelected) {
                line = theme.bg("selectedBg", line);
            }
            lines.push(truncateToWidth(line, width));
        }
        if (startIndex > 0 || endIndex < this.filteredSessions.length) {
            const scrollText = `  (${this.selectedIndex + 1}/${this.filteredSessions.length})`;
            const scrollInfo = theme.fg("muted", truncateToWidth(scrollText, width, ""));
            lines.push(scrollInfo);
        }
        return lines;
    }
    buildTreePrefix(node) {
        if (node.depth === 0) {
            return "";
        }
        const parts = node.ancestorContinues.map((continues) => (continues ? "│  " : "   "));
        const branch = node.isLast ? "└─ " : "├─ ";
        return parts.join("") + branch;
    }
    handleInput(keyData) {
        const kb = getKeybindings();
        if (this.confirmingDeletePath !== null) {
            if (kb.matches(keyData, "tui.select.confirm")) {
                const pathToDelete = this.confirmingDeletePath;
                this.setConfirmingDeletePath(null);
                void this.onDeleteSession?.(pathToDelete);
                return;
            }
            if (kb.matches(keyData, "tui.select.cancel")) {
                this.setConfirmingDeletePath(null);
                return;
            }
            return;
        }
        if (kb.matches(keyData, "tui.input.tab")) {
            if (this.onToggleScope) {
                this.onToggleScope();
            }
            return;
        }
        if (kb.matches(keyData, "app.session.toggleSort")) {
            this.onToggleSort?.();
            return;
        }
        if (this.keybindings.matches(keyData, "app.session.toggleNamedFilter")) {
            this.onToggleNameFilter?.();
            return;
        }
        if (kb.matches(keyData, "app.session.togglePath")) {
            this.showPath = !this.showPath;
            this.onTogglePath?.(this.showPath);
            return;
        }
        // 2026-10-13 (owner order, ported): delete arms removed from the session
        // picker — arm kept but dead so ctrl+d/ctrl+backspace never confirm.
        if (kb.matches(keyData, "app.session.delete")) {
            // disabled in CortexAgent
            return;
        }
        if (kb.matches(keyData, "app.session.rename")) {
            // disabled in CortexAgent
            return;
        }
        if (kb.matches(keyData, "app.session.deleteNoninvasive")) {
            if (this.searchInput.getValue().length > 0) {
                this.searchInput.handleInput(keyData);
                this.filterSessions(this.searchInput.getValue());
                return;
            }
            // disabled in CortexAgent (was: startDeleteConfirmation)
            return;
        }
        if (kb.matches(keyData, "tui.select.up")) {
            this.selectedIndex = Math.max(0, this.selectedIndex - 1);
        }
        // Down arrow
        else if (kb.matches(keyData, "tui.select.down")) {
            this.selectedIndex = Math.min(this.filteredSessions.length - 1, this.selectedIndex + 1);
        }
        // Page up - jump up by maxVisible items
        else if (kb.matches(keyData, "tui.select.pageUp")) {
            this.selectedIndex = Math.max(0, this.selectedIndex - this.maxVisible);
        }
        // Page down - jump down by maxVisible items
        else if (kb.matches(keyData, "tui.select.pageDown")) {
            this.selectedIndex = Math.min(this.filteredSessions.length - 1, this.selectedIndex + this.maxVisible);
        }
        // Enter
        else if (kb.matches(keyData, "tui.select.confirm")) {
            const selected = this.filteredSessions[this.selectedIndex];
            if (selected && this.onSelect) {
                this.onSelect(selected.session.path);
            }
        }
        // Escape - cancel
        else if (kb.matches(keyData, "tui.select.cancel")) {
            if (this.onCancel) {
                this.onCancel();
            }
        }
        // Pass everything else to search input
        else {
            this.searchInput.handleInput(keyData);
            this.filterSessions(this.searchInput.getValue());
        }
    }
}
async function deleteSessionFile(sessionPath) {
    const trashArgs = sessionPath.startsWith("-") ? ["--", sessionPath] : [sessionPath];
    const trashResult = spawnSync("trash", trashArgs, { encoding: "utf-8" });
    const getTrashErrorHint = () => {
        const parts = [];
        if (trashResult.error) {
            parts.push(trashResult.error.message);
        }
        const stderr = trashResult.stderr?.trim();
        if (stderr) {
            parts.push(stderr.split("\n")[0] ?? stderr);
        }
        if (parts.length === 0)
            return null;
        return `trash: ${parts.join(" · ").slice(0, 200)}`;
    };
    if (trashResult.status === 0 || !existsSync(sessionPath)) {
        return { ok: true, method: "trash" };
    }
    try {
        await unlink(sessionPath);
        return { ok: true, method: "unlink" };
    }
    catch (err) {
        const unlinkError = err instanceof Error ? err.message : String(err);
        const trashErrorHint = getTrashErrorHint();
        const error = trashErrorHint ? `${unlinkError} (${trashErrorHint})` : unlinkError;
        return { ok: false, method: "unlink", error };
    }
}
export class SessionSelectorComponent extends Container {
    handleInput(data) {
        if (this.mode === "rename") {
            const kb = getKeybindings();
            if (kb.matches(data, "tui.select.cancel")) {
                this.exitRenameMode();
                return;
            }
            this.renameInput.handleInput(data);
            return;
        }
        this.sessionList.handleInput(data);
    }
    canRename = true;
    sessionList;
    header;
    keybindings;
    scope = "current";
    sortMode = "threaded";
    nameFilter = "all";
    currentSessions = null;
    allSessions = null;
    currentSessionsLoader;
    allSessionsLoader;
    requestRender;
    renameSession;
    currentLoading = false;
    allLoading = false;
    allLoadSeq = 0;
    mode = "list";
    renameInput = new Input();
    renameTargetPath = null;
    _focused = false;
    get focused() {
        return this._focused;
    }
    set focused(value) {
        this._focused = value;
        this.sessionList.focused = value;
        this.renameInput.focused = value;
        if (value && this.mode === "rename") {
            this.renameInput.focused = true;
        }
    }
    buildBaseLayout(content, options) {
        this.clear();
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder((s) => theme.fg("accent", s)));
        this.addChild(new Spacer(1));
        if (options?.showHeader ?? true) {
            this.addChild(this.header);
            this.addChild(new Spacer(1));
        }
        this.addChild(content);
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder((s) => theme.fg("accent", s)));
    }
    constructor(currentSessionsLoader, allSessionsLoader, onSelect, onCancel, onExit, requestRender, options, currentSessionFilePath) {
        super();
        this.keybindings = options?.keybindings ?? KeybindingsManager.create();
        this.currentSessionsLoader = currentSessionsLoader;
        this.allSessionsLoader = allSessionsLoader;
        this.requestRender = requestRender;
        this.header = new SessionSelectorHeader(this.scope, this.sortMode, this.nameFilter, this.requestRender);
        const renameSession = options?.renameSession;
        this.renameSession = renameSession;
        this.canRename = !!renameSession;
        this.header.setShowRenameHint(options?.showRenameHint ?? this.canRename);
        this.sessionList = new SessionList([], false, this.sortMode, this.nameFilter, this.keybindings, currentSessionFilePath);
        this.buildBaseLayout(this.sessionList);
        this.renameInput.onSubmit = (value) => {
            void this.confirmRename(value);
        };
        const clearStatusMessage = () => this.header.setStatusMessage(null);
        this.sessionList.onSelect = (sessionPath) => {
            clearStatusMessage();
            onSelect(sessionPath);
        };
        this.sessionList.onCancel = () => {
            clearStatusMessage();
            onCancel();
        };
        this.sessionList.onExit = () => {
            clearStatusMessage();
            onExit();
        };
        this.sessionList.onToggleScope = () => this.toggleScope();
        this.sessionList.onToggleSort = () => this.toggleSortMode();
        this.sessionList.onToggleNameFilter = () => this.toggleNameFilter();
        this.sessionList.onRenameSession = (sessionPath) => {
            if (!renameSession)
                return;
            if (this.scope === "current" && this.currentLoading)
                return;
            if (this.scope === "all" && this.allLoading)
                return;
            const sessions = this.scope === "all" ? (this.allSessions ?? []) : (this.currentSessions ?? []);
            const session = sessions.find((s) => s.path === sessionPath);
            this.enterRenameMode(sessionPath, session?.name);
        };
        this.sessionList.onTogglePath = (showPath) => {
            this.header.setShowPath(showPath);
            this.requestRender();
        };
        this.sessionList.onDeleteConfirmationChange = (path) => {
            this.header.setConfirmingDeletePath(path);
            this.requestRender();
        };
        this.sessionList.onError = (msg) => {
            this.header.setStatusMessage({ type: "error", message: msg }, 3000);
            this.requestRender();
        };
        this.sessionList.onDeleteSession = async (sessionPath) => {
            const result = await deleteSessionFile(sessionPath);
            if (result.ok) {
                if (this.currentSessions) {
                    this.currentSessions = this.currentSessions.filter((s) => s.path !== sessionPath);
                }
                if (this.allSessions) {
                    this.allSessions = this.allSessions.filter((s) => s.path !== sessionPath);
                }
                const sessions = this.scope === "all" ? (this.allSessions ?? []) : (this.currentSessions ?? []);
                const showCwd = this.scope === "all";
                this.sessionList.setSessions(sessions, showCwd);
                const msg = result.method === "trash" ? "Session moved to trash" : "Session deleted";
                this.header.setStatusMessage({ type: "info", message: msg }, 2000);
                await this.refreshSessionsAfterMutation();
            }
            else {
                const errorMessage = result.error ?? "Unknown error";
                this.header.setStatusMessage({ type: "error", message: `Failed to delete: ${errorMessage}` }, 3000);
            }
            this.requestRender();
        };
        this.loadCurrentSessions();
    }
    loadCurrentSessions() {
        void this.loadScope("current", "initial");
    }
    enterRenameMode(sessionPath, currentName) {
        this.mode = "rename";
        this.renameTargetPath = sessionPath;
        this.renameInput.setValue(currentName ?? "");
        this.renameInput.focused = true;
        const panel = new Container();
        panel.addChild(new Text(theme.bold("Rename Session"), 1, 0));
        panel.addChild(new Spacer(1));
        panel.addChild(this.renameInput);
        panel.addChild(new Spacer(1));
        panel.addChild(new Text(theme.fg("muted", `${keyText("tui.select.confirm")} to save · ${keyText("tui.select.cancel")} to cancel`), 1, 0));
        this.buildBaseLayout(panel, { showHeader: false });
        this.requestRender();
    }
    exitRenameMode() {
        this.mode = "list";
        this.renameTargetPath = null;
        this.buildBaseLayout(this.sessionList);
        this.requestRender();
    }
    async confirmRename(value) {
        const next = value.trim();
        if (!next)
            return;
        const target = this.renameTargetPath;
        if (!target) {
            this.exitRenameMode();
            return;
        }
        const renameSession = this.renameSession;
        if (!renameSession) {
            this.exitRenameMode();
            return;
        }
        try {
            await renameSession(target, next);
            await this.refreshSessionsAfterMutation();
        }
        finally {
            this.exitRenameMode();
        }
    }
    async loadScope(scope, reason) {
        const showCwd = scope === "all";
        if (scope === "current") {
            this.currentLoading = true;
        }
        else {
            this.allLoading = true;
        }
        const seq = scope === "all" ? ++this.allLoadSeq : undefined;
        this.header.setScope(scope);
        this.header.setLoading(true);
        this.requestRender();
        const onProgress = (loaded, total) => {
            if (scope !== this.scope)
                return;
            if (seq !== undefined && seq !== this.allLoadSeq)
                return;
            this.header.setProgress(loaded, total);
            this.requestRender();
        };
        try {
            const sessions = await (scope === "current"
                ? this.currentSessionsLoader(onProgress)
                : this.allSessionsLoader(onProgress));
            if (scope === "current") {
                this.currentSessions = sessions;
                this.currentLoading = false;
            }
            else {
                this.allSessions = sessions;
                this.allLoading = false;
            }
            if (scope !== this.scope)
                return;
            if (seq !== undefined && seq !== this.allLoadSeq)
                return;
            this.header.setLoading(false);
            this.sessionList.setSessions(sessions, showCwd);
            this.requestRender();
        }
        catch (err) {
            if (scope === "current") {
                this.currentLoading = false;
            }
            else {
                this.allLoading = false;
            }
            if (scope !== this.scope)
                return;
            if (seq !== undefined && seq !== this.allLoadSeq)
                return;
            const message = err instanceof Error ? err.message : String(err);
            this.header.setLoading(false);
            this.header.setStatusMessage({ type: "error", message: `Failed to load sessions: ${message}` }, 4000);
            if (reason === "initial") {
                this.sessionList.setSessions([], showCwd);
            }
            this.requestRender();
        }
    }
    toggleSortMode() {
        this.sortMode = this.sortMode === "threaded" ? "recent" : this.sortMode === "recent" ? "relevance" : "threaded";
        this.header.setSortMode(this.sortMode);
        this.sessionList.setSortMode(this.sortMode);
        this.requestRender();
    }
    toggleNameFilter() {
        this.nameFilter = this.nameFilter === "all" ? "named" : "all";
        this.header.setNameFilter(this.nameFilter);
        this.sessionList.setNameFilter(this.nameFilter);
        this.requestRender();
    }
    async refreshSessionsAfterMutation() {
        await this.loadScope(this.scope, "refresh");
    }
    toggleScope() {
        if (this.scope === "current") {
            this.scope = "all";
            this.header.setScope(this.scope);
            if (this.allSessions !== null) {
                this.header.setLoading(false);
                this.sessionList.setSessions(this.allSessions, true);
                this.requestRender();
                return;
            }
            if (!this.allLoading) {
                void this.loadScope("all", "toggle");
            }
            return;
        }
        this.scope = "current";
        this.header.setScope(this.scope);
        this.header.setLoading(this.currentLoading);
        this.sessionList.setSessions(this.currentSessions ?? [], false);
        this.requestRender();
    }
    getSessionList() {
        return this.sessionList;
    }
}
//# sourceMappingURL=session-selector.js.map