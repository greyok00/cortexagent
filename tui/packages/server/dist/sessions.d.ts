import type { Command, EventEnvelope, SessionMetadata } from "@cortexagent/protocol";
import type { ByteConnection, ConnectionState } from "./connection.ts";
import type { CortexServerService } from "./types.ts";
interface LiveSessionManagerOptions {
    service: CortexServerService;
    isClosing: () => boolean;
    sendMessage: (connection: ConnectionState, message: EventEnvelope) => Promise<boolean>;
    closeConnection: (connection: ByteConnection) => Promise<void>;
    disconnect: (connection: ConnectionState) => Promise<void>;
    broadcastServerSnapshot: () => void;
    reportError: (error: unknown) => void;
}
export declare class LiveSessionManager {
    private readonly options;
    private readonly liveSessions;
    private readonly openingSessions;
    constructor(options: LiveSessionManagerOptions);
    executeCommand(connection: ConnectionState, command: Command): Promise<{
        command: "list";
        sessions: {
            readonly id: string;
            readonly createdAt: number;
            readonly updatedAt?: number | undefined;
            readonly parentSessionId?: string | undefined;
            readonly sessionName?: string | undefined;
            readonly cwd?: string | undefined;
        }[];
        sessionId?: undefined;
        session?: undefined;
    } | {
        sessions?: undefined;
        command: "create";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
        sessionId?: undefined;
    } | {
        sessions?: undefined;
        command: "attach";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
        sessionId?: undefined;
    } | {
        sessions?: undefined;
        command: "detach";
        sessionId: string;
        session?: undefined;
    } | {
        sessions?: undefined;
        sessionId?: undefined;
        command: "prompt";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
    } | {
        sessions?: undefined;
        sessionId?: undefined;
        command: "steer";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
    } | {
        sessions?: undefined;
        sessionId?: undefined;
        command: "abort";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
    } | {
        sessions?: undefined;
        sessionId?: undefined;
        command: "set_model";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
    } | {
        sessions?: undefined;
        sessionId?: undefined;
        command: "set_thinking";
        session: {
            readonly id: string;
            readonly name?: string | undefined;
            readonly cwd: string;
            readonly createdAt: number;
            readonly updatedAt: number;
            readonly phase: "branch_summary" | "compaction" | "idle" | "retry" | "turn";
            readonly model: {
                readonly provider: string;
                readonly id: string;
            };
            readonly thinkingLevel: "high" | "low" | "max" | "medium" | "minimal" | "off" | "xhigh";
            readonly attached: boolean;
            readonly locked: boolean;
            readonly revision: number;
            readonly transcript: ({
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "streaming";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly stopReason: "length" | "stop" | "toolUse";
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly stopReason: "error";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "assistant";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "thinking";
                    readonly thinking: string;
                    readonly redacted?: boolean | undefined;
                } | {
                    readonly type: "toolCall";
                    readonly toolCallId: string;
                    readonly toolName: string;
                    readonly input: import("@cortexagent/protocol").JsonValue;
                })[];
                readonly model: {
                    readonly provider: string;
                    readonly id: string;
                };
                readonly responseModel?: string | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "aborted";
                readonly stopReason: "aborted";
                readonly errorMessage?: string | undefined;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "running";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "complete";
                readonly isError: false;
            } | {
                readonly id: string;
                readonly role: "tool";
                readonly toolCallId: string;
                readonly toolName: string;
                readonly input: import("@cortexagent/protocol").JsonValue;
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly details?: import("@cortexagent/protocol").JsonValue | undefined;
                readonly usage?: {
                    readonly input: number;
                    readonly output: number;
                    readonly cacheRead: number;
                    readonly cacheWrite: number;
                    readonly reasoning?: number | undefined;
                    readonly totalTokens: number;
                    readonly cost: {
                        readonly input: number;
                        readonly output: number;
                        readonly cacheRead: number;
                        readonly cacheWrite: number;
                        readonly total: number;
                    };
                } | undefined;
                readonly timestamp: number;
                readonly status: "error";
                readonly isError: true;
            })[];
            readonly queuedSteer: {
                readonly id: string;
                readonly role: "user";
                readonly content: ({
                    readonly type: "text";
                    readonly text: string;
                } | {
                    readonly type: "image";
                    readonly data: string;
                    readonly mimeType: string;
                })[];
                readonly timestamp: number;
            }[];
            readonly queuedSteerCount: number;
        };
    }>;
    disconnect(connection: ConnectionState): Promise<void>;
    listMetadata(): Promise<SessionMetadata[]>;
    close(): Promise<void>;
    private runOperation;
    private acquire;
    private create;
    private handleRuntimeEvent;
    private terminate;
    private normalizedSnapshot;
    private forConnection;
    private broadcastSnapshot;
    private attach;
    private requireAttached;
    private scheduleMaybeDispose;
    private maybeDispose;
}
export {};
//# sourceMappingURL=sessions.d.ts.map