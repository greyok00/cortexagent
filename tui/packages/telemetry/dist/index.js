export { NOOP_TELEMETRY_CONTEXT } from "./noop.js";
export function defineTelemetrySchema(schema) {
    return schema;
}
function bindTypedSpanStarter(telemetryContext) {
    const startSpan = (name, attributes, callback) => telemetryContext.startSpan({ name, attributes }, (span) => callback(span, bindTypedSpanStarter(span)));
    return startSpan;
}
export function createTypedSpanStarter(telemetryContext, _schemas) {
    return bindTypedSpanStarter(telemetryContext);
}
export { InMemoryTelemetryContext } from "./memory.js";
//# sourceMappingURL=index.js.map