import { Container, SelectList } from "@cortexagent/tui";
import { getAvailableThemes, getSelectListTheme } from "../theme/theme.js";
import { DynamicBorder } from "./dynamic-border.js";
const THEME_SELECT_LIST_LAYOUT = {
    minPrimaryColumnWidth: 12,
    maxPrimaryColumnWidth: 32,
};
export class ThemeSelectorComponent extends Container {
    selectList;
    onPreview;
    constructor(currentTheme, onSelect, onCancel, onPreview) {
        super();
        this.onPreview = onPreview;
        const themes = getAvailableThemes();
        const themeItems = themes.map((name) => ({
            value: name,
            label: name,
            description: name === currentTheme ? "(current)" : undefined,
        }));
        this.addChild(new DynamicBorder());
        this.selectList = new SelectList(themeItems, 10, getSelectListTheme(), THEME_SELECT_LIST_LAYOUT);
        const currentIndex = themes.indexOf(currentTheme);
        if (currentIndex !== -1) {
            this.selectList.setSelectedIndex(currentIndex);
        }
        this.selectList.onSelect = (item) => {
            onSelect(item.value);
        };
        this.selectList.onCancel = () => {
            onCancel();
        };
        this.selectList.onSelectionChange = (item) => {
            this.onPreview(item.value);
        };
        this.addChild(this.selectList);
        this.addChild(new DynamicBorder());
    }
    getSelectList() {
        return this.selectList;
    }
}
//# sourceMappingURL=theme-selector.js.map