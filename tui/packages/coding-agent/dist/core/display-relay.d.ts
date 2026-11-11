/** Register the TUI hook used after dropped frames (full repaint). */
export declare function setDisplayRelayRecoveryHandler(handler: (() => void) | undefined): void;
export declare function isDisplayRelayActive(): boolean;
/**
 * Route terminal output through relay processes so a grabbed X server (or any
 * terminal that stops reading) can never block this process's event loop.
 */
export declare function installDisplayRelay(): void;
//# sourceMappingURL=display-relay.d.ts.map