"""CortexAgent Workflow Engine — DAG Scheduler with Topological Sort"""
from collections import defaultdict, deque
from typing import Optional
from .types import Task, TaskStatus, EngineType, BatchGroup


class DAGScheduler:
    """Directed Acyclic Graph scheduler for task execution planning."""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.dependencies: dict[str, list[str]] = {}  # task_id -> [dependency_ids]
        self.dependents: dict[str, list[str]] = {}    # task_id -> [dependent_ids]

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task
        self.dependencies[task.id] = list(task.depends_on)
        for dep_id in task.depends_on:
            if dep_id not in self.dependents:
                self.dependents[dep_id] = []
            self.dependents[dep_id].append(task.id)

    def _topological_sort(self) -> list[str]:
        """Kahn's algorithm for topological sort. Returns task IDs in execution order."""
        in_degree = {tid: len(deps) for tid, deps in self.dependencies.items()}
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        result = []

        while queue:
            tid = queue.popleft()
            result.append(tid)
            for dep_id in self.dependents.get(tid, []):
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)

        if len(result) != len(self.tasks):
            cycle = set(self.tasks.keys()) - set(result)
            raise ValueError(f"Cycle detected in DAG involving tasks: {cycle}")
        return result

    def detect_cycles(self) -> Optional[list[str]]:
        """Detect if there are cycles. Returns cycle nodes or None."""
        try:
            self._topological_sort()
            return None
        except ValueError as e:
            return list(e.args[0].split(": ")[1].strip("{}").split(", "))

    def get_ready_tasks(self, completed: set[str]) -> list[Task]:
        """Get tasks whose dependencies are all completed."""
        ready = []
        for tid, task in self.tasks.items():
            if task.status == TaskStatus.PENDING:
                deps = self.dependencies[tid]
                if all(d in completed for d in deps):
                    ready.append(task)
        return ready

    def batch_by_engine(self, tasks: list[Task]) -> list[BatchGroup]:
        """Group ready tasks by engine type for batch execution."""
        groups: dict[EngineType, list[Task]] = defaultdict(list)
        for task in tasks:
            groups[task.engine].append(task)

        return [
            BatchGroup(engine=engine, tasks=group_tasks, batch_id=f"batch_{engine.name}")
            for engine, group_tasks in sorted(groups.items(), key=lambda x: x[0].name)
        ]

    def optimize_schedule(self) -> list[BatchGroup]:
        """Full schedule optimization: topological sort + engine batching."""
        order = self._topological_sort()
        # Group consecutive tasks by engine type where possible
        scheduled: list[BatchGroup] = []
        current_engine: Optional[EngineType] = None
        current_batch: list[Task] = []

        for tid in order:
            task = self.tasks[tid]
            if task.engine != current_engine:
                if current_batch:
                    scheduled.append(BatchGroup(
                        engine=current_engine,
                        tasks=current_batch,
                        batch_id=f"batch_{current_engine.name}_{len(scheduled)}"
                    ))
                current_engine = task.engine
                current_batch = [task]
            else:
                current_batch.append(task)

        if current_batch:
            scheduled.append(BatchGroup(
                engine=current_engine,
                tasks=current_batch,
                batch_id=f"batch_{current_engine.name}_{len(scheduled)}"
            ))

        return scheduled
