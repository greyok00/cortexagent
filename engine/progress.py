"""CortexAgent Workflow Engine — Visual Progress Protocol

Renders clean visual progress cards instead of dense terminal output.
Default mode hides code blocks; developer mode expands them.
"""
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
    """Renders workflow progress as clean visual cards."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.events: list[ProgressEvent] = []
        self.phase_status: dict[str, str] = {}

    def on_progress(self, event: ProgressEvent) -> None:
        """Handle a progress event and render appropriate output."""
        self.events.append(event)
        self.phase_status[event.phase] = event.status.name

    def render_header(self, title: str) -> str:
        """Render the workflow header card."""
        lines = [
            "┌" + "─" * 70 + "┐",
            f"│ 🚀 CORTEX AGENT | {title:<53} │",
            "├" + "─" * 70 + "┤",
        ]
        return "\n".join(lines)

    def render_progress_bar(self, pct: float, width: int = 40) -> str:
        """Render a progress bar."""
        filled = int(pct * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {int(pct * 100)}%"

    def render_pipeline(self, phases: list[str]) -> str:
        """Render the pipeline status with phase indicators."""
        parts = []
        for phase in phases:
            status = self.phase_status.get(phase, "PENDING")
            icon = {"COMPLETED": "✅", "RUNNING": "⚡", "PENDING": "⏳", "FAILED": "❌"}.get(status, "⏳")
            parts.append(f"[{icon} {phase.title()}]")
        return " ──► ".join(parts)

    def render_batch(self, engine: EngineType, tasks: list, active_id: Optional[str] = None) -> str:
        """Render a batch group with task statuses."""
        icon = ENGINE_ICONS.get(engine, "❓")
        lines = [f"\n  {icon} {engine.name} Batch ({len(tasks)} tasks):"]
        for task in tasks:
            status_icon = STATUS_ICONS.get(task.status, "⏳")
            name = task.name
            marker = " ← active" if task.id == active_id else ""
            lines.append(f"    {status_icon} {name}{marker}")
        return "\n".join(lines)

    def render_summary(self, total: int, completed: int, failed: int) -> str:
        """Render final summary."""
        lines = [
            "\n" + "├" + "─" * 70 + "┤",
            f"│ 📊 Summary: {completed}/{total} tasks completed",
        ]
        if failed:
            lines.append(f"│ ❌ {failed} tasks failed")
        lines.append("└" + "─" * 70 + "┘")
        return "\n".join(lines)

    def render(self, title: str, phases: list[str], total: int, completed: int, failed: int) -> str:
        """Render full progress view."""
        parts = [
            self.render_header(title),
            self.render_pipeline(phases),
        ]

        # Progress bar
        pct = completed / total if total > 0 else 0
        parts.append(f"\n  OVERALL: {self.render_progress_bar(pct)}")

        # Summary
        parts.append(self.render_summary(total, completed, failed))

        return "\n".join(parts)
