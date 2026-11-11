export interface CortexManifest {
    extensions?: string[];
    skills?: string[];
    prompts?: string[];
    themes?: string[];
}
export declare function readCortexManifest(packageJsonPath: string): CortexManifest | null;
//# sourceMappingURL=cortex-manifest.d.ts.map