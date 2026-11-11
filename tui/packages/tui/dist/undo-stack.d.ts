export declare class UndoStack<S> {
    private stack;
    push(state: S): void;
    pop(): S | undefined;
    clear(): void;
    get length(): number;
}
//# sourceMappingURL=undo-stack.d.ts.map