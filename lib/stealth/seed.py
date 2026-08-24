
from __future__ import annotations

import hashlib


def profile_seed(profile_name: str) -> int:

    digest = hashlib.sha256(f"cortexagent/stealth/{profile_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")