#!/usr/bin/env python3
"""
CortexLLM Cold Memory Distiller — background job for Warm → Cold distillation.

Runs as a scheduled task (not on the hot path). Reads Memory_Warm, identifies
genuinely useful facts, and writes them to Memory_Cold with source/confidence/tags.

Extraction rules:
  - Configuration values (API endpoints, paths, settings)
  - Error solutions (problem → fix patterns)
  - Workflow steps (multi-step processes)
  - User preferences (stated preferences, rules)
  - Reusable knowledge (facts, definitions, reference data)

Usage:
    # Run once
    python3 cold_distiller.py

    # Run as a daemon (every 30 minutes)
    python3 cold_distiller.py --daemon --interval 1800
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from cortexllm_db import db


# Patterns that indicate useful knowledge
KNOWLEDGE_PATTERNS = {
    "configuration": [
        r"(?:api|endpoint|base)\s*[=:]\s*[\"']?https?://[^\"'\s]+",
        r"(?:port|timeout|interval|limit)\s*[=:]\s*\d+",
        r"(?:key|token|secret|password)\s*[=:]\s*[\"'][^\"']+[\"']",
        r"config(?:uration)?\s*(?:file|path|dir)",
    ],
    "error_solution": [
        r"(?:error|fix|solution|resolve|workaround)",
        r"(?:failed|crash|bug|issue)\s*(?:because|due to|caused by)",
        r"(?:try|use|run|set|change|update)\s+(?:this|that|it|the)",
    ],
    "workflow": [
        r"(?:step|stage|phase)\s*\d+",
        r"(?:first|then|next|finally|after that)",
        r"(?:workflow|process|pipeline|procedure)",
    ],
    "preference": [
        r"(?:prefer|like|want|need|require)\s+(?:to|using|the)",
        r"(?:always|never|only|must|should)\s+(?:use|do|run|set)",
        r"(?:language|format|style|mode)\s*[=:]\s*[\"']?\w+",
    ],
    "reference": [
        r"(?:is|are|means|refers to|stands for)\s+(?:a|an|the)",
        r"(?:known as|called|named|titled)",
        r"(?:version|release|build)\s*[\d.]+",
    ],
}

# Patterns that indicate LOW-value content (skip these)
LOW_VALUE_PATTERNS = [
    r"^(?:hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure|great)",
    r"^(?:how are you|what's up|good morning|good afternoon)",
    r"^(?:lol|lmao|rofl|haha|nice|awesome|cool)",
    r"^\s*$",
]


class ColdDistiller:
    """Extracts useful facts from Memory_Warm and writes to Memory_Cold."""

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = min_confidence
        self._seen_facts: Set[str] = set()
        self._load_seen_facts()

    def run(self, profile: str = None) -> Dict:
        """Run one distillation pass. Returns stats."""
        stats = {
            "scanned": 0,
            "extracted": 0,
            "skipped_low_value": 0,
            "skipped_duplicate": 0,
            "errors": 0,
            "categories": {},
        }

        # Read warm memory
        if profile:
            rows = db.get_warm(profile, limit=500)
        else:
            rows = db.reader().execute(
                "SELECT * FROM Memory_Warm ORDER BY timestamp DESC LIMIT 1000"
            ).fetchall()
            rows = [dict(r) for r in rows]

        stats["scanned"] = len(rows)

        for row in rows:
            content = row.get("content", "")
            if not content or len(content) < 20:
                continue

            # Skip low-value content
            if self._is_low_value(content):
                stats["skipped_low_value"] += 1
                continue

            # Extract facts
            facts = self._extract_facts(content, row)
            for fact in facts:
                # Check for duplicates
                fact_key = f"{fact['category']}:{fact['fact'][:100]}"
                if fact_key in self._seen_facts:
                    stats["skipped_duplicate"] += 1
                    continue

                # Write to cold memory
                try:
                    db.add_to_cold(
                        profile=row.get("profile", "shared"),
                        category=fact["category"],
                        fact=fact["fact"],
                        source=f"distiller:{row.get('platform', 'unknown')}",
                        confidence=fact["confidence"],
                        tags=fact["tags"],
                        metadata={
                            "source_row_id": row.get("id"),
                            "source_timestamp": row.get("timestamp"),
                            "distilled_at": datetime.now().isoformat(),
                        },
                    )
                    self._seen_facts.add(fact_key)
                    stats["extracted"] += 1
                    stats["categories"][fact["category"]] = \
                        stats["categories"].get(fact["category"], 0) + 1
                except Exception:
                    stats["errors"] += 1

        # Save seen facts for dedup across runs
        self._save_seen_facts()

        return stats

    # ------------------------------------------------------------------
    # Fact extraction
    # ------------------------------------------------------------------

    def _extract_facts(self, content: str, row: Dict) -> List[Dict]:
        """Extract useful facts from a message."""
        facts = []
        content_lower = content.lower()

        for category, patterns in KNOWLEDGE_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches[:2]:  # Max 2 per pattern per message
                    fact_text = match.strip()
                    if len(fact_text) < 10:
                        continue

                    # Calculate confidence based on pattern match quality
                    confidence = self._calculate_confidence(category, match, content)

                    facts.append({
                        "category": category,
                        "fact": fact_text,
                        "confidence": confidence,
                        "tags": self._generate_tags(category, row),
                    })

        return facts

    def _calculate_confidence(self, category: str, match: str,
                              content: str) -> float:
        """Calculate confidence score for an extracted fact."""
        base = 0.5

        # Longer matches are more likely to be meaningful
        if len(match) > 50:
            base += 0.2
        if len(match) > 100:
            base += 0.1

        # Assistant responses are more reliable than user messages
        # (We can't check role here since we're reading from warm memory)

        # Category-specific boosts
        if category == "configuration":
            base += 0.2  # Config values are usually precise
        elif category == "error_solution":
            base += 0.1  # Solutions are valuable but may be context-dependent
        elif category == "reference":
            base += 0.1  # Reference facts are usually accurate

        return min(base, 1.0)

    def _generate_tags(self, category: str, row: Dict) -> List[str]:
        """Generate tags for a cold memory entry."""
        tags = [category]
        platform = row.get("platform", "")
        if platform:
            tags.append(f"source:{platform}")
        return tags

    # ------------------------------------------------------------------
    # Low-value detection
    # ------------------------------------------------------------------

    def _is_low_value(self, content: str) -> bool:
        """Check if content is low-value (greetings, acknowledgments, etc.)."""
        content_stripped = content.strip().lower()
        for pattern in LOW_VALUE_PATTERNS:
            if re.match(pattern, content_stripped):
                return True
        return False

    # ------------------------------------------------------------------
    # Dedup persistence
    # ------------------------------------------------------------------

    def _load_seen_facts(self):
        """Load previously seen fact hashes."""
        try:
            seen_file = Path.home() / ".config/cortexllm" / "seen_facts.json"
            if seen_file.exists():
                self._seen_facts = set(json.loads(seen_file.read_text()))
        except Exception:
            pass

    def _save_seen_facts(self):
        """Save seen fact hashes for next run."""
        try:
            seen_file = Path.home() / ".config/cortexllm" / "seen_facts.json"
            seen_file.parent.mkdir(parents=True, exist_ok=True)
            # Keep only the most recent 10,000 to avoid unbounded growth
            facts = list(self._seen_facts)[-10000:]
            seen_file.write_text(json.dumps(facts))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="CortexLLM Cold Memory Distiller")
    parser.add_argument("--daemon", action="store_true",
                        help="Run as a daemon, repeating every --interval seconds")
    parser.add_argument("--interval", type=int, default=1800,
                        help="Interval between runs in seconds (default: 1800 = 30 min)")
    parser.add_argument("--profile", type=str, default=None,
                        help="Distill only this profile (default: all)")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                        help="Minimum confidence threshold (0.0-1.0)")

    args = parser.parse_args()

    distiller = ColdDistiller(min_confidence=args.min_confidence)

    if args.daemon:
        print(f"Cold Distiller daemon started (interval: {args.interval}s)")
        while True:
            stats = distiller.run(profile=args.profile)
            _print_stats(stats)
            time.sleep(args.interval)
    else:
        stats = distiller.run(profile=args.profile)
        _print_stats(stats)


def _print_stats(stats: Dict):
    """Print distillation stats."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"Scanned: {stats['scanned']} | "
          f"Extracted: {stats['extracted']} | "
          f"Skipped (low value): {stats['skipped_low_value']} | "
          f"Skipped (duplicate): {stats['skipped_duplicate']} | "
          f"Errors: {stats['errors']}")
    if stats["categories"]:
        cats = ", ".join(f"{k}: {v}" for k, v in stats["categories"].items())
        print(f"  Categories: {cats}")


if __name__ == "__main__":
    main()
