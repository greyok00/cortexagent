export interface RunStartEvent {
    type: "run_start";
    lane: string;
    runId: string;
}
export interface RunEndEvent {
    type: "run_end";
    lane: string;
    runId: string;
    outcome: "completed" | "aborted" | "failed";
    leafId: string;
}
export type HarnessEvent = RunStartEvent | RunEndEvent;
export type HarnessEventType = HarnessEvent["type"];
export type HarnessEventOfType<TType extends HarnessEventType> = Extract<HarnessEvent, {
    type: TType;
}>;
export type HarnessEventListener<TEvent extends HarnessEvent = HarnessEvent> = (event: TEvent) => void | Promise<void>;
export interface Events {
    on<TType extends HarnessEventType>(type: TType, listener: HarnessEventListener<HarnessEventOfType<TType>>): () => void;
}
export interface WatchHandle<TSnapshot> {
    snapshot: TSnapshot;
    start(listener: HarnessEventListener): void;
    unsubscribe(): void;
}
export declare class HarnessEventBus implements Events {
    private readonly listeners;
    private readonly watchListeners;
    on<TType extends HarnessEventType>(type: TType, listener: HarnessEventListener<HarnessEventOfType<TType>>): () => void;
    emit(event: HarnessEvent): void;
    watch<TSnapshot>(captureSnapshot: () => TSnapshot): WatchHandle<TSnapshot>;
}
//# sourceMappingURL=events.d.ts.map