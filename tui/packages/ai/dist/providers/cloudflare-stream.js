const CLOUDFLARE_ACCOUNT_ID = "CLOUDFLARE_ACCOUNT_ID";
const CLOUDFLARE_GATEWAY_ID = "CLOUDFLARE_GATEWAY_ID";
export function resolveCloudflareModel(model, env) {
    if (!env)
        return model;
    const baseUrl = model.baseUrl
        .replaceAll(`{${CLOUDFLARE_ACCOUNT_ID}}`, env[CLOUDFLARE_ACCOUNT_ID] ?? `{${CLOUDFLARE_ACCOUNT_ID}}`)
        .replaceAll(`{${CLOUDFLARE_GATEWAY_ID}}`, env[CLOUDFLARE_GATEWAY_ID] ?? `{${CLOUDFLARE_GATEWAY_ID}}`);
    return baseUrl === model.baseUrl ? model : { ...model, baseUrl };
}
export function cloudflareStreams(streams) {
    return {
        stream: (model, context, options) => streams.stream(resolveCloudflareModel(model, options?.env), context, options),
        streamSimple: (model, context, options) => streams.streamSimple(resolveCloudflareModel(model, options?.env), context, options),
    };
}
//# sourceMappingURL=cloudflare-stream.js.map