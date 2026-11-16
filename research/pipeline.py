#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import sys
import time

import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
# keys.py lives beside this file; importing it needs research/ on the path
# whether this module is run as a script or imported as research.pipeline
# See lib/cve_intel.py for the CVE lane contract.
if str(_repo_root / "research") not in sys.path:
    sys.path.insert(0, str(_repo_root / "research"))

import keys as research_keys

SITES = json.loads((Path(__file__).parent / "data" / "sites.json").read_text())
SEARX_URLS = ("http://127.0.0.1:8888",)
UA = "Mozilla/5.0 (X11; Linux x86_64) CortexAgent-Research/1.0"
EXCLUDED = set(SITES.get("excluded", []))





_DICTIONARY_DOMAINS = {
    "merriam-webster.com", "dictionary.cambridge.org", "cambridge.org",
    "indeed.com", "linkedin.com", "ziprecruiter.com", "glassdoor.com",
    "iciba.com", "baidu.com", "yourdictionary.com", "vocabulary.com",
    "collinsdictionary.com", "eudic.net", "english.cool",
    "oxfordlearnersdictionaries.com", "dictionary.com",
    "thefreedictionary.com", "swingeducation.com",
    "climbtheladder.com", "rsc.org",
}




def _brave_html(query: str, max_results: int) -> list[dict]:

    rows: list[dict] = []
    try:
        req = urllib.request.Request(
            f"https://search.brave.com/search?q={urllib.parse.quote_plus(query)}",
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read(400_000).decode("utf-8", "replace")
        seen: set[str] = set()
        for m in re.finditer(r'href="(https?://[^"]+)"', html):
            url = m.group(1)
            dom = _domain(url)
            if (not url or url in seen or not dom or dom in EXCLUDED
                    or dom.endswith("brave.com")
                    or any(dom.endswith(b) for b in (
                        "youtube.com", "facebook.com", "twitter.com",
                        "instagram.com", "linkedin.com", "pinterest.com",
                        "tiktok.com", "x.com", "apple.com", "microsoft.com",
                        "google.com")) or "typekit" in url):
                continue
            seen.add(url)
            rows.append({"title": dom, "url": url, "snippet": "",
                         "domain": dom, "tier": _tier(dom), "engine": "brave-html"})
            if len(rows) >= max_results:
                break
    except Exception:
        pass
    return rows


def _searx_single(query: str, engines: str, max_results: int) -> list[dict]:




    import re as _re
    spam_url = _re.compile(r"https?://finance\.yahoo\.com/quote/[A-Z.]{1,6}/?(?:[?#]|$)")
    q = urllib.parse.urlencode({"q": query, "format": "json",
                                "engines": engines, "safesearch": 0})
    for base in SEARX_URLS:
        try:
            req = urllib.request.Request(f"{base}/search?{q}",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            out: list[dict] = []
            for r in data.get("results", []):
                url = str(r.get("url", ""))
                dom = _domain(url)
                if not url or dom in EXCLUDED or r.get("engine") == "wiby":
                    continue
                if spam_url.match(url):
                    continue
                out.append({"title": (r.get("title") or "")[:200], "url": url,
                            "snippet": (r.get("content") or "")[:300],
                            "domain": dom, "tier": _tier(dom),
                            "engine": r.get("engine", "")})
                if len(out) >= max_results:
                    break
            if out:
                return out
        except Exception:
            continue
    return []


def _fallback_search(query: str, max_results: int) -> list[dict]:

    rows: list[dict] = []
    q = urllib.parse.quote_plus(query)



    try:
        req = urllib.request.Request(
            f"https://www.bing.com/search?q={q}&format=rss&count=20",
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            xml = r.read(200_000).decode("utf-8", "replace")
        for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
            b = m.group(1)
            t = re.search(r"<title>(.*?)</title>", b, re.S)
            l = re.search(r"<link>(.*?)</link>", b, re.S)
            d = re.search(r"<description>(.*?)</description>", b, re.S)
            if not (t and l):
                continue
            rows.append({"title": (t.group(1) or "")[:200],
                         "url": l.group(1).strip(),
                         "snippet": (d.group(1) or "")[:300],
                         "domain": "", "tier": "", "engine": "bing-rss"})
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            f"https://www.mojeek.com/search?q={q}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read(200_000).decode("utf-8", "replace")
        for m in re.finditer(
                r'<a class="ob" href="(http[^"]+)"[^>]*>(.*?)</a>', html, re.S):
            url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            rows.append({"title": title[:200], "url": url, "snippet": "",
                         "domain": "", "tier": "", "engine": "mojeek"})
    except Exception:
        pass
    return _polish_rows(rows, query, max_results)


def _polish_rows(rows: list[dict], query: str, max_results: int) -> list[dict]:

    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())} - {
        "what", "does", "when", "this", "that", "with", "from", "have",}
    # The +2 stock-trample and the −5 dictionary/yahoo-jobs
    # demotions steered ALL research toward finance-shaped answers. Finance
    # steering now applies only when the query itself is finance-shaped.
    finance_query = bool(re.search(
        r"\b(stock|stocks|shares|trading|markets?|equity|equities|investing|"
        r"price target|screener|ticker|rsi|buy|sell|bullish|bearish|"
        r"valuation|earnings|dividend|ipo)\b",
        query.lower()))
    def rank(r: dict) -> int:
        blob = (r["title"] + " " + r["url"]).lower()
        overlap = len(words & set(re.findall(r"[a-z]{4,}", blob)))


        if len(words) >= 3 and overlap < 2:
            overlap = 0


        if finance_query and re.search(
                r"\b(stock|stocks|trading|market|equity|investing|price target|screener|RSI)\b", blob):
            overlap += 2
        dom = r.get("domain") or _domain(r["url"])
        if finance_query and dom in _DICTIONARY_DOMAINS:
            overlap -= 5
        if finance_query and re.search(r"(finance\.yahoo\.com/quote|/jobs|/jobs/|viewjob)", r["url"]):
            overlap -= 5
        return overlap
    rows = sorted(rows, key=lambda r: -rank(r))
    seen: set[str] = set()
    out: list[dict] = []
    weak: list[dict] = []
    for r in rows:
        url = r["url"]
        dom = r.get("domain") or _domain(url)
        if not url or url in seen or dom in EXCLUDED or not dom:
            continue





        if rank(r) <= 0:
            weak.append(r)
            continue
        seen.add(url)
        r["domain"] = dom
        r["tier"] = _tier(dom)
        out.append(r)
        if len(out) >= max_results:
            break
    if not out and weak:
        seen.clear()
        for r in weak:
            url = r["url"]
            dom = r.get("domain") or _domain(url)
            if not url or url in seen or dom in EXCLUDED or not dom:
                continue
            seen.add(url)
            r["domain"] = dom
            r["tier"] = _tier(dom)
            r["low_overlap"] = True
            out.append(r)
            if len(out) >= max_results:
                break
    return out







TASK_RE = re.compile(r"\b(?:task[-_ ]?)?([1-4])\b")


def task_key(task_id) -> str:

    if task_id is not None and str(task_id).strip() != "":
        m = TASK_RE.search(str(task_id))
        if m:
            return f"task-{m.group(1)}"
    env = os.environ.get("RESEARCH_TASK", "")
    if env:
        m = TASK_RE.search(env)
        if m:
            return f"task-{m.group(1)}"
    return ""


def _with_task(r: dict, task_id) -> dict:

    tk = task_key(task_id)
    if tk and isinstance(r, dict) and r.get("ok"):
        r["task"] = tk
    return r


def search(query, category = "general", max_results: int = 12,
           time_range: str = "", language: str = "", task_id=None) -> dict:







    for eng in ("mojeek", "startpage", "mwmbl", "stract"):
        rows = _searx_single(query, eng, max_results)
        if len(rows) >= 3:
            return _with_task({"ok": True, "query": query,
                               "category": category,
                               "results": rows,
                               "backend": f"searxng-single:{eng}",
                               "key_backends_available": {"firecrawl": False}},
                              task_id)







        words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
        keep = [r for r in rows if r.get("snippet") and
                (words & set(re.findall(r"[a-z]{4,}", (r["title"] + " " + r["url"]).lower())))]
        if not keep and rows:
            keep = [r for r in rows if r.get("snippet") and
                    r["domain"] not in _DICTIONARY_DOMAINS]
        if keep:
            return _with_task({"ok": True, "query": query, "category": category,
                               "results": rows,
                               "backend": f"searxng-single:{eng}(thin)",
                               "key_backends_available": {"firecrawl": False}},
                              task_id)





    for eng in ("startpage news",):
        rows = _searx_single(query, eng, max_results)
        if len(rows) >= 3:
            return _with_task({"ok": True, "query": query, "category": category,
                               "results": rows,
                               "backend": f"searxng-single:{eng}",
                               "key_backends_available": {"firecrawl": False}},
                              task_id)
    fb = _brave_html(query, max_results)
    if len(fb) >= 3:
        return _with_task({"ok": True, "query": query, "category": category,
                           "results": fb, "backend": "brave-html-direct",
                           "key_backends_available": {"firecrawl": False}},
                          task_id)
    fb = _fallback_search(query, max_results)
    if len(fb) >= 3:
        return _with_task({"ok": True, "query": query, "category": category,
                           "results": fb,
                           "backend": "bing-rss+mojeek-direct",
                           "key_backends_available": {"firecrawl": False}},
                          task_id)
    merged = _searx_query(query, category, time_range, language)
    if merged.get("ok") and len(merged["results"]) >= 3:
        return _with_task(merged, task_id)
    return _with_task({"ok": False, "query": query, "category": category,
            "error": "all search backends returned <3 usable results",
            "results": [], "key_backends_available": {"firecrawl": False}},
            task_id)


def _searx_query(query: str, category: str, time_range: str, language: str,
                 max_results: int = 12) -> dict:

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
        return {"ok": False, "error": "searxng unreachable on 8888 (searx.space fallback will be tried by searxng_integrated)", "results": []}

    seen: set[str] = set()
    out: list[dict] = []
    for r in data.get("results", []):
        url = str(r.get("url", ""))
        dom = _domain(url)

        if not url or url in seen or dom in EXCLUDED or r.get("engine") == "wiby":
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
    if len(out) < 3:
        fb = _fallback_search(query, max_results)
        if len(fb) > len(out):
            return {"ok": True, "query": query, "category": category,
                    "results": fb, "backend": "bing-rss+mojeek-direct",
                    "note": "searxng degraded; direct backends used",
                    "key_backends_available": {
                        "firecrawl": research_keys.has("FIRECRAWL_API_KEY")}}
    return {"ok": True, "query": query, "category": category,
            "results": out, "key_backends_available": {
                "firecrawl": research_keys.has("FIRECRAWL_API_KEY")}}




class _Extract(HTMLParser):

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


def _wayback_url(url: str) -> str | None:

    try:
        av = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
        with urllib.request.urlopen(urllib.request.Request(av, headers={"User-Agent": UA}), timeout=15) as r:
            snap = (((json.loads(r.read()) or {}).get("archived_snapshots") or {}).get("closest") or {})
        if snap.get("available"):
            return str(snap.get("url", "")).replace("http://web.archive.org", "https://web.archive.org")
    except Exception:
        pass
    return None


def _fallback_scrape(url: str, max_chars: int) -> dict | None:


    try:
        req = urllib.request.Request("https://r.jina.ai/" + url,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = r.read(max(max_chars * 3, 60_000)).decode("utf-8", "replace")

        body = txt.split("Markdown Content:", 1)[-1]
        if body.strip():
            return {"ok": True, "url": url, "title": (txt.split("Title:", 1)[1].split("\\n", 1)[0][:200]
                                                      if "Title:" in txt else ""),
                    "domain": _domain(url), "tier": _tier(_domain(url)),
                    "fetched": _now(), "chars": len(body), "text": body[:max_chars],
                    "via": "r.jina.ai"}
    except Exception:
        pass


    try:
        _r = _patchright_scrape(url, max_chars)
        if _r:
            return _r
    except Exception:
        pass


    wu = _wayback_url(url)
    if wu:
        try:
            req = urllib.request.Request(wu, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                html = r.read(400_000).decode("utf-8", "replace")
            p = _Extract()
            try:
                p.feed(html)
            except Exception:
                pass
            text = "\\n\\n".join(p.chunks)[:max_chars]
            if text.strip():
                return {"ok": True, "url": url, "title": p.title[:200],
                        "domain": _domain(url), "tier": _tier(_domain(url)),
                        "fetched": _now(), "chars": len(text), "text": text,
                        "via": f"web.archive.org ({wu.rsplit('/', 2)[-2]})"}
        except Exception:
            pass
    return None


_PATCHRIGHT_STATE: dict = {}


def _patchright_available() -> bool:

    if "ok" in _PATCHRIGHT_STATE:
        return _PATCHRIGHT_STATE["ok"]
    try:
        from patchright.sync_api import sync_playwright  # noqa: F401
        _PATCHRIGHT_STATE["ok"] = True
    except Exception:
        _PATCHRIGHT_STATE["ok"] = False
    return _PATCHRIGHT_STATE["ok"]


_CHROME_CACHE = os.path.expanduser(
    os.environ.get("CORTEXAGENT_CHROME_CACHE", "~/.cache/ms-playwright"))
def _chrome_binary() -> str | None:
    for hit in sorted(Path(_CHROME_CACHE).glob(
            "chromium-*/chrome-linux*/chrome")):
        return str(hit)
    return None

_SCRAPE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")


def _patchright_scrape(url: str, max_chars: int) -> dict | None:

    chrome = _chrome_binary()
    if not chrome:
        return None
    try:
        from patchright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=chrome,
                                  args=["--no-sandbox"])
            ctx = b.new_context(viewport={"width": 1366, "height": 900},
                                user_agent=_SCRAPE_UA, locale="en-US")
            try:
                pg = ctx.new_page()
                pg.goto(url, timeout=45000, wait_until="domcontentloaded")
                pg.wait_for_timeout(8000)
                body = pg.inner_text("body")
                if len(body) < 800:
                    pg.reload(wait_until="domcontentloaded")
                    pg.wait_for_timeout(8000)
                    body = pg.inner_text("body")
                text = body[:max_chars]
                if text.strip():
                    return {"ok": True, "url": url,
                            "title": (pg.title() or "")[:200],
                            "domain": _domain(url), "tier": _tier(_domain(url)),
                            "fetched": _now(), "chars": len(text), "text": text,
                            "via": "patchright"}
            finally:
                b.close()
    except Exception:
        return None
    return None


def scrape(url: str, max_chars: int = 20000, task_id=None) -> dict:
    dom = _domain(url)
    if dom in EXCLUDED:
        return _with_task({"ok": False, "error": f"{dom} is on the "
                           "excluded list"}, task_id)
    html = ""
    status = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            if ctype and ("csv" in ctype or "xml" in ctype or "rss" in ctype
                          or "json" in ctype or ctype.startswith("text/plain")):


                body = r.read(max_chars + 2000).decode("utf-8", "replace")
                return {"ok": bool(body.strip()), "url": url, "title": dom,
                        "domain": dom, "tier": _tier(dom), "fetched": _now(),
                        "chars": min(len(body), max_chars),
                        "text": body[:max_chars], "raw_data": True}
            if "html" in ctype or "text" in ctype or not ctype:
                html = r.read().decode("utf-8", "replace")
            else:
                return {"ok": False, "error": f"non-text content-type: {ctype}",
                        "url": url, "status": status}
    except Exception as e:





        fb = _fallback_scrape(url, max_chars)
        if fb:
            return _with_task(fb, task_id)




        if task_key(task_id):
            cdpfb = _cdp_fetch_fallback(url, max_chars, task_id=task_id)
            if cdpfb:
                return cdpfb
        if os.environ.get("RESEARCH_ALLOW_FIRECRAWL") == "1":
            k = research_keys.get("FIRECRAWL_API_KEY")
            if k:
                fc = _firecrawl_scrape(url, k)
                if fc:
                    return {**fc, "via": "firecrawl"}
        return {"ok": False, "error": research_keys.redact(f"fetch failed: {e} (free fallbacks exhausted; firecrawl disabled by default)"),
                "url": url, "status": status}

    p = _Extract()
    try:
        p.feed(html)
    except Exception:
        pass
    text = "\n\n".join(p.chunks)[:max_chars]



    _low = text.lower()
    _wall_markers = ("access denied", "just a moment", "security verification",
                     "enable javascript and cookies", "checking your browser",
                     "attention required", "request unsuccessful",
                     "you don't have permission")
    if (not text.strip()) or len(text) < 1200 and any(m in _low for m in _wall_markers):
        fb = _fallback_scrape(url, max_chars)
        if fb and len(fb.get("text","")) > len(text):
            return _with_task(fb, task_id)

        if task_key(task_id):
            cdpfb = _cdp_fetch_fallback(url, max_chars, task_id=task_id)
            if cdpfb and len(cdpfb.get("text", "")) > len(text):
                return cdpfb
    return {"ok": bool(text), "url": url, "title": p.title[:200],
            "domain": dom, "tier": _tier(dom), "fetched": _now(),
            "chars": len(text), "text": text,
            "key_backends_available": {"firecrawl": research_keys.has("FIRECRAWL_API_KEY")}}


def _firecrawl_scrape(url: str, key: str) -> dict | None:
    try:
        import httpx
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








_TASK_REG_PATH = os.path.expanduser(
    "~/.cortexagent/research-task-registry.json")


def _session_id() -> str:
    return os.environ.get("CORTEX_SESSION_ID") or os.environ.get(
        "CORTEX_SESSION_FILE") or "unknown-session"


def task_registry(
        assign: str | None = None, task_id=None) -> dict:

    reg: dict = {}
    try:
        with open(_TASK_REG_PATH) as f:
            reg = json.load(f)
    except Exception:
        reg = {}
    if assign:
        tk = task_key(assign)
        if not tk:
            raise ValueError(f"unknown task slot: {assign!r} (task-1..task-4)")
        import socket
        prev = reg.get(tk) or {}
        prev_owner = prev.get("owner_session", "")
        sid = _session_id()
        reg[tk] = {"owner_session": sid,
                   "assigned_at": _now(),
                   "pid": os.getpid(), "host": socket.gethostname(),
                   "pages_dir": os.environ.get("RESEARCH_PAGES", "")}
        try:
            with open(_TASK_REG_PATH, "w") as f:
                json.dump(reg, f, indent=1)
        except Exception:
            pass
        out_reg = dict(reg)
        out_reg["_last_assignment"] = {
            "slot": tk, "owner_session": sid,
            "reassigned_from": prev_owner,
            "note": ("slot was previously held by " + prev_owner
                     if prev_owner and prev_owner != sid
                     else "fresh claim"),
        }
        return out_reg
    return reg


def _cdp_fetch_fallback(url: str, max_chars: int, task_id=None) -> dict | None:

    tk = task_key(task_id)
    if not tk:
        return None
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import browser_ports
        cfg = browser_ports.resolve(task=tk)
        port = int(cfg["port"])
        if port in (9223, 9224):
            return None
        if not browser_ports.ensure(cfg):
            return None
        import websocket
        cdp = f"http://127.0.0.1:{port}"
        t = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{cdp}/json/new", method="PUT"),
            timeout=15).read())
        tid, wsurl = t["id"], t["webSocketDebuggerUrl"]
        val = ""
        try:
            ws = websocket.create_connection(wsurl, timeout=30,
                                             suppress_origin=True)
            ws.send(json.dumps({"id": 10, "method": "Page.enable"}))
            ws.send(json.dumps({"id": 11, "method": "Page.navigate",
                                "params": {"url": url}}))
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    ws.settimeout(2.0)
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 11:
                        break
                    if msg.get("method") == "Page.loadEventFired":
                        break
                except websocket.WebSocketTimeoutException:
                    continue
            time.sleep(7.0)
            ws.settimeout(15.0)
            ws.send(json.dumps({"id": 12, "method": "Runtime.evaluate",
                                "params": {"expression":
                                           "document.body ? document.body.innerText : ''",
                                           "returnByValue": True}}))
            deadline = time.time() + 20
            while time.time() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("id") == 12:
                    val = (msg.get("result", {}).get("result", {})
                           .get("value", "") or "")
                    break
            ws.close()
        finally:
            try:
                urllib.request.urlopen(f"{cdp}/json/close/{tid}", timeout=10)
            except Exception:
                pass
        if val.strip():
            return {"ok": True, "url": url, "title": ""[:200],
                    "domain": _domain(url), "tier": _tier(_domain(url)),
                    "fetched": _now(), "chars": len(val), "text": val[:max_chars],
                    "via": f"cdp-task-slot:{tk}:{port}"}
    except Exception:
        return None
    return None




def deep(question: str, categories: list[str] | None = None,
         max_pages: int = 8, max_chars_per_page: int = 8000,
         task_id=None) -> dict:
    tk = task_key(task_id)
    cats = categories or _pick_categories(question)
    search_plan: list[dict] = []
    pool: dict[str, dict] = {}

    for cat in cats:
        for q in _query_variants(question, cat):
            s = search(q, category=cat, max_results=10, task_id=tk or task_id)
            search_plan.append({"category": cat, "query": q, "ok": s["ok"],
                                "n": len(s["results"])})
            for r in s["results"]:
                pool.setdefault(r["url"], r)


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
        s = scrape(r["url"], max_chars=max_chars_per_page, task_id=tk or task_id)
        pages.append({"url": r["url"], "title": r["title"], "domain": r["domain"],
                      "tier": r["tier"], "ok": s.get("ok", False),
                      "text": s.get("text", "")[:max_chars_per_page]})
        if sum(1 for p in pages if p["ok"]) >= max_pages:
            break

    facts = _extract_facts(question, pages)
    out = {
        "question": question,
        "categories": cats,
        "searches": search_plan,
        "pages_fetched": [p for p in pages if p["ok"]],
        "sources": sorted({p["url"] for p in pages if p["ok"]}),
        "findings": facts,
        "unverified": [f for f in facts if not f["source_urls"]],
        "note": "facts carry source_urls; anything in unverified has no source — treat as unconfirmed",
    }
    return _with_task(out, task_id)


def _pick_categories(question: str) -> list[str]:
    text = question.lower()
    cats = []
    for c in ("law", "osint", "dfir", "programming", "business", "markets"):
        keys = {"law": ("law", "legal", "statute", "court", "case", "regulation", "probation", "expung", "foia"),
                "osint": ("osint", "whois", "domain", "breach", "email", "phone"),
                "dfir": ("cve", "vulnerab", "security", "exploit", "malware", "patch"),
                "programming": ("python", "code", "api", "library", "framework", "programming", "bug"),
                "business": ("market", "revenue", "econom", "finance", "company", "industry"),
                "markets": ("trading", "stock", "swing", "bitcoin", "crypto", "commod", "forecast", "halving", "etf", "market")}[c]
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