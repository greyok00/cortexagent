#!/usr/bin/env python3
"""cortexllm_graph.py — Graph reasoning for CortexLLM memory.

Deterministic, fast, robust entity + relationship extraction with a correct
Python BFS traversal layer over SQLite. No dependency on the tiny LLM for the
core path — extraction is regex/lexicon based so it works even when Ollama is
down. An optional LLM enrichment path is available but never required.

Design goals (fast / safe / secure / robust):
  - Deterministic extraction: capitalized proper nouns, technical identifiers
    (snake_case, camelCase, dotted versions, IPs, URLs, CVEs, file paths, shell
    commands), and a curated tech lexicon. Typed by pattern. Reproducible.
  - Relationship extraction: regex on linguistic cues ("X depends on Y",
    "X uses Y", "X mitigates Y", "X exploits Y"...) plus co-occurrence within a
    sliding window → weighted RELATES_TO edges. Bounded and explainable.
  - Correct traversal: Python BFS with a visited set (not a fragile recursive
    CTE with a 4-way OR self-join). Bounded depth, no explosion.
  - Persisted + idempotent: nodes/edges upserted; provenance (source hash)
    recorded so re-extraction doesn't duplicate. Thread-locked, parameterized.
  - Secure: 100% local. Optional LLM enrichment is best-effort, non-blocking,
    and only contacted if a base URL is configured and reachable.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

DB_PATH = Path.home() / ".config/cortexllm/cortexllm.db"
OLLAMA_URL = os.environ.get("CORTEXLLM_OLLAMA_URL", "http://127.0.0.1:11434")
EXTRACT_MODEL = os.environ.get("CORTEXLLM_TINY_MODEL", "qwen2.5:0.5b")

# Cap extraction work per call (safety + speed)
MAX_TEXT_LEN = 200_000
MAX_ENTITIES_PER_DOC = 200
MAX_EDGES_PER_DOC = 400
COOCCUR_WINDOW = 6  # tokens within this span get a RELATES_TO edge

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Memory_Nodes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    type       TEXT    NOT NULL DEFAULT 'entity',
    platform   TEXT    NOT NULL DEFAULT 'default',
    metadata   TEXT    NOT NULL DEFAULT '{}',
    source     TEXT,                       -- content_hash of originating text
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(name, type, platform)
);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON Memory_Nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON Memory_Nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON Memory_Nodes(source);

CREATE TABLE IF NOT EXISTS Memory_Edges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES Memory_Nodes(id) ON DELETE CASCADE,
    target_id  INTEGER NOT NULL REFERENCES Memory_Nodes(id) ON DELETE CASCADE,
    relation   TEXT    NOT NULL,
    weight     REAL    NOT NULL DEFAULT 1.0,
    evidence   TEXT,
    platform   TEXT    NOT NULL DEFAULT 'default',
    source     TEXT,                       -- content_hash of originating text
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, relation, platform)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON Memory_Edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON Memory_Edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON Memory_Edges(relation);
"""

RELATION_TYPES = [
    "RELATES_TO", "DEPENDS_ON", "PRECEDES", "FOLLOWS",
    "CONTAINS", "PART_OF", "USES", "PRODUCES",
    "CONTRADICTS", "SUPPORTS", "MITIGATES", "EXPLOITS",
]

# ── Lexicon & patterns ────────────────────────────────────────────────────────
# Curated tech lexicon → entity type. Matched case-insensitively as whole tokens.
_TECH_LEXICON: Dict[str, str] = {t: "tool" for t in [
    "ollama", "llama.cpp", "llamacpp", "sqlite", "postgres", "postgresql", "mysql",
    "redis", "docker", "kubernetes", "nginx", "git", "github", "gitlab", "python",
    "javascript", "typescript", "rust", "golang", "java", "kotlin", "swift", "node",
    "react", "vue", "svelte", "django", "flask", "fastapi", "express", "nginx",
    "apache", "linux", "ubuntu", "debian", "windows", "macos", "bash", "zsh",
    "powershell", "cuda", "gpu", "cpu", "ram", "vram", "numpy", "pandas", "torch",
    "pytorch", "tensorflow", "keras", "transformers", "huggingface", "openai",
    "anthropic", "claude", "gpt", "llm", "rag", "embedding", "tfidf", "bm25",
    "cortexllm", "cortexagent", "overseer", "mcp", "daemon", "socket", "systemd",
    "three.js", "threejs", "playwright", "selenium", "burpsuite", "wireshark",
    "metasploit", "nmap", "sqlmap", "john", "hashcat", "hydra", "aircrack",
]}
_TECH_LEXICON.update({t: "concept" for t in [
    "security", "crypto", "encryption", "auth", "authentication", "authorization",
    "oauth", "jwt", "tls", "ssl", "pki", "firewall", "injection", "xss", "csrf",
    "ssrf", "rce", "lfi", "rfi", "ddos", "phishing", "malware", "ransomware",
    "backdoor", "trojan", "worm", "rootkit", "botnet", "zero-day", "zeroday",
    "pentest", "redteam", "blueteam", "forensics", "memory", "vector", "graph",
    "ontology", "taxonomy", "workflow", "scheduler", "orchestrator", "dag",
    "pipeline", "distillation", "checkpoint", "context", "pruning", "token",
]})
_TECH_LEXICON.update({t: "system" for t in [
    "database", "server", "client", "api", "rest", "graphql", "grpc", "microservice",
    "container", "vm", "kernel", "filesystem", "network", "proxy", "gateway",
    "loadbalancer", "cdn", "dns", "cdn", "queue", "kafka", "rabbitmq",
]})

# Regex patterns for typed extraction (order matters; first match wins per span)
_PATTERNS: List[Tuple[str, re.Pattern, str]] = [
    ("cve",      re.compile(r"\bCVE-\d{4}-\d{4,7}\b"), "vulnerability"),
    ("ipv4",     re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "system"),
    ("url",      re.compile(r"\bhttps?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+"), "system"),
    ("filepath", re.compile(r"(?:~/|/)?[\w.\-]+(?:/[\w.\-]+)+"), "system"),
    ("version",  re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b"), "concept"),
    ("cve_like", re.compile(r"\b[A-Z]{2,}-\d{2,}-\d{2,}\b"), "vulnerability"),
    ("snake",    re.compile(r"\b[a-z]+(?:_[a-z]+){1,}\b"), "concept"),
    ("camel",    re.compile(r"\b[a-z]+(?:[A-Z][a-z]+){1,}\b"), "concept"),
    ("screaming",re.compile(r"\b[A-Z][A-Z0-9_]{2,}(?:_[A-Z0-9]+)+\b"), "concept"),
    ("acronym",  re.compile(r"\b[A-Z]{2,6}\b"), "concept"),
    ("proper",   re.compile(r"\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,}){0,3}\b"), "person"),
]

# Capitalized words that are usually sentence-starters, not proper nouns.
_CAP_STOPWORDS = frozenset({
    "the", "this", "that", "these", "those", "then", "there", "here", "thus",
    "it", "we", "you", "they", "he", "she", "but", "and", "or", "so", "if",
    "when", "where", "what", "why", "how", "all", "some", "most", "any", "each",
    "in", "on", "at", "by", "for", "with", "from", "to", "of", "a", "an",
    "which", "while", "during", "after", "before", "because", "although",
})

# Linguistic cue → relation. Captured groups (A, B) become edge endpoints.
# Entity capture allows word/space/hyphen AND a dot only when NOT followed by
# whitespace — so "llama.cpp" / "node.js" stay whole, but "model. The overseer"
# stops at "model" (dot+space = sentence boundary).
# Greedy capture so dotted names like "llama.cpp" / "node.js" are taken whole.
# The following verb/whitespace anchor backtracks the source group correctly.
_ENT = r"([A-Za-z](?:[\w -]|\.(?!\s)){1,40})"
_CUE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(rf"\b{_ENT}\s+(?:depends(?:\s+on)?|requires?|needs?)\s+{_ENT}\b", re.I), "DEPENDS_ON"),
    (re.compile(rf"\b{_ENT}\s+(?:uses?|utilizes?|leverages?)\s+{_ENT}\b", re.I), "USES"),
    (re.compile(rf"\b{_ENT}\s+(?:produces?|generates?|creates?|outputs?)\s+{_ENT}\b", re.I), "PRODUCES"),
    (re.compile(rf"\b{_ENT}\s+(?:contains?|includes?|comprises?)\s+{_ENT}\b", re.I), "CONTAINS"),
    (re.compile(rf"\b{_ENT}\s+(?:part\s+of|belongs\s+to|is\s+a)\s+{_ENT}\b", re.I), "PART_OF"),
    (re.compile(rf"\b{_ENT}\s+(?:precedes?|comes?\s+before)\s+{_ENT}\b", re.I), "PRECEDES"),
    (re.compile(rf"\b{_ENT}\s+(?:follows?|comes?\s+after)\s+{_ENT}\b", re.I), "FOLLOWS"),
    (re.compile(rf"\b{_ENT}\s+(?:mitigates?|prevents?|blocks?|defends?\s+against)\s+{_ENT}\b", re.I), "MITIGATES"),
    (re.compile(rf"\b{_ENT}\s+(?:exploits?|attacks?|targets?)\s+{_ENT}\b", re.I), "EXPLOITS"),
    (re.compile(rf"\b{_ENT}\s+(?:supports?|enables?|backs?)\s+{_ENT}\b", re.I), "SUPPORTS"),
    (re.compile(rf"\b{_ENT}\s+(?:contradicts?|conflicts?\s+with|opposes?)\s+{_ENT}\b", re.I), "CONTRADICTS"),
]


def _clean_entity_name(name: str) -> str:
    """Strip leading determiners and trailing punctuation from a captured entity."""
    name = name.strip().rstrip(".,;:)]}")
    # Strip leading "The/A/An "
    name = re.sub(r"^(?:the|a|an)\s+", "", name, flags=re.I)
    return name.strip()

import hashlib


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


class GraphStore:
    """Graph-based knowledge store: deterministic extraction + BFS traversal."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            # Drop legacy graph tables if their UNIQUE constraint shape predates the
            # platform-aware schema (these are rebuildable index tables; were empty).
            self._drop_if_legacy_edges(conn)
            # Migrate legacy tables BEFORE running schema (indexes reference new columns).
            self._migrate_add_column(conn, "Memory_Nodes", "source", "TEXT")
            self._migrate_add_column(conn, "Memory_Edges", "source", "TEXT")
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()

    @staticmethod
    def _drop_if_legacy_edges(conn: sqlite3.Connection):
        """Drop Memory_Edges if its UNIQUE constraint lacks the platform column."""
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='Memory_Edges'"
        ).fetchone()
        if not row or not row[0]:
            return
        sql = row[0]
        # New schema UNIQUE includes platform; legacy did not.
        if "UNIQUE(source_id, target_id, relation, platform)" not in sql:
            conn.execute("DROP TABLE IF EXISTS Memory_Edges")

    @staticmethod
    def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, coltype: str):
        """Add a column if the table exists but lacks it (legacy schema migration)."""
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── entity extraction (deterministic) ─────────────────────────────────────
    def _extract_entities(self, text: str) -> List[Tuple[str, str]]:
        """Return list of (name, type) deduplicated, preserving order."""
        if not text:
            return []
        text = text[:MAX_TEXT_LEN]
        found: List[Tuple[str, str]] = []
        seen_spans: Set[Tuple[int, int]] = set()

        # 1) Lexicon hits (whole-word, case-insensitive)
        for term, etype in _TECH_LEXICON.items():
            for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I):
                span = m.span()
                if not any(self._overlap(span, s) for s in seen_spans):
                    seen_spans.add(span)
                    found.append((m.group(0), etype))
            if len(found) >= MAX_ENTITIES_PER_DOC:
                return self._dedup_entities(found)

        # 2) Regex patterns
        for _, pat, etype in _PATTERNS:
            for m in pat.finditer(text):
                span = m.span()
                if any(self._overlap(span, s) for s in seen_spans):
                    continue
                seen_spans.add(span)
                name = m.group(0).strip().rstrip(".,;:)]}")
                if not name:
                    continue
                # Skip capitalized sentence-starters ("The", "This", "But", ...)
                first_word = name.split()[0].lower() if name.split() else name.lower()
                if first_word in _CAP_STOPWORDS and len(name.split()) == 1:
                    continue
                # acronyms: skip if it's just a common English word in caps at sentence start
                if etype == "concept" and name.isupper() and len(name) <= 3 and self._is_sentence_start(text, span[0]):
                    continue
                found.append((name, etype))
                if len(found) >= MAX_ENTITIES_PER_DOC:
                    break
            if len(found) >= MAX_ENTITIES_PER_DOC:
                break

        return self._dedup_entities(found)

    @staticmethod
    def _overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
        return not (a[1] <= b[0] or b[1] <= a[0])

    @staticmethod
    def _is_sentence_start(text: str, pos: int) -> bool:
        before = text[:pos].rstrip()
        return before == "" or before[-1] in ".!?\n"

    @staticmethod
    def _dedup_entities(found: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        seen: Set[str] = set()
        out: List[Tuple[str, str]] = []
        for name, etype in found:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((name, etype))
        return out

    # ── relationship extraction (deterministic) ──────────────────────────────
    def _extract_relationships(self, text: str,
                                entities: List[Tuple[str, str]]
                                ) -> List[Tuple[str, str, str, float]]:
        """Return list of (source, relation, target, weight)."""
        if not text or len(entities) < 2:
            return []
        text = text[:MAX_TEXT_LEN]
        rels: List[Tuple[str, str, str, float]] = []
        seen: Set[Tuple[str, str, str]] = set()

        # 1) Linguistic cue patterns
        name_set = {n.lower(): n for n, _ in entities}
        for pat, relation in _CUE_PATTERNS:
            for m in pat.finditer(text):
                a = _clean_entity_name(m.group(1))
                b = _clean_entity_name(m.group(2))
                a_low, b_low = a.lower(), b.lower()
                if not a or not b or a_low == b_low:
                    continue
                # Skip if either side is just a determiner/sentence-starter
                if a_low in _CAP_STOPWORDS or b_low in _CAP_STOPWORDS:
                    continue
                # Normalize to known entity names when possible
                a_norm = name_set.get(a_low, a)
                b_norm = name_set.get(b_low, b)
                key = (a_norm.lower(), relation, b_norm.lower())
                if key in seen:
                    continue
                seen.add(key)
                rels.append((a_norm, relation, b_norm, 0.9))
                if len(rels) >= MAX_EDGES_PER_DOC:
                    return rels

        # 2) Co-occurrence within a sliding token window → RELATES_TO
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.\-]+", text)
        ent_lower = [n.lower() for n, _ in entities]
        ent_lookup = {n.lower(): n for n, _ in entities}
        window = COOCCUR_WINDOW
        for i, tok in enumerate(tokens):
            tl = tok.lower()
            if tl not in ent_lookup:
                continue
            for j in range(i + 1, min(i + window + 1, len(tokens))):
                ot = tokens[j].lower()
                if ot == tl or ot not in ent_lookup:
                    continue
                a = ent_lookup[tl]
                b = ent_lookup[ot]
                key = (tl, "RELATES_TO", ot)
                rkey = (ot, "RELATES_TO", tl)
                if key in seen or rkey in seen:
                    continue
                seen.add(key)
                # weight decays with distance
                w = max(0.1, 1.0 - (j - i) / (window + 1))
                rels.append((a, "RELATES_TO", b, round(w, 3)))
                if len(rels) >= MAX_EDGES_PER_DOC:
                    return rels
        return rels

    # ── optional LLM enrichment (best-effort, non-blocking) ───────────────────
    def _query_llm(self, prompt: str, max_tokens: int = 256) -> str:
        payload = json.dumps({
            "model": EXTRACT_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        }).encode()
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/generate",
                                         data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("response", "").strip()
        except Exception:
            return ""

    # ── storage ───────────────────────────────────────────────────────────────
    def _upsert_node(self, conn: sqlite3.Connection, name: str, node_type: str,
                     platform: str, source: Optional[str] = None) -> int:
        row = conn.execute(
            "SELECT id FROM Memory_Nodes WHERE name=? AND type=? AND platform=?",
            (name, node_type, platform),
        ).fetchone()
        if row:
            return row[0]
        cur = conn.execute(
            "INSERT INTO Memory_Nodes (name, type, platform, source) VALUES (?, ?, ?, ?)",
            (name, node_type, platform, source),
        )
        return cur.lastrowid

    def _upsert_edge(self, conn: sqlite3.Connection, src: int, tgt: int,
                     relation: str, weight: float, evidence: str,
                     platform: str, source: Optional[str] = None):
        conn.execute(
            "INSERT INTO Memory_Edges (source_id, target_id, relation, weight, evidence, platform, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source_id, target_id, relation, platform) DO UPDATE SET "
            "weight = MAX(weight, excluded.weight), "
            "evidence = COALESCE(excluded.evidence, evidence)",
            (src, tgt, relation, weight, evidence[:500], platform, source),
        )

    def extract_and_store(self, text: str, platform: str = "default",
                          use_llm: bool = False) -> dict:
        """Extract entities + relationships from text and store in the graph."""
        if not text or not text.strip():
            return {"entities_found": 0, "relationships_found": 0, "entities": [], "relationships": []}
        source = _content_hash(text)
        entities = self._extract_entities(text)
        rels = self._extract_relationships(text, entities)

        # Optional LLM enrichment (only if requested and reachable)
        if use_llm and entities:
            llm_rels = self._llm_extract_relationships(text)
            for src, rel, tgt in llm_rels:
                if rel in RELATION_TYPES and src and tgt and src.lower() != tgt.lower():
                    rels.append((src, rel, tgt, 0.6))

        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                node_ids: Dict[str, int] = {}
                for name, etype in entities:
                    nid = self._upsert_node(conn, name, etype, platform, source)
                    node_ids[name.lower()] = nid

                edge_count = 0
                for src, rel, tgt, w in rels:
                    src_id = node_ids.get(src.lower())
                    tgt_id = node_ids.get(tgt.lower())
                    if src_id is None:
                        src_id = self._upsert_node(conn, src, "entity", platform, source)
                        node_ids[src.lower()] = src_id
                    if tgt_id is None:
                        tgt_id = self._upsert_node(conn, tgt, "entity", platform, source)
                        node_ids[tgt.lower()] = tgt_id
                    if src_id == tgt_id:
                        continue
                    self._upsert_edge(conn, src_id, tgt_id, rel, w, text[:200], platform, source)
                    edge_count += 1

                conn.commit()
                return {
                    "entities_found": len(entities),
                    "relationships_found": edge_count,
                    "entities": [{"name": n, "type": t} for n, t in entities],
                    "relationships": [{"source": s, "relation": r, "target": t, "weight": w}
                                      for s, r, t, w in rels],
                }
            except Exception as e:
                conn.rollback()
                return {"error": str(e)}
            finally:
                conn.close()

    def _llm_extract_relationships(self, text: str) -> List[Tuple[str, str, str]]:
        prompt = (
            "Extract relationships between entities in this text. Use these relation types: "
            + ", ".join(RELATION_TYPES) + "\n"
            "Output one relationship per line: SourceEntity|RELATION|TargetEntity\n"
            "If none found, output: NONE\n\nText: " + text[:1500]
        )
        result = self._query_llm(prompt, 256)
        out: List[Tuple[str, str, str]] = []
        if not result or result == "NONE":
            return out
        for line in result.split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                out.append((parts[0].strip(), parts[1].strip().upper(), parts[2].strip()))
        return out

    # ── traversal (correct Python BFS — no recursive CTE) ─────────────────────
    def query_entity(self, name: str, depth: int = 2,
                     platform: Optional[str] = None) -> dict:
        """Return the subgraph around `name` up to `depth` hops."""
        with self._lock:
            conn = self._conn()
            try:
                where = "AND platform=?" if platform else ""
                params = (name, platform) if platform else (name,)
                node = conn.execute(
                    f"SELECT id, name, type FROM Memory_Nodes WHERE name=? {where} LIMIT 1",
                    params,
                ).fetchone()
                if not node:
                    return {"error": f"Entity '{name}' not found"}

                start_id = node[0]
                # BFS over edges (undirected)
                visited: Set[int] = {start_id}
                frontier = {start_id}
                edges_out: List[dict] = []
                for d in range(1, depth + 1):
                    if not frontier:
                        break
                    next_frontier: Set[int] = set()
                    placeholders = ",".join("?" * len(frontier))
                    rows = conn.execute(
                        f"SELECT source_id, target_id, relation, weight FROM Memory_Edges "
                        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                        list(frontier) + list(frontier),
                    ).fetchall()
                    for s, t, rel, w in rows:
                        neighbor = t if s in frontier else s
                        if neighbor in visited and s not in frontier:
                            # still record edge if one endpoint is new this round
                            pass
                        edges_out.append({
                            "source": s, "target": t, "relation": rel,
                            "weight": w, "depth": d,
                        })
                        if neighbor not in visited:
                            visited.add(neighbor)
                            next_frontier.add(neighbor)
                    frontier = next_frontier

                # dedup edges
                seen_e: Set[Tuple[int, int, str]] = set()
                uniq_edges = []
                for e in edges_out:
                    k = (e["source"], e["target"], e["relation"])
                    if k in seen_e:
                        continue
                    seen_e.add(k)
                    uniq_edges.append(e)

                node_ids = set(visited)
                for e in uniq_edges:
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
                placeholders = ",".join("?" * len(node_ids))
                nodes = conn.execute(
                    f"SELECT id, name, type FROM Memory_Nodes WHERE id IN ({placeholders})",
                    list(node_ids),
                ).fetchall() if node_ids else []
                return {
                    "center": {"id": node[0], "name": node[1], "type": node[2]},
                    "nodes": [{"id": n[0], "name": n[1], "type": n[2]} for n in nodes],
                    "edges": uniq_edges,
                    "total_nodes": len(nodes),
                    "total_edges": len(uniq_edges),
                }
            finally:
                conn.close()

    def find_path(self, source_name: str, target_name: str,
                  max_depth: int = 5, platform: Optional[str] = None) -> dict:
        """Shortest path (BFS) between two entities. Returns ordered steps."""
        with self._lock:
            conn = self._conn()
            try:
                where = "AND platform=?" if platform else ""
                def find_node(nm):
                    p = (nm, platform) if platform else (nm,)
                    return conn.execute(
                        f"SELECT id FROM Memory_Nodes WHERE name=? {where} LIMIT 1", p
                    ).fetchone()
                src = find_node(source_name)
                tgt = find_node(target_name)
                if not src or not tgt:
                    return {"error": "One or both entities not found"}

                src_id, tgt_id = src[0], tgt[0]
                # BFS with parent tracking
                visited: Dict[int, Optional[int]] = {src_id: None}
                edge_to: Dict[int, dict] = {}
                frontier = [src_id]
                found = False
                for _ in range(max_depth):
                    if not frontier or found:
                        break
                    nxt: List[int] = []
                    placeholders = ",".join("?" * len(frontier))
                    rows = conn.execute(
                        f"SELECT source_id, target_id, relation FROM Memory_Edges "
                        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                        frontier + frontier,
                    ).fetchall()
                    for s, t, rel in rows:
                        neighbor = t if s in frontier else s
                        if neighbor in visited:
                            continue
                        visited[neighbor] = s if s in frontier else t
                        edge_to[neighbor] = {"source": s, "target": t, "relation": rel}
                        if neighbor == tgt_id:
                            found = True
                            break
                        nxt.append(neighbor)
                    frontier = nxt

                if not found and tgt_id not in visited:
                    return {"error": f"No path found within depth {max_depth}"}

                # Reconstruct path
                steps: List[dict] = []
                cur = tgt_id
                while cur is not None and cur != src_id:
                    e = edge_to.get(cur)
                    if not e:
                        break
                    steps.append(e)
                    cur = visited[cur]
                steps.reverse()
                return {
                    "path_found": True,
                    "depth": len(steps),
                    "steps": steps,
                }
            finally:
                conn.close()

    def get_stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            try:
                nodes = conn.execute("SELECT COUNT(*) FROM Memory_Nodes").fetchone()[0]
                edges = conn.execute("SELECT COUNT(*) FROM Memory_Edges").fetchone()[0]
                rels = conn.execute(
                    "SELECT relation, COUNT(*) c FROM Memory_Edges GROUP BY relation ORDER BY c DESC"
                ).fetchall()
                types = conn.execute(
                    "SELECT type, COUNT(*) c FROM Memory_Nodes GROUP BY type ORDER BY c DESC"
                ).fetchall()
                return {
                    "total_nodes": nodes,
                    "total_edges": edges,
                    "relations": {r: c for r, c in rels},
                    "node_types": {t: c for t, c in types},
                    "extraction": "deterministic (regex + lexicon) + optional LLM",
                }
            finally:
                conn.close()


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    gs = GraphStore()
    if len(sys.argv) < 2:
        print("Usage: cortexllm_graph.py <extract|query|path|stats> [args]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "extract":
        text = " ".join(sys.argv[2:])
        use_llm = "--llm" in sys.argv
        print(json.dumps(gs.extract_and_store(text, use_llm=use_llm), indent=2))
    elif cmd == "query":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        depth = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        print(json.dumps(gs.query_entity(name, depth), indent=2))
    elif cmd == "path":
        src = sys.argv[2] if len(sys.argv) > 2 else ""
        tgt = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(gs.find_path(src, tgt), indent=2))
    elif cmd == "stats":
        print(json.dumps(gs.get_stats(), indent=2))
    else:
        print(f"Unknown command: {cmd}")