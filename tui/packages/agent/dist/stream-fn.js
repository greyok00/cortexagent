let defaultStreamFn;
export function setDefaultStreamFn(streamFn) {
    defaultStreamFn = streamFn;
}
export function getDefaultStreamFn() {
    if (!defaultStreamFn) {
        throw new Error("No default stream function configured. Pass streamFn explicitly or call setDefaultStreamFn().");
    }
    return defaultStreamFn;
}
//# sourceMappingURL=stream-fn.js.map