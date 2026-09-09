#!/usr/bin/env python3

from __future__ import annotations

import sys
import subprocess
import tempfile
import threading
import re
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
    "tiny":  330, "tiny.en": 330,
    "base":  394, "base.en": 394,
    "small": 778, "small.en": 778,
    "medium": 1500, "medium.en": 1500,
    "large":  3100, "large-v3": 3100,
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




                # 2026-08-26: NEVER fall back to CPU silently. STT must
                # stay on GPU. If the requested model doesn't fit, pick the
                # largest variant that does — never downgrade the device.
                requested = CFG.stt_model
                free = _free_vram_mib() or 0
                order = ["large-v3", "large", "medium", "small", "base", "tiny"]
                chosen = requested
                chosen_fp16 = _STT_MODEL_VRAM.get(requested, 970)
                chosen_need = max(150, chosen_fp16 // 2 + 50) + _STT_GATE_HEADROOM_MIB

                if free < chosen_need:
                    for cand in order:
                        cand_full = cand if requested.endswith(".en") else cand
                        cand_fp16 = _STT_MODEL_VRAM.get(cand_full, 0)
                        cand_need = max(150, cand_fp16 // 2 + 50) + _STT_GATE_HEADROOM_MIB
                        if free >= cand_need:
                            chosen = cand_full
                            print(
                                f"🎙️ STT: {requested} needs {chosen_need} MiB, "
                                f"only {free} MiB free — using {chosen} "
                                f"({cand_need} MiB) on GPU",
                                flush=True,
                            )
                            break
                    else:
                        try:
                            _model = WhisperModel("tiny", device="cuda",
                                                  compute_type="int8")
                            _model_device = "cuda"
                            print(f"🎙️ STT: forced tiny on GPU ({free} MiB was free)",
                                  flush=True)
                            return _model
                        except Exception as e:
                            print(
                                f"⚠️ STT: GPU unavailable ({e}) — CPU as last resort",
                                flush=True,
                            )
                            _model = WhisperModel(requested, device="cpu",
                                                  compute_type="int8")
                            _model_device = "cpu"
                            return _model

                try:
                    _model = WhisperModel(chosen, device="cuda",
                                          compute_type="int8")
                    _model_device = "cuda"
                    print(
                        f"🎙️ STT loaded {chosen} on GPU (int8, {free} MiB free)",
                        flush=True,
                    )
                except Exception as e:
                    print(f"⚠️ STT: cuda init failed ({e}) — CPU as last resort",
                          flush=True)
                    _model = WhisperModel(requested, device="cpu",
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
    port = CFG.big_model_port
    model = "big"
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
        "chat_template_kwargs": {"enable_thinking": False},
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


# ── Deterministic homophone/mishearing correction (2026-08-31) ─────────────
# The base whisper model collapses short phrases into homophones ("will it" ->
# "wheel", "will I" -> "aisle") and writes casual/contracted forms. No LLM, no
# latency — a conservative whole-word + phrase replacement table, pure Python.
#
# Single-word entries: "misheard" -> ("correct", guard). guard "verb_follow"
# only fires when the word is followed by another word AND not preceded by a
# determiner, so "wheel work" -> "will it work" but "the wheel" stays "wheel".
# guard None = unconditional (safe: the misheard form is never a valid word).
_HOMOPHONE_FIXES = {
    # meaning-changing mishearings (guarded so legit nouns survive):
    "wheel": ("will it", "verb_follow"),
    "aisle": ("will I", "verb_follow"),
    # unconditional — the misheard form is never correct:
    "alot": ("a lot", None),
    "eachother": ("each other", None),
    "everytime": ("every time", None),
    "anyways": ("anyway", None),
    "gonna": ("going to", None),
    "wanna": ("want to", None),
    "gotta": ("got to", None),
    "hafta": ("have to", None),
    "hasta": ("has to", None),
    "kinda": ("kind of", None),
    "sorta": ("sort of", None),
    "lemme": ("let me", None),
    "gimme": ("give me", None),
    "dunno": ("don't know", None),
    "shoulda": ("should have", None),
    "coulda": ("could have", None),
    "woulda": ("would have", None),
    "musta": ("must have", None),
    "oughta": ("ought to", None),
    "prolly": ("probably", None),
    "cuz": ("because", None),
    "outta": ("out of", None),
    "y'all": ("you all", None),
    "c'mon": ("come on", None),
    "'cause": ("because", None),
    "'em": ("them", None),
    "'til": ("until", None),
}

# Multi-word grammar/mishearing fixes (regex, word-boundary aware, case kept).
_PHRASE_FIXES = [
    (r"\bcould of\b", "could have"),
    (r"\bshould of\b", "should have"),
    (r"\bwould of\b", "would have"),
    (r"\bmight of\b", "might have"),
    (r"\bmust of\b", "must have"),
    (r"\bsuppose to\b", "supposed to"),
]

_DETERMINERS = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "some", "any", "no", "every",
    "each", "both", "all", "another", "other",
})


def _apply_case(word: str, replacement: str) -> str:
    if word[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _phrase_case(match: "re.Match", replacement: str) -> str:
    if match.group(0)[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def fix_homophones(text: str) -> str:
    """Deterministic correction of known whisper mishearings. No LLM, no
    latency. Only patterns in _HOMOPHONE_FIXES / _PHRASE_FIXES are touched."""
    if not text:
        return text
    # 1. Multi-word phrase fixes first (so "could of" -> "could have").
    for pat, repl in _PHRASE_FIXES:
        text = re.sub(pat, lambda m: _phrase_case(m, repl), text,
                      flags=re.IGNORECASE)
    # 2. Single-word fixes.
    words = text.split()
    out = []
    for i, w in enumerate(words):
        fix = _HOMOPHONE_FIXES.get(w.lower())
        if fix is None:
            out.append(w)
            continue
        correct, guard = fix
        if guard == "verb_follow":
            has_follow = i + 1 < len(words)
            prev = words[i - 1].lower() if i > 0 else ""
            if not (has_follow and prev not in _DETERMINERS):
                out.append(w)
                continue
        out.append(_apply_case(w, correct))
    return " ".join(out)


def _test() -> int:
    wav = Path(tempfile.gettempdir()) / "stt_sample.wav"
    subprocess.run(["espeak-ng", "-v", "en-us", "-w", str(wav),
                    "fix the proxy token accounting bug"], check=True)
    text = transcribe(wav)
    print(f"transcribed: {text!r}")
    return 0 if text.strip() else 1


if __name__ == "__main__":
    sys.exit(_test())
