import type { ResourceDiagnostic } from "./diagnostics.ts";
import { type SourceInfo } from "./source-info.ts";
export interface SkillFrontmatter {
    name?: string;
    description?: string;
    "disable-model-invocation"?: boolean;
    [key: string]: unknown;
}
export interface Skill {
    name: string;
    description: string;
    filePath: string;
    baseDir: string;
    sourceInfo: SourceInfo;
    disableModelInvocation: boolean;
}
export interface LoadSkillsResult {
    skills: Skill[];
    diagnostics: ResourceDiagnostic[];
}
export interface LoadSkillsFromDirOptions {
    dir: string;
    source: string;
}
export declare function loadSkillsFromDir(options: LoadSkillsFromDirOptions): LoadSkillsResult;
export declare function formatSkillsForPrompt(skills: Skill[]): string;
export interface LoadSkillsOptions {
    cwd: string;
    agentDir: string;
    skillPaths: string[];
    includeDefaults: boolean;
}
export declare function loadSkills(options: LoadSkillsOptions): LoadSkillsResult;
//# sourceMappingURL=skills.d.ts.map