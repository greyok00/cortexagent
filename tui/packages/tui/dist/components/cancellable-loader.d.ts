import { Loader } from "./loader.ts";
export declare class CancellableLoader extends Loader {
    private abortController;
    onAbort?: () => void;
    get signal(): AbortSignal;
    get aborted(): boolean;
    handleInput(data: string): void;
    dispose(): void;
}
//# sourceMappingURL=cancellable-loader.d.ts.map