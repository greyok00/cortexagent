import { Container, getKeybindings, Spacer, Text, truncateToWidth } from "@cortexagent/tui";
import { theme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
class UserMessageList {
    messages = [];
    selectedIndex = 0;
    onSelect;
    onCancel;
    maxVisible = 10;
    constructor(messages, initialSelectedId) {
        this.messages = messages;
        const initialIndex = initialSelectedId ? messages.findIndex((message) => message.id === initialSelectedId) : -1;
        this.selectedIndex = initialIndex >= 0 ? initialIndex : Math.max(0, messages.length - 1);
    }
    invalidate() {
        // No cached state to invalidate currently
    }
    render(width) {
        const lines = [];
        if (this.messages.length === 0) {
            lines.push(theme.fg("muted", "  No user messages found"));
            return lines;
        }
        const startIndex = Math.max(0, Math.min(this.selectedIndex - Math.floor(this.maxVisible / 2), this.messages.length - this.maxVisible));
        const endIndex = Math.min(startIndex + this.maxVisible, this.messages.length);
        for (let i = startIndex; i < endIndex; i++) {
            const message = this.messages[i];
            const isSelected = i === this.selectedIndex;
            const normalizedMessage = message.text.replace(/\n/g, " ").trim();
            const cursor = isSelected ? theme.fg("accent", "› ") : "  ";
            const maxMsgWidth = width - 2;
            const truncatedMsg = truncateToWidth(normalizedMessage, maxMsgWidth);
            const messageLine = cursor + (isSelected ? theme.bold(truncatedMsg) : truncatedMsg);
            lines.push(messageLine);
            const position = i + 1;
            const metadata = `  Message ${position} of ${this.messages.length}`;
            const metadataLine = theme.fg("muted", metadata);
            lines.push(metadataLine);
            lines.push("");
        }
        if (startIndex > 0 || endIndex < this.messages.length) {
            const scrollInfo = theme.fg("muted", `  (${this.selectedIndex + 1}/${this.messages.length})`);
            lines.push(scrollInfo);
        }
        return lines;
    }
    handleInput(keyData) {
        const kb = getKeybindings();
        if (kb.matches(keyData, "tui.select.up")) {
            this.selectedIndex = this.selectedIndex === 0 ? this.messages.length - 1 : this.selectedIndex - 1;
        }
        // Down arrow - go to next (newer) message, wrap to top when at bottom
        else if (kb.matches(keyData, "tui.select.down")) {
            this.selectedIndex = this.selectedIndex === this.messages.length - 1 ? 0 : this.selectedIndex + 1;
        }
        // Enter - select message and branch
        else if (kb.matches(keyData, "tui.select.confirm")) {
            const selected = this.messages[this.selectedIndex];
            if (selected && this.onSelect) {
                this.onSelect(selected.id);
            }
        }
        // Escape - cancel
        else if (kb.matches(keyData, "tui.select.cancel")) {
            if (this.onCancel) {
                this.onCancel();
            }
        }
    }
}
export class UserMessageSelectorComponent extends Container {
    messageList;
    constructor(messages, onSelect, onCancel, initialSelectedId) {
        super();
        this.addChild(new Spacer(1));
        this.addChild(new Text(theme.bold("Fork from Message"), 1, 0));
        this.addChild(new Text(theme.fg("muted", "Select a user message to copy the active path up to that point into a new session"), 1, 0));
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder());
        this.addChild(new Spacer(1));
        this.messageList = new UserMessageList(messages, initialSelectedId);
        this.messageList.onSelect = onSelect;
        this.messageList.onCancel = onCancel;
        this.addChild(this.messageList);
        this.addChild(new Spacer(1));
        this.addChild(new DynamicBorder());
        if (messages.length === 0) {
            setTimeout(() => onCancel(), 100);
        }
    }
    getMessageList() {
        return this.messageList;
    }
}
//# sourceMappingURL=user-message-selector.js.map