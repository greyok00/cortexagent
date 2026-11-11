#!/usr/bin/env python3
"""image_gate.py: the ONE definition of the image checks that BOTH gates
apply (relevance.gate_image on the research side, site_render's
_image_is_junk on the site build side). Before this module existed the
stock/ad/short-alt checks lived as separate copies in both files and could
drift apart silently.

These rules edit user-visible content: an image this gate rejects never
reaches the guide or the site, so each reject traces to a named check
below.

The per-consumer scope is intentional. The JUNK-word and DIAGRAM-word
alternates stay per-consumer: relevance's lists intentionally carry a few
extra words, and site_render's build-side verdict path adds its own chrome
checks (JUNK_RE/BAD_HOST_RE/AVATAR_RE). Unifying those lists is a later
behavior change; image_gate deliberately decides NOTHING about topicality.
"""

from __future__ import annotations

import re

# IMAGE_MIN_ALT_WORDS: an alt text shorter than this cannot prove the
# image is topical, unless it names a diagram shape (the caller supplies
# its own diagram matcher, kept per-consumer by design).
IMAGE_MIN_ALT_WORDS = 3

# The stock/hero URL tell and the ad-network pixel hosts: byte-identical
# in both consumers since they first existed (one definition now).
STOCK_SRC_RE = re.compile(
    r"(?i)(adobestock|istockphoto|shutterstock|gettyimages|dreamstime|"
    r"depositphotos|freepik|pexels|unsplash|_next/image|hero[_/-]|heroimage)")
AD_NETWORK_RE = re.compile(
    r"(?i)(ad\.gt|pubmatic|doubleclick|googlesyndication|adsystem|taboola|"
    r"outbrain|criteo|scorecardresearch)")
# The generic-alt matcher ("Image", "Photo of", an empty alt): identical on
# both sides (was _STOCK_ALT there).
STOCK_ALT_RE = re.compile(
    r"(?i)^\s*(?:image|img|photo|picture|pic|graphic|illustration|art|"
    r"hero|banner|background|an?\s+image\s+of|photo of|a picture of)?\s*$")


def shared_junk_reason(src: str, alt: str, diagram_words=re.compile("$^")):
    """The three checks BOTH image gates apply, in the same order, with the
    same verdict strings: stock-src, ad-network-src, short-alt-unless-
    diagram-shaped. ``diagram_words`` is the caller's own matcher (kept
    divergent by design; default never matches). Returns the reject reason
    string, or '' when these checks pass the image."""
    src = src or ""
    alt = (alt or "").strip()
    if STOCK_SRC_RE.search(src):
        return "stock/hero image"
    if AD_NETWORK_RE.search(src):
        return "ad-network pixel"
    if (len(alt.split()) < IMAGE_MIN_ALT_WORDS
            and not diagram_words.search(alt)):
        return "alt too short to verify topicality"
    return ""