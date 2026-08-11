#!/usr/bin/env python3
"""pdf_knowledge.py — Extract practical knowledge from technical PDFs into Coding_Practices DB.

Uses pdftotext for extraction and the tiny LLM (LFM2.5-1.2B) to identify
actionable practices. Saves only practical info — no intros, no fluff.

Usage:
  python3 pdf_knowledge.py /path/to/book.pdf                    # Process one PDF
  python3 pdf_knowledge.py /path/to/dir/                        # Process all PDFs in dir
  python3 pdf_knowledge.py --list                               # List already processed
  python3 pdf_knowledge.py --source "Book Title" --status       # Check what's extracted
"""
import json, os, re, sqlite3, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from datetime import datetime

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib import tiny_llm  # LFM2.5-1.2B on llama-server :8082 (no Ollama)

# ── Config ───────────────────────────────────────────────────────────────────
DB = Path.home() / ".config/cortexllm" / "cortexllm.db"
CHUNK_SIZE = 1500  # chars per chunk (fits in 1.2B context)
CHUNK_OVERLAP = 200
MAX_CHUNKS_PER_PDF = 50  # safety limit
PROCESSED_LOG = Path.home() / ".cortexagent" / "logs" / "pdf_processed.json"

# ── DB ─────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def practice_exists(category: str, practice: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM Coding_Practices WHERE category=? AND practice=?",
        (category, practice)
    ).fetchone()
    conn.close()
    return row is not None


def insert_practice(category: str, practice: str, description: str,
                    source: str, priority: str = "medium", tags: list = None):
    if practice_exists(category, practice):
        return False  # skip duplicate
    conn = get_db()
    conn.execute(
        "INSERT INTO Coding_Practices (category, practice, description, source, priority, tags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (category, practice, description, source, priority, json.dumps(tags or []))
    )
    conn.commit()
    conn.close()
    return True


# ── PDF Text Extraction ────────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    """Extract text from PDF using pdftotext."""
    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"  ⚠️  pdftotext error: {result.stderr[:200]}")
        return ""
    return result.stdout


def chunk_text(text: str) -> list:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text) and len(chunks) < MAX_CHUNKS_PER_PDF:
        end = start + CHUNK_SIZE
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        # Try to break at a sentence boundary
        break_at = text.rfind(". ", start + CHUNK_SIZE - 100, end + 100)
        if break_at > start:
            end = break_at + 1
        chunks.append(text[start:end].strip())
        start = end - CHUNK_OVERLAP
    return chunks


# ── LLM Extraction ─────────────────────────────────────────────────────────

def query_llm(prompt: str, max_tokens: int = 256) -> str:
    """Query the tiny LFM2.5-1.2B LLM on llama-server :8082 (no Ollama)."""
    try:
        result = tiny_llm.query(prompt, max_tokens=max_tokens, temperature=0.1, timeout=60)
        return result or ""
    except Exception as e:
        print(f"  ⚠️  LLM error: {e}")
        return ""


def extract_practices_from_chunk(chunk: str, source: str) -> list:
    """Use tiny LLM to extract practical practices from a text chunk.

    Returns list of (category, practice, description, priority, tags).
    """
    prompt = (
        "Extract practical cybersecurity or programming practices from this text. "
        "For each practice found, output EXACTLY one line in this format:\n"
        "CATEGORY|Practice Name|Short description|priority|tag1,tag2\n\n"
        "Rules:\n"
        "- CATEGORY: one of: Network Security, Web Security, Authentication, "
        "Input Validation, Cryptography, Social Engineering, Malware Analysis, "
        "Penetration Testing, Vulnerability Assessment, Secure Coding, "
        "Cloud Security, Mobile Security, Incident Response, Forensics, Compliance\n"
        "- Practice Name: short (5-40 chars)\n"
        "- Description: practical action (10-100 chars)\n"
        "- Priority: critical/high/medium/low\n"
        "- Tags: comma-separated, no spaces after commas\n\n"
        "If no practices found, output: NONE\n\n"
        "Text:\n" + chunk[:1200]
    )

    result = query_llm(prompt, max_tokens=512)
    if not result or result == "NONE":
        return []

    practices = []
    for line in result.split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            category = parts[0].strip()
            practice = parts[1].strip()[:80]
            desc = parts[2].strip()[:200]
            priority = parts[3].strip() if len(parts) > 3 else "medium"
            tags = [t.strip() for t in parts[4].split(",")] if len(parts) > 4 else []
            if category and practice and desc:
                practices.append((category, practice, desc, priority, tags))

    return practices


# ── Processing ─────────────────────────────────────────────────────────────

def get_processed() -> set:
    if PROCESSED_LOG.exists():
        try:
            return set(json.loads(PROCESSED_LOG.read_text()))
        except Exception:
            pass
    return set()


def mark_processed(pdf_path: str):
    processed = get_processed()
    processed.add(str(pdf_path))
    PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_LOG.write_text(json.dumps(sorted(processed), indent=2))


def process_pdf(pdf_path: str, source_name: str = None):
    """Process a single PDF and extract practices into the DB."""
    pdf_path = str(Path(pdf_path).resolve())

    if pdf_path in get_processed():
        print(f"  ⏭️  Already processed")
        return 0

    if not source_name:
        source_name = Path(pdf_path).stem.replace("_", " ").replace("-", " ")[:80]

    print(f"  📖 Extracting text...", end=" ", flush=True)
    text = extract_text(pdf_path)
    if not text or len(text.strip()) < 100:
        print("❌ (too little text)")
        return 0

    print(f"({len(text)} chars)")

    chunks = chunk_text(text)
    print(f"  🔪 Split into {len(chunks)} chunks")

    total_inserted = 0
    for i, chunk in enumerate(chunks):
        if not chunk or len(chunk) < 50:
            continue

        print(f"  🤖 Chunk {i+1}/{len(chunks)}...", end=" ", flush=True)
        practices = extract_practices_from_chunk(chunk, source_name)

        if practices:
            for cat, practice, desc, priority, tags in practices:
                if insert_practice(cat, practice, desc, source_name, priority, tags):
                    total_inserted += 1
                    print(f"✅ [{cat}] {practice[:50]}", end=" | ")
                else:
                    print(f"⏭️  [{cat}] {practice[:50]} (dupe)", end=" | ")
            print()
        else:
            print("(no practices found)")

        time.sleep(0.5)  # rate limit

    if total_inserted > 0:
        mark_processed(pdf_path)
        print(f"  ✅ Inserted {total_inserted} new practices from {source_name}")

    return total_inserted


def list_processed():
    """List all processed PDFs and their contributions."""
    processed = get_processed()
    if not processed:
        print("No PDFs processed yet.")
        return

    conn = get_db()
    print(f"{'Source':<50} {'Practices':>10}")
    print(f"{'─'*50} {'─'*10}")
    for p in sorted(processed):
        name = Path(p).stem[:48]
        count = conn.execute(
            "SELECT COUNT(*) FROM Coding_Practices WHERE source LIKE ?",
            (f"%{name[:30]}%",)
        ).fetchone()[0]
        print(f"{name:<50} {count:>10}")
    conn.close()


def show_source_status(source: str):
    """Show what's been extracted from a specific source."""
    conn = get_db()
    rows = conn.execute(
        "SELECT category, practice, priority FROM Coding_Practices WHERE source LIKE ? ORDER BY category",
        (f"%{source}%",)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"No practices found for source '{source}'")
        return

    print(f"\n📖 {source} ({len(rows)} practices)")
    for r in rows:
        pri = {"critical": "🔴", "high": "🟡", "medium": "🟢", "low": "⚪"}.get(r["priority"], "⚪")
        print(f"  {pri} [{r['category']}] {r['practice']}")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "--list":
        list_processed()
        return 0

    if cmd == "--source" and len(sys.argv) > 2:
        show_source_status(sys.argv[2])
        return 0

    # Process a path (file or directory)
    path = Path(cmd)
    if not path.exists():
        print(f"Path not found: {path}")
        return 1

    if path.is_file() and path.suffix.lower() == ".pdf":
        process_pdf(str(path))
    elif path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {path}")
            return 0
        print(f"Found {len(pdfs)} PDFs in {path}")
        total = 0
        for pdf in pdfs:
            print(f"\n📄 {pdf.name}")
            total += process_pdf(str(pdf)) or 0
        print(f"\n{'='*50}")
        print(f"Total: {total} new practices across {len(pdfs)} PDFs")
    else:
        print(f"Not a PDF or directory: {path}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
