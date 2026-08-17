"""lib/tray_dashboard.py — thin shim for the Overseer dashboard.

The full fixed-size graphical Overseer companion app now lives in
``lib/overseer_dashboard/``. This module is kept as a compatibility shim so
the tray menu (``lib/tray.py``) keeps working unchanged: it re-exports the
same entry points the old module exposed.
"""
from __future__ import annotations

from lib.overseer_dashboard import open_dashboard, open_in_thread, main  # noqa: F401

__all__ = ["open_dashboard", "open_in_thread", "main"]
