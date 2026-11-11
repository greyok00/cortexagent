// 2026-10-23: fork of cortexagent's models.ts (cortexagent lineage); carried into
// cortex-agent 2026-11-09. Local GGUF usable in
// the picker — "cortexagent-local" carries apiKey "none" so no OAuth/API-key
// check can block it. Cloud provider catalogs are emptied: cortex-agent is
// LOCAL-ONLY (same owner order as the cortexagent fork, 2026-10-14).
// contextWindow tracks the engine-server --ctx-size (server.py CTX ladder).

import type { ExtensionAPI } from "@cortexagent/coding-agent";  // 2026-10-24 hardened: renamed scope
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { state } from "./lib/shared.ts";

export default function modelsExtension(pi: ExtensionAPI): void {
	// Local-only directive: every builtin cloud catalog is emptied so the
	// picker can't offer cloud models.
	pi.registerProvider("amazon-bedrock", { models: [] });
	pi.registerProvider("anthropic", { models: [] });
	pi.registerProvider("azure-openai-responses", { models: [] });
	pi.registerProvider("baseten", { models: [] });
	pi.registerProvider("cerebras", { models: [] });
	pi.registerProvider("cloudflare-ai-gateway", { models: [] });
	pi.registerProvider("cloudflare-workers-ai", { models: [] });
	pi.registerProvider("fireworks", { models: [] });
	pi.registerProvider("github-copilot", { models: [] });
	pi.registerProvider("google", { models: [] });
	pi.registerProvider("google-vertex", { models: [] });
	pi.registerProvider("groq", { models: [] });
	pi.registerProvider("huggingface", { models: [] });
	pi.registerProvider("mistral", { models: [] });
	pi.registerProvider("nvidia", { models: [] });
	pi.registerProvider("openai", { models: [] });
	pi.registerProvider("openai-codex", { models: [] });
	pi.registerProvider("opencode", { models: [] });
	pi.registerProvider("opencode-go", { models: [] });
	pi.registerProvider("openrouter", { models: [] });
	pi.registerProvider("together", { models: [] });
	pi.registerProvider("vercel-ai-gateway", { models: [] });
	pi.registerProvider("xai", { models: [] });

	// 2026-10-18 (owner directive, carried into cortexagent): samplingParams
	// force temp 0.6 + top_p 0.95 — matches the engine-server flags.
	const SAFE_TEMP = Number(process.env.CORTEXENGINE_TEMP ?? "0.6");
	const SAFE_TOP_P = Number(process.env.CORTEXENGINE_TOP_P ?? "0.95");

	// 2026-11-10 owner: standard-ollama passthrough ("cortex-agent ollama").
	// The harness brain rides OUR slimtoken lane on :7112 -> the user's own
	// ollama endpoint (env CORTEXENGINE_OLLAMA_URL). Nothing about the
	// user's ollama is modified. Model name comes from env.
	if (process.env.CORTEXENGINE_OLLAMA === "1") {
		pi.registerProvider("cortexagent-ollama", {
			name: "Cortex Ollama passthrough (:7112 lane)",
			baseUrl: process.env.CORTEXENGINE_LOCAL_BASE || "http://127.0.0.1:7112/v1",
			apiKey: "none",
			api: "openai-completions",
			samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
			models: [
				{
					id: process.env.CORTEXENGINE_OLLAMA_MODEL || process.env.CORTEXENGINE_MODEL_NAME || "ollama-model",
					name: "your ollama model (via cortex lane)",
					reasoning: true,
					input: ["text"],
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
					contextWindow: Number(process.env.CORTEXENGINE_CTX_WINDOW ?? 131072),
					maxTokens: 32768,
					samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
				},
			],
		});
		return;
	}
	pi.registerProvider("cortexagent-local", {
		name: "Cortex Local (:7101 lane)",
		baseUrl: process.env.CORTEXENGINE_LOCAL_BASE || "http://127.0.0.1:7101/v1",
		apiKey: "none",
		api: "openai-completions",
		samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
		models: [
			{
				id: "cortexagent",
				name: "stock MoE (VRAM card, :7100)",
				reasoning: true,
				input: ["text", "image"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				// 2026-10-25 (truncation root cause): provider.ts is the *the engine*
				// provider on :8080 — it never feeds this one. Removing the old
				// 12288/4096 pair left contextWindow undefined here, and
				// _checkCompaction reads `contextWindow ?? 0`; shouldCompact()
				// returns false for any non-positive window, so compaction could
				// never fire. The session then grew to the server's 65536 ceiling
				// (log: n_tokens = 65535, truncated = 1; request 66744 tokens -> 400)
				// and replies stopped after the last few free tokens, which the TUI
				// renders as "Response was truncated before completion."
				// Must stay in step with server.py CTX (--ctx-size 81920).
				// 2026-10-28 owner: compaction at 85% of a 64k window fired
				// every ~35k tokens; 81920 moves the threshold to ~69.6k.
				// 2026-10-31 QA (GT-34 class): the TUI's CORTEXENGINE_CTX_WINDOW
				// and the server's CORTEXENGINE_CTX are two disjoint knobs
				// sharing one reality — and when the VRAM ladder settles at a
				// Lower ctx (server.py writes state/model-ctx-settled.txt),
				// the TUI never learned it and compaction fired too late
				// (400 overflow before compaction — observed live in this
				// family's fork). Follow the settled value when present.
				contextWindow: (() => {
					const envW = process.env.CORTEXENGINE_CTX_WINDOW ? Number(process.env.CORTEXENGINE_CTX_WINDOW) : null;
					let settled: number | null = null;
					try {
						const v = Number(fs.readFileSync(path.join(os.homedir(), "cortex-agent", "state", "model-ctx-settled.txt"), "utf8").trim());
						settled = Number.isFinite(v) && v > 0 ? v : null;
					} catch {}
					if (settled && envW) return Math.min(settled, envW);
					return settled ?? envW ?? 81920;
				})(),
				// 2026-11-09: 32768 — big answers on the 128k slot; clamp()
				// (simple-options.ts) still bounds it by live headroom with a
				// 1024 floor (MIN_ANSWER_TOKENS) so long contexts compact
				// instead of producing 1-token length stops.
				maxTokens: Number(process.env.CORTEXENGINE_MAX_TOKENS ?? "32768"),
				samplingParams: { temperature: SAFE_TEMP, top_p: SAFE_TOP_P },
			},
		],
	});

	void state;
}