export function isTerminalConnection(state) {
    return state.disconnected || state.stage === "closing" || state.stage === "closed";
}
//# sourceMappingURL=connection.js.map