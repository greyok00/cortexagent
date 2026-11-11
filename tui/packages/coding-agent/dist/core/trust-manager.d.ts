export type ProjectTrustDecision = boolean | null;
export interface ProjectTrustStoreEntry {
    path: string;
    decision: boolean;
}
export interface ProjectTrustUpdate {
    path: string;
    decision: ProjectTrustDecision;
}
export interface ProjectTrustOption {
    label: string;
    trusted: boolean;
    updates: ProjectTrustUpdate[];
    savedPath?: string;
}
export declare function getProjectTrustParentPath(cwd: string): string | undefined;
export declare function getProjectTrustOptions(cwd: string, options?: {
    includeSessionOnly?: boolean;
}): ProjectTrustOption[];
export declare function hasTrustRequiringProjectResources(cwd: string): boolean;
export declare class ProjectTrustStore {
    private trustPath;
    constructor(agentDir: string);
    get(cwd: string): ProjectTrustDecision;
    getEntry(cwd: string): ProjectTrustStoreEntry | null;
    set(cwd: string, decision: ProjectTrustDecision): void;
    setMany(decisions: ProjectTrustUpdate[]): void;
}
//# sourceMappingURL=trust-manager.d.ts.map