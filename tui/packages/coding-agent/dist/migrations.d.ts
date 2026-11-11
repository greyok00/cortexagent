export declare function migrateAuthToAuthJson(): string[];
export declare function migrateSessionsFromAgentRoot(): void;
export declare function showDeprecationWarnings(warnings: string[]): Promise<void>;
export declare function runMigrations(cwd: string): {
    migratedAuthProviders: string[];
    deprecationWarnings: string[];
};
//# sourceMappingURL=migrations.d.ts.map