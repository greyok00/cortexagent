import type { Model } from "@cortexagent/ai";
import { Container, type Focusable, Input } from "@cortexagent/tui";
export interface ModelsConfig {
    allModels: Model<any>[];
    enabledModelIds: string[] | null;
    refreshStatus?: string;
}
export interface ModelsCallbacks {
    onChange: (enabledModelIds: string[] | null) => void | Promise<void>;
    onPersist: (enabledModelIds: string[] | null) => void | Promise<void>;
    onCancel: () => void;
}
export declare class ScopedModelsSelectorComponent extends Container implements Focusable {
    private modelsById;
    private allIds;
    private enabledIds;
    private filteredItems;
    private selectedIndex;
    private searchInput;
    private _focused;
    get focused(): boolean;
    set focused(value: boolean);
    private listContainer;
    private footerText;
    private callbacks;
    private maxVisible;
    private isDirty;
    private refreshStatusText?;
    constructor(config: ModelsConfig, callbacks: ModelsCallbacks);
    updateModels(models: readonly Model<any>[], enabledModelIds?: string[] | null): void;
    setRefreshStatus(message: string, kind: "muted" | "success" | "warning"): void;
    private buildItems;
    private getFooterText;
    private refresh;
    private notifyChange;
    private updateList;
    handleInput(data: string): void;
    getSearchInput(): Input;
}
//# sourceMappingURL=scoped-models-selector.d.ts.map