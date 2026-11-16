import { describe, expect, it, vi } from "vitest";
import { generateImages } from "../src/images.ts";
import type { ImagesContext, ImagesModel } from "../src/types.ts";

class FakeAPIError extends Error {
	status: number;
	error: unknown;
	constructor(status: number, parsedBody: unknown) {
		super(`${status} status code (no body)`);
		this.name = "PermissionDeniedError";
		this.status = status;
		this.error = parsedBody;
	}
}

vi.mock("openai", () => {
	class FakeOpenAI {
		chat = {
			completions: {
				create: () => {
					const promise = Promise.resolve(undefined) as unknown as {
						withResponse: () => Promise<never>;
					};
					promise.withResponse = async () => {
						throw new FakeAPIError(403, { error: "blocked by gateway WAF" });
					};
					return promise;
				},
			},
		};
	}
	return { default: FakeOpenAI };
});

describe("provider error body passthrough", () => {
	it("surfaces the HTTP body reason instead of the opaque SDK message (openrouter images)", async () => {
		const model: ImagesModel<"openrouter-images"> = {
			id: "black-forest-labs/flux.2-pro",
			name: "FLUX.2 Pro",
			api: "openrouter-images",
			provider: "openrouter",
			baseUrl: "https://openrouter.ai/api/v1",
			input: ["text", "image"],
			output: ["image"],
			cost: { input: 0.015, output: 0.03, cacheRead: 0, cacheWrite: 0 },
		};
		const context: ImagesContext = {
			input: [{ type: "text", text: "Generate a dog" }],
		};

		const output = await generateImages(model, context, { apiKey: "test" });

		expect(output.stopReason).toBe("error");

		expect(output.errorMessage).toContain("403");

		expect(output.errorMessage).toContain("blocked by gateway WAF");
		expect(output.errorMessage).not.toBe("403 status code (no body)");
	});
});
