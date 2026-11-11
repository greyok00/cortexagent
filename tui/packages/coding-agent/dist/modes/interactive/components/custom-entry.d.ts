import { Container } from "@cortexagent/tui";
import type { EntryRenderer } from "../../../core/extensions/types.ts";
import type { CustomEntry } from "../../../core/session-manager.ts";
export declare class CustomEntryComponent extends Container {
    private entry;
    private renderer;
    private customComponent?;
    private _expanded;
    constructor(entry: CustomEntry<unknown>, renderer: EntryRenderer);
    hasContent(): boolean;
    setExpanded(expanded: boolean): void;
    invalidate(): void;
    private rebuild;
}
//# sourceMappingURL=custom-entry.d.ts.map