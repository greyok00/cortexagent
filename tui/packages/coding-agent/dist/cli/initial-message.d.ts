import type { ImageContent } from "@cortexagent/ai";
import type { Args } from "./args.ts";
export interface InitialMessageInput {
    parsed: Args;
    fileText?: string;
    fileImages?: ImageContent[];
    stdinContent?: string;
}
export interface InitialMessageResult {
    initialMessage?: string;
    initialImages?: ImageContent[];
}
export declare function buildInitialMessage({ parsed, fileText, fileImages, stdinContent }: InitialMessageInput): InitialMessageResult;
//# sourceMappingURL=initial-message.d.ts.map