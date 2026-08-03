#!/usr/bin/env python3
"""cortexllm_ontology.py — Ontology generation for CortexLLM.

Deterministic, rule-based categorization and taxonomy building that works on any
text (Memory_Hot, Coding_Practices, raw input). The tiny LLM is an optional,
best-effort enrichment — never required, never blocking.

Design goals (fast / safe / secure / robust):
  - Rule-based categorizer: a curated 2-level taxonomy with keyword signatures.
    Confidence from match strength (hit count + specificity). Reproducible,
    fast, and works without any model running.
  - Works on ANY content: categorize() accepts raw text; auto_tag_practices()
    backfills Coding_Practices; tag_memory() backfills Memory_Hot.
  - Taxonomy is persisted and grows: discovered high-frequency terms that don't
    fit existing categories are proposed as new subcategories (gap-driven).
  - Gap detection: low-coverage categories, unmapped content, orphan terms.
  - Optional LLM enrichment for ambiguous cases (best-effort, non-blocking).
  - Thread-locked, parameterized queries, 100% local, no PII egress.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DB_PATH = Path.home() / ".config/cortexllm/cortexllm.db"
OLLAMA_URL = os.environ.get("CORTEXLLM_OLLAMA_URL", "http://127.0.0.1:11434")
ONTOLOGY_MODEL = os.environ.get("CORTEXLLM_TINY_MODEL", "qwen2.5:0.5b")

MAX_TEXT_LEN = 200_000
MAX_TOP_TERMS = 40

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Ontology_Taxonomy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT    NOT NULL UNIQUE,
    parent_category TEXT,
    description     TEXT,
    depth           INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_parent ON Ontology_Taxonomy(parent_category);

CREATE TABLE IF NOT EXISTS Ontology_Mappings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT   NOT NULL DEFAULT 'text',   -- 'Coding_Practices' | 'Memory_Hot' | 'text'
    source_id    INTEGER,                            -- row id in source table (NULL for ad-hoc)
    content_hash TEXT,                              -- dedup for ad-hoc text
    category     TEXT    NOT NULL,
    confidence   REAL    NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    tags         TEXT    DEFAULT '[]',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_table, source_id, category),
    UNIQUE(source_table, content_hash, category)
);
CREATE INDEX IF NOT EXISTS idx_omaps_category ON Ontology_Mappings(category);
CREATE INDEX IF NOT EXISTS idx_omaps_source  ON Ontology_Mappings(source_table, source_id);
"""

# ── Curated taxonomy ─────────────────────────────────────────────────────────
# (parent, child, [keyword signatures]) — keyword match → category assignment.
# Order matters: more specific categories listed first within a parent.
_TAXONOMY: List[Tuple[str, str, List[str]]] = [
    # Security
    ("Security", "Web Security", ["xss", "csrf", "ssrf", "sql injection", "sqli", "clickjacking",
                                  "content security policy", "csp", "same-origin", "cors"]),
    ("Security", "Network Security", ["firewall", "ids", "ips", "ddos", "packet", "tcp", "udp",
                                      "port scan", "nmap", "wireshark", "pcap", "sniffing"]),
    ("Security", "Offensive Security", ["pentest", "penetration test", "red team", "exploit",
                                        "payload", "metasploit", "burpsuite", "sqlmap", "reverse shell",
                                        "privilege escalation", "lateral movement", "c2"]),
    ("Security", "Defensive Security", ["blue team", "siem", "soar", "edr", "incident response",
                                        "forensics", "threat hunting", "ioc", "detection"]),
    ("Security", "Cryptography", ["encryption", "decryption", "aes", "rsa", "sha", "hash", "hmac",
                                  "tls", "ssl", "pki", "certificate", "key exchange", "crypto"]),
    ("Security", "Vulnerabilities", ["cve", "vulnerability", "0day", "zero-day", "rce", "lfi", "rfi",
                                     "buffer overflow", "race condition", "deserialization"]),
    ("Security", "Social Engineering", ["phishing", "pretexting", "baiting", "tailgating",
                                         "social engineering", "osint", "recon"]),
    ("Security", "Malware", ["malware", "ransomware", "trojan", "worm", "rootkit", "backdoor",
                             "botnet", "polymorphic", "packed"]),
    # Development
    ("Development", "Languages", ["python", "javascript", "typescript", "rust", "golang", "java",
                                  "kotlin", "swift", "c++", "c#", "ruby", "php", "scala"]),
    ("Development", "Frameworks", ["django", "flask", "fastapi", "react", "vue", "svelte", "angular",
                                   "express", "spring", "rails", "nextjs", "next.js"]),
    ("Development", "Testing", ["unit test", "integration test", "pytest", "jest", "coverage",
                                "tdd", "mock", "fixture", "fuzzing", "regression"]),
    ("Development", "Code Quality", ["refactor", "lint", "linter", "code review", "technical debt",
                                      "clean code", "sonarqube", "static analysis"]),
    ("Development", "Version Control", ["git", "github", "gitlab", "branch", "merge", "rebase",
                                        "commit", "pull request", "pr", "diff"]),
    # Infrastructure
    ("Infrastructure", "Containers", ["docker", "container", "kubernetes", "k8s", "pod", "helm",
                                       "oci", "image", "registry"]),
    ("Infrastructure", "Cloud", ["aws", "azure", "gcp", "s3", "ec2", "lambda", "cloudfront",
                                 "cloudrun", "terraform", "cloudformation", "iac"]),
    ("Infrastructure", "Networking", ["dns", "cdn", "load balancer", "proxy", "nginx", "apache",
                                       "gateway", "subnet", "vpc", "routing"]),
    ("Infrastructure", "Operating Systems", ["linux", "ubuntu", "debian", "windows", "macos",
                                              "kernel", "systemd", "shell", "bash", "zsh"]),
    # Data
    ("Data", "Databases", ["sqlite", "postgres", "postgresql", "mysql", "mongodb", "redis",
                           "query", "index", "schema", "migration", "orm"]),
    ("Data", "Data Engineering", ["etl", "pipeline", "airflow", "spark", "kafka", "rabbitmq",
                                  "queue", "streaming", "batch", "data warehouse"]),
    ("Data", "Data Science", ["pandas", "numpy", "scipy", "statistics", "regression", "clustering",
                              "classification", "visualization", "matplotlib", "plotly"]),
    # AI/ML
    ("AI/ML", "LLM", ["llm", "language model", "transformer", "attention", "token", "context window",
                      "fine-tune", "rlhf", "prompt", "completion"]),
    ("AI/ML", "Embeddings & RAG", ["embedding", "vector", "rag", "retrieval", "tfidf", "bm25",
                                    "semantic search", "vector db", "faiss", "ann"]),
    ("AI/ML", "Knowledge Graphs", ["graph", "ontology", "taxonomy", "entity", "relation",
                                    "knowledge graph", "rdf", "sparql", "node", "edge"]),
    ("AI/ML", "Training", ["training", "inference", "gpu", "cuda", "vram", "checkpoint",
                           "quantization", "gguf", "llama.cpp", "ollama", "weights"]),
    # Memory Systems
    ("Memory Systems", "Memory Tiers", ["hot memory", "warm memory", "cold memory", "distillation",
                                         "checkpoint", "fifo", "compact", "prune", "eviction"]),
    ("Memory Systems", "Agent Memory", ["cortexllm", "cortexagent", "overseer", "mcp", "session",
                                        "resume", "context", "hook", "daemon"]),
    # Workflow
    ("Workflow", "Orchestration", ["workflow", "dag", "scheduler", "orchestrator", "pipeline",
                                    "dispatcher", "plan", "task", "stage"]),
    ("Workflow", "Automation", ["automation", "cron", "systemd", "daemon", "hook", "script",
                                 "batch", "queue", "background"]),
]


class OntologyEngine:
    """Deterministic categorization + taxonomy + gap analysis."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._init_db()
        self._seed_taxonomy()

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            # Migrate legacy Ontology_Mappings (old schema had practice_id/taxonomy_id).
            # The new schema is incompatible, so drop the legacy table if it has the old shape.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(Ontology_Mappings)").fetchall()}
            if cols and "practice_id" in cols and "source_table" not in cols:
                conn.execute("DROP TABLE Ontology_Mappings")
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

    def _seed_taxonomy(self):
        """Insert the curated taxonomy if not present."""
        with self._lock:
            conn = self._conn()
            try:
                for parent, child, _kw in _TAXONOMY:
                    conn.execute(
                        "INSERT OR IGNORE INTO Ontology_Taxonomy (category, depth) VALUES (?, 0)",
                        (parent,),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO Ontology_Taxonomy "
                        "(category, parent_category, depth, description) VALUES (?, ?, 1, ?)",
                        (child, parent, f"Subcategory of {parent}"),
                    )
                conn.commit()
            finally:
                conn.close()

    # ── categorization (deterministic) ───────────────────────────────────────
    def categorize(self, text: str) -> dict:
        """Auto-categorize text. Returns category, subcategory, confidence, matched_keywords."""
        if not text or not text.strip():
            return {"category": "Uncategorized", "subcategory": "", "confidence": 0.0,
                    "matched_keywords": []}
        body = text[:MAX_TEXT_LEN].lower()

        # Score every (parent, child) by keyword hit count + specificity
        scores: List[Tuple[str, str, float, List[str]]] = []
        for parent, child, keywords in _TAXONOMY:
            hits = [kw for kw in keywords if kw in body]
            if not hits:
                continue
            # confidence: bounded by hit count and keyword specificity
            spec = sum((len(kw.split()) + (1 if len(kw) > 6 else 0)) for kw in hits)
            conf = min(0.98, 0.4 + 0.12 * len(hits) + 0.04 * spec)
            scores.append((parent, child, conf, hits))

        if not scores:
            return {"category": "Uncategorized", "subcategory": "", "confidence": 0.0,
                    "matched_keywords": []}

        scores.sort(key=lambda x: x[2], reverse=True)
        parent, child, conf, hits = scores[0]
        return {
            "category": parent,
            "subcategory": child,
            "confidence": round(conf, 3),
            "matched_keywords": hits[:15],
            "alternatives": [{"category": p, "subcategory": c, "confidence": round(cf, 3)}
                             for p, c, cf, _ in scores[1:4]],
        }

    def categorize_and_store(self, text: str, source_table: str = "text",
                             source_id: Optional[int] = None) -> dict:
        """Categorize text and persist the mapping (idempotent)."""
        result = self.categorize(text)
        if result["category"] == "Uncategorized":
            return result
        import hashlib
        chash = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO Ontology_Mappings "
                    "(source_table, source_id, content_hash, category, confidence, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_table, source_id, chash if source_id is None else None,
                     result["subcategory"], result["confidence"],
                     json.dumps(result.get("matched_keywords", [])[:10])),
                )
                conn.commit()
            finally:
                conn.close()
        return result

    # ── optional LLM enrichment ──────────────────────────────────────────────
    def _query_llm(self, prompt: str, max_tokens: int = 256) -> str:
        payload = json.dumps({
            "model": ONTOLOGY_MODEL,
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

    def categorize_with_llm(self, text: str) -> dict:
        """Rule-based first; if low confidence, ask the LLM to refine. Best-effort."""
        base = self.categorize(text)
        if base["confidence"] >= 0.7:
            return base
        cats = sorted({c for p, c, _ in _TAXONOMY})
        prompt = (
            "Categorize this content into one of these subcategories, or 'Uncategorized'. "
            "Output: SUBCATEGORY|confidence(0-1)\nSubcategories: " + ", ".join(cats[:40]) +
            "\n\nContent: " + text[:1200]
        )
        result = self._query_llm(prompt, 128)
        if result and "|" in result:
            parts = result.split("|")
            sub = parts[0].strip()
            try:
                conf = min(max(float(parts[1].strip()), 0.0), 1.0)
            except ValueError:
                conf = 0.5
            # Find parent of this subcategory
            parent = next((p for p, c, _ in _TAXONOMY if c == sub), base["category"])
            if sub in cats:
                return {"category": parent, "subcategory": sub, "confidence": round(conf, 3),
                        "matched_keywords": base.get("matched_keywords", []),
                        "refined_by": "llm"}
        return base

    # ── taxonomy building / discovery ────────────────────────────────────────
    def build_taxonomy(self) -> dict:
        """Materialize the curated taxonomy into the DB and report coverage."""
        self._seed_taxonomy()
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT parent_category, category FROM Ontology_Taxonomy "
                    "WHERE parent_category IS NOT NULL ORDER BY parent_category"
                ).fetchall()
                tree: Dict[str, List[str]] = defaultdict(list)
                for parent, child in rows:
                    tree[parent].append(child)
                total = conn.execute("SELECT COUNT(*) FROM Ontology_Taxonomy").fetchone()[0]
                roots = conn.execute(
                    "SELECT COUNT(*) FROM Ontology_Taxonomy WHERE depth=0 OR parent_category IS NULL"
                ).fetchone()[0]
                return {"tree": dict(tree), "total_entries": total, "root_categories": roots}
            finally:
                conn.close()

    def discover_categories(self, sample: int = 1000) -> dict:
        """Find high-frequency terms in unmapped content → propose new subcategories."""
        with self._lock:
            conn = self._conn()
            try:
                # Sample recent Memory_Hot content not yet mapped
                rows = conn.execute(
                    "SELECT content FROM Memory_Hot ORDER BY id DESC LIMIT ?", (sample,)
                ).fetchall()
            finally:
                conn.close()
        if not rows:
            return {"proposed": [], "sampled": 0}

        # Tokenize and count non-stopword terms
        stop = set("the a an and or but in to for of is are was were it its with from by on at "
                   "this that we i you they he she him her our their my your".split())
        term_freq: Counter = Counter()
        for (content,) in rows:
            toks = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", (content or "").lower())
            term_freq.update(t for t in toks if t not in stop)

        # Existing categories (lowercased) to exclude
        existing = {c.lower() for _, c, _ in _TAXONOMY}
        proposed = []
        for term, freq in term_freq.most_common(MAX_TOP_TERMS):
            if term in existing or freq < 3:
                continue
            # Skip if it's already a known keyword
            if any(term in kws for _, _, kws in _TAXONOMY):
                continue
            proposed.append({"term": term, "frequency": freq})
        return {"proposed": proposed[:20], "sampled": len(rows)}

    def find_gaps(self) -> dict:
        """Find knowledge gaps: low-coverage categories, unmapped content."""
        with self._lock:
            conn = self._conn()
            try:
                # Coverage per subcategory from mappings
                coverage = conn.execute(
                    "SELECT category, COUNT(*) c FROM Ontology_Mappings GROUP BY category "
                    "ORDER BY c ASC"
                ).fetchall()
                low = [{"category": c, "count": n} for c, n in coverage if n < 3]

                # Unmapped Coding_Practices
                unmapped_cp = conn.execute("""
                    SELECT COUNT(*) FROM Coding_Practices cp
                    WHERE NOT EXISTS (
                        SELECT 1 FROM Ontology_Mappings om
                        WHERE om.source_table='Coding_Practices' AND om.source_id=cp.id)
                """).fetchone()[0] if self._table_exists(conn, "Coding_Practices") else 0
                total_cp = conn.execute("SELECT COUNT(*) FROM Coding_Practices").fetchone()[0] \
                    if self._table_exists(conn, "Coding_Practices") else 0

                # Unmapped Memory_Hot
                unmapped_hot = conn.execute("""
                    SELECT COUNT(*) FROM Memory_Hot h
                    WHERE NOT EXISTS (
                        SELECT 1 FROM Ontology_Mappings om
                        WHERE om.source_table='Memory_Hot' AND om.source_id=h.id)
                """).fetchone()[0]
                total_hot = conn.execute("SELECT COUNT(*) FROM Memory_Hot").fetchone()[0]

                return {
                    "low_count_categories": low,
                    "unmapped": {
                        "Coding_Practices": {"unmapped": unmapped_cp, "total": total_cp},
                        "Memory_Hot": {"unmapped": unmapped_hot, "total": total_hot},
                    },
                    "suggestion": "Run auto_tag_practices() and tag_memory() to map unmapped content",
                }
            finally:
                conn.close()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    # ── bulk tagging ──────────────────────────────────────────────────────────
    def auto_tag_practices(self, limit: int = 5000) -> dict:
        """Backfill Ontology_Mappings for Coding_Practices rows."""
        with self._lock:
            conn = self._conn()
            try:
                if not self._table_exists(conn, "Coding_Practices"):
                    return {"tagged": 0, "message": "Coding_Practices table not found"}
                rows = conn.execute("""
                    SELECT cp.id, cp.practice, COALESCE(cp.description,''), cp.category
                    FROM Coding_Practices cp
                    WHERE NOT EXISTS (
                        SELECT 1 FROM Ontology_Mappings om
                        WHERE om.source_table='Coding_Practices' AND om.source_id=cp.id)
                    LIMIT ?
                """, (limit,)).fetchall()
                tagged = 0
                for pid, practice, desc, _cat in rows:
                    text = f"{practice} {desc}"
                    res = self.categorize(text)
                    if res["category"] == "Uncategorized":
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO Ontology_Mappings "
                        "(source_table, source_id, category, confidence, tags) VALUES (?, ?, ?, ?, ?)",
                        ("Coding_Practices", pid, res["subcategory"],
                         res["confidence"], json.dumps(res.get("matched_keywords", [])[:10])),
                    )
                    tagged += 1
                conn.commit()
                return {"tagged": tagged, "checked": len(rows)}
            finally:
                conn.close()

    def tag_memory(self, limit: int = 5000) -> dict:
        """Backfill Ontology_Mappings for Memory_Hot rows."""
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute("""
                    SELECT h.id, h.content FROM Memory_Hot h
                    WHERE NOT EXISTS (
                        SELECT 1 FROM Ontology_Mappings om
                        WHERE om.source_table='Memory_Hot' AND om.source_id=h.id)
                    LIMIT ?
                """, (limit,)).fetchall()
                tagged = 0
                for hid, content in rows:
                    if not content:
                        continue
                    res = self.categorize(content)
                    if res["category"] == "Uncategorized":
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO Ontology_Mappings "
                        "(source_table, source_id, category, confidence, tags) VALUES (?, ?, ?, ?, ?)",
                        ("Memory_Hot", hid, res["subcategory"], res["confidence"],
                         json.dumps(res.get("matched_keywords", [])[:10])),
                    )
                    tagged += 1
                conn.commit()
                return {"tagged": tagged, "checked": len(rows)}
            finally:
                conn.close()

    def get_stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            try:
                tax = conn.execute("SELECT COUNT(*) FROM Ontology_Taxonomy").fetchone()[0]
                roots = conn.execute(
                    "SELECT COUNT(*) FROM Ontology_Taxonomy WHERE depth=0 OR parent_category IS NULL"
                ).fetchone()[0]
                maps = conn.execute("SELECT COUNT(*) FROM Ontology_Mappings").fetchone()[0]
                by_cat = conn.execute(
                    "SELECT category, COUNT(*) c FROM Ontology_Mappings GROUP BY category ORDER BY c DESC LIMIT 10"
                ).fetchall()
                return {
                    "taxonomy_entries": tax,
                    "root_categories": roots,
                    "mapped_items": maps,
                    "top_categories": {c: n for c, n in by_cat},
                    "method": "rule-based (curated taxonomy) + optional LLM",
                }
            finally:
                conn.close()


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    oe = OntologyEngine()
    if len(sys.argv) < 2:
        print("Usage: cortexllm_ontology.py <categorize|taxonomy|gaps|tag|tagmem|discover|stats> [args]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "categorize":
        text = " ".join(sys.argv[2:])
        print(json.dumps(oe.categorize(text), indent=2))
    elif cmd == "taxonomy":
        print(json.dumps(oe.build_taxonomy(), indent=2))
    elif cmd == "gaps":
        print(json.dumps(oe.find_gaps(), indent=2))
    elif cmd == "tag":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
        print(json.dumps(oe.auto_tag_practices(limit), indent=2))
    elif cmd == "tagmem":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
        print(json.dumps(oe.tag_memory(limit), indent=2))
    elif cmd == "discover":
        print(json.dumps(oe.discover_categories(), indent=2))
    elif cmd == "stats":
        print(json.dumps(oe.get_stats(), indent=2))
    else:
        print(f"Unknown command: {cmd}")