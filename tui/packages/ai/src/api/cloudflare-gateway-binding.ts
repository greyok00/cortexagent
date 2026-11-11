import type { FetchFunction } from "../types.ts";

export interface AiGatewayBinding {
	gateway(id: string): AiGatewayBindingGateway;
}

export interface AiGatewayBindingGateway {
	run(data: AiGatewayUniversalRequestLike, options?: { signal?: AbortSignal }): Promise<Response>;
}

export interface AiGatewayUniversalRequestLike {
	provider: string;
	endpoint: string;
	headers: Record<string, string>;
	query: unknown;
}

export const CLOUDFLARE_GATEWAY_BINDING_AUTH_SENTINEL = "cloudflare-gateway-binding";

export interface GatewayBindingFetchOptions {
	binding: AiGatewayBinding;

	baseUrl: string;

	gateway: string;
}

const STRIP_HEADERS = new Set(["content-length", "host", "cf-aig-authorization"]);

type FetchInput = Parameters<FetchFunction>[0];

export function createGatewayBindingFetch(options: GatewayBindingFetchOptions): FetchFunction {
	const { binding, gateway } = options;

	const base = new URL(options.baseUrl);
	const basePath = base.pathname.endsWith("/") ? base.pathname : `${base.pathname}/`;

	return async (input: FetchInput, init?: RequestInit): Promise<Response> => {
		const request = input instanceof Request ? input : undefined;
		const url = request ? request.url : input.toString();
		const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
		let parsed: URL | undefined;
		try {
			parsed = new URL(url);
		} catch {
			parsed = undefined;
		}

		if (parsed === undefined || parsed.origin !== base.origin || !parsed.pathname.startsWith(basePath)) {
			throw new Error(
				`createGatewayBindingFetch: ${method} ${url} is outside the configured gateway ` +
					`prefix (${base.origin}${basePath}); this fetch only serves its gateway-bound client`,
			);
		}

		const unexpressible = (reason: string): never => {
			throw new Error(
				`createGatewayBindingFetch: cannot express ${method} ${url} as a universal ` +
					`gateway request (${reason}); route it over HTTPS with gateway auth instead`,
			);
		};
		if (method !== "POST") return unexpressible("only POST is supported");

		const rest = parsed.pathname.slice(basePath.length);
		const slash = rest.indexOf("/");
		if (slash <= 0) {
			return unexpressible("missing provider/endpoint path");
		}
		const provider = rest.slice(0, slash);

		const endpoint = rest.slice(slash + 1) + parsed.search;

		const bodyText = await readBodyText(request, init);
		let query: unknown;
		try {
			query = bodyText === undefined ? undefined : JSON.parse(bodyText);
		} catch {
			return unexpressible("non-JSON body");
		}
		if (query === undefined) {
			return unexpressible("missing body");
		}

		const headers = collectHeaders(request, init);

		const signal = init?.signal ?? (init && "signal" in init && init.signal === null ? undefined : request?.signal);
		return binding.gateway(gateway).run({ provider, endpoint, headers, query }, signal ? { signal } : {});
	};
}

async function readBodyText(request: Request | undefined, init?: RequestInit): Promise<string | undefined> {
	const body = init?.body;
	if (body === undefined || body === null) {
		if (init && "body" in init && body === null) return undefined;
		if (request && request.body !== null) return request.clone().text();
		return undefined;
	}
	if (typeof body === "string") return body;
	if (body instanceof Uint8Array) return new TextDecoder().decode(body);
	if (body instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(body));

	return new Request("http://body.local", {
		method: "POST",
		body,

		duplex: "half",
	} as RequestInit).text();
}

function collectHeaders(request: Request | undefined, init?: RequestInit): Record<string, string> {
	const result: Record<string, string> = {};
	const add = (key: string, value: string) => {
		const name = key.toLowerCase();
		if (!STRIP_HEADERS.has(name)) result[name] = value;
	};
	const headers = init?.headers;
	if (headers === undefined) {
		if (request) {
			for (const [key, value] of request.headers) add(key, value);
		}
	} else if (headers instanceof Headers) {
		for (const [key, value] of headers) add(key, value);
	} else if (Array.isArray(headers)) {
		for (const [key, value] of headers) add(key, value);
	} else {
		for (const [key, value] of Object.entries(headers)) {
			if (value !== undefined) add(key, String(value));
		}
	}
	return result;
}
