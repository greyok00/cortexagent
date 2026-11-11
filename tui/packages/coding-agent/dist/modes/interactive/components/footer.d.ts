import { type Component } from "@cortexagent/tui";
import type { AgentSession } from "../../../core/agent-session.ts";
import type { ReadonlyFooterDataProvider } from "../../../core/footer-data-provider.ts";
export declare function formatTokens(count: number): string;
/**
 * Format tokens with a tiny Unicode block chart
 */
export declare function formatTokensWithChart(count: number, maxCount: number): string;
export declare function formatCwdForFooter(cwd: string, home: string | undefined): string;
export declare class FooterComponent implements Component {
    private autoCompactEnabled;
    private session;
    private footerData;
    constructor(session: AgentSession, footerData: ReadonlyFooterDataProvider);
    setSession(session: AgentSession): void;
    setAutoCompactEnabled(enabled: boolean): void;
    invalidate(): void;
    dispose(): void;
    render(width: number): string[];
}
//# sourceMappingURL=footer.d.ts.map