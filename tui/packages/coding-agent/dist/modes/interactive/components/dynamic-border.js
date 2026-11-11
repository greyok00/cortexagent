import { theme } from "../theme/theme.js";
export class DynamicBorder {
    color;
    constructor(color = (str) => theme.fg("border", str)) {
        this.color = color;
    }
    invalidate() {
        // No cached state to invalidate currently
    }
    render(width) {
        return [this.color("─".repeat(Math.max(1, width)))];
    }
}
//# sourceMappingURL=dynamic-border.js.map