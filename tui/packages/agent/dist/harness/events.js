export class HarnessEventBus {
    listeners = new Map();
    watchListeners = new Set();
    on(type, listener) {
        const listeners = this.listeners.get(type) ?? new Set();
        this.listeners.set(type, listeners);
        const receive = (event) => {
            if (event.type === type)
                return listener(event);
        };
        listeners.add(receive);
        return () => {
            listeners.delete(receive);
            if (listeners.size === 0)
                this.listeners.delete(type);
        };
    }
    emit(event) {
        for (const listener of this.listeners.get(event.type) ?? [])
            void listener(event);
        for (const listener of this.watchListeners)
            listener(event);
    }
    watch(captureSnapshot) {
        let listener;
        let buffered = [];
        const receive = (event) => {
            if (listener)
                void listener(event);
            else
                buffered.push(event);
        };
        this.watchListeners.add(receive);
        const snapshot = captureSnapshot();
        return {
            snapshot,
            start: (nextListener) => {
                while (buffered.length > 0) {
                    const pending = buffered;
                    buffered = [];
                    for (const event of pending)
                        void nextListener(event);
                }
                listener = nextListener;
            },
            unsubscribe: () => {
                this.watchListeners.delete(receive);
                buffered = [];
            },
        };
    }
}
//# sourceMappingURL=events.js.map