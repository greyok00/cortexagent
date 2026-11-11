import type { AutocompleteProvider } from "../autocomplete.ts";
import { type Component, type Focusable, type TUI } from "../tui.ts";
import { type SelectListTheme } from "./select-list.ts";
export interface TextChunk {
    text: string;
    startIndex: number;
    endIndex: number;
}
export declare function wordWrapLine(line: string, maxWidth: number, preSegmented?: Intl.SegmentData[]): TextChunk[];
export interface EditorTheme {
    borderColor: (str: string) => string;
    selectList: SelectListTheme;
}
export interface EditorOptions {
    paddingX?: number;
    autocompleteMaxVisible?: number;
}
export declare class Editor implements Component, Focusable {
    private state;
    focused: boolean;
    protected tui: TUI;
    private theme;
    private paddingX;
    private lastWidth;
    private scrollOffset;
    borderColor: (str: string) => string;
    private autocompleteProvider?;
    private autocompleteTriggerCharacters;
    private autocompleteTriggerPattern;
    private autocompleteDebouncePattern;
    private autocompleteList?;
    private autocompleteState;
    private autocompletePrefix;
    private autocompleteMaxVisible;
    private autocompleteAbort?;
    private autocompleteDebounceTimer?;
    private autocompleteRequestTask;
    private autocompleteStartToken;
    private autocompleteRequestId;
    private pastes;
    private pasteCounter;
    private pasteBuffer;
    private isInPaste;
    private history;
    private historyIndex;
    private historyDraft;
    private killRing;
    private lastAction;
    private jumpMode;
    private preferredVisualCol;
    private snappedFromCursorCol;
    private undoStack;
    onSubmit?: (text: string) => void;
    onChange?: (text: string) => void;
    disableSubmit: boolean;
    constructor(tui: TUI, theme: EditorTheme, options?: EditorOptions);
    private validPasteIds;
    private segment;
    getPaddingX(): number;
    setPaddingX(padding: number): void;
    getAutocompleteMaxVisible(): number;
    setAutocompleteMaxVisible(maxVisible: number): void;
    setAutocompleteProvider(provider: AutocompleteProvider): void;
    addToHistory(text: string): void;
    private isEditorEmpty;
    private isOnFirstVisualLine;
    private isOnLastVisualLine;
    private navigateHistory;
    private exitHistoryBrowsing;
    private setTextInternal;
    invalidate(): void;
    render(width: number): string[];
    /**
     * Append the sub-agent roster directly beneath the prompt input box. Only
     * currently ACTIVE sub-agents (those with a running/queued task in the
     * scheduler events log) are shown. Two lines per card so the user can see
     * what's actually spawning. When nothing is running, the section is empty
     * (no static roster noise). User feedback 2026-08-20: "all you did was
     * just add a hard list. That is not what I'm talking about."
     */
    private appendSubAgentCards;
    handleInput(data: string): void;
    private layoutText;
    getText(): string;
    private expandPasteMarkers;
    getExpandedText(): string;
    getLines(): string[];
    getCursor(): {
        line: number;
        col: number;
    };
    setText(text: string): void;
    insertTextAtCursor(text: string): void;
    private normalizeText;
    private insertTextAtCursorInternal;
    private insertCharacter;
    private handlePaste;
    private addNewLine;
    private shouldSubmitOnBackslashEnter;
    private submitValue;
    private handleBackspace;
    private setCursorCol;
    private moveToVisualLine;
    private computeVerticalMoveColumn;
    private moveToLineStart;
    private moveToLineEnd;
    private deleteToStartOfLine;
    private deleteToEndOfLine;
    private deleteWordBackwards;
    private deleteWordForward;
    private handleForwardDelete;
    private buildVisualLineMap;
    private findVisualLineAt;
    private findCurrentVisualLine;
    private moveCursor;
    private pageScroll;
    private moveWordBackwards;
    private yank;
    private yankPop;
    private insertYankedText;
    private deleteYankedText;
    private pushUndoSnapshot;
    private undo;
    private jumpToChar;
    private moveWordForwards;
    private isSlashMenuAllowed;
    private isAtStartOfMessage;
    private isInSlashCommandContext;
    private getBestAutocompleteMatchIndex;
    private createAutocompleteList;
    private tryTriggerAutocomplete;
    private handleTabCompletion;
    private handleSlashCommandCompletion;
    private forceFileAutocomplete;
    private requestAutocomplete;
    private startAutocompleteRequest;
    private setAutocompleteTriggerCharacters;
    private getAutocompleteDebounceMs;
    private runAutocompleteRequest;
    private isAutocompleteRequestCurrent;
    private applyAutocompleteSuggestions;
    private cancelAutocompleteRequest;
    private clearAutocompleteUi;
    private cancelAutocomplete;
    isShowingAutocomplete(): boolean;
    private updateAutocomplete;
}
//# sourceMappingURL=editor.d.ts.map