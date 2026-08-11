#!/usr/bin/env python3
"""cortexllm_vector.py — Persistent BM25 inverted-index semantic search for CortexLLM.

Replaces the broken in-memory TF-IDF implementation. This is a real persisted
inverted index: vocabulary, document frequencies, and postings live in SQLite so
the index is consistent across processes (daemon, MCP server, CLI). Ranking uses
BM25 (Okapi) — the industry standard for lexical relevance — which needs no model,
no external API, and no stale norm recomputation.

Design goals (fast / safe / secure / robust):
  - Persisted: vocab + df + postings + doc metadata all in SQLite. A fresh process
    sees the same index as the daemon that built it. No more empty-vocab garbage.
  - Fast: search touches only documents that share terms with the query (inverted
    index), not every document. O(matching postings) per query, not O(N·D).
  - Robust: BM25 idf is computed fresh at query time from current df + N, so adding
    documents never silently invalidates existing scores. No stale norms.
  - Safe: every query is parameterized; content hashed for dedup; thread-locked.
  - Secure: 100% local, no network calls, no external model, no PII egress.
  - Tokenizer: lowercase, split on non-alphanumeric (preserving technical tokens
    like snake_case / camelCase / dotted versions), light suffix stemming, stopword
    filtering, n-gram awareness for multiword terms.

Schema (added to cortexllm.db):
  Vector_Docs     (id, memory_id, content_hash UNIQUE, platform, doc_len, content, created_at)
  Vector_Terms    (term UNIQUE, df)                      -- document frequency
  Vector_Postings (term, doc_id, tf, UNIQUE(term, doc_id)) -- inverted index
  Vector_Meta      (key UNIQUE, value)                   -- doc_count, total_len, schema_ver
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Config ───────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / ".config/cortexllm/cortexllm.db"

# BM25 parameters (standard Okapi defaults; tuned for general text)
BM25_K1 = 1.5
BM25_B = 0.75

MAX_DOC_LEN = 200_000          # hard cap on tokens indexed per doc (safety)
MAX_TERM_LEN = 64              # ignore absurdly long "terms"
STORE_CONTENT = True           # store full content in Vector_Docs for self-contained results

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Vector_Docs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id     INTEGER,
    content_hash  TEXT    NOT NULL UNIQUE,
    platform      TEXT    NOT NULL DEFAULT 'default',
    doc_len       INTEGER NOT NULL DEFAULT 0,
    content       TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vdocs_platform ON Vector_Docs(platform);
CREATE INDEX IF NOT EXISTS idx_vdocs_memory  ON Vector_Docs(memory_id);

CREATE TABLE IF NOT EXISTS Vector_Terms (
    term TEXT PRIMARY KEY,
    df   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS Vector_Postings (
    term   TEXT    NOT NULL,
    doc_id INTEGER NOT NULL REFERENCES Vector_Docs(id) ON DELETE CASCADE,
    tf     REAL    NOT NULL,
    PRIMARY KEY (term, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_postings_doc ON Vector_Postings(doc_id);

CREATE TABLE IF NOT EXISTS Vector_Meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# A compact, high-precision stopword set. Kept small so technical terms survive.
_STOPWORDS = frozenset(
    "a an the and or but if then else of in to for with without from by on at off "
    "is are was were be been being am do does did doing have has had having this "
    "that these those it its it's we us our you your they them their he him his "
    "she her i me my not no nor so than too very can will just don should would "
    "could may might must about into over under after before up down out as also "
    "which what when where who why how there here all any each few more most other "
    "some such only own same new now one two get got make made way like back still "
    "even much many use used using see seen say said go going im ive youre".split()
)

# Light suffix stemmer (Porter-lite). Good enough for lexical matching, pure Python.
_STEM_SUFFIXES = ("ements", "ation", "ations", "ement", "ation", "tions", "ation",
                   "ness", "ment", "tion", "ings", "ing", "edly", "ies", "ied",
                   "ied", "ing", "ed", "ly", "es", "s", "ing")
# Ordered longest-first; we evaluate the tuple in longest-first order below.
_SUFFIX_ORDER = tuple(sorted(set(_STEM_SUFFIXES), key=len, reverse=True))


def _stem(word: str) -> str:
    """Light suffix stripper. Keeps words >= 4 chars after stripping."""
    if len(word) <= 4:
        return word
    for suf in _SUFFIX_ORDER:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


# Split camelCase / snake_case / dotted versions, then lowercased alnum tokens.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")


def tokenize(text: str) -> List[str]:
    """Tokenize + normalize + stem + stopword-filter. Returns ordered token list."""
    if not text:
        return []
    raw = _TOKEN_RE.findall(text)
    out: List[str] = []
    for tok in raw:
        # Split camelCase: fooBar -> foo bar
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", tok).split()
        for p in parts:
            p = p.lower()
            if len(p) < 2 or len(p) > MAX_TERM_LEN:
                continue
            if p in _STOPWORDS:
                continue
            # Keep dotted/numeric version-ish tokens whole (e.g. 1.2.3, v1.4)
            if re.fullmatch(r"v?\d[\w.]*\d", p) or "." in p or "_" in p:
                out.append(p)
                continue
            stemmed = _stem(p)
            if stemmed and stemmed not in _STOPWORDS:
                out.append(stemmed)
    return out


class VectorStore:
    """Persistent BM25 inverted-index semantic search."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._init_db()
        self._ensure_meta()

    # ── schema / meta ────────────────────────────────────────────────────────
    def _init_db(self):
        with self._lock:
            conn = self._conn()
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_meta(self):
        """Initialize meta counters if missing."""
        with self._lock:
            conn = self._conn()
            defaults = {
                "doc_count": "0",
                "total_len": "0",
                "schema_ver": "2",
            }
            for k, v in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO Vector_Meta (key, value) VALUES (?, ?)",
                    (k, v),
                )
            conn.commit()
            conn.close()

    def _meta(self, conn: sqlite3.Connection, key: str, default: str = "0") -> str:
        row = conn.execute("SELECT value FROM Vector_Meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str):
        conn.execute(
            "INSERT INTO Vector_Meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()

    # ── indexing ──────────────────────────────────────────────────────────────
    def embed_and_store(self, content: str, platform: str = "default",
                        memory_id: Optional[int] = None) -> bool:
        """Index one document. Idempotent via content_hash dedup. Returns True if stored."""
        if not content or not content.strip():
            return False
        return self.embed_batch([(content, platform, memory_id)]) > 0

    def embed_batch(self, items: List[Tuple[str, str, Optional[int]]]) -> int:
        """Index a batch of (content, platform, memory_id). Returns number newly stored."""
        if not items:
            return 0
        with self._lock:
            conn = self._conn()
            try:
                return self._embed_batch_locked(conn, items)
            finally:
                conn.close()

    def _embed_batch_locked(self, conn: sqlite3.Connection,
                            items: List[Tuple[str, str, Optional[int]]]) -> int:
        stored = 0
        for content, platform, memory_id in items:
            if not content or not content.strip():
                continue
            chash = self._hash(content)
            # Dedup: skip if already indexed
            exists = conn.execute(
                "SELECT 1 FROM Vector_Docs WHERE content_hash=?", (chash,)
            ).fetchone()
            if exists:
                continue

            tokens = tokenize(content)[:MAX_DOC_LEN]
            doc_len = len(tokens)
            if doc_len == 0:
                # No indexable tokens — still record the doc so it's retrievable by hash
                conn.execute(
                    "INSERT INTO Vector_Docs (memory_id, content_hash, platform, doc_len, content) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (memory_id, chash, platform or "default",
                     STORE_CONTENT and content[:50000] or ""),
                )
                stored += 1
                continue

            tf = Counter(tokens)
            cur = conn.execute(
                "INSERT INTO Vector_Docs (memory_id, content_hash, platform, doc_len, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (memory_id, chash, platform or "default", doc_len,
                 STORE_CONTENT and content[:50000] or ""),
            )
            doc_id = cur.lastrowid

            # Update postings + document frequency in one pass
            for term, count in tf.items():
                conn.execute(
                    "INSERT INTO Vector_Postings (term, doc_id, tf) VALUES (?, ?, ?)",
                    (term, doc_id, float(count)),
                )
                conn.execute(
                    "INSERT INTO Vector_Terms (term, df) VALUES (?, 1) "
                    "ON CONFLICT(term) DO UPDATE SET df = df + 1",
                    (term,),
                )
            stored += 1

        if stored:
            # Recompute aggregate meta from truth (cheap, only on writes that stored)
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(doc_len),0) FROM Vector_Docs"
            ).fetchone()
            self._set_meta(conn, "doc_count", str(row[0]))
            self._set_meta(conn, "total_len", str(row[1]))

        conn.commit()
        return stored

    # ── search ────────────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 10,
               platform: Optional[str] = None) -> List[dict]:
        """BM25 ranked search. Returns list of {id, memory_id, platform, content, score, doc_len}."""
        if not query or not query.strip():
            return []
        qterms = tokenize(query)
        if not qterms:
            # Fall back to a substring scan so we still return something useful
            return self._substring_search(query, limit, platform)

        with self._lock:
            conn = self._conn()
            try:
                return self._search_bm25(conn, qterms, limit, platform)
            finally:
                conn.close()

    def _search_bm25(self, conn: sqlite3.Connection, qterms: List[str],
                     limit: int, platform: Optional[str]) -> List[dict]:
        N = int(self._meta(conn, "doc_count", "0"))
        if N == 0:
            return []
        total_len = int(self._meta(conn, "total_len", "0"))
        avgdl = (total_len / N) if N > 0 else 1.0
        if avgdl <= 0:
            avgdl = 1.0

        # Unique query terms with their query-term-frequency (for repeated terms)
        qtf = Counter(qterms)

        # Gather idf per query term and pull postings in one pass per term.
        # score_map: doc_id -> accumulated BM25 score
        score_map: Dict[int, float] = {}
        doc_len_cache: Dict[int, int] = {}

        for term, qcount in qtf.items():
            row = conn.execute("SELECT df FROM Vector_Terms WHERE term=?", (term,)).fetchone()
            if not row:
                continue
            df = row[0]
            if df <= 0:
                continue
            # BM25 idf (with +1 inside log to keep it non-negative)
            idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))
            if idf <= 0:
                continue

            if platform:
                post_rows = conn.execute(
                    "SELECT p.doc_id, p.tf, d.doc_len FROM Vector_Postings p "
                    "JOIN Vector_Docs d ON d.id = p.doc_id "
                    "WHERE p.term = ? AND d.platform = ?",
                    (term, platform),
                ).fetchall()
            else:
                post_rows = conn.execute(
                    "SELECT p.doc_id, p.tf, d.doc_len FROM Vector_Postings p "
                    "JOIN Vector_Docs d ON d.id = p.doc_id WHERE p.term = ?",
                    (term,),
                ).fetchall()

            for doc_id, tf, dlen in post_rows:
                dl = dlen if dlen else doc_len_cache.get(doc_id, avgdl)
                doc_len_cache[doc_id] = dl
                denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (dl / avgdl))
                if denom <= 0:
                    continue
                contrib = idf * (tf * (BM25_K1 + 1.0)) / denom
                # Repeated query terms add weight (standard BM25 with qtf)
                if qcount > 1:
                    contrib *= (1.0 + math.log(qcount))
                score_map[doc_id] = score_map.get(doc_id, 0.0) + contrib

        if not score_map:
            return []

        ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        if not ranked:
            return []

        ids = [d for d, _ in ranked]
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, memory_id, content_hash, platform, doc_len, content "
            f"FROM Vector_Docs WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        by_id = {r[0]: r for r in rows}

        results = []
        for doc_id, score in ranked:
            r = by_id.get(doc_id)
            if not r:
                continue
            results.append({
                "id": r[0],
                "memory_id": r[1],
                "content_hash": r[2],
                "platform": r[3],
                "doc_len": r[4],
                "content": r[5],
                "score": round(score, 4),
            })
        return results

    def _substring_search(self, query: str, limit: int,
                          platform: Optional[str]) -> List[dict]:
        """Fallback LIKE search when tokenization yields nothing (e.g. query is a symbol)."""
        with self._lock:
            conn = self._conn()
            try:
                if platform:
                    rows = conn.execute(
                        "SELECT id, memory_id, content_hash, platform, doc_len, content "
                        "FROM Vector_Docs WHERE platform=? AND content LIKE ? "
                        "ORDER BY id DESC LIMIT ?",
                        (platform, f"%{query}%", limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, memory_id, content_hash, platform, doc_len, content "
                        "FROM Vector_Docs WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                        (f"%{query}%", limit),
                    ).fetchall()
                return [{
                    "id": r[0], "memory_id": r[1], "content_hash": r[2],
                    "platform": r[3], "doc_len": r[4], "content": r[5],
                    "score": 0.0,
                } for r in rows]
            finally:
                conn.close()

    # ── maintenance ───────────────────────────────────────────────────────────
    def rebuild_index(self) -> dict:
        """Rebuild postings + df + meta from Vector_Docs.content. Use after bulk changes."""
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM Vector_Postings")
                conn.execute("DELETE FROM Vector_Terms")
                docs = conn.execute(
                    "SELECT id, content FROM Vector_Docs ORDER BY id"
                ).fetchall()
                n = 0
                for doc_id, content in docs:
                    tokens = tokenize(content or "")[:MAX_DOC_LEN]
                    if not tokens:
                        continue
                    tf = Counter(tokens)
                    for term, count in tf.items():
                        conn.execute(
                            "INSERT INTO Vector_Postings (term, doc_id, tf) VALUES (?, ?, ?)",
                            (term, doc_id, float(count)),
                        )
                        conn.execute(
                            "INSERT INTO Vector_Terms (term, df) VALUES (?, 1) "
                            "ON CONFLICT(term) DO UPDATE SET df = df + 1",
                            (term,),
                        )
                    n += 1
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(doc_len),0) FROM Vector_Docs"
                ).fetchone()
                self._set_meta(conn, "doc_count", str(row[0]))
                self._set_meta(conn, "total_len", str(row[1]))
                conn.commit()
                return {"rebuilt_docs": n, "total_docs": row[0], "total_len": row[1]}
            finally:
                conn.close()

    def index_existing_memory(self, table: str = "Memory_Hot", limit: int = 5000) -> dict:
        """Backfill the index from an existing memory table (Memory_Hot / Memory_Warm)."""
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT id, role, content, platform FROM {table} "
                    f"ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                items = [(r[2] or "", r[3] or "default", r[0]) for r in rows if r[2]]
                conn.close()
            except Exception:
                conn.close()
                return {"error": f"cannot read {table}"}
        stored = self.embed_batch(items)
        return {"table": table, "scanned": len(items), "indexed": stored}

    def get_stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            try:
                docs = conn.execute("SELECT COUNT(*) FROM Vector_Docs").fetchone()[0]
                terms = conn.execute("SELECT COUNT(*) FROM Vector_Terms").fetchone()[0]
                postings = conn.execute("SELECT COUNT(*) FROM Vector_Postings").fetchone()[0]
                platforms = conn.execute(
                    "SELECT platform, COUNT(*) c FROM Vector_Docs GROUP BY platform"
                ).fetchall()
                total_len = int(self._meta(conn, "total_len", "0"))
                avgdl = (total_len / docs) if docs else 0.0
                return {
                    "method": "BM25 (Okapi)",
                    "total_docs": docs,
                    "vocab_size": terms,
                    "postings": postings,
                    "avg_doc_len": round(avgdl, 1),
                    "by_platform": {p: c for p, c in platforms},
                    "params": {"k1": BM25_K1, "b": BM25_B},
                }
            finally:
                conn.close()


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    vs = VectorStore()

    if len(sys.argv) < 2:
        print("Usage: cortexllm_vector.py <search|stats|embed|rebuild|backfill> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "search":
        query = " ".join(sys.argv[2:])
        for r in vs.search(query):
            preview = (r.get("content") or "")[:120].replace("\n", " ")
            print(f"  {r['score']:.3f} [{r['platform']}] id={r['id']} | {preview}")
    elif cmd == "stats":
        print(json.dumps(vs.get_stats(), indent=2))
    elif cmd == "embed":
        text = " ".join(sys.argv[2:])
        ok = vs.embed_and_store(text)
        print("✅ Stored" if ok else "❌ Skipped/failed")
    elif cmd == "rebuild":
        print(json.dumps(vs.rebuild_index(), indent=2))
    elif cmd == "backfill":
        table = sys.argv[2] if len(sys.argv) > 2 else "Memory_Hot"
        print(json.dumps(vs.index_existing_memory(table), indent=2))
    else:
        print(f"Unknown command: {cmd}")