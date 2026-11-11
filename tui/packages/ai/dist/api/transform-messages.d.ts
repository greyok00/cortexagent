import type { Api, AssistantMessage, Message, Model } from "../types.ts";
export declare function transformMessages<TApi extends Api>(messages: Message[], model: Model<TApi>, normalizeToolCallId?: (id: string, model: Model<TApi>, source: AssistantMessage) => string): Message[];
//# sourceMappingURL=transform-messages.d.ts.map