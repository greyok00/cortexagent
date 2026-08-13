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

# Bootstrap: make the repo root importable when spawned as a plain script
# (`python3 lib/stt_daemon.py`), not `-m`. The shell provides it via
# PYTHONPATH, but systemd-spawned processes (the tray) don't — without
# this, `from lib.config import CFG` raises ModuleNotFoundError and the
# daemon dies on start.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1

STATE_FILE = Path.home() / ".cortexagent" / "state" / "stt_daemon.json"
SOCKET_PATH = Path.home() / ".cortexagent" / "state" / "stt.sock"


def _write_state(**updates) -> None:
    import json
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = {}
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _read_state() -> dict:
    import json
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _send_control(command: str, mode: str | None = None) -> dict:
    import json
    import socket
    payload = {"command": command}
    if mode:
        payload["mode"] = mode
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(str(SOCKET_PATH))
            s.sendall(json.dumps(payload).encode())
            resp = s.recv(4096).decode()
    except (ConnectionRefusedError, FileNotFoundError):
        # Stale socket from a previous run — no daemon listening.
        return {"ok": False, "reason": "STT daemon not running"}
    return json.loads(resp) if resp else {"ok": False, "reason": "no response"}


def _mic_device():
    """Configured mic device, or None (sounddevice default) if it's gone.

    A stale device name (e.g. a headset that was unplugged) must not kill
    the daemon — fall back to the system default input.
    """
    import sounddevice as sd
    from lib.config import CFG
    name = CFG.stt_mic_device
    if not name:
        return None
    try:
        sd.query_devices(name, kind="input")
        return name
    except Exception:
        return None


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

    def __init__(self, combo: set, on_start, on_stop, mode_event=None):
        self.combo = combo
        self.on_start = on_start
        self.on_stop = on_stop
        self.mode_event = mode_event
        self.pressed: set = set()
        self.active = False

    def on_press(self, key):
        if self.mode_event is not None and not self.mode_event.is_set():
            return
        name = _key_name(key)
        if name in self.combo:
            self.pressed.add(name)
            if not self.active and self.pressed == self.combo:
                self.active = True
                self.on_start()

    def on_release(self, key):
        if self.mode_event is not None and not self.mode_event.is_set():
            return
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


def run_hotkey(mode_event=None) -> None:
    from pynput import keyboard
    from lib.config import CFG
    combo = _parse_hotkey(CFG.stt_hotkey)
    listener = HotkeyListener(combo, on_start=_start_recording, on_stop=_stop_recording,
                              mode_event=mode_event)
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


def rms(samples: np.ndarray) -> float:
    """Root-mean-square energy of a float32 sample buffer."""
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def vad_capture(on_clip, stop_event=None, mode_event=None, block_sec: float = 0.1) -> None:
    """Continuously listen; call on_clip(clip) when a speech segment ends.

    Speech onset: RMS > threshold. Speech end: `vad_silence_sec` of trailing
    silence. Debounce: a clip shorter than 0.3s is dropped (mic clicks).
    """
    import sounddevice as sd
    from lib.config import CFG
    threshold = CFG.stt_vad_threshold
    silence_limit = max(1, int(CFG.stt_vad_silence_sec / block_sec))
    block = int(SAMPLE_RATE * block_sec)
    speech: list = []
    in_speech = False
    silence_blocks = 0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                        dtype="float32", device=_mic_device(),
                        blocksize=block) as stream:
        while not (stop_event and stop_event.is_set()):
            data, _ = stream.read(block)
            if mode_event is not None and not mode_event.is_set():
                in_speech = False
                speech = []
                silence_blocks = 0
                continue
            if rms(data[:, 0]) > threshold:
                if not in_speech:
                    in_speech = True
                    speech = []
                speech.append(data.copy())
                silence_blocks = 0
            elif in_speech:
                silence_blocks += 1
                speech.append(data.copy())
                if silence_blocks >= silence_limit:
                    clip = np.concatenate(speech)[:, 0]
                    in_speech = False
                    if len(clip) >= int(SAMPLE_RATE * 0.3):
                        on_clip(clip)


def _socket_server(stop_event, mode_events) -> None:
    import json
    import socket
    import threading
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCKET_PATH))
    srv.listen(4)
    modes = {"hotkey": mode_events["hotkey"].is_set(),
             "vad": mode_events["vad"].is_set()}

    while not stop_event.is_set():
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        with conn:
            data = conn.recv(4096).decode()
            try:
                req = json.loads(data)
            except Exception:
                conn.sendall(b'{"ok": false, "reason": "bad json"}')
                continue
            cmd = req.get("command")
            if cmd == "set-mode":
                mode = req.get("mode")
                if mode in ("hotkey", "vad", "both", "off"):
                    modes["hotkey"] = mode in ("hotkey", "both")
                    modes["vad"] = mode in ("vad", "both")
                    if modes["hotkey"]:
                        mode_events["hotkey"].set()
                    else:
                        mode_events["hotkey"].clear()
                    if modes["vad"]:
                        mode_events["vad"].set()
                    else:
                        mode_events["vad"].clear()
                    _write_state(running=True, modes=dict(modes))
                    conn.sendall(b'{"ok": true}')
                else:
                    conn.sendall(b'{"ok": false, "reason": "bad mode"}')
            elif cmd == "stop":
                _write_state(running=False, modes=dict(modes))
                conn.sendall(b'{"ok": true}')
                stop_event.set()
            else:
                conn.sendall(b'{"ok": false, "reason": "unknown command"}')
    srv.close()


def _test() -> int:
    print("🎙️ recording 2s…", flush=True)
    clip = record_clip(2.0)
    from lib import stt
    text = stt.transcribe_and_cleanup(clip)
    print(f"transcribed: {text!r}")
    return 0 if text.strip() else 1


def run() -> int:
    import os
    import threading
    from lib.config import CFG
    stop_event = threading.Event()
    mode_events = {"hotkey": threading.Event(), "vad": threading.Event()}
    mode_events["hotkey"].set()
    if CFG.stt_speak_to_capture:
        mode_events["vad"].set()
    threads = [
        threading.Thread(target=_socket_server, args=(stop_event, mode_events),
                         daemon=True, name="stt-socket"),
        threading.Thread(target=run_hotkey, args=(mode_events["hotkey"],),
                         daemon=True, name="stt-hotkey"),
        threading.Thread(target=vad_capture,
                         args=(_handle_clip, stop_event),
                         kwargs={"mode_event": mode_events["vad"]},
                         daemon=True, name="stt-vad"),
    ]
    for t in threads:
        t.start()
    _write_state(running=True, pid=os.getpid(),
                 modes={"hotkey": mode_events["hotkey"].is_set(),
                        "vad": mode_events["vad"].is_set()})
    try:
        stop_event.wait()  # released by the socket server on "stop"
    except KeyboardInterrupt:
        pass
    _write_state(running=False, modes={"hotkey": False, "vad": False})
    return 0


def control(command: str, mode: str | None = None) -> int:
    import json
    if command == "status":
        print(json.dumps(_read_state(), indent=2))
        return 0
    if not SOCKET_PATH.exists():
        print("STT daemon not running — start it with 'cortexagent voice start'")
        return 1
    resp = _send_control(command, mode)
    print(json.dumps(resp, indent=2))
    return 0 if resp.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="CortexAgent STT daemon")
    ap.add_argument("--test", action="store_true", help="record 2s + transcribe (no typing)")
    ap.add_argument("command", nargs="?", default=None,
                    help="start|stop|status|set-mode")
    ap.add_argument("mode", nargs="?", default=None, help="hotkey|vad|both|off")
    args = ap.parse_args()
    if args.test:
        return _test()
    if args.command == "start":
        import subprocess
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        time.sleep(0.5)
        return control("status")
    if args.command in ("stop", "status", "set-mode"):
        return control(args.command, args.mode)
    return run()


if __name__ == "__main__":
    sys.exit(main())
