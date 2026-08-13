#!/usr/bin/env python3
"""lib/domain_db.py — per-domain knowledge SQLite DBs (FTS5 + sqlite-vec).

Each domain (business, dfir, law, osint, programming) is a SQLite DB at
~/.cortexagent/domains/<domain>.db:
  - documents      (id, source, chunk_index, chunk, chunk_hash UNIQUE, created_at)
  - documents_fts  FTS5 external-content virtual table (keyword search)
  - documents_vec  vec0 virtual table (semantic search, embedding float[384])

Hybrid search: FTS5 BM25 + vec0 semantic merged via reciprocal rank fusion
(RRF, k=60). If sqlite-vec is missing or inference fails, search falls back
to FTS5-only — semantic is an enhancement, never a blocker.

Usage:
  python3 lib/domain_db.py --smoke
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402

DOMAINS_DIR = CFG.state_dir / "domains"
ALLOWED_DOMAINS = ("business", "dfir", "law", "osint", "programming")
RRF_K = 60
EMBED_DIM = 384

_VEC_FLAG: Dict[str, bool] = {}


def _db_path(domain: str) -> Path:
    return DOMAINS_DIR / f"{domain}.db"


def _connect(domain: str) -> sqlite3.Connection:
    """Open (creating) the domain DB. Loads vec0 if sqlite-vec is available."""
    DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    path = str(_db_path(domain))
    con = sqlite3.connect(path)
    con.enable_load_extension(True)
    vec = False
    try:
        import sqlite_vec
        sqlite_vec.load(con)
        vec = True
    except Exception:
        vec = False
    _VEC_FLAG[path] = vec
    return con


def _vec_available(con: sqlite3.Connection) -> bool:
    """True if this connection has sqlite-vec loaded. Derives the DB path via
    PRAGMA database_list so callers never have to pass state around."""
    path = con.execute("PRAGMA database_list").fetchone()[2]
    return _VEC_FLAG.get(path, False)


def _init_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        "CREATE TABLE IF NOT EXISTS documents ("
        "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  source      TEXT NOT NULL,"
        "  chunk_index INTEGER NOT NULL,"
        "  chunk       TEXT NOT NULL,"
        "  chunk_hash  TEXT NOT NULL UNIQUE,"
        "  created_at  TEXT NOT NULL);"
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5("
        "  chunk, content=documents, content_rowid=id);"
    )
    if _vec_available(con):
        con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS documents_vec USING vec0("
            f"embedding float[{EMBED_DIM}], +doc_id INTEGER)")
    con.commit()


def _store_chunk(con: sqlite3.Connection, source: str, index: int,
                 chunk: str, emb: Optional[List[float]]) -> None:
    """Insert one chunk into documents + FTS (sync) + vec0 (if emb given)."""
    chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()
    cur = con.execute(
        "INSERT INTO documents (source, chunk_index, chunk, chunk_hash, created_at) "
        "VALUES (?,?,?,?,?)",
        (source, index, chunk, chunk_hash, datetime.now().isoformat()))
    rowid = cur.lastrowid
    con.execute("INSERT INTO documents_fts (rowid, chunk) VALUES (?, ?)",
                (rowid, chunk))
    if emb is not None and _vec_available(con):
        con.execute(
            "INSERT INTO documents_vec (embedding, doc_id) VALUES (?, ?)",
            (json.dumps(emb), rowid))
    con.commit()


def search(domain: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Hybrid search: FTS5 BM25 + vec0 semantic, merged via RRF.

    Returns [{"source","chunk","score","rank"}] truncated to limit.
    Falls back to FTS5-only if sqlite-vec missing / embedding fails.
    """
    if domain not in ALLOWED_DOMAINS or not query or not query.strip():
        return []
    db = _db_path(domain)
    if not db.exists():
        return []
    agg: Dict[int, Dict[str, Any]] = {}
    con = _connect(domain)
    try:
        try:
            rows = con.execute(
                "SELECT d.id, d.source, d.chunk FROM documents_fts f "
                "JOIN documents d ON d.id = f.rowid "
                "WHERE documents_fts MATCH ? LIMIT ?",
                (query, limit * 3)).fetchall()
            for rank, (doc_id, source, chunk) in enumerate(rows, 1):
                agg.setdefault(doc_id, {"source": source, "chunk": chunk, "score": 0.0})
                agg[doc_id]["score"] += 1.0 / (RRF_K + rank)
        except sqlite3.OperationalError:
            pass  # malformed MATCH query — skip keyword half
        if _vec_available(con):
            try:
                from lib.domain_embed import DomainEmbedder
                emb = DomainEmbedder().embed(query)
                rows = con.execute(
                    "SELECT v.doc_id, d.source, d.chunk FROM ("
                    "  SELECT doc_id FROM documents_vec WHERE embedding MATCH ? "
                    "  ORDER BY distance LIMIT ?) v "
                    "JOIN documents d ON d.id = v.doc_id",
                    (json.dumps(emb), limit * 3)).fetchall()
                for rank, (doc_id, source, chunk) in enumerate(rows, 1):
                    agg.setdefault(doc_id, {"source": source, "chunk": chunk, "score": 0.0})
                    agg[doc_id]["score"] += 1.0 / (RRF_K + rank)
            except Exception:
                pass  # embedding failed — keyword results still stand
    finally:
        con.close()
    ranked = sorted(agg.values(), key=lambda r: -r["score"])[:limit]
    return [{"source": r["source"], "chunk": r["chunk"],
             "score": r["score"], "rank": i + 1}
            for i, r in enumerate(ranked)]


def count(domain: str) -> int:
    db = _db_path(domain)
    if not db.exists():
        return 0
    con = _connect(domain)
    try:
        return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        con.close()


def _smoke() -> int:
    """Self-test: schema, store, FTS5 + vec0 hybrid search, RRF ordering.

    Runs against an isolated temp DOMAINS_DIR (never touches the real
    ~/.cortexagent/domains). _connect() probes sqlite-vec itself, so the
    vec0 half of the test is exercised when sqlite-vec is installed.
    """
    fails = 0
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    old = DOMAINS_DIR
    globals()["DOMAINS_DIR"] = tmp
    try:
        con = _connect("osint")
        _init_schema(con)
        c1a = "blocked IP 10.0.0.5 was seen beaconing"
        c1b = "the malware used a unique domain"
        c2 = "quarterly business revenue grew 12 percent"
        try:
            from lib.domain_embed import DomainEmbedder
            _emb = DomainEmbedder().embed
            c1a_emb, c1b_emb, c2_emb = _emb(c1a), _emb(c1b), _emb(c2)
        except Exception:
            # model unavailable — fall back to synthetic vectors; the vec hit
            # check below reports a clean failure instead of crashing
            c1a_emb = c1b_emb = c2_emb = None
        _store_chunk(con, "case1.txt", 0, c1a, c1a_emb)
        _store_chunk(con, "case1.txt", 1, c1b, c1b_emb)
        _store_chunk(con, "case2.txt", 0, c2, c2_emb)
        # dedup: re-storing the exact same chunk is blocked by UNIQUE hash
        try:
            _store_chunk(con, "case1.txt", 0, c1a, None)
            print("❌ dedup: duplicate chunk accepted")
            fails += 1
        except sqlite3.IntegrityError:
            pass  # correct — UNIQUE constraint blocks the duplicate
        con.close()
        # FTS5 keyword hit
        r = search("osint", "blocked IP")
        if not r or r[0]["source"] != "case1.txt":
            print(f"❌ FTS5 hit: {r}")
            fails += 1
        # vec0 semantic hit — query text is most similar to the case1.txt chunk
        # (which contains "beaconing"), using real model embeddings
        r = search("osint", "beaconing host", limit=2)
        if not r or r[0]["source"] != "case1.txt":
            print(f"❌ vec hit: {r}")
            fails += 1
        # empty query → []
        if search("osint", "   ") != []:
            print("❌ empty query not empty")
            fails += 1
        # unknown domain → []
        if search("nope", "x") != []:
            print("❌ unknown domain not empty")
            fails += 1
        if count("osint") != 3:
            print(f"❌ count: {count('osint')}")
            fails += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        globals()["DOMAINS_DIR"] = old
    print("domain_db smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/domain_db.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
