import { truncateToWidth, visibleWidth } from "../utils.js";
export class TruncatedText {
    text;
    paddingX;
    paddingY;
    constructor(text, paddingX = 0, paddingY = 0) {
        this.text = text;
        this.paddingX = paddingX;
        this.paddingY = paddingY;
    }
    invalidate() {
        // No cached state to invalidate currently
    }
    render(width) {
        const result = [];
        const emptyLine = " ".repeat(width);
        for (let i = 0; i < this.paddingY; i++) {
            result.push(emptyLine);
        }
        const availableWidth = Math.max(1, width - this.paddingX * 2);
        let singleLineText = this.text;
        const newlineIndex = this.text.indexOf("\n");
        if (newlineIndex !== -1) {
            singleLineText = this.text.substring(0, newlineIndex);
        }
        const displayText = truncateToWidth(singleLineText, availableWidth);
        const leftPadding = " ".repeat(this.paddingX);
        const rightPadding = " ".repeat(this.paddingX);
        const lineWithPadding = leftPadding + displayText + rightPadding;
        const lineVisibleWidth = visibleWidth(lineWithPadding);
        const paddingNeeded = Math.max(0, width - lineVisibleWidth);
        const finalLine = lineWithPadding + " ".repeat(paddingNeeded);
        result.push(finalLine);
        for (let i = 0; i < this.paddingY; i++) {
            result.push(emptyLine);
        }
        return result;
    }
}
//# sourceMappingURL=truncated-text.js.map