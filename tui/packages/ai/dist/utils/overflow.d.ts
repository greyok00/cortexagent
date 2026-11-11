import type { AssistantMessage } from "../types.ts";
export declare function isContextOverflow(message: AssistantMessage, contextWindow?: number): boolean;
export declare function isRecoverableLength(message: AssistantMessage, desiredMaxOutput: number): boolean;
export declare function getOverflowPatterns(): RegExp[];
//# sourceMappingURL=overflow.d.ts.map