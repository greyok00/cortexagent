
from typing import Optional
from .types import TaskStatus, ProgressEvent, EngineType


ENGINE_ICONS = {
    EngineType.LLM_REASONING: "🧠",
    EngineType.LLM_CODE: "💻",
    EngineType.WEB_RESEARCH: "🌐",
    EngineType.IMAGE_GEN: "🎨",
    EngineType.SYSTEM_EXEC: "⚙️",
    EngineType.DOCKER: "🐳",
    EngineType.FILE_OPS: "📁",
}

STATUS_ICONS = {
    TaskStatus.PENDING: "⏳",
    TaskStatus.RUNNING: "⚡",
    TaskStatus.COMPLETED: "✅",
    TaskStatus.FAILED: "❌",
    TaskStatus.SKIPPED: "⏭️",
    TaskStatus.RETRYING: "🔄",
}


class ProgressRenderer:


    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.events: list[ProgressEvent] = []
        self.phase_status: dict[str, str] = {}

    def on_progress(self, event: ProgressEvent) -> None:

        self.events.append(event)
        self.phase_status[event.phase] = event.status.name

    def render_header(self, title: str) -> str:

        lines = [
            "┌" + "─" * 70 + "┐",
            f"│ 🚀 CORTEX AGENT | {title:<53} │",
            "├" + "─" * 70 + "┤",
        ]
        return "\n".join(lines)

    def render_progress_bar(self, pct: float, width: int = 40) -> str:

        filled = int(pct * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {int(pct * 100)}%"

    def render_pipeline(self, phases: list[str]) -> str:

        parts = []
        for phase in phases:
            status = self.phase_status.get(phase, "PENDING")
            icon = {"COMPLETED": "✅", "RUNNING": "⚡", "PENDING": "⏳", "FAILED": "❌"}.get(status, "⏳")
            parts.append(f"[{icon} {phase.title()}]")
        return " ──► ".join(parts)

    def render_batch(self, engine: EngineType, tasks: list, active_id: Optional[str] = None) -> str:

        icon = ENGINE_ICONS.get(engine, "❓")
        lines = [f"\n  {icon} {engine.name} Batch ({len(tasks)} tasks):"]
        for task in tasks:
            status_icon = STATUS_ICONS.get(task.status, "⏳")
            name = task.name
            marker = " ← active" if task.id == active_id else ""
            lines.append(f"    {status_icon} {name}{marker}")
        return "\n".join(lines)

    def render_summary(self, total: int, completed: int, failed: int) -> str:

        lines = [
            "\n" + "├" + "─" * 70 + "┤",
            f"│ 📊 Summary: {completed}/{total} tasks completed",
        ]
        if failed:
            lines.append(f"│ ❌ {failed} tasks failed")
        lines.append("└" + "─" * 70 + "┘")
        return "\n".join(lines)

    def render(self, title: str, phases: list[str], total: int, completed: int, failed: int) -> str:

        parts = [
            self.render_header(title),
            self.render_pipeline(phases),
        ]


        pct = completed / total if total > 0 else 0
        parts.append(f"\n  OVERALL: {self.render_progress_bar(pct)}")


        parts.append(self.render_summary(total, completed, failed))

        return "\n".join(parts)
