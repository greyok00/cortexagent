import type { AgentTool } from "@cortexagent/agent-core";
import { Box } from "@cortexagent/tui";
import { type Static, Type } from "typebox";
import type { ToolDefinition } from "../extensions/types.ts";
import { type EditDiffError, type EditDiffResult } from "./edit-diff.ts";
type EditPreview = EditDiffResult | EditDiffError;
type EditRenderState = {
    callComponent?: EditCallRenderComponent;
};
declare const editSchema: Type.TObject<{
    path: Type.TString;
    edits: Type.TArray<Type.TObject<{
        oldText: Type.TString;
        newText: Type.TString;
    }>>;
}>;
export declare const editToolSystemPromptContribution: {
    readonly snippet: "Make precise file edits with exact text replacement, including multiple disjoint edits in one call";
    readonly guidelines: readonly ["Use edit for precise changes (edits[].oldText must match exactly)", "When changing multiple separate locations in one file, use one edit call with multiple entries in edits[] instead of multiple edit calls", "Each edits[].oldText is matched against the original file, not after earlier edits are applied. Do not emit overlapping or nested edits. Merge nearby changes into one edit.", "Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions."];
};
export type EditToolInput = Static<typeof editSchema>;
export interface EditToolDetails {
    diff: string;
    patch: string;
    firstChangedLine?: number;
}
export interface EditOperations {
    readFile: (absolutePath: string) => Promise<Buffer>;
    writeFile: (absolutePath: string, content: string) => Promise<void>;
    access: (absolutePath: string) => Promise<void>;
}
export interface EditToolOptions {
    operations?: EditOperations;
}
type EditCallRenderComponent = Box & {
    preview?: EditPreview;
    previewArgsKey?: string;
    previewPending?: boolean;
    settledError?: boolean;
};
export declare function createEditToolDefinition(cwd: string, options?: EditToolOptions): ToolDefinition<typeof editSchema, EditToolDetails | undefined, EditRenderState>;
export declare function createEditTool(cwd: string, options?: EditToolOptions): AgentTool<typeof editSchema>;
export {};
//# sourceMappingURL=edit.d.ts.map