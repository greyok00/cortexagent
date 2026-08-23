"""lib/tkinter_strip — Tkinter control strip with circle-icon buttons.

Re-exports the public API so callers can `from lib.tkinter_strip import
CortexStrip`. The actual implementation lives in `strip.py`.
"""
from .strip import CortexStrip, ICON_DIR

__all__ = ["CortexStrip", "ICON_DIR"]
