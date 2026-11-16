import { describe, expect, it } from "vitest";
import {
	type AiGatewayUniversalRequestLike,
	CLOUDFLARE_GATEWAY_BINDING_AUTH_SENTINEL,
	createGatewayBindingFetch,
} from "../src/api/cloudflare-gateway-binding.ts";
import { streamSimple as streamOpenAICompletions } from "../src/api/openai-completions.ts";
import type { Model } from "../src/types.ts";

const BASE_URL = "https://gateway.ai.cloudflare.com/v1/account-id/my-gateway";

interface CapturedRun {
	gatewayId: string;
	data: AiGatewayUniversalRequestLike;
	options: { signal?: AbortSignal } | undefined;
}

function fakeBinding(response?: Response) {
	const runs: CapturedRun[] = [];
	const binding = {
		gateway: (gatewayId: string) => ({
			run: (data: AiGatewayUniversalRequestLike, options?: { signal?: AbortSignal }) => {
				runs.push({ gatewayId, data, options });
				return Promise.resolve(response ?? new Response("{}"));
			},
		}),
	};
	return { binding, runs };
}

describe("createGatewayBindingFetch", () => {
	it("derives provider and endpoint from gateway passthrough URLs", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
			method: "POST",
			body: JSON.stringify({ model: "claude" }),
		});
		await fetchFn(`${BASE_URL}/openai/responses`, {
			method: "POST",
			body: JSON.stringify({ model: "gpt" }),
		});
		await fetchFn(`${BASE_URL}/workers-ai/v1/chat/completions`, {
			method: "POST",
			body: JSON.stringify({ model: "@cf/meta/llama" }),
		});

		expect(runs.map((run) => [run.data.provider, run.data.endpoint])).toEqual([
			["anthropic", "v1/messages"],
			["openai", "responses"],
			["workers-ai", "v1/chat/completions"],
		]);
		expect(runs.map((run) => run.gatewayId)).toEqual(["my-gateway", "my-gateway", "my-gateway"]);
		expect(runs[0].data.query).toEqual({ model: "claude" });
	});

	it("keeps the query string in the endpoint", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(`${BASE_URL}/openai/responses?beta=true`, {
			method: "POST",
			body: "{}",
		});

		expect(runs[0].data.endpoint).toBe("responses?beta=true");
	});

	it("lowercases header names so case-variant duplicates collapse", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
			method: "POST",
			headers: { "Anthropic-Version": "2023-06-01" },
			body: "{}",
		});

		expect(runs[0].data.headers).toEqual({ "anthropic-version": "2023-06-01" });
	});

	it("lets init headers replace a Request input's headers, per the fetch spec", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(
			new Request(`${BASE_URL}/anthropic/v1/messages`, {
				method: "POST",
				headers: { "x-from-request": "yes" },
				body: "{}",
			}),
			{ headers: { "x-from-init": "yes" } },
		);

		expect(runs[0].data.headers["x-from-init"]).toBe("yes");
		expect(runs[0].data.headers["x-from-request"]).toBeUndefined();
	});

	it("strips gateway auth and derived headers, forwards the rest", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"Content-Length": "17",
				"CF-AIG-Authorization": `Bearer ${CLOUDFLARE_GATEWAY_BINDING_AUTH_SENTINEL}`,
				"cf-aig-metadata": '{"user":"42"}',
				"anthropic-version": "2023-06-01",
				"x-api-key": "provider-key",
			},
			body: "{}",
		});

		const headers = Object.fromEntries(
			Object.entries(runs[0].data.headers).map(([key, value]) => [key.toLowerCase(), value]),
		);
		expect(headers["cf-aig-authorization"]).toBeUndefined();
		expect(headers["content-length"]).toBeUndefined();
		expect(headers["cf-aig-metadata"]).toBe('{"user":"42"}');
		expect(headers["anthropic-version"]).toBe("2023-06-01");

		expect(headers["x-api-key"]).toBe("provider-key");
	});

	it("accepts Request inputs and forwards their headers and body", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(
			new Request(`${BASE_URL}/openai/chat/completions`, {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ stream: true }),
			}),
		);

		expect(runs).toHaveLength(1);
		expect(runs[0].data.provider).toBe("openai");
		expect(runs[0].data.endpoint).toBe("chat/completions");
		expect(runs[0].data.query).toEqual({ stream: true });
		expect(runs[0].data.headers["content-type"]).toBe("application/json");
	});

	it("forwards the abort signal", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });
		const controller = new AbortController();

		await fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
			method: "POST",
			body: "{}",
			signal: controller.signal,
		});

		expect(runs[0].options?.signal).toBe(controller.signal);
	});

	it("lets an explicit `signal: null` in init clear a Request input's signal, per the fetch spec", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });
		const controller = new AbortController();

		await fetchFn(
			new Request(`${BASE_URL}/anthropic/v1/messages`, {
				method: "POST",
				body: "{}",
				signal: controller.signal,
			}),
			{ signal: null },
		);

		expect(runs).toHaveLength(1);
		expect(runs[0].options?.signal).toBeUndefined();
	});

	it("returns the binding response untouched, including streaming bodies", async () => {
		const stream = new ReadableStream<Uint8Array>({
			start(controller) {
				controller.enqueue(new TextEncoder().encode("data: {}\n\n"));
				controller.close();
			},
		});
		const bindingResponse = new Response(stream, {
			status: 200,
			headers: { "content-type": "text/event-stream", "cf-aig-log-id": "log-1" },
		});
		const { binding } = fakeBinding(bindingResponse);
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		const response = await fetchFn(`${BASE_URL}/workers-ai/v1/chat/completions`, {
			method: "POST",
			body: "{}",
		});

		expect(response).toBe(bindingResponse);
		expect(response.headers.get("cf-aig-log-id")).toBe("log-1");
		expect(await response.text()).toBe("data: {}\n\n");
	});

	it("rejects in-prefix requests the universal endpoint cannot express", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await expect(fetchFn(`${BASE_URL}/anthropic/v1/messages`, { method: "GET" })).rejects.toThrow(
			"cannot express GET",
		);
		await expect(fetchFn(`${BASE_URL}/anthropic/v1/messages`, { method: "POST", body: "not json" })).rejects.toThrow(
			"non-JSON body",
		);
		await expect(fetchFn(`${BASE_URL}/anthropic`, { method: "POST", body: "{}" })).rejects.toThrow(
			"missing provider/endpoint path",
		);
		expect(runs).toHaveLength(0);
	});

	it("rejects URLs outside the gateway prefix: transport selection is the caller's", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await expect(
			fetchFn("https://api.openai.com/v1/chat/completions", { method: "POST", body: "{}" }),
		).rejects.toThrow("outside the configured gateway prefix");

		await expect(
			fetchFn("https://gateway.ai.cloudflare.com/v1/other-account/my-gateway/anthropic/v1/messages", {
				method: "POST",
				body: "{}",
			}),
		).rejects.toThrow("outside the configured gateway prefix");
		expect(runs).toHaveLength(0);
	});

	it("matches and splits on the URL-normalized path, as real fetch would send it", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });

		await fetchFn(`${BASE_URL}/anthropic/../anthropic/v1/./messages`, {
			method: "POST",
			body: JSON.stringify({ model: "claude" }),
		});
		expect(runs.map((run) => [run.data.provider, run.data.endpoint])).toEqual([["anthropic", "v1/messages"]]);

		await expect(
			fetchFn(`${BASE_URL}/../other-gateway/anthropic/v1/messages`, { method: "POST", body: "{}" }),
		).rejects.toThrow("outside the configured gateway prefix");
		expect(runs).toHaveLength(1);
	});

	it("consumes a one-shot stream body for the JSON probe", async () => {
		const { binding, runs } = fakeBinding();
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });
		const streamOf = (text: string) =>
			new ReadableStream<Uint8Array>({
				start(controller) {
					controller.enqueue(new TextEncoder().encode(text));
					controller.close();
				},
			});

		await fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
			method: "POST",
			body: streamOf('{"model":"claude"}'),
			duplex: "half",
		} as RequestInit);
		expect(runs).toHaveLength(1);
		expect(runs[0].data.query).toEqual({ model: "claude" });

		await expect(
			fetchFn(`${BASE_URL}/anthropic/v1/messages`, {
				method: "POST",
				body: streamOf("not json"),
				duplex: "half",
			} as RequestInit),
		).rejects.toThrow("non-JSON body");
		expect(runs).toHaveLength(1);
	});

	it("keeps SDK placeholder auth out of entries when paired with null auth headers", async () => {
		const { binding, runs } = fakeBinding(
			Response.json({ error: { type: "bad_request", message: "stubbed" } }, { status: 400 }),
		);
		const fetchFn = createGatewayBindingFetch({ binding, baseUrl: BASE_URL, gateway: "my-gateway" });
		const model: Model<"openai-completions"> = {
			id: "test-model",
			name: "Test Model",
			api: "openai-completions",
			provider: "openai",
			baseUrl: `${BASE_URL}/openai`,
			reasoning: false,
			input: ["text"],
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
			contextWindow: 10_000,
			maxTokens: 1_000,
		};

		const result = await streamOpenAICompletions(
			model,
			{ messages: [{ role: "user", content: "hello", timestamp: 1 }] },
			{
				headers: {
					"cf-aig-authorization": `Bearer ${CLOUDFLARE_GATEWAY_BINDING_AUTH_SENTINEL}`,
					Authorization: null,
					"x-api-key": null,
				},
				fetch: fetchFn,
				maxRetries: 0,
			},
		).result();

		expect(result.stopReason).toBe("error");
		expect(runs).toHaveLength(1);
		expect(runs[0].data.provider).toBe("openai");
		const headerNames = Object.keys(runs[0].data.headers);
		expect(headerNames).not.toContain("authorization");
		expect(headerNames).not.toContain("x-api-key");
		expect(headerNames).not.toContain("cf-aig-authorization");
	});
});
