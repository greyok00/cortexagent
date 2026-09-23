#!/usr/bin/env python3
"""research/pipeline.py — search, scrape, and deep-research pipeline.

Local-only: SearXNG JSON API first (127.0.0.1:9999 → :8888), firecrawl
(when a key is present in ~/.cortexagent/research/.env) as a fallback for
hard-to-fetch pages. Keys are used inside this module's outbound requests
only and are scrubbed from everything that leaves this process.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import keys as research_keys

SITES = json.loads((Path(__file__).parent / "data" / "sites.json").read_text())
SEARX_URLS = ("http://127.0.0.1:9999", "http://127.0.0.1:8888")
UA = "Mozilla/5.0 (X11; Linux x86_64) CortexAgent-Research/1.0"
EXCLUDED = set(SITES.get("excluded", []))


# ── search ──────────────────────────────────────────────────────────────────

def search(query: str, category: str = "general", max_results: int = 12,
           time_range: str = "", language: str = "") -> dict:
    q = urllib.parse.urlencode({
        "q": query, "format": "json", "safesearch": 0,
        **({"categories": category} if category and category != "general" else {}),
        **({"time_range": time_range} if time_range else {}),
        **({"language": language} if language else {}),
    })
    for base in SEARX_URLS:
        try:
            req = urllib.request.Request(f"{base}/search?{q}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            break
        except Exception:
            continue
    else:
        return {"ok": False, "error": "searxng unreachable on 9999/8888", "results": []}

    seen: set[str] = set()
    out: list[dict] = []
    for r in data.get("results", []):
        url = str(r.get("url", ""))
        dom = _domain(url)
        if not url or url in seen or dom in EXCLUDED:
            continue
        seen.add(url)
        out.append({
            "title": (r.get("title") or "")[:200],
            "url": url,
            "snippet": (r.get("content") or "")[:300],
            "domain": dom,
            "tier": _tier(dom),
            "engine": r.get("engine", ""),
        })
        if len(out) >= max_results:
            break
    return {"ok": True, "query": query, "category": category,
            "results": out, "key_backends_available": {
                "firecrawl": research_keys.has("FIRECRAWL_API_KEY")}}


# ── scrape ──────────────────────────────────────────────────────────────────

class _Extract(HTMLParser):
    """Readable-text extractor: drop script/style/nav junk, keep headings."""
    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header",
             "aside", "form", "iframe", "button", "select", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_h1 = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "h1":
            self._in_h1 = True
        elif tag in ("p", "li", "tr", "h2", "h3", "h4", "pre", "blockquote", "td"):
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "h1":
            self._in_h1 = False
        elif tag in ("p", "tr", "h2", "h3", "h4", "pre", "blockquote") and self._buf:
            text = " ".join("".join(self._buf).split())
            if len(text) > 40:
                self.chunks.append(text)
            self._buf = []

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_h1 and not self.title:
            self.title = data.strip()
        if self._buf is not None:
            self._buf.append(data)


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
        return ".".join(host.split(".")[-2:])
    except Exception:
        return ""


def _tier(domain: str) -> str:
    for cat, entries in SITES["categories"].items():
        for e in entries:
            if domain.endswith(e["domain"]):
                return e["tier"]
    return "unlisted"


def scrape(url: str, max_chars: int = 20000) -> dict:
    dom = _domain(url)
    if dom in EXCLUDED:
        return {"ok": False, "error": f"{dom} is on the excluded list"}
    html = ""
    status = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            if "html" in ctype or "text" in ctype or not ctype:
                html = r.read().decode("utf-8", "replace")
            else:
                return {"ok": False, "error": f"non-text content-type: {ctype}",
                        "url": url, "status": status}
    except Exception as e:
        # firecrawl fallback (key-based, stays in-process)
        k = research_keys.get("FIRECRAWL_API_KEY")
        if k:
            fc = _firecrawl_scrape(url, k)
            if fc:
                return {**fc, "via": "firecrawl"}
        return {"ok": False, "error": research_keys.redact(f"fetch failed: {e}"),
                "url": url, "status": status}

    p = _Extract()
    try:
        p.feed(html)
    except Exception:
        pass
    text = "\n\n".join(p.chunks)[:max_chars]
    return {"ok": bool(text), "url": url, "title": p.title[:200],
            "domain": dom, "tier": _tier(dom), "fetched": _now(),
            "chars": len(text), "text": text,
            "key_backends_available": {"firecrawl": research_keys.has("FIRECRAWL_API_KEY")}}


def _firecrawl_scrape(url: str, key: str) -> dict | None:
    try:
        import httpx  # local dep for the fallback lane only
        r = httpx.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {key}"},
            json={"url": url, "formats": ["markdown"]},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            md = (data.get("data") or {}).get("markdown", "")
            if md:
                return {"ok": True, "url": url, "title": (data.get("data") or {}).get("metadata", {}).get("title", ""),
                        "chars": len(md), "text": md[:20000], "fetched": _now()}
    except Exception:
        pass
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


# ── deep pipeline ───────────────────────────────────────────────────────────

def deep(question: str, categories: list[str] | None = None,
         max_pages: int = 8, max_chars_per_page: int = 8000) -> dict:
    """Search → select diverse domains → scrape → extract → cited brief."""
    cats = categories or _pick_categories(question)
    search_plan: list[dict] = []
    pool: dict[str, dict] = {}

    for cat in cats:
        for q in _query_variants(question, cat):
            s = search(q, category=cat, max_results=10)
            search_plan.append({"category": cat, "query": q, "ok": s["ok"],
                                "n": len(s["results"])})
            for r in s["results"]:
                pool.setdefault(r["url"], r)

    # primary-tier first, then secondary; cap pages per domain for diversity
    def rank(r: dict) -> tuple[int, int]:
        return (0 if r["tier"] == "primary" else 1 if r["tier"] == "secondary" else 2,
                -len(r["snippet"]))
    ordered = sorted(pool.values(), key=rank)[: max_pages * 2]
    per_domain: dict[str, int] = {}
    pages: list[dict] = []
    for r in ordered:
        if per_domain.get(r["domain"], 0) >= 2:
            continue
        per_domain[r["domain"]] = per_domain.get(r["domain"], 0) + 1
        s = scrape(r["url"], max_chars=max_chars_per_page)
        pages.append({"url": r["url"], "title": r["title"], "domain": r["domain"],
                      "tier": r["tier"], "ok": s.get("ok", False),
                      "text": s.get("text", "")[:max_chars_per_page]})
        if sum(1 for p in pages if p["ok"]) >= max_pages:
            break

    facts = _extract_facts(question, pages)
    return {
        "question": question,
        "categories": cats,
        "searches": search_plan,
        "pages_fetched": [p for p in pages if p["ok"]],
        "sources": sorted({p["url"] for p in pages if p["ok"]}),
        "findings": facts,
        "unverified": [f for f in facts if not f["source_urls"]],
        "note": "facts carry source_urls; anything in unverified has no source — treat as unconfirmed",
    }


def _pick_categories(question: str) -> list[str]:
    text = question.lower()
    cats = []
    for c in ("law", "osint", "dfir", "programming", "business"):
        keys = {"law": ("law", "legal", "statute", "court", "case", "regulation", "probation", "expung", "foia"),
                "osint": ("osint", "whois", "domain", "breach", "email", "phone"),
                "dfir": ("cve", "vulnerab", "security", "exploit", "malware", "patch"),
                "programming": ("python", "code", "api", "library", "framework", "programming", "bug"),
                "business": ("market", "revenue", "econom", "finance", "company", "industry")}[c]
        if any(k in text for k in keys):
            cats.append(c)
    return cats or ["general"]


def _query_variants(question: str, cat: str) -> list[str]:
    base = question[:180]
    variants = [f"{base} site:{d}" for d in _top_domains(cat, 2)]
    return [base] + variants


def _top_domains(cat: str, n: int) -> list[str]:
    entries = SITES["categories"].get(cat, SITES["categories"]["general"])
    return [e["domain"] for e in entries if e["tier"] == "primary"][:n]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _extract_facts(question: str, pages: list[dict]) -> list[dict]:
    """Keyword-overlap sentence extraction with per-fact source attribution."""
    q_terms = {w for w in re.findall(r"[a-z]{4,}", question.lower())}
    facts: list[dict] = []
    for p in pages:
        if not p.get("ok"):
            continue
        for sent in _SENT_SPLIT.split(p.get("text", "")):
            s = " ".join(sent.split())
            if not (80 <= len(s) <= 400):
                continue
            low = s.lower()
            score = sum(1 for t in q_terms if t in low)
            if score >= 2:
                facts.append({"text": s, "source_url": p["url"],
                              "source_domain": p["domain"], "tier": p["tier"]})
    # dedupe near-identical sentences, merge sources per fact text
    merged: dict[str, dict] = {}
    for f in facts:
        key = f["text"][:120]
        m = merged.setdefault(key, {**f, "source_urls": [], "source_domains": []})
        if f["source_url"] not in m["source_urls"]:
            m["source_urls"].append(f["source_url"])
            m["source_domains"].append(f["source_domain"])
    out = [{k: v for k, v in m.items() if k != "source_url" and k != "source_domain"}
           for m in merged.values()]
    out.sort(key=lambda f: (-len(f["source_urls"]), f["tier"] != "primary"))
    return out[:40]