export interface PromiseResolvers<T> {
    promise: Promise<T>;
    resolve(value: T | PromiseLike<T>): void;
    reject(reason?: unknown): void;
}
export declare function createPromiseResolvers<T>(): PromiseResolvers<T>;
//# sourceMappingURL=promise.d.ts.map