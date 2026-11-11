import { createTypedSpanStarter, NOOP_TELEMETRY_CONTEXT, type TelemetryContext } from "@cortexagent/telemetry";
import { describe, expect, expectTypeOf, it } from "vitest";
import {
	AGENT_TELEMETRY_SCHEMAS,
	AI_TELEMETRY_SCHEMA,
	type AiSpanEndAttributes,
	type AiSpanStartAttributes,
	HARNESS_TELEMETRY_SCHEMA,
	type HarnessSpanEndAttributes,
	type HarnessSpanStartAttributes,
	startAiSpan,
	startHarnessSpan,
} from "../../src/harness/telemetry.ts";

describe("agent telemetry schemas", () => {
	it("serializes both schemas and generates the checked-in reference", () => {
		expect(() => JSON.stringify(AI_TELEMETRY_SCHEMA)).not.toThrow();
		expect(() => JSON.stringify(HARNESS_TELEMETRY_SCHEMA)).not.toThrow();
		expect(AGENT_TELEMETRY_SCHEMAS).toEqual([AI_TELEMETRY_SCHEMA, HARNESS_TELEMETRY_SCHEMA]);
		expect(Object.keys(HARNESS_TELEMETRY_SCHEMA.spans)).toEqual([
			"cortex.harness.run",
			"cortex.harness.compaction",
			"cortex.harness.navigation",
			"cortex.harness.checkpoint",
			"cortex.harness.turn",
			"cortex.harness.step",
			"cortex.harness.tool",
			"cortex.harness.hook",
			"cortex.harness.sleep",
			"cortex.harness.event_handler",
			"cortex.session.write",
		]);
	});

	it("starts AI-request and harness spans through one composed typed starter", async () => {
		const startSpan = createTypedSpanStarter(NOOP_TELEMETRY_CONTEXT, AGENT_TELEMETRY_SCHEMAS);
		await startSpan(
			"cortex.harness.step",
			{
				"cortex.lane.name": "main",
				"cortex.operation.id": "operation",
				"cortex.step.kind": "assistant",
				"cortex.step.attempt": 1,
			},
			async (stepSpan, startChildSpan) => {
				stepSpan.setAttributes({ "cortex.step.outcome": "succeeded" });
				await startChildSpan(
					"cortex.ai.request",
					{
						"cortex.ai.operation": "stream",
						"cortex.ai.provider": "provider",
						"cortex.ai.model": "model",
						"cortex.ai.api": "api",
						"cortex.ai.streaming": true,
					},
					(requestSpan) => {
						requestSpan.setAttributes({ "cortex.ai.response.stop_reason": "stop" });
					},
				);
			},
		);
	});

	it("infers exact AI start and optional end attributes", async () => {
		type Start = AiSpanStartAttributes<"cortex.ai.request">;
		type End = AiSpanEndAttributes<"cortex.ai.request">;
		expectTypeOf<Start>().toMatchTypeOf<{
			"cortex.ai.operation": "stream" | "fetch_deferred" | "cancel_deferred" | "generate_images";
			"cortex.ai.provider": string;
			"cortex.ai.model": string;
			"cortex.ai.api": string;
			"cortex.ai.streaming": boolean;
			"cortex.ai.deferred"?: boolean;
		}>();
		expectTypeOf<End["cortex.ai.response.stop_reason"]>().toEqualTypeOf<
			"stop" | "length" | "tool_use" | "error" | "aborted" | "deferred" | undefined
		>();

		const telemetryContext: TelemetryContext = NOOP_TELEMETRY_CONTEXT;
		await startAiSpan(
			telemetryContext,
			"cortex.ai.request",
			{
				"cortex.ai.operation": "stream",
				"cortex.ai.provider": "provider",
				"cortex.ai.model": "model",
				"cortex.ai.api": "api",
				"cortex.ai.streaming": true,
			},
			(span) => {
				span.setAttributes({ "cortex.ai.response.stop_reason": "tool_use" });
				// @ts-expect-error cortex.ai.request declares no span events
				span.addEvent("chunk");
			},
		);

		const compileTimeFailures = () => {
			const extraAttributes = {
				"cortex.ai.operation": "stream",
				"cortex.ai.provider": "provider",
				"cortex.ai.model": "model",
				"cortex.ai.api": "api",
				"cortex.ai.streaming": true,
				"cortex.ai.unknown": true,
			} as const;
			// @ts-expect-error variables with unknown attributes are rejected
			void startAiSpan(telemetryContext, "cortex.ai.request", extraAttributes, () => {});
			// @ts-expect-error missing required start attributes
			void startAiSpan(telemetryContext, "cortex.ai.request", { "cortex.ai.operation": "stream" }, () => {});
		};
		expectTypeOf(compileTimeFailures).toBeFunction();
	});

	it("infers per-span harness literals and optional completion enrichment", async () => {
		type RunStart = HarnessSpanStartAttributes<"cortex.harness.run">;
		type RunEnd = HarnessSpanEndAttributes<"cortex.harness.run">;
		expectTypeOf<RunStart["cortex.operation.kind"]>().toEqualTypeOf<"run">();
		expectTypeOf<RunEnd["cortex.operation.outcome"]>().toEqualTypeOf<
			"completed" | "aborted" | "failed" | "suspended" | undefined
		>();

		const telemetryContext: TelemetryContext = NOOP_TELEMETRY_CONTEXT;
		await startHarnessSpan(
			telemetryContext,
			"cortex.harness.run",
			{
				"cortex.session.id": "session",
				"cortex.lane.name": "main",
				"cortex.operation.id": "operation",
				"cortex.operation.kind": "run",
				"cortex.operation.recovery": false,
			},
			(span) => {
				span.setAttributes({ "cortex.operation.outcome": "completed" });
				span.setAttributes({});
				// @ts-expect-error the harness schema declares no span events
				span.addEvent("result");
			},
		);

		const compileTimeFailures = () => {
			const extraRunAttributes = {
				"cortex.session.id": "session",
				"cortex.lane.name": "main",
				"cortex.operation.id": "operation",
				"cortex.operation.kind": "run",
				"cortex.operation.recovery": false,
				"cortex.unknown": true,
			} as const;
			// @ts-expect-error variables with unknown attributes are rejected
			void startHarnessSpan(telemetryContext, "cortex.harness.run", extraRunAttributes, () => {});
			void startHarnessSpan(
				telemetryContext,
				"cortex.harness.checkpoint",
				{
					"cortex.lane.name": "main",
					"cortex.operation.id": "operation",
					"cortex.checkpoint.kind": "normal",
				},
				(span) => {
					// @ts-expect-error empty end schemas reject every attribute
					span.setAttributes({ "cortex.unknown": true });
				},
			);
			void startHarnessSpan(
				telemetryContext,
				"cortex.harness.run",
				{
					"cortex.session.id": "session",
					"cortex.lane.name": "main",
					"cortex.operation.id": "operation",
					// @ts-expect-error run spans accept only the run operation kind
					"cortex.operation.kind": "navigation",
					"cortex.operation.recovery": false,
				},
				() => {},
			);
			// @ts-expect-error missing required run start attributes
			void startHarnessSpan(telemetryContext, "cortex.harness.run", {}, () => {});
		};
		expectTypeOf(compileTimeFailures).toBeFunction();
	});
});
