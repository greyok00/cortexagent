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
