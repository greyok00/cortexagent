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
import queue
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


def _daemon_alive() -> bool:
    """True if a daemon is actually listening on the control socket.

    Distinguishes a live daemon from a stale socket file left by a crash.
    Sends a real ``ping`` so the server replies — a bare connect-and-close
    would make the server's ``recv`` return b'' and (before the resilient
    handler) crash its socket thread with BrokenPipeError.
    """
    import socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(str(SOCKET_PATH))
            s.sendall(b'{"command": "ping"}')
            resp = s.recv(4096).decode()
            return '"ok": true' in resp
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


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


# Tokens faster-whisper-base emits when transcribing silence / breath / mic noise.
# We never want these typed into a focused prompt — they're hallucinations.
_GARBAGE_TOKENS = frozenset({
    "", ".", "..", "...", ". .", ". . .", ". . . .", ",", ", ,",
    "uh", "uhh", "uh huh", "um", "umm", "hmm", "huh", "mm",
    "[blank_audio]", "[silence]", "(silence)", "[music]",
})


def _text_is_meaningful(text: str) -> bool:
    """True if `text` is real content, not a Whisper silence hallucination.

    Drops pure-punctuation runs and the small set of breath/filler tokens
    that faster-whisper-base emits on non-speech audio. Everything else —
    including short real words like 'yes' or 'ok' — passes through.
    """
    if not text:
        return False
    # Pure punctuation/whitespace: any combo of ".", ",", " ", "\t", "\n"
    if all(c in "., \t\n" for c in text):
        return False
    normalized = text.strip().lower()
    return normalized not in _GARBAGE_TOKENS
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


_clip_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=8)


def _transcribe_worker() -> None:
    """Transcribe queued clips and type them at the cursor.

    Runs in its own thread so a slow transcription never blocks the VAD
    capture loop — otherwise everything spoken while transcribing is
    dropped (the mic stream isn't read during the synchronous call).
    While the queue is quiet, double as the VRAM idle-monitor: periodically
    let the STT engine free its CUDA model so the big model keeps its memory.
    """
    from lib import stt
    while True:
        try:
            clip = _clip_queue.get(timeout=5.0)
        except queue.Empty:
            stt.unload_if_idle()
            continue
        try:
            text = stt.transcribe_and_cleanup(clip)
            if text and _text_is_meaningful(text):
                type_text(text)
            elif text:
                print(f"  (dropped garbage transcript: {text!r})", flush=True)
        except Exception as e:
            print(f"⚠️ transcribe failed: {e}", flush=True)
        finally:
            _clip_queue.task_done()


def _handle_clip(clip: np.ndarray) -> None:
    """Queue a recorded clip for transcription (non-blocking)."""
    try:
        _clip_queue.put_nowait(clip)
    except queue.Full:
        # Backlog — drop the oldest so we never fall behind the mic.
        try:
            _clip_queue.get_nowait()
        except queue.Empty:
            pass
        _clip_queue.put_nowait(clip)


def run_hotkey(mode_event=None, stop_event=None) -> None:
    from pynput import keyboard
    from lib.config import CFG
    combo = _parse_hotkey(CFG.stt_hotkey)
    listener = HotkeyListener(combo, on_start=_start_recording, on_stop=_stop_recording,
                              mode_event=mode_event)
    with keyboard.Listener(on_press=listener.on_press,
                           on_release=listener.on_release) as kl:
        # Poll for shutdown so the listener is stopped cleanly instead of
        # being killed mid-callback when the process exits (which segfaults).
        while not (stop_event and stop_event.is_set()):
            kl.join(timeout=0.5)
        kl.stop()


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

    Max-length flush: when accumulated speech crosses `stt_vad_max_utterance_sec`
    (default 10s), the clip is committed even without a pause. Stops
    unbounded growth on long monologues and prevents new utterances from
    being absorbed into a clip that hasn't flushed yet.
    """
    import sounddevice as sd
    from lib.config import CFG
    threshold = CFG.stt_vad_threshold
    silence_limit = max(1, int(CFG.stt_vad_silence_sec / block_sec))
    max_utt_sec = max(0.0, float(CFG.stt_vad_max_utterance_sec or 0.0))
    max_utt_blocks = int(max_utt_sec / block_sec) if max_utt_sec > 0 else 0
    block = int(SAMPLE_RATE * block_sec)
    speech: list = []
    speech_blocks = 0  # count of in-speech blocks since current onset
    in_speech = False
    silence_blocks = 0
    while not (stop_event and stop_event.is_set()):
        dev = _mic_device()
        if dev is None and CFG.stt_mic_device:
            # A mic is configured but currently unavailable (unplugged /
            # PipeWire re-enumeration). Wait and retry instead of falling
            # back to a possibly-broken default device — the daemon
            # self-heals the moment the mic returns, no restart needed.
            print("⚠️ mic unavailable — retrying in 2s", flush=True)
            if stop_event:
                stop_event.wait(2.0)
            else:
                time.sleep(2.0)
            continue
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype="float32", device=dev,
                                blocksize=block) as stream:
                while not (stop_event and stop_event.is_set()):
                    data, _ = stream.read(block)
                    if mode_event is not None and not mode_event.is_set():
                        in_speech = False
                        speech = []
                        speech_blocks = 0
                        silence_blocks = 0
                        continue
                    if rms(data[:, 0]) > threshold:
                        if not in_speech:
                            in_speech = True
                            speech = []
                            speech_blocks = 0
                        speech.append(data.copy())
                        speech_blocks += 1
                        silence_blocks = 0
                    elif in_speech:
                        silence_blocks += 1
                        speech.append(data.copy())
                        speech_blocks += 1
                        if silence_blocks >= silence_limit:
                            clip = np.concatenate(speech)[:, 0]
                            in_speech = False
                            if len(clip) >= int(SAMPLE_RATE * 0.3):
                                on_clip(clip)
                            speech = []
                            speech_blocks = 0
                            continue
                    # Max-length flush — fires when user has been talking
                    # continuously past the configured cap.
                    if (
                        in_speech
                        and max_utt_blocks > 0
                        and speech_blocks >= max_utt_blocks
                    ):
                        clip = np.concatenate(speech)[:, 0]
                        in_speech = False
                        if len(clip) >= int(SAMPLE_RATE * 0.3):
                            on_clip(clip)
                        speech = []
                        speech_blocks = 0
                        silence_blocks = 0
        except Exception as e:
            # InputStream failed (device vanished mid-stream) — retry.
            print(f"⚠️ mic error ({e}) — retrying in 2s", flush=True)
            if stop_event:
                stop_event.wait(2.0)
            else:
                time.sleep(2.0)


def _safe_send(conn, payload: bytes) -> None:
    """Send a reply, swallowing the error if the client already closed.

    A client that connects and disconnects mid-handshake (health probes,
    timeouts) must never kill the socket server thread with BrokenPipeError.
    """
    try:
        conn.sendall(payload)
    except OSError:
        pass


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
    try:
        srv.bind(str(SOCKET_PATH))
    except OSError:
        # Another daemon already owns the socket — don't linger as a zombie.
        stop_event.set()
        return
    srv.listen(4)
    modes = {"hotkey": mode_events["hotkey"].is_set(),
             "vad": mode_events["vad"].is_set()}

    while not stop_event.is_set():
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        try:
            with conn:
                data = conn.recv(4096).decode()
                if not data:
                    # Health probe / connect-and-close — nothing to answer.
                    continue
                try:
                    req = json.loads(data)
                except Exception:
                    _safe_send(conn, b'{"ok": false, "reason": "bad json"}')
                    continue
                cmd = req.get("command")
                if cmd == "ping":
                    _safe_send(conn, b'{"ok": true}')
                elif cmd == "set-mode":
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
                        _safe_send(conn, b'{"ok": true}')
                    else:
                        _safe_send(conn, b'{"ok": false, "reason": "bad mode"}')
                elif cmd == "stop":
                    _write_state(running=False, modes=dict(modes))
                    _safe_send(conn, b'{"ok": true}')
                    stop_event.set()
                else:
                    _safe_send(conn, b'{"ok": false, "reason": "unknown command"}')
        except Exception:
            # A single bad client must never kill the control socket.
            continue
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
    # Hotkey hold-to-talk is OFF by default — the tray exposes only the
    # speak-to-text (VAD) toggle. `set-mode hotkey` can still enable it.
    if CFG.stt_speak_to_capture:
        mode_events["vad"].set()
    threads = [
        threading.Thread(target=_socket_server, args=(stop_event, mode_events),
                         daemon=True, name="stt-socket"),
        threading.Thread(target=run_hotkey, args=(mode_events["hotkey"], stop_event),
                         daemon=True, name="stt-hotkey"),
        threading.Thread(target=vad_capture,
                         args=(_handle_clip, stop_event),
                         kwargs={"mode_event": mode_events["vad"]},
                         daemon=True, name="stt-vad"),
        threading.Thread(target=_transcribe_worker,
                         daemon=True, name="stt-transcribe"),
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
    # Let the audio threads close their streams cleanly before the process
    # exits — killing PortAudio/PipeWire mid-callback segfaults on shutdown.
    for t in threads:
        t.join(timeout=2)
    # Only clear "running" if the state file still points at THIS process.
    # A rapid stop→start (the tray toggle, idempotent start) can spawn a
    # fresh daemon while this one is draining its audio threads — its
    # shutdown write must not clobber the new daemon's running:true state.
    if _read_state().get("pid") == os.getpid():
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
        if _daemon_alive():
            return control("status")  # already running — don't spawn a duplicate
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
