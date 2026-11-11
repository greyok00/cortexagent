import type { ExactTelemetryAttributes, SchemaTelemetrySpan, TelemetryContext, TelemetrySchemaSpanEndAttributes, TelemetrySchemaSpanEventAttributes, TelemetrySchemaSpanEventName, TelemetrySchemaSpanName, TelemetrySchemaSpanStartAttributes, TelemetrySchemaSpanUnion } from "@cortexagent/telemetry";
export type { AttributeValue, ExactTelemetryAttributes, SchemaTelemetrySpan, SpanAttributes, SpanOptions, SpanStatus, TelemetryAttributeDefinition, TelemetryAttributeMetadata, TelemetryAttributeType, TelemetryContext, TelemetryEventAttributeDefinition, TelemetryEventDefinition, TelemetryParentDefinition, TelemetrySchemaDefinition, TelemetrySchemaSpanEndAttributes, TelemetrySchemaSpanEventAttributes, TelemetrySchemaSpanEventName, TelemetrySchemaSpanName, TelemetrySchemaSpanStartAttributes, TelemetrySchemaSpanUnion, TelemetrySpan, TelemetrySpanDefinition, TelemetryStartAttributeDefinition, TypedSpanStarter, } from "@cortexagent/telemetry";
export declare const AI_TELEMETRY_SCHEMA: {
    readonly version: 1;
    readonly spans: {
        readonly "cortex.ai.request": {
            readonly description: "One logical request to an AI provider";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.ai.operation": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["stream", "fetch_deferred", "cancel_deferred", "generate_images"];
                    readonly description: "Logical provider operation";
                };
                readonly "cortex.ai.provider": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Selected provider id";
                };
                readonly "cortex.ai.model": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Requested model id";
                };
                readonly "cortex.ai.api": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Provider API id";
                };
                readonly "cortex.ai.streaming": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this operation returns a stream";
                };
                readonly "cortex.ai.deferred": {
                    readonly type: "boolean";
                    readonly required: false;
                    readonly description: "Whether the operation requests or participates in deferred execution";
                };
            };
            readonly endAttributes: {
                readonly "cortex.ai.response.model": {
                    readonly type: "string";
                    readonly description: "Concrete response model";
                };
                readonly "cortex.ai.response.id": {
                    readonly type: "string";
                    readonly cardinality: "high";
                    readonly description: "Provider response id";
                };
                readonly "cortex.ai.response.stop_reason": {
                    readonly type: "string";
                    readonly values: readonly ["stop", "length", "tool_use", "error", "aborted", "deferred"];
                    readonly description: "Normalized terminal response reason";
                };
                readonly "cortex.ai.http.status_code": {
                    readonly type: "number";
                    readonly description: "Final HTTP status";
                };
                readonly "cortex.ai.usage.input_tokens": {
                    readonly type: "number";
                    readonly description: "Reported input tokens";
                };
                readonly "cortex.ai.usage.output_tokens": {
                    readonly type: "number";
                    readonly description: "Reported output tokens";
                };
                readonly "cortex.ai.usage.cache_read_tokens": {
                    readonly type: "number";
                    readonly description: "Reported cache-read tokens";
                };
                readonly "cortex.ai.usage.cache_write_tokens": {
                    readonly type: "number";
                    readonly description: "Reported cache-write tokens";
                };
                readonly "cortex.ai.usage.reasoning_tokens": {
                    readonly type: "number";
                    readonly description: "Reported reasoning tokens";
                };
                readonly "cortex.ai.usage.total_tokens": {
                    readonly type: "number";
                    readonly description: "Reported total tokens";
                };
                readonly "cortex.ai.usage.cost": {
                    readonly type: "number";
                    readonly description: "Reported total cost";
                };
                readonly "cortex.ai.stream.chunk_count": {
                    readonly type: "number";
                    readonly description: "Streamed update chunk count";
                };
                readonly "cortex.ai.stream.time_to_first_chunk_ms": {
                    readonly type: "number";
                    readonly description: "Elapsed milliseconds to first update chunk";
                };
                readonly "cortex.ai.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Provider or transport error class";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The operation throws or returns an error result";
            };
        };
    };
};
export type AiSpanName = TelemetrySchemaSpanName<typeof AI_TELEMETRY_SCHEMA>;
export type AiSpanStartAttributes<Name extends AiSpanName> = TelemetrySchemaSpanStartAttributes<typeof AI_TELEMETRY_SCHEMA, Name>;
export type AiSpanEndAttributes<Name extends AiSpanName> = TelemetrySchemaSpanEndAttributes<typeof AI_TELEMETRY_SCHEMA, Name>;
export type AiSpanAttributes<Name extends AiSpanName> = AiSpanStartAttributes<Name> & AiSpanEndAttributes<Name>;
export type AiSpanEventName<Name extends AiSpanName> = TelemetrySchemaSpanEventName<typeof AI_TELEMETRY_SCHEMA, Name>;
export type AiSpanEventAttributes<Name extends AiSpanName, EventName extends AiSpanEventName<Name>> = TelemetrySchemaSpanEventAttributes<typeof AI_TELEMETRY_SCHEMA, Name, EventName>;
export type AiTelemetrySpan<Name extends AiSpanName> = SchemaTelemetrySpan<typeof AI_TELEMETRY_SCHEMA, Name>;
export type AiSpan = TelemetrySchemaSpanUnion<typeof AI_TELEMETRY_SCHEMA>;
export declare function startAiSpan<Name extends AiSpanName, const Attributes extends AiSpanStartAttributes<Name>, Result>(telemetryContext: TelemetryContext, name: Name, attributes: ExactTelemetryAttributes<AiSpanStartAttributes<Name>, Attributes>, callback: (span: AiTelemetrySpan<Name>) => Result | Promise<Result>): Promise<Result>;
export declare const HARNESS_TELEMETRY_SCHEMA: {
    readonly version: 1;
    readonly spans: {
        readonly "cortex.harness.run": {
            readonly description: "One admitted in-process run invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["run"];
                    readonly description: "Run operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "aborted", "failed", "suspended"];
                    readonly description: "Run invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The run fails or throws";
            };
        };
        readonly "cortex.harness.compaction": {
            readonly description: "One admitted in-process manual compaction invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["compaction"];
                    readonly description: "Compaction operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "declined", "aborted", "failed"];
                    readonly description: "Compaction invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The compaction fails or throws";
            };
        };
        readonly "cortex.harness.navigation": {
            readonly description: "One admitted in-process navigation invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["navigation"];
                    readonly description: "Navigation operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "declined", "aborted", "failed"];
                    readonly description: "Navigation invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The navigation fails or throws";
            };
        };
        readonly "cortex.harness.checkpoint": {
            readonly description: "One run checkpoint";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.checkpoint.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["normal", "failure_drain", "abort_reconcile"];
                    readonly description: "Checkpoint purpose";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Checkpoint work throws";
            };
        };
        readonly "cortex.harness.turn": {
            readonly description: "One assistant response and its tool batch";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.turn.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Invocation-local turn id";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Turn work throws";
            };
        };
        readonly "cortex.harness.step": {
            readonly description: "One durable retry attempt";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.turn", "cortex.harness.checkpoint", "cortex.harness.compaction", "cortex.harness.navigation"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.step.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["assistant", "compaction", "branch_summary"];
                    readonly description: "Retryable step kind";
                };
                readonly "cortex.step.attempt": {
                    readonly type: "number";
                    readonly required: true;
                    readonly description: "One-based durable attempt number";
                };
                readonly "cortex.compaction.reason": {
                    readonly type: "string";
                    readonly required: false;
                    readonly values: readonly ["manual", "threshold", "overflow"];
                    readonly description: "Compaction trigger";
                };
            };
            readonly endAttributes: {
                readonly "cortex.step.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["succeeded", "retry", "failed", "aborted", "deferred", "overflow"];
                    readonly description: "Attempt outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The attempt retries, fails, or throws";
            };
        };
        readonly "cortex.harness.tool": {
            readonly description: "One raw phase-2 tool execution";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.turn", "cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.turn.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Invocation-local live turn id";
                };
                readonly "cortex.tool.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Tool name";
                };
                readonly "cortex.tool.call_id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Tool call id";
                };
                readonly "cortex.tool.replay": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["never", "safe"];
                    readonly description: "Declared replay policy";
                };
                readonly "cortex.tool.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this is recovery execution";
                };
            };
            readonly endAttributes: {
                readonly "cortex.tool.is_error": {
                    readonly type: "boolean";
                    readonly description: "Whether raw phase-2 execution returned an error";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Raw phase-2 execution returns an error";
            };
        };
        readonly "cortex.harness.hook": {
            readonly description: "One registered hook handler invocation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id when accepted";
                };
                readonly "cortex.hook.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["before_run", "before_resume", "before_run_end", "transform_context", "before_request", "before_payload", "after_response", "before_tool", "after_tool", "before_compaction", "before_navigation"];
                    readonly description: "Hook name";
                };
                readonly "cortex.hook.registration_id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly description: "Stable hook registration id";
                };
            };
            readonly endAttributes: {
                readonly "cortex.hook.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "skipped", "blocked", "failed"];
                    readonly description: "Handler outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The handler throws";
            };
        };
        readonly "cortex.harness.sleep": {
            readonly description: "One retry delay";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.step", "cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.sleep.delay_ms": {
                    readonly type: "number";
                    readonly required: true;
                    readonly description: "Requested delay in milliseconds";
                };
            };
            readonly endAttributes: {
                readonly "cortex.sleep.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["elapsed", "aborted"];
                    readonly description: "Delay outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Sleep work throws";
            };
        };
        readonly "cortex.harness.event_handler": {
            readonly description: "One passive event listener invocation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.event.type": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "low";
                    readonly values: readonly ["run_start", "run_resume", "run_suspend", "run_abort", "run_end", "fault", "handler_error", "turn_start", "turn_end", "retry_scheduled", "retry_start", "retry_end", "message_start", "message_update", "message_end", "tool_start", "tool_update", "tool_end", "entry_added", "write_pending", "queue_update", "fact_update", "config_update", "compaction_start", "compaction_end", "navigation_start", "navigation_end", "lane_created", "usage"];
                    readonly description: "Delivered harness event type";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Lane name for lane-scoped events";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The listener throws";
            };
        };
        readonly "cortex.session.write": {
            readonly description: "One committed session mutation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id when accepted";
                };
                readonly "cortex.session.mutation": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["entry", "record", "lane", "fact"];
                    readonly description: "Session mutation kind";
                };
                readonly "cortex.session.item_type": {
                    readonly type: "string";
                    readonly required: false;
                    readonly description: "Entry, record, lane, or fact subtype";
                };
            };
            readonly endAttributes: {
                readonly "cortex.session.seq": {
                    readonly type: "number";
                    readonly description: "Committed session sequence when exposed";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Storage rejects the mutation";
            };
        };
    };
};
export declare const AGENT_TELEMETRY_SCHEMAS: readonly [{
    readonly version: 1;
    readonly spans: {
        readonly "cortex.ai.request": {
            readonly description: "One logical request to an AI provider";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.ai.operation": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["stream", "fetch_deferred", "cancel_deferred", "generate_images"];
                    readonly description: "Logical provider operation";
                };
                readonly "cortex.ai.provider": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Selected provider id";
                };
                readonly "cortex.ai.model": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Requested model id";
                };
                readonly "cortex.ai.api": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Provider API id";
                };
                readonly "cortex.ai.streaming": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this operation returns a stream";
                };
                readonly "cortex.ai.deferred": {
                    readonly type: "boolean";
                    readonly required: false;
                    readonly description: "Whether the operation requests or participates in deferred execution";
                };
            };
            readonly endAttributes: {
                readonly "cortex.ai.response.model": {
                    readonly type: "string";
                    readonly description: "Concrete response model";
                };
                readonly "cortex.ai.response.id": {
                    readonly type: "string";
                    readonly cardinality: "high";
                    readonly description: "Provider response id";
                };
                readonly "cortex.ai.response.stop_reason": {
                    readonly type: "string";
                    readonly values: readonly ["stop", "length", "tool_use", "error", "aborted", "deferred"];
                    readonly description: "Normalized terminal response reason";
                };
                readonly "cortex.ai.http.status_code": {
                    readonly type: "number";
                    readonly description: "Final HTTP status";
                };
                readonly "cortex.ai.usage.input_tokens": {
                    readonly type: "number";
                    readonly description: "Reported input tokens";
                };
                readonly "cortex.ai.usage.output_tokens": {
                    readonly type: "number";
                    readonly description: "Reported output tokens";
                };
                readonly "cortex.ai.usage.cache_read_tokens": {
                    readonly type: "number";
                    readonly description: "Reported cache-read tokens";
                };
                readonly "cortex.ai.usage.cache_write_tokens": {
                    readonly type: "number";
                    readonly description: "Reported cache-write tokens";
                };
                readonly "cortex.ai.usage.reasoning_tokens": {
                    readonly type: "number";
                    readonly description: "Reported reasoning tokens";
                };
                readonly "cortex.ai.usage.total_tokens": {
                    readonly type: "number";
                    readonly description: "Reported total tokens";
                };
                readonly "cortex.ai.usage.cost": {
                    readonly type: "number";
                    readonly description: "Reported total cost";
                };
                readonly "cortex.ai.stream.chunk_count": {
                    readonly type: "number";
                    readonly description: "Streamed update chunk count";
                };
                readonly "cortex.ai.stream.time_to_first_chunk_ms": {
                    readonly type: "number";
                    readonly description: "Elapsed milliseconds to first update chunk";
                };
                readonly "cortex.ai.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Provider or transport error class";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The operation throws or returns an error result";
            };
        };
    };
}, {
    readonly version: 1;
    readonly spans: {
        readonly "cortex.harness.run": {
            readonly description: "One admitted in-process run invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["run"];
                    readonly description: "Run operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "aborted", "failed", "suspended"];
                    readonly description: "Run invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The run fails or throws";
            };
        };
        readonly "cortex.harness.compaction": {
            readonly description: "One admitted in-process manual compaction invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["compaction"];
                    readonly description: "Compaction operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "declined", "aborted", "failed"];
                    readonly description: "Compaction invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The compaction fails or throws";
            };
        };
        readonly "cortex.harness.navigation": {
            readonly description: "One admitted in-process navigation invocation";
            readonly parents: {
                readonly kind: "root_or_external";
            };
            readonly startAttributes: {
                readonly "cortex.session.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Session id";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.operation.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this invocation resumes durable work";
                };
                readonly "cortex.operation.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["navigation"];
                    readonly description: "Navigation operation kind";
                };
            };
            readonly endAttributes: {
                readonly "cortex.error.code": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Stable operation error code";
                };
                readonly "cortex.error.type": {
                    readonly type: "string";
                    readonly cardinality: "low";
                    readonly description: "Low-cardinality operation error class";
                };
                readonly "cortex.operation.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "declined", "aborted", "failed"];
                    readonly description: "Navigation invocation outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The navigation fails or throws";
            };
        };
        readonly "cortex.harness.checkpoint": {
            readonly description: "One run checkpoint";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.checkpoint.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["normal", "failure_drain", "abort_reconcile"];
                    readonly description: "Checkpoint purpose";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Checkpoint work throws";
            };
        };
        readonly "cortex.harness.turn": {
            readonly description: "One assistant response and its tool batch";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.turn.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Invocation-local turn id";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Turn work throws";
            };
        };
        readonly "cortex.harness.step": {
            readonly description: "One durable retry attempt";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.turn", "cortex.harness.checkpoint", "cortex.harness.compaction", "cortex.harness.navigation"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.step.kind": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["assistant", "compaction", "branch_summary"];
                    readonly description: "Retryable step kind";
                };
                readonly "cortex.step.attempt": {
                    readonly type: "number";
                    readonly required: true;
                    readonly description: "One-based durable attempt number";
                };
                readonly "cortex.compaction.reason": {
                    readonly type: "string";
                    readonly required: false;
                    readonly values: readonly ["manual", "threshold", "overflow"];
                    readonly description: "Compaction trigger";
                };
            };
            readonly endAttributes: {
                readonly "cortex.step.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["succeeded", "retry", "failed", "aborted", "deferred", "overflow"];
                    readonly description: "Attempt outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The attempt retries, fails, or throws";
            };
        };
        readonly "cortex.harness.tool": {
            readonly description: "One raw phase-2 tool execution";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.turn", "cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.turn.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Invocation-local live turn id";
                };
                readonly "cortex.tool.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly description: "Tool name";
                };
                readonly "cortex.tool.call_id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Tool call id";
                };
                readonly "cortex.tool.replay": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["never", "safe"];
                    readonly description: "Declared replay policy";
                };
                readonly "cortex.tool.recovery": {
                    readonly type: "boolean";
                    readonly required: true;
                    readonly description: "Whether this is recovery execution";
                };
            };
            readonly endAttributes: {
                readonly "cortex.tool.is_error": {
                    readonly type: "boolean";
                    readonly description: "Whether raw phase-2 execution returned an error";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Raw phase-2 execution returns an error";
            };
        };
        readonly "cortex.harness.hook": {
            readonly description: "One registered hook handler invocation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id when accepted";
                };
                readonly "cortex.hook.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["before_run", "before_resume", "before_run_end", "transform_context", "before_request", "before_payload", "after_response", "before_tool", "after_tool", "before_compaction", "before_navigation"];
                    readonly description: "Hook name";
                };
                readonly "cortex.hook.registration_id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly description: "Stable hook registration id";
                };
            };
            readonly endAttributes: {
                readonly "cortex.hook.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["completed", "skipped", "blocked", "failed"];
                    readonly description: "Handler outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The handler throws";
            };
        };
        readonly "cortex.harness.sleep": {
            readonly description: "One retry delay";
            readonly parents: {
                readonly kind: "spans";
                readonly spans: readonly ["cortex.harness.step", "cortex.harness.run"];
            };
            readonly startAttributes: {
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id";
                };
                readonly "cortex.sleep.delay_ms": {
                    readonly type: "number";
                    readonly required: true;
                    readonly description: "Requested delay in milliseconds";
                };
            };
            readonly endAttributes: {
                readonly "cortex.sleep.outcome": {
                    readonly type: "string";
                    readonly values: readonly ["elapsed", "aborted"];
                    readonly description: "Delay outcome";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Sleep work throws";
            };
        };
        readonly "cortex.harness.event_handler": {
            readonly description: "One passive event listener invocation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.event.type": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "low";
                    readonly values: readonly ["run_start", "run_resume", "run_suspend", "run_abort", "run_end", "fault", "handler_error", "turn_start", "turn_end", "retry_scheduled", "retry_start", "retry_end", "message_start", "message_update", "message_end", "tool_start", "tool_update", "tool_end", "entry_added", "write_pending", "queue_update", "fact_update", "config_update", "compaction_start", "compaction_end", "navigation_start", "navigation_end", "lane_created", "usage"];
                    readonly description: "Delivered harness event type";
                };
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Lane name for lane-scoped events";
                };
            };
            readonly endAttributes: {};
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "The listener throws";
            };
        };
        readonly "cortex.session.write": {
            readonly description: "One committed session mutation";
            readonly parents: {
                readonly kind: "any";
            };
            readonly startAttributes: {
                readonly "cortex.lane.name": {
                    readonly type: "string";
                    readonly required: true;
                    readonly cardinality: "high";
                    readonly description: "Lane name";
                };
                readonly "cortex.operation.id": {
                    readonly type: "string";
                    readonly required: false;
                    readonly cardinality: "high";
                    readonly description: "Durable operation id when accepted";
                };
                readonly "cortex.session.mutation": {
                    readonly type: "string";
                    readonly required: true;
                    readonly values: readonly ["entry", "record", "lane", "fact"];
                    readonly description: "Session mutation kind";
                };
                readonly "cortex.session.item_type": {
                    readonly type: "string";
                    readonly required: false;
                    readonly description: "Entry, record, lane, or fact subtype";
                };
            };
            readonly endAttributes: {
                readonly "cortex.session.seq": {
                    readonly type: "number";
                    readonly description: "Committed session sequence when exposed";
                };
            };
            readonly status: {
                readonly default: "ok";
                readonly errorWhen: "Storage rejects the mutation";
            };
        };
    };
}];
export type HarnessSpanName = TelemetrySchemaSpanName<typeof HARNESS_TELEMETRY_SCHEMA>;
export type HarnessSpanStartAttributes<Name extends HarnessSpanName> = TelemetrySchemaSpanStartAttributes<typeof HARNESS_TELEMETRY_SCHEMA, Name>;
export type HarnessSpanEndAttributes<Name extends HarnessSpanName> = TelemetrySchemaSpanEndAttributes<typeof HARNESS_TELEMETRY_SCHEMA, Name>;
export type HarnessSpanAttributes<Name extends HarnessSpanName> = HarnessSpanStartAttributes<Name> & HarnessSpanEndAttributes<Name>;
export type HarnessSpanEventName<Name extends HarnessSpanName> = TelemetrySchemaSpanEventName<typeof HARNESS_TELEMETRY_SCHEMA, Name>;
export type HarnessSpanEventAttributes<Name extends HarnessSpanName, EventName extends HarnessSpanEventName<Name>> = TelemetrySchemaSpanEventAttributes<typeof HARNESS_TELEMETRY_SCHEMA, Name, EventName>;
export type HarnessTelemetrySpan<Name extends HarnessSpanName> = SchemaTelemetrySpan<typeof HARNESS_TELEMETRY_SCHEMA, Name>;
export type HarnessSpan = TelemetrySchemaSpanUnion<typeof HARNESS_TELEMETRY_SCHEMA>;
export declare function startHarnessSpan<Name extends HarnessSpanName, const Attributes extends HarnessSpanStartAttributes<Name>, Result>(telemetryContext: TelemetryContext, name: Name, attributes: ExactTelemetryAttributes<HarnessSpanStartAttributes<Name>, Attributes>, callback: (span: HarnessTelemetrySpan<Name>) => Result | Promise<Result>): Promise<Result>;
//# sourceMappingURL=telemetry.d.ts.map