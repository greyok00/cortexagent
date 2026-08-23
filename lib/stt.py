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
_STT_OOM_FLOOR_MIB = 256  # only release whisper when truly about to OOM-kill.
# 256 MiB is below the cudaMalloc minimum (typically ~280 MiB) so any
# attempt to allocate would fail loudly with OOM — not silently evict
# whisper mid-clip. 512 was too high: it tripped on every big-model
# generation spike (kv-cache grows 1-2 MiB per token) and unloaded
# whisper, causing the next clip to pay a 5s reload. With small-int8
# (480 MiB), whisper is half the size it was at design time, so this
# conservative floor is safe.
# Minimum free VRAM (MiB) before whisper may load on CUDA. The old gate of
# 6 GB was wrong on this box: with the big model (Qwen3.6-35B, ~13.7 GB)
# + overseer (LFM2.5-1.2B, ~0.95 GB) resident there is only ~1.3 GB free,
# so the 6 GB gate ALWAYS forced STT onto CPU — ~10-20× slower and greedy
# (beam=1) instead of beam=5, which is what produced "extremely bad delay"
# / "misses half the text" / "terribly formed" complaints on 2026-08-20.
#
# Real VRAM costs (faster-whisper, same workload):
#   small  int8  ≈ 480 MiB   fp16 ≈ 970 MiB
#   base   int8  ≈ 290 MiB   fp16 ≈ 580 MiB
#   tiny   int8  ≈ 150 MiB   fp16 ≈ 300 MiB
#
# Gate = model-cost(fp16) + 100 MiB safety + 50 MiB headroom for KV growth on
# long clips. So with the daemon running small we need ≥ 1120 MiB free to
# safely load. The OOM floor (512 MiB) continues to govern whether we
# unload (unload_if_idle) — the two thresholds together guarantee the big
# model never loses context to a transient whisper load.
_STT_MODEL_VRAM = {  # fp16 costs on this box (int8 is half)
    "tiny":  300, "tiny.en": 300,
    "base":  580, "base.en": 580,
    "small": 970, "small.en": 970,
    "medium": 2300, "medium.en": 2300,
    "large":  3900, "large-v3": 3900,
}
_STT_GATE_HEADROOM_MIB = 150  # model cost + this = "enough room to load"


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


def _gpu_available(model_name: str) -> bool:
    """True when CUDA can host the given whisper model without risking the
    big model's context.

    Gate is sized to the actual cost whisper will incur at our chosen
    compute_type (int8 — see _get_model), which is roughly half of the
    fp16 number listed in the table. With the 13.7 GB big model + 0.95 GB
    overseer resident we ALWAYS have ~500 MiB free, so we use int8 costs
    to land in that envelope. The OOM floor (_STT_OOM_FLOOR_MIB) handled
    by unload_if_idle() protects against the big model ever being asked
    to free memory under pressure.
    """
    free = _free_vram_mib()
    if free is None:
        return False
    fp16 = _STT_MODEL_VRAM.get(model_name, 970)
    # int8 ≈ fp16 / 2 (CTranslate2 weights + activations compress similarly)
    int8_estimate = max(150, fp16 // 2 + 50)  # 50 MiB CTranslate2 runtime overhead
    need = int8_estimate + _STT_GATE_HEADROOM_MIB
    return free >= need


def _get_model():
    global _model, _model_device
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                from lib.config import CFG
                # CUDA fastpath regardless of "auto"/"cuda" — the user has
                # had STT silently fall back to CPU too often (2026-08-20).
                # If the model fits per _gpu_available() we always prefer
                # GPU. CPU only when the gate genuinely fails.
                if _gpu_available(CFG.stt_model):
                    try:
                        # int8 on CUDA: small = ~480 MiB instead of fp16's
                        # ~970. Cuts VRAM ~50% with no perceptible loss at
                        # this beam size. Combined with the lowered OOM
                        # floor, whisper now STAYS resident across big-model
                        # generation spikes instead of being silently
                        # unloaded and re-loaded on the next clip.
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
    """STAY RESIDENT: do not unload whisper unless VRAM is about to OOM-kill.

    Older policy unloaded when free < 512 MiB. That fired on every big-model
    generation spike (kv-cache +1-2 MiB / token during long generations) and
    forced a 5s CUDA reload on the very next clip — exactly the silent
    degradation users reported ("fast sometimes, slow other times, no
    visible reason"). With small-int8 = 480 MiB + big+overseer locked at
    14.78 GB, steady-state free is ~520 MiB — comfortably above this floor
    of 256 MiB (the lowest a CUDA malloc can actually succeed at). If we
    ever cross that line, the kernel would have already failed an alloc,
    so unloading at 256 MiB is the conservative last-resort.

    Whisper is the priority victim because it's the only model the user can
    tolerate a brief reload on; the big model and overseer must not lose
    context for the next chat turn.
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

    NOTE: we deliberately do NOT pass an ``initial_prompt``. A long prompt of
    complete sentences acts as strong *previous* text, and on short/quiet VAD
    clips faster-whisper continues the prompt's own phrases instead of
    transcribing — it hallucinated "Done." and "The model is loaded." (both
    from the prompt) into the focused window (2026-08-19). Punctuation/case
    polish is left to the optional cleanup pass; raw whisper output is faithful.
    """
    model = _get_model()
    # Adaptive beam: on CUDA the GPU parallelizes beam search — width 5
    # costs nothing and is more accurate. CPU floor is width 2 (directive:
    # never greedy again — beam-1 single-hypothesis decoding is what lets a
    # noisy-room clip drop words). The serial beam-2 pass is ~1.6-2x the
    # greedy cost, but the transcribe worker is async (8-slot queue) so the
    # mic never blocks on it. faster-whisper expects 16kHz mono float32
    # numpy arrays (no sampling_rate kwarg — that's an openai-whisper /
    # whisper.cpp param).
    beam = 5 if _model_device == "cuda" else 2
    # condition_on_previous_text=False is the canonical fix for whisper's
    # self-perpetuating "you" / "thank you" hallucination on short VAD clips:
    # by default each clip conditions on the previous clip's text, so a single
    # hallucinated "you" keeps regenerating on every subsequent clip. Each VAD
    # clip is independent speech, so disabling cross-clip conditioning is both
    # safe and the actual cure for "STT keeps adding 'you' all the time"
    # (2026-08-20).
    segments, _info = model.transcribe(
        audio,
        beam_size=beam,
        language="en",
        condition_on_previous_text=False,
        # Stricter no-speech gate. faster-whisper's default (0.6) lets many
        # near-silent/noise segments through, and whisper hallucinates "you" /
        # "so" / "thank you" on exactly those. Lowering it makes whisper skip
        # more non-speech segments itself; whisper still keeps real speech
        # (it only skips when logprob is low). Directly fixes "ST says 'you'
        # when I'm not even saying anything" (2026-08-20).
        no_speech_threshold=0.4,
    )
    return "".join(seg.text for seg in segments).strip()


def cleanup(text: str) -> str:
    """Clean a transcript via the tiny overseer (:8082). Falls back to raw.

    Never raises and never blocks: any failure (model down, timeout, bad
    response) returns the input unchanged.

    Output is capped to ``CFG.stt_cleanup_max_sentences`` (default 4) so a
    single dictation burst doesn't dump a paragraph into the focused prompt.
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
        # Cap to N sentences so a long dictation doesn't overload the prompt.
        return _cap_sentences(cleaned, CFG.stt_cleanup_max_sentences)
    except Exception:
        return text  # fallback — STT never blocks on the model


def _cap_sentences(text: str, max_sentences: int) -> str:
    """Return the first `max_sentences` sentences from `text`.

    Sentence boundaries: ``.``, ``!``, ``?`` followed by whitespace + capital
    or end-of-string. We never split inside a sentence — if the cap falls
    mid-sentence we include the partial sentence to preserve meaning.
    """
    if max_sentences <= 0:
        return text
    import re
    # Split on sentence-terminator + space; keep the terminator on the left.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(parts) <= max_sentences:
        # Even when under the cap, strip trailing whitespace per sentence.
        return " ".join(p.strip() for p in parts if p.strip())
    return " ".join(p.strip() for p in parts[:max_sentences] if p.strip())


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
