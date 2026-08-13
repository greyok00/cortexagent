# CortexAgent — Step 3: Domain DBs + Ingestion Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

Part of the SlimToken orchestration layer (see
`2026-08-12-slimtoken-orchestration-design.md`). This spec designs **step 3**:
the domain knowledge layer — per-domain SQLite databases with FTS5 keyword
search + semantic embeddings, plus the ingestion pipeline that fills them.

---

## 1. Goal

Give the overseer model fast, domain-specific knowledge retrieval. Five
domains: `business`, `dfir`, `law`, `osint`, `programming`. Each domain is a
SQLite DB with:

- **FTS5** — built-in inverted-index keyword search (fast, zero deps).
- **vec0 (sqlite-vec)** — semantic search via a small CPU embedding model
  (all-MiniLM-L6-v2, ~80MB, onnxruntime). User-confirmed: embeddings now.

The DBs are the **fast knowledge layer**, separate from CortexLLM (which stays
the conversation/command memory). `rag_query` becomes a composite tool that
searches CortexLLM memory (step 1) + the domain DB (this step).

---

## 2. Architecture

```
Ingestion (cron jobs + ingest_domain tool)
   │  source text → chunk → embed → store
   ▼
~/.cortexagent/domains/<domain>.db
   ├── documents        (id, source, chunk_index, chunk, created_at)
   ├── documents_fts   (FTS5 virtual table, keyword)
   └── documents_vec   (vec0 virtual table, embedding float[384])

rag_query(domain, query)
   ├── CortexLLM memory search   (step 1, real)
   └── Domain DB search          (this step)
         ├── FTS5 BM25 → ranked
         ├── vec0 semantic → ranked
         └── merge (reciprocal rank fusion) → top-N
```

- **Embedding model**: all-MiniLM-L6-v2 (ONNX, 384-dim, ~80MB), CPU via
  onnxruntime (already installed). Lazy-loaded singleton, downloaded on first
  use (one-time, like the STT design's faster-whisper).
- **CPU only** — GPU stays reserved for the big model.

---

## 3. Storage schema

Per-domain DB at `~/.cortexagent/domains/<domain>.db`:

```sql
CREATE TABLE documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,          -- file path / URL / title
    chunk_index INTEGER NOT NULL,       -- position in source doc
    chunk       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- FTS5 keyword index (external content → no duplicate storage)
CREATE VIRTUAL TABLE documents_fts USING fts5(
    chunk, content=documents, content_rowid=id
);

-- sqlite-vec semantic index
CREATE VIRTUAL TABLE documents_vec USING vec0(
    embedding float[384],
    +doc_id INTEGER
);
```

- FTS5 is built into SQLite — no extension install.
- `vec0` requires the sqlite-vec extension (install: `pip install sqlite-vec`
  + `con.enable_load_extension(True)` + `con.load_extension("vec0")`).
- `doc_id` in `documents_vec` links embeddings back to `documents.id`.
- DBs are created lazily on first write to a domain.

---

## 4. Embedding layer — `lib/domain_embed.py`

```python
class DomainEmbedder:
    """Lazy-loaded all-MiniLM-L6-v2 via onnxruntime. CPU. Singleton."""

    def embed(self, text: str) -> list[float]:   # 384-dim
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
```

- Model: `all-MiniLM-L6-v2` ONNX (~80MB), downloaded on first use to
  `~/.cortexagent/models/` (one-time, like faster-whisper auto-download).
- onnxruntime already installed (verified 2026-08-12).
- Batch embedding for ingestion (chunks embed in one pass — much faster than
  one-by-one).
- Singleton, lazy-loaded — no model load until the first embed call.

---

## 5. Ingestion pipeline — `lib/domain_ingest.py`

```python
def ingest(domain: str, source: str, text: str) -> dict:
    """Chunk → embed → store. Returns {"ok": bool, "chunks": n, "error": str}."""

def chunk_text(text: str, chunk_tokens: int = 500, overlap: int = 50) -> list[str]:
    """Split text into ~500-token chunks with 50-token overlap."""
```

- **Chunking**: ~500 tokens, 50-token overlap (context continuity across
  chunk boundaries). Tokenizer: simple whitespace/word split (no model needed
  for chunking).
- **Dedup**: skip chunks whose content hash already exists (idempotent
  re-ingest).
- **Source tracking**: `source` = file path / URL / title, so results can be
  cited back to origin.
- **Batch embed**: all chunks of a source embed in one `embed_batch` call.

### 5.1 `ingest_domain` tool (registry)

Registered in step 1 as a stub; filled in here:

```json
{
  "name": "ingest_domain",
  "description": "Ingest text into a domain knowledge base",
  "parameters": {
    "type": "object",
    "properties": {
      "domain": {"type": "string", "enum": ["business","dfir","law","osint","programming"]},
      "source": {"type": "string", "description": "file path / URL / title"},
      "text":   {"type": "string", "description": "content to ingest"}
    },
    "required": ["domain", "source", "text"]
  }
}
```

The overseer model can ingest data it finds (web_search results, parsed
documents) directly via this tool.

---

## 6. Search — hybrid FTS5 + vector

```python
def search(domain: str, query: str, limit: int = 10) -> list[dict]:
    """Hybrid search: FTS5 BM25 + vec0 semantic, merged via RRF."""
```

- **FTS5**: `SELECT ... FROM documents_fts WHERE documents_fts MATCH ?`
  → BM25-ranked keyword hits.
- **vec0**: `embed(query)` → `SELECT doc_id FROM documents_vec WHERE
  embedding MATCH ? ORDER BY distance LIMIT k` → semantic hits.
- **Merge**: reciprocal rank fusion (RRF) — `score = Σ 1/(k + rank)`,
  `k=60`. Deterministic, no tuning.
- **Result shape**: `[{"source", "chunk", "score", "rank"}]`, truncated to
  `limit`, formatted as plain text for the model.

### 6.1 `rag_query` domain-DB backend

`rag_query(domain, query)` (composite, from step 1) gains its second backend:

```
rag_query(domain, query, limit=10)
   ├── CortexLLM memory search   (step 1 — hot/warm/cold)
   └── Domain DB search           (this step — FTS5 + vec0, RRF merge)
   → merge both result sets, format as ranked plain text
```

If the domain DB doesn't exist yet, the domain-DB half returns empty
gracefully (same as step 1) — the tool still works on CortexLLM memory alone.

---

## 7. Cron ingestion jobs

The existing scheduler (`lib/overseer.py:schedule_add`, cron) runs ingestion
jobs. A new task type `ingest`:

```
schedule_add("osint-daily", "ingest", "cron", "0 3 * * *",
             prompt="", command="python3 scripts/ingest_osint.py")
```

- `_execute_task` gains an `ingest` branch → `domain_ingest.ingest(...)`.
- Ingestion scripts live in `scripts/` (e.g., `ingest_osint.py`) — they pull
  a source (file, URL, export) and call `ingest(domain, source, text)`.
- Runs in the background on the existing tick loop — no new daemon.

---

## 8. Error handling

| Failure | Behavior |
|---|---|
| Embedding model not downloaded | Auto-download on first use (~80MB, one-time); log + retry |
| sqlite-vec missing | `search` falls back to FTS5-only (keyword still works); log a warning |
| Domain DB doesn't exist | `search` returns empty; `ingest` creates it lazily |
| Embedding inference fails | `search` falls back to FTS5-only for that query |
| Ingest of a huge source | Chunked + batched; per-source timeout; partial ingest is fine (idempotent re-run) |
| Duplicate source re-ingest | Content-hash dedup — no duplicate chunks |

**Fallback rule:** semantic search is an enhancement, never a blocker. If
embeddings fail for any reason, FTS5 keyword search still answers the query.

---

## 9. Testing

| Test | What it proves |
|---|---|
| `lib/domain_embed.py --smoke` | Embeds a sample string → 384-dim vector, non-zero |
| `lib/domain_ingest.py --smoke` | Ingests a sample doc → chunks stored, FTS5 + vec0 populated |
| `lib/domain_db.py --smoke` | Hybrid search returns ranked results; FTS5-only fallback works with sqlite-vec absent |
| `rag_query` composite | Searches CortexLLM memory + domain DB, merges |
| `ingest_domain` tool | Registry call ingests text end-to-end |
| Cron ingest | Scheduled `ingest` task runs on the tick loop |
| Smoke gate | `cortexagent doctor` + `tests/run_smoke.py` extended |

---

## 10. Files

| File | Change |
|---|---|
| `lib/domain_db.py` | NEW — per-domain SQLite (FTS5 + vec0), hybrid search, RRF merge |
| `lib/domain_embed.py` | NEW — all-MiniLM-L6-v2 via onnxruntime, lazy singleton |
| `lib/domain_ingest.py` | NEW — chunk → embed → store, dedup, `ingest()` |
| `lib/tool_registry.py` | FILL `ingest_domain` stub; FILL `rag_query` domain-DB backend |
| `lib/overseer.py` | `_execute_task` gains `ingest` task type |
| `scripts/ingest_*.py` | NEW — per-domain ingestion scripts (cron targets) |
| `tests/run_smoke.py` | ADD domain-DB checks |
| `docs/superpowers/specs/2026-08-10-daily-changelog.md` | ADD row |

---

## 11. Out of scope (later steps)

- Adapters (step 4) — `parse_document`/`describe_image`/`transcribe_audio`
  become real; their output feeds `ingest_domain` for document ingestion.
- Domain-DB search polish (step 5) — ingestion job library + tuning.
- Android (Phase 2).

---

## 12. Tracking

- This file = `docs/superpowers/specs/2026-08-12-domain-db-design.md`
- Master spec = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
