"""lib/overseer_dashboard — the fixed-size Overseer companion application.

Entry points:
  - ``open_dashboard()``   open the window (blocking)
  - ``open_in_thread()``   open the window in a background thread
  - ``main()``             CLI entry

The old ``lib/tray_dashboard.py`` is now a thin shim that re-exports these
so the tray menu keeps working unchanged.
"""
from __future__ import annotations

from .ui import open_dashboard, open_in_thread, main  # noqa: F401

__all__ = ["open_dashboard", "open_in_thread", "main"]
