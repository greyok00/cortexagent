
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import tkinter as tk
from tkinter import ttk


_HERE = Path(__file__).resolve().parent
ICON_DIR = _HERE / "icons"



def _load_icon(name: str, size: tuple[int, int] = (28, 28)):

    p = ICON_DIR / name
    if not p.exists():
        return None
    try:
        from PIL import Image, ImageTk  # type: ignore
        img = Image.open(p)
        img = img.resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        try:
            return tk.PhotoImage(file=str(p))
        except Exception:
            return None



def _send_key(key: str) -> bool:

    if not shutil.which("xdotool"):
        return False
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key],
            check=False, timeout=2,
        )
        return True
    except Exception:
        return False


def _send_ctrlandc() -> bool:

    if not shutil.which("xdotool"):
        return False
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+c"],
            check=False, timeout=2,
        )
        return True
    except Exception:
        return False


def _copy_from_clipboard() -> str:


    if shutil.which("xclip"):
        try:
            r = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass

    if shutil.which("xsel"):
        try:
            r = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass

    if shutil.which("wl-paste"):
        try:
            r = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass

    if shutil.which("xdotool"):
        try:

            wid = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            if wid:



                pass
        except Exception:
            pass
    return ""


def _attach_file() -> None:

    if not shutil.which("zenity"):
        return
    try:
        r = subprocess.run(
            ["zenity", "--file-selection", "--title=Attach a file"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0 and r.stdout.strip():
            path = r.stdout.strip()
            if shutil.which("xdotool"):
                subprocess.run(
                    ["xdotool", "type", "--delay", "1", "--clearmodifiers", path],
                    check=False, timeout=5,
                )
    except Exception:
        pass



class _IconButton(tk.Frame):


    def __init__(self, parent, icon_name: str, label: str, command,
                 fg: str = "#e8e0d0", bg: str = "#0d0a07",
                 active_bg: str = "#1a1612", border: str = "#d4a050"):
        super().__init__(parent, bg=bg, padx=4, pady=4)
        self._cmd = command
        self._bg = bg
        self._active_bg = active_bg
        self._border = border
        self._fg = fg


        self.icon_img = _load_icon(icon_name)
        self._icon_label = tk.Label(self, image=self.icon_img, bg=bg, cursor="hand2")
        self._icon_label.pack(side="top", pady=(2, 2))
        self._icon_label.bind("<Button-1>", self._on_click)
        self._icon_label.bind("<Enter>", self._on_enter)
        self._icon_label.bind("<Leave>", self._on_leave)


        self._lbl = tk.Label(self, text=label, bg=bg, fg=fg,
                             font=("Mono", 9, "bold"))
        self._lbl.pack(side="top", pady=(0, 2))
        self._lbl.bind("<Button-1>", self._on_click)

    def _on_click(self, _evt=None):
        try:
            self._cmd()
        except Exception:
            pass

    def _on_enter(self, _evt=None):
        self._bg = self._active_bg
        self.configure(bg=self._bg)
        self._icon_label.configure(bg=self._bg)
        self._lbl.configure(bg=self._bg)

    def _on_leave(self, _evt=None):
        self._bg = self._bg if hasattr(self, "_bg") else "#0d0a07"
        self._bg = self._original_bg
        self.configure(bg=self._bg)
        self._icon_label.configure(bg=self._bg)
        self._lbl.configure(bg=self._bg)

    @property
    def _original_bg(self):
        return getattr(self, "_bg_orig", "#0d0a07")



class CortexStrip(tk.Frame):


    def __init__(self, parent, on_copy=None, **kwargs):





        try:
            from lib.popup_themes import load_settings, get_palette
            _pal = get_palette(load_settings().get("theme", "amber"))
            _bg     = _pal["bg"]
            _accent = _pal["accent"]
            _border = _pal["border"]
            _fg     = _pal["fg"]
        except Exception:
            _bg, _accent, _border, _fg = "#0d0a07", "#d4a050", "#3a3530", "#e8e0d0"
        super().__init__(parent, bg=_bg, **kwargs)
        self._bg = _bg
        self._accent = _accent
        self._border = _border
        self._fg = _fg
        self._on_copy = on_copy
        self._build()

    def _build(self):

        sep = tk.Frame(self, bg=self._border, height=1)
        sep.pack(side="top", fill="x")


        row = tk.Frame(self, bg=self._bg)
        row.pack(side="top", fill="x", padx=8, pady=4)






        _IconButton(
            row, "esc.png", "Esc.",
            command=lambda: _send_key("Escape"),
        ).pack(side="left", expand=True, fill="x", padx=4)


        _IconButton(
            row, "ctrl_c.png", "Ctrl+C",
            command=self._on_copy_click,
        ).pack(side="left", expand=True, fill="x", padx=4)


        _IconButton(
            row, "clip.png", "Attach",
            command=lambda: _attach_file(),
        ).pack(side="left", expand=True, fill="x", padx=4)


        _IconButton(
            row, "enter.png", "Enter",
            command=lambda: _send_key("Return"),
        ).pack(side="left", expand=True, fill="x", padx=4)

    def _on_copy_click(self):

        _send_ctrlandc()

        time.sleep(0.1)
        text = _copy_from_clipboard()
        if text and self._on_copy:
            try:
                self._on_copy(text)
            except Exception:
                pass



def _smoke() -> int:
    fails = 0
    def check(label, ok):
        nonlocal fails
        print(f"  {'✅' if ok else '❌'} {label}")
        if not ok:
            fails += 1

    print("→ tkinter_strip smoke")
    for f in ("esc.png", "ctrl_c.png", "clip.png", "enter.png"):
        check(f"icon {f} exists", (ICON_DIR / f).exists())

    root = tk.Tk()
    root.title("Cortex Strip Smoke")
    root.geometry("800x200")
    root.configure(bg="#0d0a07")
    strip = CortexStrip(root)
    strip.pack(side="bottom", fill="x")


    tk.Label(root, text="(smoke test — close to exit)", bg="#0d0a07",
             fg="#8a7d68").pack(expand=True, fill="both")
    root.update()
    print("  ✅ strip built")
    root.destroy()
    print(f"{'✅ PASS' if fails == 0 else f'❌ {fails} failures'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_smoke())
