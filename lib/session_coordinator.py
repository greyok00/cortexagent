"""
session_coordinator.py — Inter-session coordination for CortexAgent.

Prevents sessions from stepping on each other's toes by:
1. Broadcasting session status/last activity to a shared state file
2. Reading other session's last activity before acting
3. Logging session awareness in memory so all sessions see the context

Usage:
  coordinator = SessionCoordinator()
  coordinator.broadcast(status="working", task="memory refactor")
  others = coordinator.poll()  # returns list of {session, status, last_seen}
  coordinator.log_awareness("claude active")  # writes to hot memory with awareness header
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional


# Shared state file (all sessions read/write this)
SESSION_STATE_FILE = Path.home() / ".config/cortexllm/memory/session_state.json"


class SessionCoordinator:
    """Manages inter-session awareness via shared state file."""

    def __init__(self, session_name: str = "cortexagent"):
        self.session_name = session_name
        self.state_file = SESSION_STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def _read_state(self) -> dict:
        """Read current session state."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {"sessions": {}}

    def _write_state(self, state: dict) -> None:
        """Atomic write to session state file."""
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.rename(self.state_file)
        except OSError:
            pass

    def broadcast(self, status: str = "idle", task: str = None,
                  metadata: dict = None) -> dict:
        """Broadcast this session's status to all other sessions.

        Other sessions will see this entry when they poll().

        Args:
            status: "idle", "working", "thinking", "blocked", etc.
            task: Brief description of what you're doing
            metadata: Extra context (platform, session_id, etc.)
        """
        state = self._read_state()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        state["sessions"][self.session_name] = {
            "status": status,
            "task": task or "idle",
            "last_seen": now,
            "metadata": metadata or {},
        }
        state["_last_updated"] = now
        self._write_state(state)
        return {"status": "broadcast", "session": self.session_name}

    def poll(self) -> List[Dict]:
        """Read all session states. Returns list sorted by last_seen (newest first)."""
        state = self._read_state()
        sessions = []
        for name, info in state.get("sessions", {}).items():
            sessions.append({
                "session": name,
                **info,
                "is_local": name == self.session_name,
            })
        # Sort by last_seen descending
        sessions.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
        return sessions

    def is_active(self, session: str = "claude", within_seconds: int = 300) -> bool:
        """Check if another session is recently active."""
        sessions = self.poll()
        for s in sessions:
            if s["session"] == session and not s["is_local"]:
                last_seen = s.get("last_seen", "")
                try:
                    last_ts = time.mktime(time.strptime(last_seen, "%Y-%m-%d %H:%M:%S"))
                    if (time.time() - last_ts) < within_seconds:
                        return True
                except ValueError:
                    pass
        return False

    def log_awareness(self, message: str, level: str = "info") -> dict:
        """Write an awareness log entry to hot memory that all sessions can read.

        This ensures the conversation context includes inter-session awareness.

        Args:
            message: What to log (e.g., "claude active, checking their work")
            level: "info", "warn", "critical"
        """
        # Write to our own hot memory with awareness header
        from lib.memory_thin import append

        awareness_msg = (
            f"[SESSION-AWARENESS] {level}: {message}\n"
            f"  (cortexagent at {time.strftime('%H:%M:%S')})"
        )
        path = append(awareness_msg, role="system")

        # Also broadcast to state file
        self.broadcast(status="aware", task=message[:40])

        return {"status": "logged", "path": str(path)}

    def get_other_sessions(self) -> List[Dict]:
        """Get list of other sessions (not this one) with status."""
        return [s for s in self.poll() if not s["is_local"]]

    def summarize_activity(self) -> str:
        """Summarize what other sessions are doing for quick reference."""
        sessions = self.get_other_sessions()
        if not sessions:
            return "No other active sessions detected."

        lines = [f"Other sessions ({len(sessions)}):"]
        for s in sessions[:5]:  # Top 5
            lines.append(
                f"  - {s['session']}: {s['status']} "
                f"({s['task'][:40]}...)"
            )
        return "\n".join(lines)


# Singleton for easy access
_coordinator = None


def get_coordinator(session_name: str = "cortexagent") -> SessionCoordinator:
    """Get or create the session coordinator singleton."""
    global _coordinator
    if _coordinator is None or _coordinator.session_name != session_name:
        _coordinator = SessionCoordinator(session_name)
    return _coordinator


if __name__ == "__main__":
    # Test the coordinator
    c = SessionCoordinator("cortexagent")

    # Simulate other session
    c.broadcast(status="working", task="memory refactor")
    time.sleep(0.1)

    # Simulate another session (in reality, this would be claude.jsonl)
    state = c._read_state()
    state["sessions"]["claude"] = {
        "status": "idle",
        "task": "reading",
        "last_seen": "2026-08-16 20:50:00",
    }
    c._write_state(state)

    # Check what's out there
    others = c.get_other_sessions()
    print("Other sessions:", others)

    # Log awareness
    c.log_awareness("claude idle, cortexagent working on memory refactor")
    print("Awareness logged")

    # Summarize
    print("\n" + c.summarize_activity())

    print("\nSession coordinator OK")
