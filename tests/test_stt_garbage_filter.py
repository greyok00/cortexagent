#!/usr/bin/env python3
"""tests/test_stt_garbage_filter.py — regression tests for STT hallucination filter.

User-reported noise transcripts the daemon must drop before typing:
  P-P-P-P-P          (fan noise as repeated plosives)
  pppp, AAAA         (single-letter runs)
  um Mike.STTskill in ppp   (dotted-word hallucination surrounded by filler)
  sorry sorry sorry   (word-repetition hallucination)
  x x x x x           (single-token repeat)
  I'm sorry I'm sorry I'm sorry   (apology hallucination)
  thank you. thank you. thank you.

Real speech that must still pass:
  yes, ok, hi, no, run tests, hello world, stop, go
  U.S.A., B.B. King, Dr. Smith, I went to the U.S.A. last year
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make `lib.stt_daemon` importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.stt_daemon import _text_is_meaningful  # noqa: E402


# ── Garbage that MUST be filtered ────────────────────────────────────────────

GARBAGE = [
    # User-reported fan-noise hallucinations
    "P-P-P-P-P",
    "p-p-p-p",
    "B-B-B-B",
    # Single-letter runs (any case)
    "pppp",
    "AAAA",
    "sssss",
    "Mmmmm",
    # Dotted-word hallucination with filler surroundings
    "i am um Mike.STTskill in ppp",
    "um Mike.STTskill",
    "uh Mike.STTskill uh",
    # Word-repetition hallucinations
    "sorry sorry sorry",
    "thank you thank you thank you",
    "thank you. thank you. thank you.",
    "okay. okay. okay.",
    "I love you. I love you. I love you.",
    "see you later. see you later.",
    "bye bye bye",
    "bye bye",
    # Apology repetition
    "I'm sorry I'm sorry I'm sorry",
    "I'm sorry. I'm sorry. I'm sorry.",
    # Phrase repetition — user-reported 2026-08-17 deep-breath hallucination
    "i'm going to take a deep breath i'm going to take a deep breath",
    "I'm going to take a deep breath. I'm going to take a deep breath.",
    "let me think let me think",
    "are you there are you there",
    "the cat sat on the mat the cat sat on the mat",
    "i don't know i don't know",
    "do you hear me do you hear me",
    # YouTube outro hallucination — user-reported 2026-08-20: STT keeps
    # typing "Thank you so much for watching, and I'll see you in the next
    # video!" (Whisper hallucinating a channel outro on ambient noise).
    # The punctuation-insensitive canonical-outro match must drop these.
    "Thank you so much for watching, and I'll see you in the next video!",
    "thank you so much for watching, and i'll see you in the next video",
    "Thank you so much for watching",
    "thanks so much for watching and i'll see you in the next video",
    "thank you so much for watching and see you in the next video",
    "thank you for watching and i'll see you in the next video",
    "thanks for watching and i'll see you in the next video",
    # "very much" variants — user reported the model ALSO says these, and
    # they slipped the first "so much"-only denylist (2026-08-20).
    "Thank you very much for watching, and I'll see you in the next video!",
    "thank you very much for watching, and i'll see you in the next video",
    "thank you very much for watching",
    "thanks very much for watching",
    "thanks very much for watching and i'll see you in the next video",
    # Full outro WITH prefix + sign-off — user-reported 2026-08-20: the
    # "for watching" + "next video" marker combo must drop these regardless
    # of the prefix/suffix wording.
    "That's all for now. Thanks for watching. I'll see you in the next video. Bye.",
    "thats all for now thanks for watching ill see you in the next video bye",
    "That's all for now. Thanks for watching. Bye.",
    # Single-token repetitions (Whisper silence hallucinations)
    "x x x x x",
    "p p p p p",
    "a a a a",
    # Original denylist (must still be filtered)
    "",
    ".",
    "..",
    "...",
    ". . .",
    ",",
    "uh",
    "umm",
    "hmm",
    "[silence]",
    "(silence)",
    "[music]",
]


# ── Real speech that MUST pass through ───────────────────────────────────────

REAL = [
    "yes",
    "Yes",  # case-insensitive
    "YES",
    "ok",
    "OK",
    "okay",
    "hi",
    "no",
    "stop",
    "go",
    "run",
    "test",
    "run tests",
    "hello world",
    "I am working on the project",
    "thanks",  # short but real
    "thank you",
    # Real abbreviations and dotted-text in conversation
    "U.S.A.",
    "B.B. King",
    "Dr. Smith",
    "I went to the U.S.A. last year",
    "e.g.",
    "i.e.",
    "Mr. Smith arrived.",
    # Punctuation at boundaries
    "Mike.",
    "?",
    "!",
    "no!",
    "yes.",
    # Whitespace variations
    "  yes  ",
    "\thello\n",
    # YouTube-outro words used in REAL conversation must NOT be dropped
    # (only whole-transcript exact outro matches are filtered).
    "thanks for watching the video, I appreciate it",
    "I'll see you in the next video tomorrow",
    "thank you so much for watching over the project",
    "thank you very much for watching that build with me",
    # "that's all for now" used in REAL conversation (no "for watching" +
    # outro-marker combo) must NOT be dropped.
    "that's all for now, let's move on to the next part",
    "that's all for now",
]


class TestGarbageFiltered(unittest.TestCase):
    """Every entry in GARBAGE must be classified as not meaningful."""

    def test_all_garbage_filtered(self):
        for text in GARBAGE:
            with self.subTest(text=text):
                self.assertFalse(
                    _text_is_meaningful(text),
                    f"Garbage was accepted: {text!r}",
                )


class TestRealSpeechPasses(unittest.TestCase):
    """Every entry in REAL must be classified as meaningful."""

    def test_all_real_passes(self):
        for text in REAL:
            with self.subTest(text=text):
                self.assertTrue(
                    _text_is_meaningful(text),
                    f"Real speech was dropped: {text!r}",
                )


class TestEdgeCases(unittest.TestCase):
    """One-off invariants."""

    def test_empty_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful(""))

    def test_whitespace_only_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful("   "))
        self.assertFalse(_text_is_meaningful("\t\n"))

    def test_punctuation_only_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful("..."))
        self.assertFalse(_text_is_meaningful(", , ,"))

    def test_single_real_word_is_meaningful(self):
        # The user's existing rule: real short words pass through.
        for word in ("yes", "no", "ok", "hi", "stop", "go", "run"):
            with self.subTest(word=word):
                self.assertTrue(_text_is_meaningful(word))


if __name__ == "__main__":
    unittest.main(verbosity=2)