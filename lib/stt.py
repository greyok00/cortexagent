#!/usr/bin/env python3
"""stt — CortexAgent speech-to-text engine.

Wraps faster-whisper (CTranslate2) for transcription and the tiny overseer
(:8082) for cleanup. Shared by the CLI daemon (lib/stt_daemon.py) and the
webui (/api/stt). Device is auto-detected: CUDA when free VRAM allows it
(``stt_device=auto``, the default), else CPU int8 — so dictation stays fast
without ever OOMing the big model.

Usage:
    python3 lib/stt.py --test   # transcribe a generated sample, print result
"""
from __future__ import annotations

import sys
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Union

Audio = Union[str, Path, "numpy.ndarray"]

_model = None  # lazy faster-whisper singleton
_model_lock = threading.Lock()
_model_device = "cpu"  # device the singleton actually loaded on
# Whisper stays resident once loaded — dictation must be instant, not pay a
# 2-3s CUDA reload after idle. It fits alongside the big model (13.7GB) +
# overseer (0.95GB) with ~1GB free, so the only reason to free it is a
# genuine OOM risk: free VRAM under this floor (a big-model generation
# spike). The daemon's transcribe worker calls unload_if_idle() every 5s.
_STT_OOM_FLOOR_MIB = 512
# Minimum free VRAM (MiB) before whisper may load on CUDA. Measured on this
# box: big model (Qwen3.6-35B, 13.7GB) + overseer (LFM2.5-1.2B, ~0.95GB) +
# whisper base fp16 (~0.43GB) = ~15.1GB, leaving ~1GB free on the 16GB card.
# So >= 6GB free proves the big model is NOT loaded — the GPU is genuinely
# idle and whisper fits with room to spare. Below that, dictation runs on
# CPU so the big model always gets its VRAM.
_STT_CUDA_MIN_FREE_MIB = 6 * 1024


def _free_vram_mib() -> Optional[int]:
    """Free VRAM in MiB (nvidia-smi), or None if no NVIDIA GPU / query fails."""
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
    """True if the big model (:8080) is loaded — used by the load gate so
    whisper never loads on CUDA while the big model is resident."""
    import socket
    from lib.config import CFG
    try:
        with socket.create_connection(("127.0.0.1", CFG.big_model_port), timeout=1):
            return True
    except OSError:
        return False


def _gpu_available() -> bool:
    """CUDA is safe only when the big model is down AND real VRAM is free.

    The free-VRAM check subsumes the big-model check at load time (big up →
    ~1GB free), but a fresh boot before the overseer loads anything also
    shows ~15GB free, so this is the honest gate: whisper fits alongside the
    overseer and big model only when they aren't resident.
    """
    free = _free_vram_mib()
    return free is not None and free >= _STT_CUDA_MIN_FREE_MIB and not _big_model_up()


def _get_model():
    global _model, _model_device
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                from lib.config import CFG
                device = CFG.stt_device
                if device == "auto":
                    # CUDA is ~10-20x faster than CPU for dictation, but only
                    # when the big model isn't loaded — whisper base fp16
                    # (0.43GB) fits beside big (13.7GB) + overseer (0.95GB)
                    # with only ~1GB free, so the 6GB gate proves the GPU is
                    # genuinely idle before loading. A failed cudaMalloc also
                    # falls back cleanly and never disturbs the big model's
                    # already-allocated context.
                    if _gpu_available():
                        try:
                            _model = WhisperModel(CFG.stt_model, device="cuda",
                                                  compute_type="float16")
                            _model_device = "cuda"
                        except Exception:
                            _model = WhisperModel(CFG.stt_model, device="cpu",
                                                  compute_type="int8")
                            _model_device = "cpu"
                    else:
                        _model = WhisperModel(CFG.stt_model, device="cpu",
                                              compute_type="int8")
                        _model_device = "cpu"
                else:
                    _model = WhisperModel(CFG.stt_model, device=device,
                                          compute_type="float16" if device == "cuda" else "int8")
                    _model_device = device
    return _model


def unload_if_idle() -> None:
    """Free whisper only when VRAM is genuinely about to OOM.

    Whisper stays resident once loaded — dictation must be instant, not pay
    a 2-3s CUDA reload. It fits alongside the big model (13.7GB) + overseer
    (0.95GB) with ~1GB free, so idle time and the big model appearing no
    longer unload it. The one exception: free VRAM under the OOM floor (a
    big-model generation spike) — then whisper frees itself so the big
    model never crashes. The next transcribe() reloads lazily.
    """
    global _model
    if _model is None:
        return
    if _model_device != "cuda":
        return  # CPU model holds no VRAM — nothing to free
    free = _free_vram_mib()
    if free is not None and free < _STT_OOM_FLOOR_MIB:
        with _model_lock:
            if _model is not None:
                _model = None


def transcribe(audio: Audio) -> str:
    """Transcribe audio (path or numpy float32 array) to raw text.

    English-only (``language="en"``) per user directive — dictation must never
    emit other languages. It also skips the language-detection pass, so it's
    faster than auto-detect.
    """
    model = _get_model()
    # Adaptive beam: on CUDA the GPU parallelizes beam search — width 5
    # costs nothing and is more accurate. On CPU the search is serial, so
    # beam 1 (greedy) is ~2-3x faster and keeps dictation snappy even when
    # the GPU is busy with the big model. faster-whisper expects 16kHz mono
    # float32 numpy arrays (no sampling_rate kwarg — that's an
    # openai-whisper/whisper.cpp param).
    beam = 5 if _model_device == "cuda" else 1
    segments, _info = model.transcribe(audio, beam_size=beam, language="en")
    return "".join(seg.text for seg in segments).strip()


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
    model = "tiny" if target == "tiny" else "big"
    prompt = (
        "You are a transcription cleaner. Fix punctuation, capitalization, "
        "and expand abbreviations in the following speech-to-text transcript. "
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
        return cleaned or text
    except Exception:
        return text  # fallback — STT never blocks on the model


def transcribe_and_cleanup(audio: Audio) -> str:
    """Full pipeline: transcribe → cleanup. Never raises."""
    raw = transcribe(audio)
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
