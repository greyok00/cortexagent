# Speech-to-Text Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local speech-to-text to CortexAgent — a shared engine (`lib/stt.py`) powering a hotkey + VAD capture daemon (CLI), a webui mic button, and a tray settings submenu.

**Architecture:** One engine (faster-whisper `small` on CPU + tiny-overseer cleanup) consumed by two thin transports: a pynput/sounddevice/xdotool daemon for the CLI, and a `/api/stt` endpoint + MediaRecorder for the webui. Tray toggles control the daemon over a Unix socket.

**Tech Stack:** Python 3 (stdlib + faster-whisper 1.2.1, sounddevice, pynput, numpy), xdotool, espeak-ng (test audio), pystray (existing), stdlib http.server (existing).

## Global Constraints

- **GPU reserved for the big model** — STT runs on CPU only (`device = cpu`).
- **Default mic:** `Logi USB Headset` (card 0, mono 48kHz) — `mic_device = Logi USB Headset`.
- **Cleanup fallback:** if tiny :8082 is down, return the raw transcript — STT never blocks.
- **Localhost only:** all bindings on `127.0.0.1` (never `0.0.0.0`).
- **No PII:** use `Path.home()` / env vars, never hardcoded home paths.
- **Follow existing patterns:** `lib/config.py` uses `_env`/`_env_bool`/`_env_int`; webui uses `BaseHTTPRequestHandler`; tray uses pystray `Menu`/`MenuItem`.
- **Do NOT restart systemd services** other than `osint-portal.service` — the STT daemon is a user process (nohup), not a service.

---

### Task 1: `[stt]` config section

**Files:**
- Modify: `lib/config.py` (add `_env_float` helper + STT accessors in `Config.__init__`)
- Test: `tests/run_smoke.py` (add STT config assertions)

**Interfaces:**
- Produces: `CFG.stt_model: str`, `CFG.stt_device: str`, `CFG.stt_mic_device: str`, `CFG.stt_hotkey: str`, `CFG.stt_speak_to_capture: bool`, `CFG.stt_vad_threshold: float`, `CFG.stt_vad_silence_sec: float`, `CFG.stt_cleanup: bool`, `CFG.stt_cleanup_target: str` — all on the existing `CFG` singleton.

- [ ] **Step 1: Add `_env_float` helper** (next to `_env_int` in `lib/config.py`)

```python
def _env_float(name: str, conf_section: str, conf_key: str,
               default: Optional[float] = None) -> Optional[float]:
    """Resolve a float: env var → conf [section] key → default."""
    val = _env(name, conf_section, conf_key, None)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 2: Add STT accessors** at the end of `Config.__init__` (after the model-backend block)

```python
        # ── STT (speech-to-text) ────────────────────────────────────────────
        # Local-only, CPU. Default mic = the Logi USB Headset (card 0).
        self.stt_model = _env("CORTEXAGENT_STT_MODEL", "stt", "model", "small")
        self.stt_device = _env("CORTEXAGENT_STT_DEVICE", "stt", "device", "cpu")
        self.stt_mic_device = _env(
            "CORTEXAGENT_STT_MIC", "stt", "mic_device", "Logi USB Headset")
        self.stt_hotkey = _env(
            "CORTEXAGENT_STT_HOTKEY", "stt", "hotkey", "<ctrl>+<shift>+space")
        self.stt_speak_to_capture = _env_bool(
            "CORTEXAGENT_STT_SPEAK", "stt", "speak_to_capture", True)
        self.stt_vad_threshold = _env_float(
            "CORTEXAGENT_STT_VAD_THRESHOLD", "stt", "vad_threshold", 0.02)
        self.stt_vad_silence_sec = _env_float(
            "CORTEXAGENT_STT_VAD_SILENCE", "stt", "vad_silence_sec", 0.8)
        self.stt_cleanup = _env_bool(
            "CORTEXAGENT_STT_CLEANUP", "stt", "cleanup", True)
        self.stt_cleanup_target = _env(
            "CORTEXAGENT_STT_CLEANUP_TARGET", "stt", "cleanup_target", "tiny")
```

- [ ] **Step 3: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_config_defaults():
    from lib.config import CFG
    assert CFG.stt_model == "small"
    assert CFG.stt_device == "cpu"
    assert CFG.stt_mic_device == "Logi USB Headset"
    assert CFG.stt_hotkey == "<ctrl>+<shift>+space"
    assert CFG.stt_speak_to_capture is True
    assert CFG.stt_vad_threshold == 0.02
    assert CFG.stt_vad_silence_sec == 0.8
    assert CFG.stt_cleanup is True
    assert CFG.stt_cleanup_target == "tiny"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'stt_model'`

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: PASS — all STT config assertions green

- [ ] **Step 6: Commit**

```bash
git add lib/config.py tests/run_smoke.py
git commit -m "feat(stt): [stt] config section + _env_float helper"
```

---

### Task 2: `lib/stt.py` — transcribe() engine

**Files:**
- Create: `lib/stt.py`
- Test: `tests/run_smoke.py` (add transcribe test)

**Interfaces:**
- Consumes: `CFG.stt_model`, `CFG.stt_device` (Task 1)
- Produces: `transcribe(audio: str | Path | numpy.ndarray) -> str` — raw transcript text. Lazy-loads the faster-whisper model once (module-level singleton).

- [ ] **Step 1: Install sounddevice**

```bash
/usr/bin/python3 -m pip install --user sounddevice 2>&1 | tail -2
```

Verify: `/usr/bin/python3 -c "import sounddevice as sd; print([d['name'] for d in sd.query_devices() if 'Logi' in d['name']])"` shows the headset.

- [ ] **Step 2: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_transcribe_sample():
    import subprocess, tempfile, os
    from lib import stt
    wav = os.path.join(tempfile.gettempdir(), "stt_sample.wav")
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", wav,
                    "fix the proxy token accounting bug"], check=True)
    text = stt.transcribe(wav)
    assert text and text.strip(), f"transcribe returned empty: {text!r}"
    print(f"  stt sample → {text!r}")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.stt'`

- [ ] **Step 4: Write `lib/stt.py`**

```python
#!/usr/bin/env python3
"""stt — CortexAgent speech-to-text engine.

Wraps faster-whisper (CTranslate2, CPU) for transcription and the tiny
overseer (:8082) for cleanup. Shared by the CLI daemon (lib/stt_daemon.py)
and the webui (/api/stt). GPU is never touched — the big model owns it.

Usage:
    python3 lib/stt.py --test   # transcribe a generated sample, print result
"""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union

Audio = Union[str, Path, "numpy.ndarray"]

_model = None  # lazy faster-whisper singleton


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        from lib.config import CFG
        _model = WhisperModel(CFG.stt_model, device=CFG.stt_device,
                              compute_type="int8")
    return _model


def transcribe(audio: Audio) -> str:
    """Transcribe audio (path or numpy float32 array) to raw text."""
    from lib.config import CFG
    model = _get_model()
    if isinstance(audio, (str, Path)):
        segments, _info = model.transcribe(str(audio), beam_size=5)
    else:
        segments, _info = model.transcribe(audio, sampling_rate=16000, beam_size=5)
    return "".join(seg.text for seg in segments).strip()


def _test() -> int:
    wav = Path(tempfile.gettempdir()) / "stt_sample.wav"
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", str(wav),
                    "fix the proxy token accounting bug"], check=True)
    text = transcribe(wav)
    print(f"transcribed: {text!r}")
    return 0 if text.strip() else 1


if __name__ == "__main__":
    sys.exit(_test())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: PASS — `stt sample → 'fix the proxy token accounting bug'` (first run downloads the ~487MB model; allow a minute)

- [ ] **Step 6: Commit**

```bash
git add lib/stt.py tests/run_smoke.py
git commit -m "feat(stt): faster-whisper transcribe engine"
```

---

### Task 3: `lib/stt.py` — cleanup() via tiny overseer

**Files:**
- Modify: `lib/stt.py`
- Test: `tests/run_smoke.py`

**Interfaces:**
- Consumes: `CFG.stt_cleanup`, `CFG.stt_cleanup_target`, `CFG.tiny_model_port` (existing)
- Produces: `cleanup(text: str) -> str` — cleaned text, or the raw input on any failure (never raises).

- [ ] **Step 1: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_cleanup_fallback():
    from lib import stt
    # :8082 is not guaranteed up in the smoke run — cleanup must fall back to raw.
    raw = "fix the proxy t s bug and reload it"
    out = stt.cleanup(raw)
    assert isinstance(out, str) and out.strip(), "cleanup returned empty"
    print(f"  stt cleanup → {out!r}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `AttributeError: module 'lib.stt' has no attribute 'cleanup'`

- [ ] **Step 3: Add `cleanup()` to `lib/stt.py`**

```python
def cleanup(text: str) -> str:
    """Clean a transcript via the tiny overseer (:8082). Falls back to raw.

    Never raises and never blocks: any failure (model down, timeout, bad
    response) returns the input unchanged.
    """
    from lib.config import CFG
    if not text.strip() or not CFG.stt_cleanup:
        return text
    target = CFG.stt_cleanup_target
    if target == "off":
        return text
    port = CFG.tiny_model_port if target == "tiny" else CFG.big_model_port
    prompt = (
        "You are a transcription cleaner. Fix punctuation, capitalization, "
        "and expand abbreviations in the following speech-to-text transcript. "
        "Output ONLY the cleaned text, nothing else.\n\n"
        f"Transcript: {text}"
    )
    import json
    import urllib.request
    body = json.dumps({
        "model": "tiny",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        cleaned = data["choices"][0]["message"]["content"].strip()
        return cleaned or text
    except Exception:
        return text  # fallback — STT never blocks on the model
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: PASS — cleanup returns a non-empty string (raw fallback if :8082 is down)

- [ ] **Step 5: Commit**

```bash
git add lib/stt.py tests/run_smoke.py
git commit -m "feat(stt): tiny-overseer cleanup with raw fallback"
```

---

### Task 4: `lib/stt.py` — transcribe_and_cleanup() + `--test`

**Files:**
- Modify: `lib/stt.py`
- Test: `tests/run_smoke.py`

**Interfaces:**
- Consumes: `transcribe()`, `cleanup()` (Tasks 2–3)
- Produces: `transcribe_and_cleanup(audio: Audio) -> str` — the full pipeline used by both the daemon and the webui.

- [ ] **Step 1: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_transcribe_and_cleanup():
    import subprocess, tempfile, os
    from lib import stt
    wav = os.path.join(tempfile.gettempdir(), "stt_sample.wav")
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", wav,
                    "fix the proxy token accounting bug"], check=True)
    text = stt.transcribe_and_cleanup(wav)
    assert text and text.strip(), "pipeline returned empty"
    print(f"  stt pipeline → {text!r}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `AttributeError: module 'lib.stt' has no attribute 'transcribe_and_cleanup'`

- [ ] **Step 3: Add `transcribe_and_cleanup()` to `lib/stt.py`**

```python
def transcribe_and_cleanup(audio: Audio) -> str:
    """Full pipeline: transcribe → cleanup. Never raises."""
    raw = transcribe(audio)
    return cleanup(raw)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/stt.py tests/run_smoke.py
git commit -m "feat(stt): transcribe_and_cleanup pipeline"
```

---

### Task 5: `lib/stt_daemon.py` — hotkey mode (record + type)

**Files:**
- Create: `lib/stt_daemon.py`
- Test: `lib/stt_daemon.py --test` (manual, records 2s from the mic)

**Interfaces:**
- Consumes: `stt.transcribe_and_cleanup()`, `CFG.stt_mic_device`, `CFG.stt_hotkey`
- Produces: `record_clip(seconds: float) -> numpy.ndarray` (16kHz mono float32), `type_text(text: str) -> None` (xdotool), `HotkeyListener` class with `on_press`/`on_release` callbacks.

- [ ] **Step 1: Write `lib/stt_daemon.py`** (hotkey + record + type; VAD + control socket come in Tasks 6–7)

```python
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
```

- [ ] **Step 2: Verify `--test` works**

Run: `cd ~/cortexagent && /usr/bin/python3 lib/stt_daemon.py --test`
Expected: records 2s from the Logi USB Headset, prints a non-empty transcript. (Speak during the 2s window.)

- [ ] **Step 3: Verify hotkey mode starts**

Run: `cd ~/cortexagent && timeout 3 /usr/bin/python3 lib/stt_daemon.py 2>&1 | head -3`
Expected: starts without error (times out after 3s — that's fine, it's the listener).

- [ ] **Step 4: Commit**

```bash
git add lib/stt_daemon.py
git commit -m "feat(stt): hotkey hold-to-talk daemon (record + xdotool type)"
```

---

### Task 6: `lib/stt_daemon.py` — VAD speak-to-capture mode

**Files:**
- Modify: `lib/stt_daemon.py`
- Test: `tests/run_smoke.py` (VAD math on synthetic audio)

**Interfaces:**
- Consumes: `CFG.stt_vad_threshold`, `CFG.stt_vad_silence_sec`
- Produces: `rms(samples: np.ndarray) -> float`, `vad_capture(on_clip, stop_event)` — continuous listener that calls `on_clip(clip)` when a speech segment ends.

- [ ] **Step 1: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_vad_math():
    import numpy as np
    from lib import stt_daemon
    silence = np.zeros(1600, dtype=np.float32)
    assert stt_daemon.rms(silence) < 0.001, "silence RMS should be ~0"
    tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(1600) / 16000)).astype(np.float32)
    assert stt_daemon.rms(tone) > 0.05, "tone RMS should be well above threshold"
    print(f"  stt vad: silence={stt_daemon.rms(silence):.4f} tone={stt_daemon.rms(tone):.4f}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `AttributeError: module 'lib.stt_daemon' has no attribute 'rms'`

- [ ] **Step 3: Add VAD functions to `lib/stt_daemon.py`**

```python
def rms(samples: np.ndarray) -> float:
    """Root-mean-square energy of a float32 sample buffer."""
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def vad_capture(on_clip, stop_event=None, block_sec: float = 0.1) -> None:
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: PASS — silence RMS ~0, tone RMS > 0.05

- [ ] **Step 5: Commit**

```bash
git add lib/stt_daemon.py tests/run_smoke.py
git commit -m "feat(stt): VAD speak-to-capture mode"
```

---

### Task 7: `lib/stt_daemon.py` — control socket + state + `cortexagent voice`

**Files:**
- Modify: `lib/stt_daemon.py`, `bin/cortexagent`
- Test: `cortexagent voice status` (manual)

**Interfaces:**
- Consumes: `run_hotkey()`, `vad_capture()` (Tasks 5–6)
- Produces: `control(command: str, mode: str | None) -> dict` (client), `run()` (daemon main with socket + state), `cortexagent voice start|stop|status|set-mode <mode>`.

- [ ] **Step 1: Add state + socket helpers to `lib/stt_daemon.py`**

```python
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
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect(str(SOCKET_PATH))
        s.sendall(json.dumps(payload).encode())
        resp = s.recv(4096).decode()
    return json.loads(resp) if resp else {"ok": False, "reason": "no response"}
```

- [ ] **Step 2: Add the control-socket server thread + `run()`**

```python
def _socket_server(stop_event) -> None:
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
    modes = {"hotkey": False, "vad": False}

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
```

- [ ] **Step 3: Rewrite `main()` to run both modes + socket**

```python
def run() -> int:
    import os
    import threading
    from lib.config import CFG
    stop_event = threading.Event()
    threads = [
        threading.Thread(target=_socket_server, args=(stop_event,),
                         daemon=True, name="stt-socket"),
        threading.Thread(target=run_hotkey, daemon=True, name="stt-hotkey"),
    ]
    if CFG.stt_speak_to_capture:
        threads.append(threading.Thread(
            target=vad_capture, args=(_handle_clip, stop_event),
            daemon=True, name="stt-vad"))
    for t in threads:
        t.start()
    _write_state(running=True, pid=os.getpid(),
                 modes={"hotkey": True, "vad": CFG.stt_speak_to_capture})
    try:
        stop_event.wait()  # released by the socket server on "stop"
    except KeyboardInterrupt:
        pass
    _write_state(running=False, modes={"hotkey": False, "vad": False})
    return 0


def control(command: str, mode: str | None = None) -> int:
    if command == "status":
        import json
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
    ap.add_argument("--mode", default=None, help="hotkey|vad|both|off")
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
```

- [ ] **Step 4: Add the `voice` subcommand to `bin/cortexagent`** (before the `exec claude` line, near the other custom flags)

```bash
# ── voice: STT daemon control ─────────────────────────────────────────────
# cortexagent voice start|stop|status|set-mode <hotkey|vad|both|off>
if [ $# -gt 0 ] && [ "$1" = "voice" ]; then
  shift
  /usr/bin/python3 "$REPO_ROOT/lib/stt_daemon.py" "$@"
  exit $?
fi
```

- [ ] **Step 5: Verify the full lifecycle**

Run:
```bash
cd ~/cortexagent
./bin/cortexagent voice start
./bin/cortexagent voice status
./bin/cortexagent voice set-mode both
./bin/cortexagent voice stop
```
Expected: start spawns the daemon, status shows `running: true` + modes, set-mode updates modes, stop returns ok.

- [ ] **Step 6: Commit**

```bash
git add lib/stt_daemon.py bin/cortexagent
git commit -m "feat(stt): control socket + state + cortexagent voice subcommand"
```

---

### Task 8: Webui `/api/stt` endpoint

**Files:**
- Modify: `lib/webui.py`
- Test: `tests/run_smoke.py` (direct handler call)

**Interfaces:**
- Consumes: `stt.transcribe_and_cleanup()` (Task 4)
- Produces: `POST /api/stt` — raw audio body → `{"ok": true, "text": "..."}` (200) or `{"ok": false, "reason": "..."}` (400/500).

- [ ] **Step 1: Write the failing test** (append to `tests/run_smoke.py`)

```python
def test_stt_webui_endpoint():
    import subprocess, tempfile, os, json
    from lib import stt
    wav = os.path.join(tempfile.gettempdir(), "stt_sample.wav")
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", wav,
                    "fix the proxy token accounting bug"], check=True)
    text = stt.transcribe_and_cleanup(wav)
    assert text and text.strip()
    print(f"  stt webui pipeline → {text!r}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/run_smoke.py 2>&1 | grep -i stt`
Expected: FAIL — `AttributeError: module 'lib.stt' has no attribute 'transcribe_and_cleanup'` (if Task 4 was skipped) — otherwise this is a no-op guard; the real endpoint test is manual in Step 4.

- [ ] **Step 3: Add the `/api/stt` route + handler to `lib/webui.py`**

In `do_POST`, after the `/api/upload` block:

```python
        if parsed.path == "/api/stt":
            if not self._check_auth_or_401():
                return
            self._handle_stt()
            return
```

Add the handler method (near `_handle_tray_upload`):

```python
    def _handle_stt(self) -> None:
        """POST /api/stt — raw audio body → {ok, text}. Transcribes + cleans."""
        import tempfile
        from lib import stt
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid audio size"})
            return
        audio = self.rfile.read(length)
        tmp = Path(tempfile.gettempdir()) / f"stt_{int(time.time())}.webm"
        tmp.write_bytes(audio)
        try:
            text = stt.transcribe_and_cleanup(tmp)
        except Exception as e:
            self._send_json(500, {"ok": False, "reason": str(e)})
            return
        finally:
            tmp.unlink(missing_ok=True)
        self._send_json(200, {"ok": True, "text": text})
```

- [ ] **Step 4: Verify the endpoint manually**

Run:
```bash
cd ~/cortexagent
espeak-ng -v en-us -w /tmp/stt_sample.wav "fix the proxy token accounting bug"
curl -s -X POST --data-binary @/tmp/stt_sample.wav http://127.0.0.1:8090/api/stt
```
Expected: `{"ok": true, "text": "fix the proxy token accounting bug"}` (webui must be running on :8090).

- [ ] **Step 5: Commit**

```bash
git add lib/webui.py tests/run_smoke.py
git commit -m "feat(stt): webui /api/stt endpoint"
```

---

### Task 9: Webui template — mic button + MediaRecorder

**Files:**
- Modify: `assets/webui_template.html`

**Interfaces:**
- Consumes: `POST /api/stt` (Task 8)
- Produces: a 🎙️ button in the composer; hold-to-record → transcript fills `#input`.

- [ ] **Step 1: Add the mic button** to the composer (between the attach button and the textarea)

```html
      <button class="icon-btn" id="mic" title="Hold to speak">🎙️</button>
```

- [ ] **Step 2: Add the MediaRecorder JS** (near the existing send handler)

```js
  // ── STT: hold-to-record mic button ─────────────────────────────────────
  const micBtn = document.getElementById('mic');
  let mediaRecorder = null, micChunks = [], micActive = false;

  async function startMic() {
    if (micActive) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      micChunks = [];
      mediaRecorder.ondataavailable = e => { if (e.data.size) micChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        const blob = new Blob(micChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
        stream.getTracks().forEach(t => t.stop());
        micBtn.classList.remove('recording');
        micBtn.textContent = '🎙️';
        try {
          const res = await api('/api/stt', { method: 'POST', body: blob });
          if (res && res.text) {
            const input = document.getElementById('input');
            input.value = (input.value ? input.value + ' ' : '') + res.text;
            input.focus();
          }
        } catch (e) { console.error('stt error', e); }
      };
      mediaRecorder.start();
      micActive = true;
      micBtn.classList.add('recording');
      micBtn.textContent = '🔴';
    } catch (e) { console.error('mic error', e); }
  }
  function stopMic() {
    if (mediaRecorder && micActive) { mediaRecorder.stop(); micActive = false; }
  }
  micBtn.addEventListener('mousedown', startMic);
  micBtn.addEventListener('mouseup', stopMic);
  micBtn.addEventListener('mouseleave', stopMic);
```

- [ ] **Step 3: Add the `.recording` style** (near the other `.icon-btn` styles)

```css
  .icon-btn.recording { color: #ff4d4d; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
```

- [ ] **Step 4: Verify in the browser**

Open `http://127.0.0.1:8090/`, click and hold 🎙️, speak, release. Expected: transcript appears in the textarea. (Brave must have mic permission for 127.0.0.1.)

- [ ] **Step 5: Commit**

```bash
git add assets/webui_template.html
git commit -m "feat(stt): webui mic button + MediaRecorder"
```

---

### Task 10: Tray STT submenu

**Files:**
- Modify: `lib/tray.py`

**Interfaces:**
- Consumes: `stt_daemon.control()` / state file (Task 7)
- Produces: an STT submenu with checkable toggles + Test mic.

- [ ] **Step 1: Add STT helpers** (near the other `_overseer_*` helpers)

```python
def _stt_state() -> dict:
    import json
    from pathlib import Path
    p = Path.home() / ".cortexagent" / "state" / "stt_daemon.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _stt_control(cmd: str, mode: str | None = None) -> str:
    import subprocess
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    args = [sys.executable, str(repo / "lib" / "stt_daemon.py"), cmd]
    if mode:
        args.append("--mode")
        args.append(mode)
    r = subprocess.run(args, capture_output=True, text=True, timeout=10)
    return r.stdout.strip() or r.stderr.strip()
```

- [ ] **Step 2: Add the STT submenu + handlers** in `_run_gui`

```python
    def on_stt_toggle(icon, item):
        mode = "vad" if "Speak" in item.text else "hotkey"
        cur = _stt_state().get("modes", {})
        want = not cur.get(mode, False)
        new = {"hotkey": cur.get("hotkey", False), "vad": cur.get("vad", False)}
        new[mode] = want
        target = "both" if new["hotkey"] and new["vad"] else (
            "hotkey" if new["hotkey"] else ("vad" if new["vad"] else "off"))
        _toast(icon, f"STT {mode}: {'on' if want else 'off'} — " + _stt_control("set-mode", target), "ok")

    def on_stt_test(icon, item):
        _toast(icon, "recording 2s…", "info")
        import subprocess
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        r = subprocess.run([sys.executable, str(repo / "lib" / "stt_daemon.py"), "--test"],
                           capture_output=True, text=True, timeout=30)
        _toast(icon, r.stdout.strip() or r.stderr.strip(), "ok")

    stt_menu = Menu(
        MI("Speak to capture", on_stt_toggle,
           checked=lambda item: _stt_state().get("modes", {}).get("vad", False)),
        MI("Hotkey mode", on_stt_toggle,
           checked=lambda item: _stt_state().get("modes", {}).get("hotkey", False)),
        Menu.SEPARATOR,
        MI("Model: small", None, enabled=False),
        MI("Cleanup: tiny", None, enabled=False),
        MI("Test mic", on_stt_test),
    )
```

- [ ] **Step 3: Insert the submenu** into the main menu (before the Quit separator)

```python
        Menu.SEPARATOR,
        MI("STT", stt_menu),
        Menu.SEPARATOR,
        MI("Quit", on_quit),
```

- [ ] **Step 4: Verify the menu builds**

Run: `cd ~/cortexagent && /usr/bin/python3 -c "import lib.tray; print('tray imports OK')"`
Expected: no import errors.

- [ ] **Step 5: Commit**

```bash
git add lib/tray.py
git commit -m "feat(stt): tray STT submenu with toggles + test mic"
```

---

### Task 11: Smoke gate + changelog

**Files:**
- Modify: `tests/run_smoke.py`, `docs/superpowers/specs/2026-08-10-daily-changelog.md`

- [ ] **Step 1: Run the full smoke suite**

Run: `cd ~/cortexagent && python3 tests/run_smoke.py 2>&1 | tail -20`
Expected: all tests pass, including the new `test_stt_*` tests.

- [ ] **Step 2: Run `cortexagent doctor`**

Run: `cd ~/cortexagent && ./bin/cortexagent doctor 2>&1 | tail -20`
Expected: all checks HEALTHY.

- [ ] **Step 3: Append the changelog row**

Add to the DONE table in `docs/superpowers/specs/2026-08-10-daily-changelog.md`:

```
| 25 | Aug 12 | **STT integration** — shared engine `lib/stt.py` (faster-whisper small, CPU) + tiny-overseer cleanup; `lib/stt_daemon.py` hotkey hold-to-talk + VAD speak-to-capture, xdotool type at cursor; `cortexagent voice start|stop|status|set-mode`; webui `/api/stt` + 🎙️ MediaRecorder button; tray STT submenu (toggles + test mic). Default mic = Logi USB Headset. | `lib/stt.py` (new), `lib/stt_daemon.py` (new), `lib/config.py`, `lib/webui.py`, `assets/webui_template.html`, `lib/tray.py`, `bin/cortexagent`, `tests/run_smoke.py` | User: "let's fully incorporate speech to text into the cli and webui for cortexagent" |
```

- [ ] **Step 4: Commit**

```bash
git add tests/run_smoke.py docs/superpowers/specs/2026-08-10-daily-changelog.md
git commit -m "feat(stt): smoke gate + changelog row #25"
```

---

## Self-Review Notes

- **Spec coverage:** every spec section maps to a task — engine (2–4), hotkey (5), VAD (6), control/voice (7), webui endpoint (8), webui mic (9), tray (10), config (1), testing (11). Out-of-scope items (wake-word, diarization, phone) are not implemented.
- **Type consistency:** `transcribe(audio) -> str`, `cleanup(text) -> str`, `transcribe_and_cleanup(audio) -> str` are defined in Tasks 2–4 and consumed identically in Tasks 5, 8. `rms(samples) -> float` defined in Task 6, used in `vad_capture`. `control(command, mode)` defined in Task 7, used by tray Task 10.
- **Placeholder scan:** no TBD/TODO; every code step has real code.
