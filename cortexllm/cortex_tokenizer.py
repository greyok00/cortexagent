"""cortex_tokenizer — BM25 tokenizer with Cython optimization.

FALLBACK: Pure Python implementation (used when .so not compiled).

Usage:
  from cortexllm.cortex_tokenizer import tokenize, count_tokens
  tokens = tokenize("CortexAgent uses llama-server")
  count = count_tokens("hello world test")
"""
from __future__ import annotations

import re
from typing import List

# ── Constants ─────────────────────────────────────────────────────────────────

STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "dare",
    "ought", "used", "it", "its", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their", "what", "which", "who",
    "whom", "where", "when", "how", "why", "not", "no", "nor", "so",
    "if", "then", "than", "too", "very", "just", "about", "above",
    "after", "again", "all", "also", "any", "as", "because", "before",
    "between", "each", "few", "fewer", "into", "more", "most", "other",
    "out", "over", "same", "some", "such", "through", "under", "until",
    "up", "while", "down", "off", "once", "here", "there", "only",
})

MAX_TERM_LEN = 64
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")


def tokenize(text) -> List[str]:
    """Tokenize + normalize + stem + stopword-filter.
    
    Returns ordered token list.
    
    Args:
        text: String or bytes input.
    
    Returns:
        List of normalized tokens (lowercase, stemmed, filtered).
    """
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')
    if not text:
        return []
    
    raw = _TOKEN_RE.findall(text)
    out: List[str] = []
    for tok in raw:
        # Split camelCase: fooBar -> foo bar
        parts = _split_camel_case(tok)
        for p in parts:
            p = p.lower()
            if len(p) < 2 or len(p) > MAX_TERM_LEN:
                continue
            if p in STOPWORDS:
                continue
            # Keep dotted/numeric version-ish tokens whole (e.g. 1.2.3, v1.4)
            if re.fullmatch(r"v?\d[\w.]*\d", p) or "." in p or "_" in p:
                out.append(p)
                continue
            stemmed = _stem(p)
            if stemmed and stemmed not in STOPWORDS:
                out.append(stemmed)
    return out


def count_tokens(text) -> int:
    """Count tokens after filtering."""
    return len(tokenize(text))


def _split_camel_case(word: str) -> List[str]:
    """Split camelCase words: fooBar -> ['foo', 'Bar']."""
    parts = []
    current = []
    for i, c in enumerate(word):
        if i > 0 and c.isupper() and word[i-1].islower():
            if current:
                parts.append("".join(current))
                current = []
        current.append(c)
    if current:
        parts.append("".join(current))
    return parts


def _stem(word: str) -> str:
    """Simple Porter-like stemmer."""
    w = word.lower()
    if len(w) < 4:
        return w
    for suffix, replacement in [
        ("tion", ""), ("ness", ""), ("ment", ""),
        ("ful", ""), ("ing", ""), ("ed", ""),
        ("ly", ""), ("ous", ""),
    ]:
        if w.endswith(suffix):
            return w[:-len(suffix)] + replacement
    return w


# ── Self-tests ────────────────────────────────────────────────────────────────
def _smoke() -> int:
    """Self-test the tokenizer."""
    fails = 0
    
    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal fails
        if not cond:
            print(f"❌ {label}: {detail}")
            fails += 1
        else:
            print(f"✅ {label}")
    
    # Basic tokenization
    tokens = tokenize("CortexAgent is a local AI agent")
    check("tokenization produces tokens", len(tokens) > 0, str(tokens))
    check("stopwords filtered", "a" not in tokens, str(tokens))
    check("contains cortex", any("cortex" in t for t in tokens), str(tokens))
    
    # CamelCase splitting
    tokens = tokenize("CortexAgent")
    check("camelCase split", any(t == "agent" for t in tokens), str(tokens))
    
    # Empty input
    check("empty string", tokenize("") == [], "")
    check("empty bytes", tokenize(b"") == [], "")
    
    # Token counting
    check("count_tokens", count_tokens("hello world") >= 1, "")
    
    # Bytes input
    tokens = tokenize(b"CortexAgent uses llama")
    check("bytes input", len(tokens) > 0, str(tokens))
    
    print("✅ cortex_tokenizer smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(_smoke() if "--smoke" in sys.argv else 0)
