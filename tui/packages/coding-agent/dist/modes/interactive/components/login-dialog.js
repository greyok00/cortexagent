import { Container, getKeybindings, Input, Spacer, Text } from "@cortexagent/tui";
import { openBrowser } from "../../../utils/open-browser.js";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
import { keyHint } from "./keybinding-hints.js";
export class LoginDialogComponent extends Container {
    contentContainer;
    input;
    tui;
    abortController = new AbortController();
    inputResolver;
    inputRejecter;
    onComplete;
    _focused = false;
    get focused() {
        return this._focused;
    }
    set focused(value) {
        this._focused = value;
        this.input.focused = value;
    }
    constructor(tui, providerId, onComplete, providerNameOverride, titleOverride) {
        super();
        this.tui = tui;
        this.onComplete = onComplete;
        const providerName = providerNameOverride || providerId;
        const title = titleOverride ?? `Login to ${providerName}`;
        this.addChild(new DynamicBorder());
        this.addChild(new Text(theme.fg("accent", theme.bold(title)), 1, 0));
        this.contentContainer = new Container();
        this.addChild(this.contentContainer);
        this.input = new Input();
        this.input.onSubmit = () => {
            if (this.inputResolver) {
                const value = this.input.getValue();
                this.replaceInputWithSubmittedText(value);
                this.inputResolver(value);
                this.inputResolver = undefined;
                this.inputRejecter = undefined;
            }
        };
        this.input.onEscape = () => {
            this.cancel();
        };
        this.addChild(new DynamicBorder());
    }
    get signal() {
        return this.abortController.signal;
    }
    replaceInputWithSubmittedText(value) {
        this.contentContainer.children = this.contentContainer.children.map((child) => child === this.input ? new Text(`> ${value}`, 0, 0) : child);
    }
    cancel() {
        this.abortController.abort();
        if (this.inputRejecter) {
            this.inputRejecter(new Error("Login cancelled"));
            this.inputResolver = undefined;
            this.inputRejecter = undefined;
        }
        this.onComplete(false, "Login cancelled");
    }
    showAuth(url, instructions) {
        this.contentContainer.clear();
        this.contentContainer.addChild(new Spacer(1));
        const linkedUrl = `\x1b]8;;${url}\x07${url}\x1b]8;;\x07`;
        this.contentContainer.addChild(new Text(theme.fg("accent", linkedUrl), 1, 0));
        const clickHint = process.platform === "darwin" ? "Cmd+click to open" : "Ctrl+click to open";
        const hyperlink = `\x1b]8;;${url}\x07${clickHint}\x1b]8;;\x07`;
        this.contentContainer.addChild(new Text(theme.fg("dim", hyperlink), 1, 0));
        if (instructions) {
            this.contentContainer.addChild(new Spacer(1));
            this.contentContainer.addChild(new Text(theme.fg("warning", instructions), 1, 0));
        }
        openBrowser(url);
        this.tui.requestRender();
    }
    showDeviceCode(info) {
        this.contentContainer.clear();
        this.contentContainer.addChild(new Spacer(1));
        const linkedUrl = `\x1b]8;;${info.verificationUri}\x07${info.verificationUri}\x1b]8;;\x07`;
        this.contentContainer.addChild(new Text(theme.fg("accent", linkedUrl), 1, 0));
        const clickHint = process.platform === "darwin" ? "Cmd+click to open" : "Ctrl+click to open";
        const hyperlink = `\x1b]8;;${info.verificationUri}\x07${clickHint}\x1b]8;;\x07`;
        this.contentContainer.addChild(new Text(theme.fg("dim", hyperlink), 1, 0));
        this.contentContainer.addChild(new Spacer(1));
        this.contentContainer.addChild(new Text(theme.fg("warning", `Enter code: ${info.userCode}`), 1, 0));
        this.tui.requestRender();
    }
    showManualInput(prompt) {
        this.input.setValue("");
        this.contentContainer.addChild(new Spacer(1));
        this.contentContainer.addChild(new Text(theme.fg("dim", prompt), 1, 0));
        this.contentContainer.addChild(this.input);
        this.contentContainer.addChild(new Text(`(${keyHint("tui.select.cancel", "to cancel")})`, 1, 0));
        this.tui.requestRender();
        return new Promise((resolve, reject) => {
            this.inputResolver = resolve;
            this.inputRejecter = reject;
        });
    }
    showPrompt(message, placeholder) {
        this.contentContainer.addChild(new Spacer(1));
        this.contentContainer.addChild(new Text(theme.fg("text", message), 1, 0));
        if (placeholder) {
            this.contentContainer.addChild(new Text(theme.fg("dim", `e.g., ${placeholder}`), 1, 0));
        }
        this.contentContainer.addChild(this.input);
        this.contentContainer.addChild(new Text(`(${keyHint("tui.select.cancel", "to cancel,")} ${keyHint("tui.select.confirm", "to submit")})`, 1, 0));
        this.input.setValue("");
        this.tui.requestRender();
        return new Promise((resolve, reject) => {
            this.inputResolver = resolve;
            this.inputRejecter = reject;
        });
    }
    showDetails(lines) {
        this.contentContainer.clear();
        this.contentContainer.addChild(new Spacer(1));
        for (const line of lines) {
            this.contentContainer.addChild(new Text(line, 1, 0));
        }
        this.tui.requestRender();
    }
    showInfo(message, links = [], showCloseHint = false) {
        this.contentContainer.addChild(new Spacer(1));
        this.contentContainer.addChild(new Text(theme.fg("text", message), 1, 0));
        for (const link of links) {
            const text = link.label ? `${link.label}: ${link.url}` : link.url;
            const hyperlink = `\x1b]8;;${link.url}\x07${text}\x1b]8;;\x07`;
            this.contentContainer.addChild(new Text(theme.fg("accent", hyperlink), 1, 0));
        }
        if (showCloseHint) {
            this.contentContainer.addChild(new Spacer(1));
            this.contentContainer.addChild(new Text(`(${keyHint("tui.select.cancel", "to close")})`, 1, 0));
        }
        this.tui.requestRender();
    }
    showWaiting(message) {
        this.contentContainer.addChild(new Spacer(1));
        this.contentContainer.addChild(new Text(theme.fg("dim", message), 1, 0));
        this.contentContainer.addChild(new Text(`(${keyHint("tui.select.cancel", "to cancel")})`, 1, 0));
        this.tui.requestRender();
    }
    showProgress(message) {
        this.contentContainer.addChild(new Text(theme.fg("dim", message), 1, 0));
        this.tui.requestRender();
    }
    handleInput(data) {
        const kb = getKeybindings();
        if (kb.matches(data, "tui.select.cancel")) {
            this.cancel();
            return;
        }
        this.input.handleInput(data);
    }
}
//# sourceMappingURL=login-dialog.js.map