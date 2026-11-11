import type { Component } from "../tui.ts";
export interface SettingItem {
    id: string;
    label: string;
    description?: string;
    currentValue: string;
    values?: string[];
    submenu?: (currentValue: string, done: (selectedValue?: string) => void) => Component;
}
export interface SettingsListTheme {
    label: (text: string, selected: boolean) => string;
    value: (text: string, selected: boolean) => string;
    description: (text: string) => string;
    cursor: string;
    hint: (text: string) => string;
}
export interface SettingsListOptions {
    enableSearch?: boolean;
}
export declare class SettingsList implements Component {
    private items;
    private filteredItems;
    private theme;
    private selectedIndex;
    private maxVisible;
    private onChange;
    private onCancel;
    private searchInput?;
    private searchEnabled;
    private submenuComponent;
    private submenuItemIndex;
    constructor(items: SettingItem[], maxVisible: number, theme: SettingsListTheme, onChange: (id: string, newValue: string) => void, onCancel: () => void, options?: SettingsListOptions);
    updateValue(id: string, newValue: string): void;
    invalidate(): void;
    render(width: number): string[];
    private renderMainList;
    handleInput(data: string): void;
    private activateItem;
    private closeSubmenu;
    private applyFilter;
    private addHintLine;
}
//# sourceMappingURL=settings-list.d.ts.map