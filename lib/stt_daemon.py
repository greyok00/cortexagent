#!/usr/bin/env python3

from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import time
from pathlib import Path






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

        return {"ok": False, "reason": "STT daemon not running"}
    return json.loads(resp) if resp else {"ok": False, "reason": "no response"}


def _daemon_alive() -> bool:

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

    import sounddevice as sd
    frames = int(SAMPLE_RATE * seconds)
    data = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS,
                  dtype="float32", device=_mic_device())
    sd.wait()
    return data[:, 0]


def type_text(text: str) -> None:

    subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "1", text],
                   check=False)


def _key_name(key) -> str:
    from pynput import keyboard
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    if isinstance(key, keyboard.KeyCode):
        return key.char or f"<{key.vk}>"




_GARBAGE_TOKENS = frozenset({
    "", ".", "..", "...", ". .", ". . .", ". . . .", ",", ", ,",
    "uh", "uhh", "uh huh", "um", "umm", "hmm", "huh", "mm",
    "[blank_audio]", "[silence]", "(silence)", "[music]",


    "i'm sorry i'm sorry i'm sorry",
    "i'm sorry. i'm sorry. i'm sorry.",
    "i'm sorry. i'm sorry.",
    "thank you. thank you. thank you.",
    "thank you thank you thank you",
    "thank you. thank you.",
    "thanks for watching",
    "thanks for watching!",


    "thank you very much",
    "thank you. thank you very much.",
    "thanks for watching the show",
    "thank you so much",
    "subscribe to my channel",
    "subscribe to the channel",
    "subscribe to my channel and",
    "subscribe to the channel and",
    "subscribe to my channel please",
    "subscribe to the channel please",
    "subscribe",
    "bye",
    "bye bye",
    "bye bye bye",
    "okay. okay. okay.",
    "okay. okay.",
    "i love you. i love you. i love you.",
    "i love you. i love you.",
    "see you later. see you later.",
})









import re as _re
_RE_LETTER_DASH_RUN = _re.compile(r"^[a-zA-Z](?:-[a-zA-Z]){3,}$")
_RE_LETTER_RUN = _re.compile(r"^([a-zA-Z])\1{3,}$")
_RE_WORD_REPEAT = _re.compile(r"^(\S+)(?:\s+\1){2,}$")
_RE_DOTTED_WORDS = _re.compile(r"[a-zA-Z]\.[a-zA-Z]")


_WORD = _re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")
_RE_SINGLE_TOKEN_REPEAT = _re.compile(r"^(\S{1,3})(\s+\1){3,}$")
_RE_PHRASE_REPEAT = _re.compile(
    r"^((?:\S+\s+){2,}\S+)\s+\1\.?$"
)






_STUTTER_TOKENS = frozenset({
    "i", "i'm", "im", "me", "my", "sorry", "thank", "you", "your", "love",
    "bye", "okay", "ok", "uh", "um", "umm", "mm", "hmm", "so", "oh", "ah",
    "hey", "hi", "yeah", "yes", "no", "well", "like", "just", "a", "an",
    "the", "and", "to", "of", "it", "that", "this",
})







_NOISE_ONLY_WORDS = frozenset({
    "you", "your", "yours", "so", "yeah", "yep", "uh", "um", "umm", "mm",
    "hmm", "oh", "ah", "well", "like", "i", "im", "me", "my", "sorry",
    "thank", "and", "the", "to", "of", "it", "that", "this", "just", "a",
    "an", "know", "what",
})









_STUTTER_COLLAPSE = _re.compile(
    r"\b([a-zA-Z]+(?:'[a-zA-Z]+)?)\b(?:\s*,?\s*\1\b)+",
    _re.IGNORECASE,
)








_FILLER_WORDS = frozenset({

    "i", "im", "i'm", "a", "an", "the", "is", "it", "to", "of", "in",
    "on", "and", "or", "but", "uh", "um", "umm", "uhh", "mm", "hmm",
    "so", "no", "ok", "okay", "ah", "oh", "hey", "hi", "ya", "yeah",
    "you", "your", "yours", "we", "us", "me", "my", "mine", "at", "by",
    "as", "if", "for", "with", "from", "this", "that", "what", "which",
    "when", "where", "why", "how", "not", "do", "did", "does", "be",
    "been", "being", "am", "have", "has", "had", "are", "was", "were",
    "will", "would", "could", "should", "can", "may", "might", "shall",
    "their", "there", "then", "than", "these", "those", "here",
    "he", "she", "him", "her", "his", "hers", "its", "let's", "lets",

    "like", "well", "right", "just", "actually", "basically",
    "literally", "anyway", "anyways",

    "ppp", "pp", "xxx", "xxx.", "mmm", "huh", "huhh",
})











_HALLUCINATION_TOKENS = frozenset({






    "thank", "thanks", "you", "your", "yours", "very", "much", "watching",
    "watch", "show", "subscribe", "subscribed", "channel", "bye", "love",
    "see", "later", "welcome", "please", "enjoy", "appreciate", "appreciated",
})





_HALLUCINATION_OUTRO_PHRASES = frozenset({
    "thanks for watching", "thanks for watching the show",
    "thank you for watching", "subscribe to my channel",
    "see you in the next video", "see you next time",
    "thanks for listening", "thanks for your time",







    "thank you so much for watching",
    "thank you very much for watching",
    "thanks very much for watching",
    "thank you so much for watching and ill see you in the next video",
    "thank you very much for watching and ill see you in the next video",
    "thank you so much for watching and see you in the next video",
    "thanks so much for watching and ill see you in the next video",
    "thanks very much for watching and ill see you in the next video",
    "thank you for watching and ill see you in the next video",
    "thanks for watching and ill see you in the next video",
    "thanks for watching and see you in the next video",





    "thats all for now thanks for watching ill see you in the next video bye",



    "bye bye bye",
})


def _clean_phrase(text: str) -> str:

    return " ".join(_re.sub(r"[^\w ]", "", text.lower()).split())




_OUTRO_CANONICAL = frozenset(_clean_phrase(p) for p in _HALLUCINATION_OUTRO_PHRASES)








_RE_OUTRO_FOR_WATCHING = _re.compile(
    r"^thanks? (?:you )?(?:so |very )?much? for watching"
    r"(?: and (?:ill? |i will )?see you in (?:the )?next video)?$"
)









_OUTRO_MARKERS = ("next video", "subscribe", "channel", "thats all for now", "bye bye")


def _text_is_meaningful(text: str) -> bool:

    if not text:
        return False

    if all(c in "., \t\n" for c in text):
        return False
    normalized = text.strip().lower()


    if _RE_LETTER_DASH_RUN.match(normalized):
        return False
    if _RE_LETTER_RUN.match(normalized):
        return False
    if _RE_WORD_REPEAT.match(normalized):
        return False
    if _RE_SINGLE_TOKEN_REPEAT.match(normalized):
        return False
    if _RE_PHRASE_REPEAT.match(normalized):
        return False







    if " " in normalized:
        tokens = normalized.split()
        non_dotted = [t for t in tokens if not _RE_DOTTED_WORDS.search(t)]
        dotted = [t for t in tokens if _RE_DOTTED_WORDS.search(t)]


        if dotted and non_dotted:
            looks_like_filler = all(
                _re.sub(r"[^\w]", "", t) in _FILLER_WORDS
                for t in non_dotted
            )
            if looks_like_filler and len(tokens) <= 8:
                return False








        cleaned = _clean_phrase(normalized)



        if _RE_OUTRO_FOR_WATCHING.match(cleaned):
            return False




        if (
            "for watching" in cleaned
            and any(m in cleaned for m in _OUTRO_MARKERS)
            and len(cleaned.split()) <= 20
        ):
            return False
        if cleaned in _OUTRO_CANONICAL:
            return False




        for phrase in _OUTRO_CANONICAL:
            if cleaned == f"{phrase} {phrase}":
                return False






    toks = [_re.sub(r"[^\w']", "", t).lower() for t in normalized.split() if t.strip()]
    if toks and toks[0] in _NOISE_ONLY_WORDS and (
        len(toks) == 1 or all(t == toks[0] for t in toks)
    ):
        return False

    return normalized not in _GARBAGE_TOKENS


def _strip_leading_garbage(text: str) -> str:

    if not text:
        return text
    matches = list(_WORD.finditer(text))





    if len(matches) < 2:
        return text
    words = [m.group(0).lower() for m in matches]



    for plen in (2, 1, 3, 4):
        if plen > len(words):
            continue
        phrase = tuple(words[:plen])
        if not all(w in _STUTTER_TOKENS for w in phrase):
            continue

        n = 1
        while n * plen + plen <= len(words) and \
              tuple(words[n * plen:(n + 1) * plen]) == phrase:
            n += 1
        if n < 2:
            continue

        end_idx = matches[n * plen - 1].end()
        rest = text[end_idx:].lstrip(" ,.!?;:\t\n")

        if not rest or all(c in ".,!? \t\n" for c in rest):
            return ""
        return rest
    return text


def _strip_repeated_stutter(text: str) -> str:

    def _collapse(m):


        if m.group(1).lower() in _STUTTER_TOKENS:
            return m.group(1)
        return m.group(0)

    if not text:
        return text
    collapsed = _STUTTER_COLLAPSE.sub(_collapse, text)
    if collapsed == text:
        return text
    tokens = [m.group(0).lower() for m in _WORD.finditer(collapsed)]
    if tokens and all(w in _STUTTER_TOKENS for w in tokens):
        return ""
    return collapsed


class HotkeyListener:


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
       return {part.strip().lower() for part in hotkey.split("+") if part.strip()}


_clip_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=8)


def _transcribe_worker() -> None:

    from lib import stt
    while True:
        try:
            clip = _clip_queue.get(timeout=5.0)
        except queue.Empty:
            stt.unload_if_idle()
            continue
        try:
            text = stt.transcribe_and_cleanup(clip)



            text = _strip_leading_garbage(text)
            text = _strip_repeated_stutter(text)
            clip_rms = float(np.sqrt(np.mean(clip.astype(np.float32) ** 2))) if clip.size else 0.0
            duration = clip.size / SAMPLE_RATE if clip.size else 0.0
            rms_tag = f"clip_rms={clip_rms:.4f} dur={duration:.2f}s"
            if text and _text_is_meaningful(text):
                print(f"  📝 {rms_tag}  text={text!r}", flush=True)
                type_text(text)
            elif text:
                print(f"  🗑 {rms_tag}  dropped={text!r}", flush=True)
        except Exception as e:
            print(f"⚠️ transcribe failed: {e}", flush=True)
        finally:
            _clip_queue.task_done()


_TARGET_PEAK = 0.70


def _normalize_clip(clip: np.ndarray) -> tuple[np.ndarray, float]:

    if clip.size == 0:
        return clip, 0.0
    peak = float(np.max(np.abs(clip)))
    clip_ratio = float(np.mean(np.abs(clip) > 0.999))
    if peak <= 0 or peak < _TARGET_PEAK:
        return clip, clip_ratio
    return clip * (_TARGET_PEAK / peak), clip_ratio


def _handle_clip(clip: np.ndarray) -> None:

    clip, clip_ratio = _normalize_clip(clip)
    if clip_ratio > 0.01:
        print(f"⚠️ mic CLIPPING — {clip_ratio*100:.1f}% of samples at max level. "
              f"Lower the input/mic volume; maxed gain distorts STT.", flush=True)
    try:
        _clip_queue.put_nowait(clip)
    except queue.Full:

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

    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def vad_capture(on_clip, stop_event=None, mode_event=None, block_sec: float = 0.1) -> None:

    import sounddevice as sd
    from lib.config import CFG
    threshold = CFG.stt_vad_threshold
    silence_limit = max(1, int(CFG.stt_vad_silence_sec / block_sec))
    max_utt_sec = max(0.0, float(CFG.stt_vad_max_utterance_sec or 0.0))
    max_utt_blocks = int(max_utt_sec / block_sec) if max_utt_sec > 0 else 0
    block = int(SAMPLE_RATE * block_sec)
    speech: list = []
    speech_blocks = 0
    in_speech = False
    silence_blocks = 0
    while not (stop_event and stop_event.is_set()):
        dev = _mic_device()
        if dev is None and CFG.stt_mic_device:




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

            print(f"⚠️ mic error ({e}) — retrying in 2s", flush=True)
            if stop_event:
                stop_event.wait(2.0)
            else:
                time.sleep(2.0)


def _safe_send(conn, payload: bytes) -> None:

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
        stop_event.wait()
    except KeyboardInterrupt:
        pass


    for t in threads:
        t.join(timeout=2)




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
            return control("status")
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
