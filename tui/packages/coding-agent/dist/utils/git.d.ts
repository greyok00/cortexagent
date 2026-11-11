export type GitSource = {
    type: "git";
    repo: string;
    host: string;
    path: string;
    ref?: string;
    pinned: boolean;
};
export declare function parseGitUrl(source: string): GitSource | null;
//# sourceMappingURL=git.d.ts.map