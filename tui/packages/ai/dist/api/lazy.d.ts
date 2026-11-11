import type { Api, AssistantMessageEvent, Model, ProviderStreams } from "../types.ts";
import { AssistantMessageEventStream } from "../utils/event-stream.ts";
export declare function lazyStream(model: Model<Api>, setup: () => Promise<AsyncIterable<AssistantMessageEvent>>): AssistantMessageEventStream;
export interface LazyApiCapabilities {
    fetchDeferred?: boolean;
    cancelDeferred?: boolean;
}
export declare function lazyApi(load: () => Promise<ProviderStreams>, capabilities?: LazyApiCapabilities): ProviderStreams;
//# sourceMappingURL=lazy.d.ts.map