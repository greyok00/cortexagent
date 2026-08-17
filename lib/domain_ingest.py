#!/usr/bin/env python3
"""lib/domain_ingest.py — chunk → embed → store for the domain knowledge layer.

Ingests a source's text into a domain DB: split into ~200-word chunks with
50-word overlap, batch-embed via all-MiniLM-L6-v2, store with content-hash
dedup (idempotent re-ingest). Source is tracked per chunk so results can be
cited back to origin.

Chunk size is 200 words (~212 tokens) so each chunk fits the embedder's
256-token context (MAX_SEQ in lib/domain_embed.py) with no truncation —
a larger chunk would be cut to 256 tokens and its embedding would cover
only part of the chunk.

Usage:
  python3 lib/domain_ingest.py --smoke
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import domain_db  # noqa: E402

CHUNK_TOKENS = 200  # ~212 tokens — fits the embedder's 256-token context (MAX_SEQ)
OVERLAP = 50


def chunk_text(text: str, chunk_tokens: int = CHUNK_TOKENS,
               overlap: int = OVERLAP) -> List[str]:
    """Split text into ~chunk_tokens-word chunks with `overlap`-word overlap."""
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    i = 0
    step = max(chunk_tokens - overlap, 1)
    while i < len(words):
        # Skip a trailing partial chunk whose words are already covered by the
        # previous chunk's overlap window (avoids "five" after "three four five").
        if chunks and len(words) - i <= overlap:
            break
        chunks.append(" ".join(words[i:i + chunk_tokens]))
        i += step
    return chunks


def ingest(domain: str, source: str, text: str) -> dict:
    """Chunk → embed → store. Returns {"ok", "chunks", "error"}."""
    if domain not in domain_db.ALLOWED_DOMAINS:
        return {"ok": False, "chunks": 0, "error": f"unknown domain: {domain}"}
    if not source or not source.strip():
        return {"ok": False, "chunks": 0, "error": "source must be non-empty"}
    if not text or not text.strip():
        return {"ok": True, "chunks": 0, "error": ""}
    chunks = chunk_text(text)
    if not chunks:
        return {"ok": True, "chunks": 0, "error": ""}
    con = domain_db._connect(domain)
    try:
        domain_db._init_schema(con)
        vec = domain_db._vec_available(con)
        embs = None
        if vec:
            try:
                from lib.domain_embed import DomainEmbedder
                embs = DomainEmbedder().embed_batch(chunks)
            except Exception:
                embs = None  # FTS5-only fallback
        stored = 0
        for i, chunk in enumerate(chunks):
            try:
                domain_db._store_chunk(con, source, i, chunk,
                                       embs[i] if embs and i < len(embs) else None)
                stored += 1
            except sqlite3.IntegrityError:
                pass  # duplicate chunk (content-hash UNIQUE) — skip
    finally:
        con.close()
    return {"ok": True, "chunks": stored, "error": ""}


def _smoke() -> int:
    fails = 0
    # chunk_text
    c = chunk_text("one two three four five", chunk_tokens=3, overlap=1)
    if c != ["one two three", "three four five"]:
        print(f"❌ chunk_text overlap: {c}")
        fails += 1
    if chunk_text("") != []:
        print("❌ chunk_text empty")
        fails += 1
    # ingest into an isolated domain DB
    import tempfile
    from pathlib import Path
    import shutil
    tmp = Path(tempfile.mkdtemp())
    old = domain_db.DOMAINS_DIR
    domain_db.DOMAINS_DIR = tmp
    try:
        r = ingest("dfir", "report1.txt", "IOC: attacker used the IP 10.0.0.5. " * 30)
        if not r.get("ok") or r.get("chunks", 0) < 1:
            print(f"❌ ingest: {r}")
            fails += 1
        r2 = ingest("dfir", "report1.txt", "IOC: attacker used the IP 10.0.0.5. " * 30)
        if not r2.get("ok") or r2.get("chunks", 0) != 0:
            print(f"❌ dedup re-ingest not 0: {r2}")
            fails += 1
        hits = domain_db.search("dfir", "attacker IP")
        if not hits:
            print("❌ search after ingest empty")
            fails += 1
        r3 = ingest("nope", "x", "text")
        if r3.get("ok") or "unknown domain" not in r3.get("error", ""):
            print(f"❌ unknown domain: {r3}")
            fails += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        domain_db.DOMAINS_DIR = old
    print("domain_ingest smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/domain_ingest.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
