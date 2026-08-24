#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import domain_ingest, domain_db  # noqa: E402
from lib.config import CFG  # noqa: E402


def source_dir(domain: str) -> Path:

    return CFG.state_dir / "domains" / "sources" / domain


def ingest_dir(domain: str, src_dir: Path) -> int:

    src_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted(src_dir.iterdir()):
        if not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
            r = domain_ingest.ingest(domain, str(f), text)
            total += r.get("chunks", 0)
            if not r.get("ok"):


                print(f"  {f.name}: {r.get('error', 'ingest failed')}", file=sys.stderr)
            else:
                print(f"  {f.name}: {r.get('chunks', 0)} chunks")
        except Exception as e:
            print(f"  {f.name}: ERROR {e}", file=sys.stderr)
    print(f"{domain} ingest done — {total} chunks stored")
    return total


def _smoke() -> int:
    fails = 0
    tmp = Path(tempfile.mkdtemp())
    old = domain_db.DOMAINS_DIR
    domain_db.DOMAINS_DIR = tmp
    try:
        src = tmp / "sources" / "dfir"
        src.mkdir(parents=True, exist_ok=True)
        (src / "report1.txt").write_text("IOC: attacker used IP 10.0.0.5. " * 30)
        n = ingest_dir("dfir", src)
        if n < 1:
            print(f"❌ ingest_dir stored {n} chunks")
            fails += 1
        hits = domain_db.search("dfir", "attacker IP")
        if not hits:
            print("❌ search after ingest_dir empty")
            fails += 1

        n2 = ingest_dir("dfir", src)
        if n2 != 0:
            print(f"❌ re-ingest not idempotent: {n2} chunks")
            fails += 1

        bad = tmp / "sources" / "nope"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "x.txt").write_text("text")
        ingest_dir("nope", bad)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        domain_db.DOMAINS_DIR = old
    print("ingest_common smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 scripts/ingest_common.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
