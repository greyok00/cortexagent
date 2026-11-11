import { Type } from "typebox";
export function StringEnum(values, options) {
    return Type.Unsafe({
        type: "string",
        enum: values,
        ...(options?.description && { description: options.description }),
        ...(options?.default && { default: options.default }),
    });
}
//# sourceMappingURL=typebox-helpers.js.map