#!/usr/bin/env python3
"""lib/scheduler/ui.py — Scheduler UI components for Pi/WebUI/CLI/tray.

Provides:
  1. Canonical scheduler strip (compact display)
  2. Expanded view (next 5 tasks with actions)
  3. Test task filtering (ephemeral=true hidden in normal mode)
  4. Malformed label sanitization
  5. Colorblind-safe glyph + color pairs

Design:
  Compact strip format:
    ● Scheduler · 6 active · q 2 · next: nightly smoke @ 22:00 · ! 1 failed

  Expanded view:
    Next 5 tasks (title, state, next_run) + actions (pause, resume, run, cancel)

  Test tasks:
    kind=test, ephemeral=true → hidden in normal mode
    Visible only in dev diagnostics mode
"""
import re
import html
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def sanitize_title(title: str, max_len: int = 40) -> str:
    """Sanitize task title for display.
    
    - Strip ANSI escape sequences
    - Strip control characters
    - Truncate to max_len
    - Replace dangerous characters
    """
    # Strip ANSI escape sequences
    title = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', title)
    # Strip cron-like wildcards (*, /, -) that leak through
    title = re.sub(r'[*/]', '', title)
    # Strip control characters (keep spaces, tabs, printable)
    title = ''.join(c for c in title if ord(c) >= 32 or c in ('\t', '\n'))
    # Truncate
    if len(title) > max_len:
        title = title[:max_len].rstrip() + '…'
    # HTML-escape
    title = html.escape(title)
    return title


def format_time(time_str: Optional[str], now: Optional[datetime] = None) -> str:
    """Format time string for display.
    
    Shows relative time if within 24h, absolute if further.
    """
    if not time_str:
        return "?"
    
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        now = now or datetime.now(timezone.utc)
        diff = dt - now
        
        if abs(diff.total_seconds()) < 60:
            return "now"
        elif abs(diff.total_seconds()) < 3600:
            mins = int(abs(diff.total_seconds()) / 60)
            return f"{mins}m {'ago' if diff.total_seconds() < 0 else 'in'}"
        elif abs(diff.total_seconds()) < 86400:
            hours = int(abs(diff.total_seconds()) / 3600)
            return f"{hours}h {'ago' if diff.total_seconds() < 0 else 'in'}"
        else:
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return time_str[:16]


# ── Status Glyphs (colorblind-safe) ──────────────────────────────────────────

STATUS_GLYPHS = {
    "scheduled": ("◌", "muted"),    # Pending
    "queued": ("◍", "info"),        # Firing
    "running": ("◍", "info"),       # Running
    "succeeded": ("✓", "success"),  # Done
    "failed": ("✕", "danger"),      # Error
    "paused": ("○", "muted"),       # Idle
    "canceled": ("✕", "muted"),     # Cancelled
    "archived": ("▤", "muted"),     # Archived
    "interrupted": ("✕", "warn"),   # Interrupted
    "retry_wait": ("⧖", "warn"),    # Waiting for retry
}

STATUS_COLORS = {
    "success": (108, "#9ECE6A"),   # Soft green
    "warn": (179, "#E0AF68"),      # Warm amber
    "danger": (203, "#F7768E"),    # Muted red-pink
    "info": (111, "#7AA2F7"),      # Sky blue
    "muted": (60, "#565F89"),      # Slate
}


def status_glyph(state: str) -> str:
    """Get glyph for task state."""
    return STATUS_GLYPHS.get(state, ("?", "muted"))[0]


def status_color(state: str) -> tuple:
    """Get (256-color index, RGB hex) for task state."""
    color_name = STATUS_GLYPHS.get(state, ("?", "muted"))[1]
    return STATUS_COLORS.get(color_name, (60, "#565F89"))


# ── Scheduler Strip ──────────────────────────────────────────────────────────

def scheduler_strip(tasks: List[Dict], queue_depth: int = 0,
                    failed_count: int = 0,
                    dev_mode: bool = False) -> str:
    """Render canonical scheduler strip.
    
    Compact format:
      ● Scheduler · 6 active · q 2 · next: nightly smoke @ 22:00 · ! 1 failed
    
    Args:
        tasks: List of task dicts (from store.list())
        queue_depth: Number of tasks in queue
        failed_count: Number of failed tasks
        dev_mode: Show test tasks and ephemeral
    
    Returns:
        Single-line string for display in Pi/CLI/tray/WebUI
    """
    # Filter tasks
    if not dev_mode:
        tasks = [t for t in tasks if not (t.get("kind") == "test" and t.get("ephemeral", False))]
    
    # Count by state
    active = len([t for t in tasks if t.get("state") in ("scheduled", "queued", "running")])
    failed = len([t for t in tasks if t.get("state") == "failed"])
    paused = len([t for t in tasks if t.get("state") == "paused"])
    
    # Find next scheduled
    next_task = None
    next_run_time = None
    for t in sorted(tasks, key=lambda x: x.get("next_run_at") or "9999"):
        if t.get("state") in ("scheduled", "queued") and t.get("enabled", True):
            if not dev_mode and t.get("kind") == "test" and t.get("ephemeral"):
                continue
            next_task = t.get("title", "unknown")
            next_run_time = t.get("next_run_at")
            break
    
    # Build components
    components = ["● Scheduler"]
    components.append(f"{active} active")
    components.append(f"q {queue_depth}")
    if paused > 0:
        components.append(f"⏸ {paused}")
    if next_task and next_run_time:
        time_display = format_time(next_run_time)
        components.append(f"next: {sanitize_title(next_task, 20)} @ {time_display}")
    if failed > 0 or failed_count > 0:
        total_failed = failed + failed_count
        components.append(f"! {total_failed} failed")
    
    return " · ".join(components)


# ── Expanded View ────────────────────────────────────────────────────────────

def scheduler_expanded(tasks: List[Dict], max_show: int = 5,
                       dev_mode: bool = False) -> List[str]:
    """Render expanded scheduler view (next N tasks with actions).
    
    Returns list of lines for multi-line display.
    """
    # Filter and sort
    if not dev_mode:
        tasks = [t for t in tasks if not (t.get("kind") == "test" and t.get("ephemeral", False))]
    
    tasks = sorted(tasks, key=lambda x: x.get("next_run_at") or "9999")[:max_show]
    
    lines = []
    lines.append("  ╭───────────────────────────────────────────────────────────╮")
    lines.append("  │ Scheduler (expanded)                                      │")
    lines.append("  ├───────────────────────────────────────────────────────────┤")
    
    for i, task in enumerate(tasks):
        title = sanitize_title(task.get("title", "unnamed"), 30)
        state = task.get("state", "unknown")
        glyph = status_glyph(state)
        time_display = format_time(task.get("next_run_at"))
        
        # Actions
        actions = []
        if state in ("scheduled", "paused"):
            actions.append("resume")
        elif state == "queued":
            actions.append("run")
        elif state in ("failed", "interrupted"):
            actions.append("retry")
        if state not in ("succeeded", "canceled", "archived"):
            actions.append("cancel")
        actions_str = ",".join(actions) if actions else "—"
        
        # Format line
        line = f"  │ {glyph} {title:<30} {state:<12} {time_display:<15} [{actions_str}] "
        if i < len(tasks) - 1:
            line += "│"
        else:
            line += "│"
        lines.append(line)
    
    lines.append("  ╰───────────────────────────────────────────────────────────╯")
    
    return lines


# ── SchedulerUI Class ───────────────────────────────────────────────────────

class SchedulerUI:
    """Scheduler UI component factory."""
    
    def __init__(self, tasks=None, queue_depth=0, failed_count=0):
        self.tasks = tasks or []
        self.queue_depth = queue_depth
        self.failed_count = failed_count
    
    def render_strip(self, dev_mode=False):
        return scheduler_strip(self.tasks, self.queue_depth, self.failed_count, dev_mode)
    
    def render_expanded(self, max_show=5, dev_mode=False):
        return scheduler_expanded(self.tasks, max_show, dev_mode)
    
    def render_test_summary(self):
        return format_test_task_summary(self.tasks)


# ── Test Task Helpers ────────────────────────────────────────────────────────

def is_test_task(task: Dict) -> bool:
    """Check if task is a test/fixture task."""
    return task.get("kind") == "test" and task.get("ephemeral", False)


def format_test_task_summary(tasks: List[Dict]) -> str:
    """Format summary of test tasks (for dev diagnostics)."""
    test_tasks = [t for t in tasks if is_test_task(t)]
    if not test_tasks:
        return "  No test tasks"
    
    lines = []
    lines.append("  ╭───────────────────────────────────────────────────────────╮")
    lines.append("  │ Test Tasks (dev mode)                                     │")
    lines.append("  ├───────────────────────────────────────────────────────────┤")
    
    for task in test_tasks[:10]:
        title = sanitize_title(task.get("title", "unnamed"), 30)
        state = task.get("state", "unknown")
        lines.append(f"  │ • {title:<30} {state:<12} │")
    
    lines.append("  ╰───────────────────────────────────────────────────────────╯")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Self-test and demo."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        print("Scheduler UI smoke tests:")
        
        # Test sanitize_title
        title = sanitize_title("smoke-test (0 9 * * *)", max_len=40)
        assert "smoke-test" in title
        assert "*" not in title
        print(f"  ✅ sanitize_title: '{title}'")
        
        # Test format_time
        now = datetime.now(timezone.utc)
        future = (now.replace(hour=9, minute=0, second=0)).isoformat()
        time_display = format_time(future)
        print(f"  ✅ format_time: '{time_display}'")
        
        # Test scheduler_strip
        tasks = [
            {"title": "daily backup", "state": "scheduled", "enabled": True,
             "next_run_at": (datetime.now(timezone.utc).replace(hour=2, minute=0)).isoformat()},
            {"title": "verify-test", "state": "scheduled", "enabled": True,
             "next_run_at": (datetime.now(timezone.utc).replace(hour=3, minute=0)).isoformat(),
             "kind": "test", "ephemeral": True},
        ]
        strip_normal = scheduler_strip(tasks, queue_depth=2, failed_count=1)
        strip_dev = scheduler_strip(tasks, queue_depth=2, failed_count=1, dev_mode=True)
        
        assert "verify-test" not in strip_normal, "Test task leaked into normal strip"
        # In dev mode, test tasks are included in the count
        assert "2 active" in strip_dev, f"Expected 2 active in dev mode, got: {strip_dev}"
        assert "1 active" in strip_normal, f"Expected 1 active in normal mode, got: {strip_normal}"
        print(f"  ✅ scheduler_strip (normal): '{strip_normal}'")
        print(f"  ✅ scheduler_strip (dev): '{strip_dev}'")
        
        # Test expanded view
        expanded = scheduler_expanded(tasks[:1])
        assert len(expanded) > 2
        print(f"  ✅ scheduler_expanded: {len(expanded)} lines")
        
        # Test test task helpers
        test_task = {"kind": "test", "ephemeral": True}
        assert is_test_task(test_task)
        print(f"  ✅ is_test_task: {is_test_task(test_task)}")
        
        print("\n✅ All scheduler UI tests passed")
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "strip":
        # Demo scheduler strip
        tasks = [
            {"title": "daily backup", "state": "scheduled", "enabled": True,
             "next_run_at": (datetime.now(timezone.utc).replace(hour=9, minute=0)).isoformat()},
        ]
        print(scheduler_strip(tasks, queue_depth=0, failed_count=0))
        return
    
    print("usage: ui.py smoke | strip", file=sys.stderr)


if __name__ == "__main__":
    main()
