import { type TUnsafe } from "typebox";
export declare function StringEnum<T extends readonly string[]>(values: T, options?: {
    description?: string;
    default?: T[number];
}): TUnsafe<T[number]>;
//# sourceMappingURL=typebox-helpers.d.ts.map