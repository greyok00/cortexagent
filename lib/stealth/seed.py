"""seed — stable per-profile deterministic seed.

A profile's seed is a pure function of its name, so the same profile always
gets the same fingerprint across sessions (stable for the life of the
profile), while distinct profiles get distinct fingerprints. The seed drives
all fingerprint randomization downstream (canvas/WebGL/audio noise, profile
selection) so the synthetic identity is coherent and session-stable.
"""
from __future__ import annotations

import hashlib


def profile_seed(profile_name: str) -> int:
    """Return a stable 32-bit unsigned int seed for a profile name.

    Same name -> same seed forever; different names -> different seeds with
    good avalanche (sha-256 truncated). 32-bit matches the JS mulberry32 PRNG.
    """
    digest = hashlib.sha256(f"cortexagent/stealth/{profile_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")