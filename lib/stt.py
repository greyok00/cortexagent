#!/usr/bin/env python3

from __future__ import annotations

import sys
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Union

Audio = Union[str, Path, "numpy.ndarray"]

_model = None
_model_lock = threading.Lock()
_model_device = "cpu"

_CONFIG_CACHE = {"cfg": None}


def _get_config():
    """Lazy + thread-safe config read (avoids sys.path races during startup)."""
    if _CONFIG_CACHE["cfg"] is None:
        from lib.config import CFG
        _CONFIG_CACHE["cfg"] = CFG
    return _CONFIG_CACHE["cfg"]





_STT_OOM_FLOOR_MIB = 256
























_STT_MODEL_VRAM = {
    "tiny":  300, "tiny.en": 300,
    "base":  580, "base.en": 580,
    "small": 970, "small.en": 970,
    "medium": 2300, "medium.en": 2300,
    "large":  3900, "large-v3": 3900,
}
_STT_GATE_HEADROOM_MIB = 150


def _free_vram_mib() -> Optional[int]:

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _big_model_up() -> bool:

    import socket
    from lib.config import CFG
    try:
        with socket.create_connection(("127.0.0.1", CFG.big_model_port), timeout=1):
            return True
    except OSError:
        return False


def _gpu_available(model_name: str) -> bool:

    free = _free_vram_mib()
    if free is None:
        return False
    fp16 = _STT_MODEL_VRAM.get(model_name, 970)

    int8_estimate = max(150, fp16 // 2 + 50)
    need = int8_estimate + _STT_GATE_HEADROOM_MIB
    return free >= need


def _get_model():
    global _model, _model_device
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                from lib.config import CFG




                if _gpu_available(CFG.stt_model):
                    try:






                        _model = WhisperModel(CFG.stt_model, device="cuda",
                                              compute_type="int8")
                        _model_device = "cuda"
                    except Exception:
                        _model = WhisperModel(CFG.stt_model, device="cpu",
                                              compute_type="int8")
                        _model_device = "cpu"
                else:
                    _model = WhisperModel(CFG.stt_model, device="cpu",
                                          compute_type="int8")
                    _model_device = "cpu"
    return _model


def unload_if_idle() -> None:

    global _model
    if _model is None:
        return
    if _model_device != "cuda":
        return
    free = _free_vram_mib()
    if free is not None and free < _STT_OOM_FLOOR_MIB:
        with _model_lock:
            if _model is not None:
                _model = None


def transcribe(audio: Audio) -> str:

    model = _get_model()








    beam = 5 if _model_device == "cuda" else 2







    segments, _info = model.transcribe(
        audio,
        beam_size=beam,
        language="en",
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},






        no_speech_threshold=0.4,
    )
    return "".join(seg.text for seg in segments).strip()


def transcribe_streaming(audio: Audio):
    """Yield (segment_text, is_final) per segment so the worker can type words
    incrementally as they're decoded, instead of typing the whole clip at once.

    Streaming matters for perceived latency: on a 10s utterance with the
    small model + CUDA, faster-whisper finishes each segment in 0.5-1.5s.
    Without streaming, the user waits the full ~3-4s clip-transcribe time
    before any text appears; with it, text starts appearing within ~1s.
    """
    model = _get_model()
    beam = 5 if _model_device == "cuda" else 2
    segments, _info = model.transcribe(
        audio,
        beam_size=beam,
        language="en",
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        no_speech_threshold=0.4,
    )
    seg_list = list(segments)
    for i, seg in enumerate(seg_list):
        yield seg.text, i == len(seg_list) - 1


def cleanup(text: str) -> str:

    CFG = _get_config()
    if not text.strip() or not CFG.stt_cleanup:
        return text
    target = CFG.stt_cleanup_target
    if target == "off":
        return text
    port = CFG.tiny_model_port if target == "tiny" else CFG.big_model_port
    model = "tiny" if target == "tiny" else "big"
    prompt = (
        "You are a transcription cleaner. Fix punctuation, capitalization, "
        "and expand abbreviations in the following speech-to-text transcript. "
        f"Keep the output to at most {CFG.stt_cleanup_max_sentences} sentences. "
        "Output ONLY the cleaned text, nothing else.\n\n"
        f"Transcript: {text}"
    )
    import json
    import urllib.request
    body = json.dumps({
        "model": model,
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
        if not cleaned:
            return text

        return _cap_sentences(cleaned, CFG.stt_cleanup_max_sentences)
    except Exception:
        return text


def _cap_sentences(text: str, max_sentences: int) -> str:

    if max_sentences <= 0:
        return text
    import re

    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(parts) <= max_sentences:

        return " ".join(p.strip() for p in parts if p.strip())
    return " ".join(p.strip() for p in parts[:max_sentences] if p.strip())


def transcribe_and_cleanup(audio: Audio) -> str:

    raw = transcribe(audio)

    cleanup_enabled = getattr(_get_config(), "stt_cleanup", False)
    if not cleanup_enabled:
        return raw
    return cleanup(raw)


def _test() -> int:
    wav = Path(tempfile.gettempdir()) / "stt_sample.wav"
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", str(wav),
                    "fix the proxy token accounting bug"], check=True)
    text = transcribe(wav)
    print(f"transcribed: {text!r}")
    return 0 if text.strip() else 1


if __name__ == "__main__":
    sys.exit(_test())
