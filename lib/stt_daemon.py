#!/usr/bin/env python3
"""stt_daemon — CortexAgent speech-to-text daemon.

Capture modes (both can run at once):
  hotkey  — hold Ctrl+Shift+Space to record, release to transcribe+type
  vad     — always listening; speech onset/offset via RMS energy (Task 6)

Control: Unix socket ~/.cortexagent/state/stt.sock (Task 7)
State:   ~/.cortexagent/state/stt_daemon.json (Task 7)

Usage:
    python3 lib/stt_daemon.py            # run daemon (hotkey + vad per config)
    python3 lib/stt_daemon.py --test     # record 2s, transcribe, print (no typing)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1


def _mic_device() -> str:
    from lib.config import CFG
    return CFG.stt_mic_device


def record_clip(seconds: float = 2.0) -> np.ndarray:
    """Record `seconds` of audio from the configured mic (16kHz mono float32)."""
    import sounddevice as sd
    frames = int(SAMPLE_RATE * seconds)
    data = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS,
                  dtype="float32", device=_mic_device())
    sd.wait()
    return data[:, 0]


def type_text(text: str) -> None:
    """Type text at the cursor via xdotool (works in any X11 app)."""
    subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "1", text],
                   check=False)


def _key_name(key) -> str:
    from pynput import keyboard
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    if isinstance(key, keyboard.KeyCode):
        return key.char or f"<{key.vk}>"
    return str(key)


class HotkeyListener:
    """Hold-to-talk: fires on_start when the combo is fully pressed, on_stop
    when any key in the combo releases."""

    def __init__(self, combo: set, on_start, on_stop):
        self.combo = combo
        self.on_start = on_start
        self.on_stop = on_stop
        self.pressed: set = set()
        self.active = False

    def on_press(self, key):
        name = _key_name(key)
        if name in self.combo:
            self.pressed.add(name)
            if not self.active and self.pressed == self.combo:
                self.active = True
                self.on_start()

    def on_release(self, key):
        name = _key_name(key)
        if name in self.combo:
            self.pressed.discard(name)
            if self.active:
                self.active = False
                self.on_stop()


def _parse_hotkey(hotkey: str) -> set:
    """'<ctrl>+<shift>+space' → {'<ctrl>', '<shift>', '<space>'}."""
    return {part.strip().lower() for part in hotkey.split("+") if part.strip()}


def _handle_clip(clip: np.ndarray) -> None:
    """Transcribe + cleanup + type a recorded clip."""
    from lib import stt
    text = stt.transcribe_and_cleanup(clip)
    if text:
        type_text(text)


def run_hotkey() -> None:
    from pynput import keyboard
    from lib.config import CFG
    combo = _parse_hotkey(CFG.stt_hotkey)
    listener = HotkeyListener(combo, on_start=_start_recording, on_stop=_stop_recording)
    with keyboard.Listener(on_press=listener.on_press,
                           on_release=listener.on_release) as kl:
        kl.join()


_recorder = {"stream": None, "frames": []}


def _start_recording() -> None:
    import sounddevice as sd
    _recorder["frames"] = []
    _recorder["stream"] = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
        device=_mic_device(), callback=_record_cb)
    _recorder["stream"].start()
    print("🔴 recording…", flush=True)


def _record_cb(indata, frames, time_info, status):
    _recorder["frames"].append(indata.copy())


def _stop_recording() -> None:
    stream = _recorder.get("stream")
    if stream is None:
        return
    stream.stop()
    stream.close()
    _recorder["stream"] = None
    if _recorder["frames"]:
        clip = np.concatenate(_recorder["frames"])[:, 0]
        print("⏹ transcribing…", flush=True)
        _handle_clip(clip)


def _test() -> int:
    print("🎙️ recording 2s…", flush=True)
    clip = record_clip(2.0)
    from lib import stt
    text = stt.transcribe_and_cleanup(clip)
    print(f"transcribed: {text!r}")
    return 0 if text.strip() else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="CortexAgent STT daemon")
    ap.add_argument("--test", action="store_true", help="record 2s + transcribe (no typing)")
    args = ap.parse_args()
    if args.test:
        return _test()
    run_hotkey()
    return 0


if __name__ == "__main__":
    sys.exit(main())
