export interface WordNavigationOptions {
    segment?: (text: string) => Iterable<Intl.SegmentData>;
    isAtomicSegment?: (segment: string) => boolean;
}
export declare function findWordBackward(text: string, cursor: number, options?: WordNavigationOptions): number;
export declare function findWordForward(text: string, cursor: number, options?: WordNavigationOptions): number;
//# sourceMappingURL=word-navigation.d.ts.map