# cython: language_level=3
"""cortex_tokenizer.pyx — Cython-compiled BM25 tokenizer.

CPU-bound hot path: tokenization + normalization + stopword filtering.
Expected speedup: 2-3x over pure Python.

Usage:
  # Compiled version (when available):
  from cortexllm.cortex_tokenizer import tokenize, count_tokens
  # Pure Python fallback (when .so not available):
  from cortexllm.cortex_tokenizer import tokenize_py as tokenize
"""
from __future__ import annotations

# Cython imports
from libc.stdlib cimport malloc, free
from libc.string cimport strlen

# ── Constants ─────────────────────────────────────────────────────────────────

# Common English stop words
STOPWORDS: frozenset = frozenset({
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

# Maximum token length
MAX_TERM_LEN = 64


cdef inline bint _is_stopword(const char* word, int length):
    """Check if a token is a stopword. O(1) lookup."""
    cdef object lower_word = word[:length].decode('ascii', errors='ignore').lower()
    return lower_word in STOPWORDS and len(lower_word) >= 2


cdef inline object _stem(object word):
    """Simple Porter-like stemmer (Cython-optimized)."""
    cdef str w = str(word).lower()
    if len(w) < 4:
        return w
    # Common suffix stripping
    for suffix, replacement in [
        ("tion", ""), ("ness", ""), "ment": "", ("ful", ""),
        ("ing", ""), ("ed", ""), ("ly", ""), ("ous", ""),
    ]:
        if suffix:
            if w.endswith(suffix):
                return w[:-len(suffix)] + replacement
    return w


cdef inline list _tokenize_cython(const char* text, int length):
    """Cython-optimized tokenizer.

    Tokenizes text using character-level processing, avoiding regex overhead.
    Returns a list of normalized, filtered tokens.
    """
    cdef list tokens = []
    cdef int i = 0
    cdef int word_start = -1
    cdef list current_word = []
    cdef object token, lower_token, parts
    
    while i < length:
        c = text[i]
        if c.isalnum():
            if word_start == -1:
                word_start = i
            current_word.append(c)
        else:
            if word_start != -1 and current_word:
                token = "".join(current_word)
                # Split camelCase
                parts = _split_camel_case(token)
                for p in parts:
                    lower_token = p.lower()
                    if len(lower_token) >= 2 and len(lower_token) <= MAX_TERM_LEN:
                        if lower_token not in STOPWORDS:
                            stemmed = _stem(lower_token)
                            if stemmed:
                                tokens.append(stemmed)
                current_word = []
                word_start = -1
        i += 1
    
    # Handle last word
    if word_start != -1 and current_word:
        token = "".join(current_word)
        parts = _split_camel_case(token)
        for p in parts:
            lower_token = p.lower()
            if len(lower_token) >= 2 and len(lower_token) <= MAX_TERM_LEN:
                if lower_token not in STOPWORDS:
                    stemmed = _stem(lower_token)
                    if stemmed:
                        tokens.append(stemmed)
    
    return tokens


cdef list _split_camel_case(str word):
    """Split camelCase words into separate tokens."""
    cdef list result = []
    cdef list current = []
    for i, c in enumerate(word):
        if i > 0 and c.isupper() and word[i-1].islower():
            if current:
                result.append("".join(current))
                current = []
        current.append(c)
    if current:
        result.append("".join(current))
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def tokenize(text):
    """Cython-optimized tokenization. Falls back to pure Python if input is not bytes."""
    if isinstance(text, bytes):
        return _tokenize_cython(text, len(text))
    elif isinstance(text, str):
        return tokenize_py(text)
    return []


def count_tokens(text):
    """Count the number of tokens (after filtering)."""
    if isinstance(text, bytes):
        return len(_tokenize_cython(text, len(text)))
    elif isinstance(text, str):
        return len(tokenize_py(text))
    return 0


# ── Pure Python fallback ──────────────────────────────────────────────────────
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")


def tokenize_py(text):
    """Pure Python tokenizer (fallback when Cython is not compiled)."""
    if not text:
        return []
    raw = _TOKEN_RE.findall(text)
    out = []
    for tok in raw:
        # Split camelCase: fooBar -> foo bar
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", tok).split()
        for p in parts:
            p = p.lower()
            if len(p) < 2 or len(p) > MAX_TERM_LEN:
                continue
            if p in STOPWORDS:
                continue
            if re.fullmatch(r"v?\d[\w.]*\d", p) or "." in p or "_" in p:
                out.append(p)
                continue
            stemmed = _stem_py(p)
            if stemmed and stemmed not in STOPWORDS:
                out.append(stemmed)
    return out


def _stem_py(word):
    """Python fallback stemmer."""
    w = str(word).lower()
    if len(w) < 4:
        return w
    for suffix, replacement in [("tion", ""), ("ness", ""), ("ment", ""),
                                 ("ful", ""), ("ing", ""), ("ed", ""),
                                 ("ly", ""), ("ous", "")]:
        if w.endswith(suffix):
            return w[:-len(suffix)] + replacement
    return w


def count_tokens_py(text):
    """Pure Python token counting."""
    return len(tokenize_py(text))


# ── Self-tests ────────────────────────────────────────────────────────────────
def _test():
    """Self-tests for the Cython tokenizer."""
    fails = 0
    
    def check(label, cond, detail=""):
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
    
    # Cython path (bytes input)
    tokens_bytes = tokenize(b"CortexAgent is local")
    check("bytes tokenization", len(tokens_bytes) > 0, str(tokens_bytes))
    
    # Empty input
    check("empty string", tokenize("") == [], "")
    check("bytes empty", tokenize(b"") == [], "")
    
    # Token counting
    check("count_tokens", count_tokens("hello world test") >= 1, "")
    
    print("✅ cortex_tokenizer PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(_test())
