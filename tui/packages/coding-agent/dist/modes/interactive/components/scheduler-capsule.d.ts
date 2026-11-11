import { type Component } from "@cortexagent/tui";
/**
 * Scheduler capsule — compact, borderless, at most 3 rows (header + 1-2 task rows).
 * Renders nothing when there are no tasks to show.
 */
export declare class SchedulerCapsuleComponent implements Component {
    private _cached?;
    invalidate(): void;
    render(width: number): string[];
}
//# sourceMappingURL=scheduler-capsule.d.ts.map