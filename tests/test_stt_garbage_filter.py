#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.stt_daemon import _text_is_meaningful  # noqa: E402




GARBAGE = [

    "P-P-P-P-P",
    "p-p-p-p",
    "B-B-B-B",

    "pppp",
    "AAAA",
    "sssss",
    "Mmmmm",

    "i am um Mike.STTskill in ppp",
    "um Mike.STTskill",
    "uh Mike.STTskill uh",

    "sorry sorry sorry",
    "thank you thank you thank you",
    "thank you. thank you. thank you.",
    "okay. okay. okay.",
    "I love you. I love you. I love you.",
    "see you later. see you later.",
    "bye bye bye",
    "bye bye",

    "I'm sorry I'm sorry I'm sorry",
    "I'm sorry. I'm sorry. I'm sorry.",

    "i'm going to take a deep breath i'm going to take a deep breath",
    "I'm going to take a deep breath. I'm going to take a deep breath.",
    "let me think let me think",
    "are you there are you there",
    "the cat sat on the mat the cat sat on the mat",
    "i don't know i don't know",
    "do you hear me do you hear me",




    "Thank you so much for watching, and I'll see you in the next video!",
    "thank you so much for watching, and i'll see you in the next video",
    "Thank you so much for watching",
    "thanks so much for watching and i'll see you in the next video",
    "thank you so much for watching and see you in the next video",
    "thank you for watching and i'll see you in the next video",
    "thanks for watching and i'll see you in the next video",


    "Thank you very much for watching, and I'll see you in the next video!",
    "thank you very much for watching, and i'll see you in the next video",
    "thank you very much for watching",
    "thanks very much for watching",
    "thanks very much for watching and i'll see you in the next video",



    "That's all for now. Thanks for watching. I'll see you in the next video. Bye.",
    "thats all for now thanks for watching ill see you in the next video bye",
    "That's all for now. Thanks for watching. Bye.",

    "x x x x x",
    "p p p p p",
    "a a a a",

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




REAL = [
    "yes",
    "Yes",
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
    "thanks",
    "thank you",

    "U.S.A.",
    "B.B. King",
    "Dr. Smith",
    "I went to the U.S.A. last year",
    "e.g.",
    "i.e.",
    "Mr. Smith arrived.",

    "Mike.",
    "?",
    "!",
    "no!",
    "yes.",

    "  yes  ",
    "\thello\n",


    "thanks for watching the video, I appreciate it",
    "I'll see you in the next video tomorrow",
    "thank you so much for watching over the project",
    "thank you very much for watching that build with me",


    "that's all for now, let's move on to the next part",
    "that's all for now",
]


class TestGarbageFiltered(unittest.TestCase):


    def test_all_garbage_filtered(self):
        for text in GARBAGE:
            with self.subTest(text=text):
                self.assertFalse(
                    _text_is_meaningful(text),
                    f"Garbage was accepted: {text!r}",
                )


class TestRealSpeechPasses(unittest.TestCase):


    def test_all_real_passes(self):
        for text in REAL:
            with self.subTest(text=text):
                self.assertTrue(
                    _text_is_meaningful(text),
                    f"Real speech was dropped: {text!r}",
                )


class TestEdgeCases(unittest.TestCase):


    def test_empty_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful(""))

    def test_whitespace_only_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful("   "))
        self.assertFalse(_text_is_meaningful("\t\n"))

    def test_punctuation_only_is_not_meaningful(self):
        self.assertFalse(_text_is_meaningful("..."))
        self.assertFalse(_text_is_meaningful(", , ,"))

    def test_single_real_word_is_meaningful(self):

        for word in ("yes", "no", "ok", "hi", "stop", "go", "run"):
            with self.subTest(word=word):
                self.assertTrue(_text_is_meaningful(word))


if __name__ == "__main__":
    unittest.main(verbosity=2)