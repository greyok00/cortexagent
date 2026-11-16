#!/usr/bin/env python3
"""extractors.py — multi-extractor content funnel for knowledge-ingestor.
Layers, best-effort in order, first good result wins; structured side-harvest
always runs (tables/code/RSS). Everything degrades gracefully if a lib is absent.

  layer 1  trafilatura   main-article text (best boilerplate rejection)
  layer 2  selectolax+Grab  fallback: node harvest + kbcore's parser
  side     code/tables harvest for developer docs (kept as structured extras)
  feeds    feedparser    RSS/Atom discovery on doc index pages (changelog lanes)
  robots   urllib.robotparser politeness gate (skip disallowed paths)
"""
import re, json, urllib.robotparser as _rp
from urllib.parse import urlparse

def _get(url, timeout=25):
    import kbcore
    return kbcore.fetch(url, timeout=timeout)

def robots_ok(url, timeout=8):
    try:
        u=urlparse(url)
        base=f"{u.scheme}://{u.netloc}"
        rp=_rp.RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try: rp.read()
        except Exception: return True, "robots-unreadable(allow)"
        ua="*"
        if not rp.can_fetch(ua, url):
            return False, "robots-disallow"
        return True, "robots-ok"
    except Exception:
        return True, "robots-error(allow)"

def trafilatura_text(html, url):
    try:
        import trafilatura
        txt=trafilatura.extract(html, url=url, include_comments=False,
                                include_tables=True, include_code_blocks=True,
                                favor_recall=False, with_metadata=True)  # compact JSON-LD metadata for provenance
        if not txt: return None, None
        meta=None
        try:
            m=trafilatura.extract_metadata(html, url)
            if m:
                meta={"title":m.title,"sitename":m.sitename,"date":str(m.date or "")}
        except Exception: pass
        return txt, meta
    except ImportError:
        return None, None

def selectolax_harvest(html):
    """(text, code_blocks, tables) via fast tree walk; None-safe."""
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        return None, [], []
    tree=HTMLParser(html)
    for n in tree.css("script,style,noscript,nav,footer,header,aside,form"):
        if hasattr(n,"decompose"): n.decompose()
    text=tree.text(separator="\n", strip=True) or ""
    text=re.sub(r"\n{3,}","\n\n",text)
    code=["\n".join(n.text(strip=True) for n in node.css("span,div")) or node.text(strip=True)
          for node in tree.css("pre, code")]
    code=[c for c in code if len(c)>30][:40]
    tables=[]
    for tb in tree.css("table")[:20]:
        rows=[]
        for tr in tb.css("tr")[:60]:
            cells=[td.text(strip=True) for td in tr.css("th,td")]
            if cells: rows.append(" | ".join(c[:80] for c in cells))
        if 3<len(rows[0:1]) or len(rows)>1:
            tables.append("\n".join(rows))
    return text, code, tables

def feed_links(base_url, html):
    """Discover RSS/Atom feeds on a docs index (changelog subscription targets)."""
    out=[]
    try:
        for m in re.finditer(r'<link[^>]+(rss|atom)[^>]*>', html, re.I):
            href=re.search(r'href="([^"]+)"', m.group(0))
            if href:
                u=href.group(1)
                if u.startswith("http"): out.append(u)
                elif u.startswith("/"): out.append(f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}{u}")
        if not out and "atom.xml" in html: out.append(base_url.rstrip("/")+"/atom.xml")
    except Exception: pass
    return out[:6]

def process(url, html):
    """Unified entry: returns dict(text, code, tables, feeds, extractor, meta)."""
    txt, meta = trafilatura_text(html, url)
    ext="trafilatura" if txt else ""
    body_code, tables=[], []
    if not txt or len(txt)<400:
        s_text, body_code, tables = selectolax_harvest(html)
        if not txt or len(txt)<400:
            txt = s_text or txt
            ext = ext or ("selectolax" if s_text else "none")
    feeds=feed_links(url, html)
    return {"text": txt or "", "code": body_code, "tables": tables,
            "feeds": feeds, "extractor": ext or "grab-fallback", "meta": meta}

def process_code_anno(recs_html_tuple):
    """Given process() output, produce extra records for code blocks/tables
    (kept as separate chunks tagged in title, so embeddings stay focused)."""
    pass  # wired at kbserver_patch layer where add_records is called
