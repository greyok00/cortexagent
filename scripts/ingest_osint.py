#!/usr/bin/env python3
"""scripts/ingest_osint.py — ingest OSINT source files into the osint domain DB.

Reads every file under ~/.cortexagent/domains/sources/osint/ (created if
absent) and ingests it via domain_ingest. Idempotent (content-hash dedup).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import domain_ingest  # noqa: E402
from lib.config import CFG  # noqa: E402

SRC = CFG.state_dir / "domains" / "sources" / "osint"


def main() -> int:
    SRC.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted(SRC.iterdir()):
        if not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
            r = domain_ingest.ingest("osint", str(f), text)
            total += r.get("chunks", 0)
            print(f"  {f.name}: {r.get('chunks', 0)} chunks")
        except Exception as e:
            print(f"  {f.name}: ERROR {e}", file=sys.stderr)
    print(f"osint ingest done — {total} chunks stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
