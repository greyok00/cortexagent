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
import re
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
    # Whisper apology/repetition hallucinations on fan noise or silence.
    # Repeated 3+ times verbatim.
    "i'm sorry i'm sorry i'm sorry",
    "i'm sorry. i'm sorry. i'm sorry.",
    "i'm sorry. i'm sorry.",
    "thank you. thank you. thank you.",
    "thank you thank you thank you",
    "thank you. thank you.",
    "thanks for watching",
    "thanks for watching!",
    # User-reported variants (2026-08-18) that slipped past the exact-match
    # denylist and got typed into the focused window.
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

# Structural patterns that are essentially always Whisper hallucinations on
# non-speech audio. Applied BEFORE the denylist so they catch things like
# "P-P-P-P-P" (fan noise as repeated plosives) and "pppp" without needing to
# enumerate every letter.
#
# Each rule is paired with a comment explaining why we accept the false-positive
# risk: real speech rarely looks like repeated letter/dash runs, and a
# hallucination that slips through types random garbage into the user's chat.
import re as _re
_RE_LETTER_DASH_RUN = _re.compile(r"^[a-zA-Z](?:-[a-zA-Z]){3,}$")  # "P-P-P-P-P", "b-b-b-b"
_RE_LETTER_RUN = _re.compile(r"^([a-zA-Z])\1{3,}$")                 # "pppp", "AAAA"
_RE_WORD_REPEAT = _re.compile(r"^(\S+)(?:\s+\1){2,}$")              # "sorry sorry sorry"
_RE_DOTTED_WORDS = _re.compile(r"[a-zA-Z]\.[a-zA-Z]")               # "Mike.STTskill"
# A real word, possibly with an apostrophe contraction ("i'm", "it's").
# Used by _strip_leading_garbage to tokenize for leading-stutter detection.
_WORD = _re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")
_RE_SINGLE_TOKEN_REPEAT = _re.compile(r"^(\S{1,3})(\s+\1){3,}$")    # "x x x x", "a a a"
_RE_PHRASE_REPEAT = _re.compile(
    r"^((?:\S+\s+){2,}\S+)\s+\1\.?$"                                # multi-word phrase X X
)
# Stutter/apology words Whisper prepends to speech during mic noise. Used by
# _strip_leading_garbage to decide if a LEADING repeated phrase is a harmless
# hallucination stutter ("I'm sorry I'm sorry I'm sorry…") rather than real
# content. Only phrases composed ENTIRELY of these tokens get stripped, so
# real emphasis like "please please please help me" or "I really really want
# this" is preserved (those words aren't in this set).
_STUTTER_TOKENS = frozenset({
    "i", "i'm", "im", "me", "my", "sorry", "thank", "you", "your", "love",
    "bye", "okay", "ok", "uh", "um", "umm", "mm", "hmm", "so", "oh", "ah",
    "hey", "hi", "yeah", "yes", "no", "well", "like", "just", "a", "an",
    "the", "and", "to", "of", "it", "that", "this",
})

# Whisper hallucinates a BARE "you" / "you know" / "so" / "yeah" on silence
# even below the no-speech skip threshold. A user dictating never emits a
# standalone 1-2 word filler run, so drop such transcripts outright. Deliberately
# EXCLUDES real short commands ("yes"/"no"/"ok"/"hi") so genuine dictation of
# those survives. User-reported "ST says 'you' when I'm not even saying
# anything" (2026-08-20).
_NOISE_ONLY_WORDS = frozenset({
    "you", "your", "yours", "so", "yeah", "yep", "uh", "um", "umm", "mm",
    "hmm", "oh", "ah", "well", "like", "i", "im", "me", "my", "sorry",
    "thank", "and", "the", "to", "of", "it", "that", "this", "just", "a",
    "an", "know", "what",
})

# Collapse runs of 2+ identical words ANYWHERE in the transcript (not just
# leading), punctuation-tolerant. Whisper hallucinates "you you you." /
# "you, you, you." on mic noise/silence and appends such runs after real
# speech ("I mean you you you"). The \S+-anchored repeat regexes in
# _text_is_meaningful miss these (trailing punctuation breaks the exact-token
# match) and _strip_leading_garbage only looks at the front — so they typed
# through. \1 backrefs the same word (case/punct-insensitive); whether to
# collapse depends on the word being a stutter token, decided in _collapse.
_STUTTER_COLLAPSE = _re.compile(
    r"\b([a-zA-Z]+(?:'[a-zA-Z]+)?)\b(?:\s*,?\s*\1\b)+",
    _re.IGNORECASE,
)

# Short filler words Whisper emits during silence/noise. The dotted-word rule
# uses this list to decide if a transcript's non-dotted words look like
# noise-surrounding hallucinations vs real conversation.
#
# Adding a word here widens what counts as "filler" — keep entries limited
# to words that almost never carry semantic content on their own. Real short
# content words like 'cat', 'mat', 'run', 'dog' are deliberately excluded.
_FILLER_WORDS = frozenset({
    # Articles, pronouns, copulae, modals
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
    # Common Whisper filler on silence / breath
    "like", "well", "right", "just", "actually", "basically",
    "literally", "anyway", "anyways",
    # Garbage tokens Whisper injects into noise transcriptions
    "ppp", "pp", "xxx", "xxx.", "mmm", "huh", "huhh",
})

# Gratitude / outro vocabulary Whisper hallucinates on silence — "thank you
# very much", "thanks for watching the show", "subscribe to my channel", etc.
# These are the user-reported phrases (2026-08-18) that slipped past the
# exact-match denylist because Whisper varies the wording each time.
#
# The rule below drops a SHORT transcript (<= 8 tokens) when EVERY token is in
# this set. Real content almost always includes a content word outside this
# list ("thank you for your help with the build"), so it survives; a pure
# gratitude/outro hallucination is all these words and gets dropped. This is
# the same false-positive trade-off the dotted-word rule already accepts.
_HALLUCINATION_TOKENS = frozenset({
    # gratitude / outro — limited to tokens that ONLY appear in YouTube-style
    # outros. Real short utterances ("thank you", "I love you", "see you
    # later") use these same words but must NOT be filtered, so the
    # `_HALLUCINATION_OUTRO_PHRASES` set below is what we actually consult.
    # This set is kept around for the dotted-word rule only — it does NOT
    # participate in the "all-tokens-in-set" outro check.
    "thank", "thanks", "you", "your", "yours", "very", "much", "watching",
    "watch", "show", "subscribe", "subscribed", "channel", "bye", "love",
    "see", "later", "welcome", "please", "enjoy", "appreciate", "appreciated",
})

# Canonical Whisper outro phrases — only drop transcripts whose normalized
# form equals one of these. Common in-conversation phrases ("thank you",
# "I love you", "see you later") ARE real speech and must NOT be filtered
# just because Whisper occasionally attaches them as outros.
_HALLUCINATION_OUTRO_PHRASES = frozenset({
    "thanks for watching", "thanks for watching the show",
    "thank you for watching", "subscribe to my channel",
    "see you in the next video", "see you next time",
    "thanks for listening", "thanks for your time",
    # Full YouTube-outro sentence Whisper hallucinates as ONE utterance
    # (user-reported 2026-08-20: "Thank you so much for watching, and I'll
    # see you in the next video!" kept getting typed into the prompt). Stored
    # in cleaned form (see _clean_phrase) so the matcher is punctuation- and
    # apostrophe-insensitive — Whisper's wording varies every run. Both
    # "so much" AND "very much" variants are covered (the log showed both;
    # the structural _RE_OUTRO_FOR_WATCHING rule catches the family broadly).
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
    # Full outro WITH prefix + sign-off (user-reported 2026-08-20: "That's all
    # for now. Thanks for watching. I'll see you in the next video. Bye.").
    # The marker-based _OUTRO_MARKERS rule below catches this family broadly;
    # this entry keeps the exact phrase in the canonical set for the repeat
    # check.
    "thats all for now thanks for watching ill see you in the next video bye",
    # "bye bye bye" is a Whisper silence/noise hallucination — it's pure
    # repetition and would already be caught by _RE_WORD_REPEAT, but the
    # denylist entry keeps the rule explicit for downstream code paths.
    "bye bye bye",
})


def _clean_phrase(text: str) -> str:
    """Normalize a transcript for canonical-outro matching: lowercase, drop
    every non-word character (commas, periods, exclamations, apostrophes),
    collapse whitespace. Whisper's outro hallucinations vary wording AND
    punctuation between runs ("watching, and I'll" vs "watching and ill"),
    so comparing cleaned forms lets one denylist entry catch every variant.
    """
    return " ".join(_re.sub(r"[^\w ]", "", text.lower()).split())


# Cleaned forms of the canonical outros — the actual comparison set used by
# _text_is_meaningful (membership + repeat checks both go through this).
_OUTRO_CANONICAL = frozenset(_clean_phrase(p) for p in _HALLUCINATION_OUTRO_PHRASES)

# Whisper varies the "for watching" outro wording on EVERY run ("thank you so
# much", "thank you very much", "thanks very much", "thank you for watching",
# with or without "and I'll see you in the next video"). Enumerating every
# variant is a losing arms race — match the STRUCTURE of the outro on the
# cleaned form instead (anchored, so real dictation that merely CONTAINS these
# words — "thank you for watching that with me", "thanks for watching the
# video, I appreciate it" — does NOT match because it doesn't end there).
_RE_OUTRO_FOR_WATCHING = _re.compile(
    r"^thanks? (?:you )?(?:so |very )?much? for watching"
    r"(?: and (?:ill? |i will )?see you in (?:the )?next video)?$"
)

# Whisper's outro hallucinations keep growing new prefixes/suffixes around the
# same core ("That's all for now. Thanks for watching. I'll see you in the next
# video. Bye." — user-reported 2026-08-20). Enumerating full sentences is a
# losing arms race. Instead: any SHORT transcript that contains the outro's
# signature "for watching" PLUS a follow-up outro marker is a YouTube-outro
# hallucination, whatever the prefix/suffix wording. Real dictation that merely
# mentions watching ("thanks for watching the video, I appreciate it") lacks the
# follow-up marker and survives.
_OUTRO_MARKERS = ("next video", "subscribe", "channel", "thats all for now", "bye bye")


def _text_is_meaningful(text: str) -> bool:
    """True if `text` is real content, not a Whisper silence hallucination.

    Drops pure-punctuation runs, a denylist of known breath/filler tokens,
    and structurally-obvious hallucinations:
      - letter-with-dash runs ("P-P-P-P-P")
      - single-letter runs ("pppp", "AAAA")
      - same word/short-token repeated 3+ times
      - same multi-word phrase repeated back-to-back
        ("i'm going to take a deep breath i'm going to take a deep breath")
      - dotted-word hallucinations like "Mike.STTskill" (only when the
        dotted pattern is the WHOLE text — single-token abbreviations
        like "U.S.A." are not affected)

    Real short words like 'yes', 'ok', 'no', 'hi' still pass through.
    """
    if not text:
        return False
    # Pure punctuation/whitespace: any combo of ".", ",", " ", "\t", "\n"
    if all(c in "., \t\n" for c in text):
        return False
    normalized = text.strip().lower()

    # Structural hallucinations — cheap regex checks first.
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
    # Dotted-word hallucination: Whisper emits tokens like "Mike.STTskill"
    # on mic noise, surrounded by filler tokens ("i am um Mike.STTskill in
    # ppp"). Real abbreviations ("U.S.A.", "B.B. King", "Dr. Smith") are
    # used inside meaningful sentences. We flag dotted-token transcripts
    # ONLY when every non-dotted token is in the curated _FILLER_WORDS set
    # (curated to be heavy on stopwords + Whisper noise vocabulary, light on
    # real short words like 'the'/'cat'/'mat' that should pass through).
    if " " in normalized:
        tokens = normalized.split()
        non_dotted = [t for t in tokens if not _RE_DOTTED_WORDS.search(t)]
        dotted = [t for t in tokens if _RE_DOTTED_WORDS.search(t)]
        # Only fire when there IS at least one dotted token (otherwise we'd
        # be matching on a stopword-only sentence like "are you there").
        if dotted and non_dotted:
            looks_like_filler = all(
                _re.sub(r"[^\w]", "", t) in _FILLER_WORDS
                for t in non_dotted
            )
            if looks_like_filler and len(tokens) <= 8:
                return False
        # Gratitude / outro hallucination: drop only when the transcript IS a
        # canonical Whisper outro (whole text equals one of the short set,
        # compared punctuation-insensitively via _clean_phrase — Whisper
        # varies commas/periods/apostrophes between runs of the same outro,
        # e.g. "watching, and I'll" vs "watching and ill"). Real content like
        # "thank you" or "I love you" (said once, in conversation, not as a
        # YouTube-style outro) survives because it is not in the canonical
        # outro set.
        cleaned = _clean_phrase(normalized)
        # Structural outro match — catches the whole "for watching" family
        # ("so much" / "very much" / with or without "and I'll see you in the
        # next video") without enumerating every wording variant.
        if _RE_OUTRO_FOR_WATCHING.match(cleaned):
            return False
        # Marker-based outro detection: "for watching" + a follow-up outro
        # marker ("next video", "subscribe", "channel", "that's all for now",
        # "bye bye") = YouTube-outro hallucination, whatever the prefix/suffix
        # wording. Word-count guard keeps long real dictation safe.
        if (
            "for watching" in cleaned
            and any(m in cleaned for m in _OUTRO_MARKERS)
            and len(cleaned.split()) <= 20
        ):
            return False
        if cleaned in _OUTRO_CANONICAL:
            return False
        # Also drop the trailing/repeated outro pattern: transcripts whose
        # token sequence is one canonical outro repeated 2+ times.
        # Punctuation-insensitive: the "X. X." variants collapse to the same
        # cleaned form, so one compare covers both.
        for phrase in _OUTRO_CANONICAL:
            if cleaned == f"{phrase} {phrase}":
                return False

    # Silence/noise hallucination: a bare noise word ("you", "so", "yeah") or a
    # pure repeat of it ("you you"). A user dictating never emits these alone.
    # Real multi-word phrases with a content word ("thank you", "you know") are
    # NOT matched (different tokens), and real "yes"/"no"/"ok" aren't in the
    # noise set — both survive.
    toks = [_re.sub(r"[^\w']", "", t).lower() for t in normalized.split() if t.strip()]
    if toks and toks[0] in _NOISE_ONLY_WORDS and (
        len(toks) == 1 or all(t == toks[0] for t in toks)
    ):
        return False

    return normalized not in _GARBAGE_TOKENS


def _strip_leading_garbage(text: str) -> str:
    """Strip a leading repeated stutter phrase (Whisper hallucination) from the
    front of an otherwise-meaningful transcript.

    Whisper often prepends a stutter of the same short phrase before real
    speech, e.g. "I'm sorry, I'm sorry, I'm sorry, I'm sorry, I'm sorry. Okay
    so it's still in the I'm sorry thing again…". The message IS meaningful, so
    `_text_is_meaningful` correctly keeps it — but the leading hallucination
    still gets typed. This strips a phrase repeated 2+ times at the very start
    (comma/period/space separated) when the whole phrase is made of known
    stutter/apology words (_STUTTER_TOKENS), leaving the real content intact.

    Guards against false positives:
      - A single "I'm sorry" (a genuine apology) is NOT stripped — only a
        repeated (2+) stutter.
      - Real emphasis like "please please please help me" or "I really really
        want this" is preserved, because 'please'/'really' aren't in the
        stutter set.
    If nothing meaningful remains after stripping, returns "" so the caller
    drops the whole transcript.
    """
    if not text:
        return text
    matches = list(_WORD.finditer(text))
    # Need at least 2 words before we can even look for a 2x repeat of a
    # single word. (The old >=4 guard let a short utterance like "you you go"
    # slip through unstripped — a leading single-word stutter only needs 2
    # words to repeat. The plen loop below still returns text unchanged when
    # no real 2+ repeat exists, so lowering the floor is safe.)
    if len(matches) < 2:
        return text
    words = [m.group(0).lower() for m in matches]

    # Try phrase lengths 1..4; prefer the shortest that repeats (a 2-word
    # phrase "i'm sorry" over a 1-word "i'm").
    for plen in (2, 1, 3, 4):
        if plen > len(words):
            continue
        phrase = tuple(words[:plen])
        if not all(w in _STUTTER_TOKENS for w in phrase):
            continue
        # Count consecutive repeats of `phrase` from the very start.
        n = 1
        while n * plen + plen <= len(words) and \
              tuple(words[n * plen:(n + 1) * plen]) == phrase:
            n += 1
        if n < 2:
            continue
        # Strip the repeated phrases; drop any leading separator of the rest.
        end_idx = matches[n * plen - 1].end()
        rest = text[end_idx:].lstrip(" ,.!?;:\t\n")
        # If only punctuation/whitespace remains, the whole thing was garbage.
        if not rest or all(c in ".,!? \t\n" for c in rest):
            return ""
        return rest
    return text


def _strip_repeated_stutter(text: str) -> str:
    """Collapse a run of 2+ identical stutter tokens anywhere in the text to a
    single token, and drop the whole transcript if only stutter remains (a
    silence/noise hallucination). Punctuation-tolerant.

    - "I mean you you you."     -> "I mean you."   (collapse trailing run)
    - "you, you, you."          -> ""              (pure run — nothing real)
    - "you know what I mean"    -> unchanged       (single 'you')
    - "please please please"    -> unchanged       ('please' isn't stutter)
    """
    def _collapse(m):
        # Only collapse when the repeated word is a stutter token; keep
        # genuine emphasis like "please please please" (not in the set) intact.
        if m.group(1).lower() in _STUTTER_TOKENS:
            return m.group(1)  # single occurrence
        return m.group(0)      # leave the whole run as-is

    if not text:
        return text
    collapsed = _STUTTER_COLLAPSE.sub(_collapse, text)
    if collapsed == text:
        return text  # no repeat to collapse
    tokens = [m.group(0).lower() for m in _WORD.finditer(collapsed)]
    if tokens and all(w in _STUTTER_TOKENS for w in tokens):
        return ""  # only stutter left — it was a silence hallucination
    return collapsed


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
            # Strip a leading repeated filler stutter ("I'm sorry, I'm sorry…")
            # from the front of an otherwise-meaningful transcript, then
            # collapse any repeated-stutter run ("you you you") anywhere.
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


_TARGET_PEAK = 0.70  # ~ -3 dBFS: full-range signal, safely below clipping.


def _normalize_clip(clip: np.ndarray) -> tuple[np.ndarray, float]:
    """Scale a float32 clip so its peak ≈ _TARGET_PEAK — soft normalization
    only, never amplifies (quiet clips pass through untouched so background
    noise isn't boosted). Returns (clip, clip_ratio) where clip_ratio is the
    fraction of samples pinned at max amplitude. clip_ratio above ~1% means
    the mic/input is hard-clipping: the waveform is flat-topped and no
    software can recover the lost consonants — the user must lower the input
    volume.
    """
    if clip.size == 0:
        return clip, 0.0
    peak = float(np.max(np.abs(clip)))
    clip_ratio = float(np.mean(np.abs(clip) > 0.999))
    if peak <= 0 or peak < _TARGET_PEAK:
        return clip, clip_ratio
    return clip * (_TARGET_PEAK / peak), clip_ratio


def _handle_clip(clip: np.ndarray) -> None:
    """Queue a recorded clip for transcription (non-blocking)."""
    clip, clip_ratio = _normalize_clip(clip)
    if clip_ratio > 0.01:
        print(f"⚠️ mic CLIPPING — {clip_ratio*100:.1f}% of samples at max level. "
              f"Lower the input/mic volume; maxed gain distorts STT.", flush=True)
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
