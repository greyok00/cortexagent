// sampling-guard.ts — force sane sampling params for the local thinking model.
// Owner directive 2026-10-18 (carried into cortexagent 2026-10-23): the
// abliterated Qwen3.6 at temp 1.0 loops and ignores instructions. This
// extension intercepts every provider request and clamps temperature to 0.6,
// top_p to 0.95. Reads overrides from env: CORTEXENGINE_TEMP / CORTEXENGINE_TOP_P.

import type { ExtensionAPI } from "@cortexagent/coding-agent";

function num(env: string | undefined, fallback: number): number {
	const v = Number(env);
	return Number.isFinite(v) && v >= 0 ? v : fallback;
}

export default function samplingGuard(pi: ExtensionAPI): void {
	const temp = num(process.env.CORTEXENGINE_TEMP, 0.6);
	const topP = num(process.env.CORTEXENGINE_TOP_P, 0.95);

	pi.on("before_provider_request", (event) => {
		const payload = event.payload as Record<string, unknown> | null;
		if (!payload || typeof payload !== "object") return;

		// Only touch chat/completions payloads.
		const hasMessages = Array.isArray(payload.messages);
		if (!hasMessages) return;

		// Clamp temperature — never let it exceed the safe value.
		const current = Number(payload.temperature);
		if (!Number.isFinite(current) || current > temp) {
			payload.temperature = temp;
		}

		// Clamp top_p.
		const currentP = Number(payload.top_p);
		if (!Number.isFinite(currentP) || currentP > topP) {
			payload.top_p = topP;
		}
	});
}