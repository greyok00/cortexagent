import type { ProviderEnv, ProviderHeaders } from "../types.ts";

export interface ModelAuth {
	apiKey?: string;
	headers?: ProviderHeaders;
	baseUrl?: string;
}

export interface ApiKeyCredential {
	type: "api_key";
	key?: string;
	env?: ProviderEnv;
}

export interface OAuthCredentials {
	refresh: string;
	access: string;
	expires: number;
	[key: string]: unknown;
}

export interface OAuthCredential extends OAuthCredentials {
	type: "oauth";
}

export type Credential = ApiKeyCredential | OAuthCredential;

export interface CredentialInfo {
	providerId: string;
	type: Credential["type"];
}

export interface AuthOperationOptions {
	signal?: AbortSignal;
}

export interface CredentialStore {
	read(providerId: string, options?: AuthOperationOptions): Promise<Credential | undefined>;

	list(options?: AuthOperationOptions): Promise<readonly CredentialInfo[]>;

	modify(
		providerId: string,
		fn: (current: Credential | undefined) => Promise<Credential | undefined>,
		options?: AuthOperationOptions,
	): Promise<Credential | undefined>;

	delete(providerId: string, options?: AuthOperationOptions): Promise<void>;
}

export interface AuthContext {
	env(name: string): Promise<string | undefined>;

	fileExists(path: string): Promise<boolean>;
}

export interface AuthResult {
	auth: ModelAuth;

	env?: ProviderEnv;

	source?: string;
}

export interface AuthCheck {
	source?: string;
	type: "api_key" | "oauth";
}

export type AuthType = "api_key" | "oauth";

export type AuthPrompt = { signal?: AbortSignal } & (
	| { type: "text"; message: string; placeholder?: string }
	| { type: "secret"; message: string; placeholder?: string }
	| { type: "select"; message: string; options: readonly { id: string; label: string; description?: string }[] }
	| { type: "manual_code"; message: string; placeholder?: string }
);

export interface AuthInfoLink {
	url: string;
	label?: string;
}

export type AuthEvent =
	| { type: "info"; message: string; links?: readonly AuthInfoLink[] }
	| { type: "auth_url"; url: string; instructions?: string }
	| {
			type: "device_code";
			userCode: string;
			verificationUri: string;
			intervalSeconds?: number;
			expiresInSeconds?: number;
	  }
	| { type: "progress"; message: string };

export interface AuthInteraction {
	signal?: AbortSignal;

	prompt(prompt: AuthPrompt): Promise<string>;
	notify(event: AuthEvent): void;
}

export type ProviderAuthInteraction = AuthInteraction & { signal: AbortSignal };

export interface ApiKeyAuth {
	name: string;

	login?(interaction: ProviderAuthInteraction): Promise<ApiKeyCredential>;

	check?(input: {
		ctx: AuthContext;
		credential?: ApiKeyCredential;
		signal: AbortSignal;
	}): Promise<AuthCheck | undefined>;

	resolve(input: {
		ctx: AuthContext;
		credential?: ApiKeyCredential;
		signal: AbortSignal;
	}): Promise<AuthResult | undefined>;
}

export interface OAuthAuth {
	name: string;

	isSubscription?: boolean;

	loginLabel?: string;

	login(interaction: ProviderAuthInteraction): Promise<OAuthCredential>;

	refresh(credential: OAuthCredential, signal: AbortSignal): Promise<OAuthCredential>;

	toAuth(credential: OAuthCredential): Promise<ModelAuth>;
}

export interface ProviderAuth {
	apiKey?: ApiKeyAuth;
	oauth?: OAuthAuth;
}
