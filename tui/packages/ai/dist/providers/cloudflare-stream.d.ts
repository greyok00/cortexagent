import type { Api, Model, ProviderEnv, ProviderStreams } from "../types.ts";
export declare function resolveCloudflareModel<TApi extends Api>(model: Model<TApi>, env: ProviderEnv | undefined): Model<TApi>;
export declare function cloudflareStreams(streams: ProviderStreams): ProviderStreams;
//# sourceMappingURL=cloudflare-stream.d.ts.map