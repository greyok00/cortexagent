#!/usr/bin/env python3
"""scripts/ingest_programming.py — ingest programming source files into the programming domain DB."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ingest_common import ingest_dir, source_dir  # noqa: E402


def main() -> int:
    ingest_dir("programming", source_dir("programming"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
