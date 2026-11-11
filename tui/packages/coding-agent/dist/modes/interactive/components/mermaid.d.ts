import type { MarkdownTransformer } from "../../../core/extensions/types.ts";
import type { MermaidRenderingMode } from "../../../core/settings-manager.ts";
import type { Theme } from "../theme/theme.ts";
interface MermaidTransformerOptions {
    getMode: () => MermaidRenderingMode;
    theme?: Theme;
}
export declare function createMermaidMarkdownTransformer(options: MermaidTransformerOptions): MarkdownTransformer;
export {};
//# sourceMappingURL=mermaid.d.ts.map