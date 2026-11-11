export declare const DEFAULT_MAX_FRAME_LENGTH: number;
export interface FrameDecoderOptions {
    maxFrameLength?: number;
}
export declare class FrameError extends Error {
    constructor(message: string);
}
export declare function encodeFrame(payload: Uint8Array): Uint8Array;
export declare function assertCompleteFrame(frame: Uint8Array, options?: FrameDecoderOptions): void;
export declare class FrameDecoder {
    private readonly header;
    private headerLength;
    private readonly maxFrameLength;
    private payloadBlocks;
    private currentPayloadBlock;
    private currentPayloadBlockLength;
    private expectedPayloadLength;
    private payloadLength;
    private state;
    constructor(options?: FrameDecoderOptions);
    push(chunk: Uint8Array): Uint8Array[];
    end(): void;
    private fail;
}
//# sourceMappingURL=framing.d.ts.map