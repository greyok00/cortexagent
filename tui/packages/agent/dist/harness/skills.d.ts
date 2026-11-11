import { type ExecutionEnv, type Skill } from "./types.ts";
export type SkillDiagnosticCode = "file_info_failed" | "list_failed" | "read_failed" | "parse_failed" | "invalid_metadata";
export interface SkillDiagnostic {
    type: "warning";
    code: SkillDiagnosticCode;
    message: string;
    path: string;
}
export declare function formatSkillInvocation(skill: Skill, additionalInstructions?: string): string;
export declare function loadSkills(env: ExecutionEnv, dirs: string | string[]): Promise<{
    skills: Skill[];
    diagnostics: SkillDiagnostic[];
}>;
export declare function loadSourcedSkills<TSource, TSkill extends Skill = Skill>(env: ExecutionEnv, inputs: Array<{
    path: string;
    source: TSource;
}>, mapSkill?: (skill: Skill, source: TSource) => TSkill): Promise<{
    skills: Array<{
        skill: TSkill;
        source: TSource;
    }>;
    diagnostics: Array<SkillDiagnostic & {
        source: TSource;
    }>;
}>;
//# sourceMappingURL=skills.d.ts.map