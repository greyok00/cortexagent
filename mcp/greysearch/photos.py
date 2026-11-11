"""photos.py: Greysearch image lane (LLM-free, keyword-driven).

SearXNG image lane -> Wikimedia Commons -> Openverse, with
license-provenance metadata on every hit and an anti-tarpit 5s+ pace
toward our OWN instance. Course-family processors intentionally not
ported; this module serves the portal and the site builder: keyword
queries in, real relevant images + provenance out.
"""

"""Real-photo insertion for course modules and guides.

Guides and modules carry relevant real images plus other visual aids
(charts, tables, graphs). Sources are keyless: Wikimedia Commons search
first, Openverse as fallback. Images stay topical: every photo query is
built from the module/guide's own title and lesson words. Nothing is
invented; where a query returns nothing relevant the module is skipped
and counted.

The builder's own pipeline (site_render.download_images) then downloads the
inserted URLs into site assets, so pages end up self-contained. Alt text is
carried from the source's own description when available (>=3 words to pass
the semantic image gate; junk words avoided on purpose).

Idempotent: a module already carrying an "*Image:" provenance line is not
touched again.
"""

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0"
COMMONS = "https://commons.wikimedia.org/w/api.php"
OPENVERSE = "https://api.openverse.org/v1/images/"

_STOP = set("""a an and are as at be by been being can could do did does
done for from how in into is it its may might must of on or shall should
that the this to use used using what when which while who why will with
would you your""".split())

_CACHE: dict[str, dict[str, Any]] = {}
_REPO_ROOT = Path(__file__).resolve().parent
_CACHE_PATH = Path(os.path.expanduser("~/.cache/greysearch/photo-query-cache.json"))
_CACHE_LOCK = threading.Lock()

def _load_cache() -> None:
    if not _CACHE and _CACHE_PATH.exists():
        try:
            _CACHE.update(json.loads(_CACHE_PATH.read_text()))
        except Exception:
            pass

def _save_cache() -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(_CACHE))
    except Exception:
        pass

MONTHS = {"january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"}
_FILLER = {"master", "guide", "best", "top", "new", "complete", "ultimate",
           "overview", "introduction", "practical", "review", "summary",
           "released", "release", "launch", "launched", "roundup", "versus"}

def keywords(text: str, n: int = 4) -> str:
    """Title/query keyword extraction rules:

    - hyphenated compounds stay whole ("open-weight" is one keyword);
    - a month+year pair ("October 2026") is KEPT as one date unit and moved
      to the FRONT of the query;
    - filler heads (master/guide/best/top/...) dropped;
    - when over budget, the DATE + the last (most specific) tail words win.
    "Best Open-Weight Reasoning LLM released by October 2026" (n=4)
      -> "october 2026 open-weight reasoning llm"  (1 date unit + 3 words)."""
    words = [w.strip("-") for w in
             re.sub(r"[^a-z0-9 -]", " ", (text or "").lower()).split()]
    words = [w for w in words if w and w not in _STOP and len(w) > 2]
    date_units, tail, skip = [], [], set()
    for i, w in enumerate(words):
        if i in skip:
            continue
        if w in MONTHS and i + 1 < len(words) and words[i + 1].isdigit():
            key = f"{w} {words[i + 1]}"
            if key not in date_units:
                date_units.append(key)
            skip.update((i, i + 1))
            continue
        if w not in _FILLER and not w.isdigit():
            tail.append(w)
    tail = list(dict.fromkeys(tail))
    if len(tail) > n - len(date_units):
        keep = n - len(date_units)
        tail = tail[-keep:] if keep > 0 else []
    units = date_units + tail
    return " ".join(units[: max(n, 1)])

def _norm_img_url(url: str) -> str:
    """Fix malformed media URLs from upstream APIs: a doubled slash in the
    path (e.g. .../iiif/2//4006...) gets HTTP 403 from strict servers, which
    silently turned guide images into remote-only links."""
    u = url or ""
    if "://" not in u:
        return u
    scheme, host, path = u.split("://", 1)[0], u.split("://", 1)[1], ""
    if "/" in host:
        host, path = host.split("/", 1)
        path = "/" + re.sub(r"/{2,}", "/", path.lstrip("/"))
    return f"{scheme}://{host}{path}"

def _http_json(url: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None

def commons_search(q: str) -> dict[str, Any] | None:
    """Commons file search. First pass on file titles (intitle:, far more
    topical than full-text), second pass full-text; imageinfo needs explicit
    iiprop to return url/mime/size, and extmetadata carries license/artist."""
    for gsr in (f"intitle:{q}", f"filetype:bitmap {q}"):
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "imageinfo",
            "generator": "search", "gsrsearch": f"filetype:bitmap {gsr}",
            "gsrnamespace": 6, "gsrlimit": 8, "iiurlwidth": 1024,
            "iiprop": "url|mime|size|extmetadata"})
        data = _http_json(f"{COMMONS}?{params}")
        if not data:
            continue
        pages = (data.get("query") or {}).get("pages") or {}
        for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            info = (p.get("imageinfo") or [{}])[0]
            mime, w = info.get("mime", ""), info.get("width") or 0
            title = p.get("title", "").replace("File:", "").rsplit(".", 1)[0]
            if mime in ("image/jpeg", "image/png") and (w or 0) >= 600:
                if re.search(r"(?i)logo|icon|coat of arms|flag of|map of\b", title):
                    continue
                meta = info.get("extmetadata") or {}
                lic = (meta.get("LicenseShortName") or {}).get("value", "")
                artist = re.sub(r"<[^>]+>", "",
                                (meta.get("Artist") or {}).get("value", ""))[:60]
                return {"url": _norm_img_url(info.get("thumburl") or info.get("url") or ""),
                        "title": title,
                        "creator": artist or (info.get("user") or "Wikimedia Commons"),
                        "license": f"{lic or 'CC'} via Wikimedia Commons",
                        "width": w}
    return None

def openverse_search(q: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode({"q": q, "page_size": 12})
    data = _http_json(f"{OPENVERSE}?{params}")
    if not data:
        return None
    qt = set(re.sub(r"[^a-z ]", " ", q.lower()).split())
    for r in data.get("results") or []:
        title = (r.get("title") or "").lower()
        if not qt & set(re.sub(r"[^a-z ]", " ", title).split()):
            continue
        if (r.get("width") or 0) >= 600 and r.get("url") and r.get("extension", "jpg").lower() in ("jpg", "jpeg", "png"):
            return {"url": _norm_img_url(r["url"]),
                    "title": re.sub(r"\s+", " ", (r.get("title") or q))[:80],
                    "creator": (r.get("creator") or r.get("source") or "")[:60],
                    "license": f"{(r.get('license') or '').upper()} via Openverse",
                    "width": r.get("width")}
    return None

SEARX = "http://127.0.0.1:8888"
_JUNK_IMG = re.compile(
    r"(?i)repository-images\.githubusercontent|badge|logo|avatar|icon|svg\b"
    r"|\.svg($|\?)|favicon|sprite|placeholder")

def searx_image_hits(q: str, limit: int = 20,
                     engines: list[str] | None = None) -> list[dict[str, Any]]:
    """Keyword -> real-image search through the LOCAL SearXNG images lane
    (duckduckgo/bing/openverse image engines): search by keyword, download
    real relevant images. Falls back silently on any failure.

    engines: optional user selection joined ADDITIVELY into the
    images request's engines= param; empty/None keeps the request
    byte-for-byte as before."""
    _hit_params: dict[str, Any] = {"q": q, "categories": "images",
                                   "format": "json"}
    if engines:
        _hit_params["engines"] = ",".join(dict.fromkeys(
            str(x).strip().lower() for x in engines if str(x).strip()))
    params = urllib.parse.urlencode(_hit_params)
    try:
        req = urllib.request.Request(f"{SEARX}/search?{params}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out, seen = [], set()
    for r in data.get("results") or []:
        src = r.get("img_src") or ""
        title = re.sub(r"\s+", " ", (r.get("title") or "")).strip()
        if not src or src in seen:
            continue
        seen.add(src)
        if _JUNK_IMG.search(src) or _JUNK_IMG.search(title):
            continue
        path = src.split("?")[0].split("#")[0].split(".")
        if path[-1].lower() not in ("jpg", "jpeg", "png", "webp"):
            continue
        if not _img_topical(title, q):
            continue
        out.append({"url": _norm_img_url(src), "title": title[:80],
                    "creator": r.get("source", "SearXNG image lane"),
                    "license": f"web image via {', '.join(r.get('engines') or ['image search'])}",
                    "width": 0})
        if len(out) >= limit:
            break
    return out

def photo_pool(queries: list[str], per_query: int = 12,
               engines: list[str] | None = None) -> list[dict[str, Any]]:
    """Union of image-lane hits across keyword ladder, deduped by URL."""
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in queries:
        if not q:
            continue
        for hit in searx_image_hits(q, per_query, engines=engines):
            if hit["url"] not in seen:
                seen.add(hit["url"])
                pool.append(hit)
    return pool


_PERSON_STOCK_RE = re.compile(
    r"(?i)\b(?:wom[ae]n|girls?|ladies?|man|men|boys?|executives?"
    r"|business(?:woman|man|person|people|team|meeting)|models?|portrait"
    r"|selfie|beautiful|beauty|smiling|handsome|shaking\s+hands"
    r"|offering\s+handshake)\b")
_NON_LATIN_SCRIPT_RE = re.compile(
    "[\u0370-\u03ff\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff"
    "\u0900-\u097f\u0e00-\u0e7f\u3040-\u30ff\u31f0-\u31ff"
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af"
    "\u1100-\u11ff\u3130-\u318f\uff00-\uffef]")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27bf\u2b00-\u2bff\ufe00-\ufe0f]")

def _content_tokens(text: str) -> set:
    """Content tokens: lowered alphanumeric words, >=3 chars, no stopwords."""
    return {t for t in re.sub(r"[^a-z0-9 -]", " ", (text or "").lower()).split()
            if len(t) > 2 and t not in _STOP}

def _img_topical(title: str, q: str) -> bool:
    """Full candidate gate for one image title against a query.

    - >= 2 DISTINCT content tokens shared with the query (or the query's one
      content token when it is a single-token topic; sparse topics keep
      their lane);
    - person/stock-photo markers (woman/lady/executive/model/portrait/...)
      reject the candidate UNLESS the query itself is about people/stock
      imagery;
    - non-Latin script in the title for a pure-ASCII query rejects;
    - emoji/pictograph icons in the title reject (icon, not illustration).
    Empty-token queries (e.g. fully non-ASCII) skip the floor only.
    """
    title_l = title or ""
    q_content, t_content = _content_tokens(q), _content_tokens(title_l)
    shared = q_content & t_content
    if len(q_content) > 1 and len(shared) < 2:
        return False
    if len(q_content) == 1 and not shared:
        return False
    if _EMOJI_RE.search(title_l):
        return False
    if _PERSON_STOCK_RE.search(title_l) and not _PERSON_STOCK_RE.search(q or ""):
        return False
    if (q or "").isascii() and _NON_LATIN_SCRIPT_RE.search(title_l):
        return False
    return True

def _topical_hit(hit, q: str) -> bool:
    """A stored/fresh hit must be TOPICAL for the query. Without this
    recheck, a cached art-museum image could pass as a valid hit, and a
    bare word like "handshake" alone would pass a person stock photo.
    Delegates to the shared `_img_topical` gate (distinct-token floor +
    person-stock/script/emoji guards) after the URL guard."""
    if not hit or not hit.get("url"):
        return False
    return _img_topical(hit.get("title") or "", q)

def find_photo(q: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        _load_cache()
        if q in _CACHE:
            hit = _CACHE[q]
            return hit if _topical_hit(hit, q) else None
    hit = commons_search(q) or openverse_search(q)
    if hit and not hit.get("url"):
        hit = None
    if hit and not _img_topical(hit.get("title") or "", q):
        hit = None
    if hit:
        with _CACHE_LOCK:
            _CACHE[q] = hit
            _save_cache()
    return hit

def insert_photo(md: str, photo: dict[str, str], what: str) -> str:
    """Insert ![alt](url) + provenance line after the first body paragraph."""
    alt = re.sub(r"\s+", " ", f'{what}: {photo["title"]}').strip()
    alt = re.sub(r"(?i)\b(logo|icon|avatar|thumbnail|banner|placeholder|"
                 r"stock photo|stock image|hero image)\b", "figure", alt)
    if len(alt.split()) < 3:
        alt = f"{what} illustration {alt}"
    block = (f"\n\n![{alt}]({photo['url']})\n\n"
             f"*Image: {photo['title']} ({photo['creator']}, "
             f"{photo['license']}).*\n")
    lines = md.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip()
                              or lines[i].lstrip().startswith(("#", "```", "![", "*Image:"))):
        i += 1
    j = i
    while j + 1 < len(lines) and lines[j + 1].strip() and not lines[j + 1].lstrip().startswith(("#", "```", "![", "*Image:")):
        j += 1
    return "\n".join(lines[: j + 1]) + block + "\n" + "\n".join(lines[j + 1:])

def keyword_ladder(text: str) -> list[str]:
    """Ladder shape: the FULL specific phrase FIRST, and the ladder
    NEVER narrows below 3 words, because specific queries are the point;
    broader entries are only fallbacks. A phrase of <=3 words is a
    single-entry ladder. "dns tunneling detection techniques" ->
    ["dns tunneling detection techniques", "dns tunneling detection"]."""
    toks = [t for t in re.sub(r"[^a-z0-9 -]", " ", (text or "").lower()).split()
            if t not in _STOP and len(t) > 2 and not t.isdigit()]
    uniq = list(dict.fromkeys(toks))
    if not uniq:
        return []
    out = [" ".join(uniq)]
    words = list(uniq)
    while len(words) > 3:
        words = words[:-1]
        q = " ".join(words)
        if q and q not in out:
            out.append(q)
    return out

def commons_pool(q: str, limit: int = 8) -> list[dict[str, Any]]:
    """Topical Commons bitmap pool. Pass 1 is an exact intitle:"phrase"
    search (topical by construction), pass 2 is full-text under the strict
    shared-words gate below."""
    out: list[dict[str, Any]] = []
    if len(q.split()) >= 2:
        phrase = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "imageinfo",
            "generator": "search",
            "gsrsearch": 'filetype:bitmap intitle:"' + q + '"',
            "gsrnamespace": 6, "gsrlimit": limit, "iiurlwidth": 1024,
            "iiprop": "url|mime|size|extmetadata"})
        data = _http_json(f"{COMMONS}?{phrase}")
        pages = ((data or {}).get("query") or {}).get("pages") or {}
        for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            info = (p.get("imageinfo") or [{}])[0]
            mime, w = info.get("mime", ""), info.get("width") or 0
            title = p.get("title", "").replace("File:", "").rsplit(".", 1)[0]
            if mime not in ("image/jpeg", "image/png") or (w or 0) < 600:
                continue
            if re.search(r"(?i)logo|icon|coat of arms|flag of|map of\b", title):
                continue
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            artist = re.sub(r"<[^>]+>", "",
                            (meta.get("Artist") or {}).get("value", ""))[:60]
            out.append({"url": info.get("thumburl") or info.get("url") or "",
                        "title": title, "creator": artist or "Wikimedia Commons",
                        "license": f"{lic or 'CC'} via Wikimedia Commons",
                        "width": w})
            if len(out) >= limit:
                break
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "imageinfo",
        "generator": "search", "gsrsearch": f"filetype:bitmap {q}",
        "gsrnamespace": 6, "gsrlimit": limit, "iiurlwidth": 1024,
        "iiprop": "url|mime|size|extmetadata"})
    data = _http_json(f"{COMMONS}?{params}")
    if not data:
        return out
    pages = (data.get("query") or {}).get("pages") or {}
    qt = set(re.sub(r"[^a-z ]", " ", q.lower()).split()) - _STOP
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        mime, w = info.get("mime", ""), info.get("width") or 0
        title = p.get("title", "").replace("File:", "").rsplit(".", 1)[0]
        if mime not in ("image/jpeg", "image/png") or (w or 0) < 600:
            continue
        if re.search(r"(?i)logo|icon|coat of arms|flag of|map of\b", title):
            continue
        meta = info.get("extmetadata") or {}
        tt = set(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()) - _STOP
        shared = qt & tt
        if len(qt) <= 1:
            if not (len(shared) == len(qt) and qt):
                continue
        elif len(shared) < 2:
            continue
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:60]
        out.append({"url": info.get("thumburl") or info.get("url") or "",
                    "title": title, "creator": artist or "Wikimedia Commons",
                    "license": f"{lic or 'CC'} via Wikimedia Commons",
                    "width": w})
        if len(out) >= limit:
            break
    return out

def openverse_pool(q: str, limit: int = 8) -> list[dict[str, Any]]:
    """All topical Openverse hits (same relevance gate as openverse_search)."""
    params = urllib.parse.urlencode({"q": q, "page_size": 20})
    data = _http_json(f"{OPENVERSE}?{params}")
    out: list[dict[str, Any]] = []
    if not data:
        return out
    qt = set(re.sub(r"[^a-z0-9 ]", " ", q.lower()).split()) - _STOP
    for r in data.get("results") or []:
        title = (r.get("title") or "").lower()
        shared = qt & set(re.sub(r"[^a-z0-9 ]", " ", title).split()) - _STOP
        if qt and (len(qt) <= 1 and not shared or len(qt) > 1 and len(shared) < 2):
            continue
        if (r.get("width") or 0) < 600 or not r.get("url"):
            continue
        if r.get("extension", "jpg").lower() not in ("jpg", "jpeg", "png"):
            continue
        out.append({"url": r["url"],
                    "title": re.sub(r"\s+", " ", (r.get("title") or q))[:80],
                    "creator": (r.get("creator") or r.get("source") or "")[:60],
                    "license": f"{(r.get('license') or '').upper()} via Openverse",
                    "width": r.get("width")})
        if len(out) >= limit:
            break
    return out

_POOL_CACHE: dict[str, list[dict[str, Any]]] = {}
_POOL_LOCK = threading.Lock()

def download_with_provenance(photo: dict, dest_dir: Path, stem: str = "img",
                             width_min: int = 600) -> dict | None:
    """Keyword -> relevant REAL image saved as a file. Saves
    <stem>.jpg|png|webp plus a sidecar .txt carrying
    title/creator/license provenance for attribution. Returns the dict with
    "file" set, or None on any failure. Resume reuse: an existing
    file + sidecar pair for this stem is returned as-is, since the imgcand
    dir is durable and a resumed run re-downloads only what is missing."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = photo.get("url") or ""
    if not url:
        return None
    ext = ".jpg"
    m = re.search(r"\.(jpe?g|png|webp)(?:$|\?)", url.lower())
    if m:
        ext = f".{m.group(1).replace('jpeg', 'jpg')}"
    dest = dest_dir / (stem + ext)
    for cand_ext in (".jpg", ".png", ".webp"):
        saved = dest_dir / (stem + cand_ext)
        side = saved.with_suffix(".txt")
        if not (saved.is_file() and side.is_file()):
            continue
        meta: Dict[str, str] = {}
        try:
            for line in side.read_text(encoding="utf-8",
                                       errors="replace").splitlines():
                if ":" in line:
                    _k, _v = line.split(":", 1)
                    meta[_k.strip().lower()] = _v.strip()
        except Exception:
            meta = {}
        out = dict(photo)
        out.update({
            "file": str(saved),
            "provenance": str(side),
            "title": meta.get("title") or photo.get("title") or "",
            "creator": meta.get("creator") or photo.get("creator") or "",
            "license": meta.get("license") or photo.get("license") or "",
            "url": meta.get("source") or photo.get("url") or "",
        })
        return out

    def _dl():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read(6 * 1024 * 1024)
    from concurrent.futures import ThreadPoolExecutor as _TPE
    try:
        with _TPE(max_workers=1) as _ex:
            data = _ex.submit(_dl).result(timeout=25.0)
        if not data or len(data) < 5000:
            return None
        dest.write_bytes(data)
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    side = dest.with_suffix(".txt")
    side.write_text(
        f"source: {url}\ntitle: {photo.get('title','')}\n"
        f"creator: {photo.get('creator','')}\n"
        f"license: {photo.get('license','')}\n")
    out = dict(photo)
    out["file"] = str(dest)
    out["provenance"] = str(side)
    return out

def guide_images(question: str, accepted_pages: list, per_page: int = 1,
                 dest_dir: Path | None = None,
                 engines: list[str] | None = None) -> list[dict]:
    """Portal/guide entry: 0-3 topical images for an accepted corpus.

    Deterministic: keyword ladder from the question + page titles -> pool
    via our own image lane + Commons/Openverse fallbacks -> dedupe ->
    download with provenance. Never calls a model; never blocks on failure
    (empty list = text-only guide, exactly like the anti-tarpit posture).

    engines: pass-through of the run's selected images-lane
    engines to the pool's image search; None keeps the lane as before.

    TOPIC floor: every candidate must ALSO share
    a word with the ORIGINAL research question, not just the page title.
    A page titled "Cybersecurity Atlas" once seeded 'atlas' queries that
    returned art-museum hits sharing only that one junk token. Topical
    means grounded in the research itself.
    """
    out: list[dict] = []
    queries = keyword_ladder(question or "")
    for p in (accepted_pages or [])[:3]:
        t = (p.get("clean") or {}).get("title") or p.get("title") or ""
        if t:
            queries.insert(0, keywords(t, 3))
    seen: set[str] = set()
    n_added = 0
    cap = max(per_page, 1) * 3
    for q in queries[:8]:
        if n_added >= cap:
            break
        for cand in ([find_photo(q)] if find_photo(q) else []) + \
                photo_pool([q], per_query=6, engines=engines):
            u = cand.get("url", "")
            if not u or u in seen:
                continue
            if not _img_topical(cand.get("title") or "", question or ""):
                continue
            seen.add(u)
            stem = re.sub(r"[^a-z0-9]+", "-",
                          (q + "-" + str(n_added)).lower())[:48] or f"img{n_added}"
            dl = download_with_provenance(
                cand, dest_dir or _REPO_ROOT / "assets" / "photo-cache", stem)
            if dl:
                out.append(dl)
                n_added += 1
                if n_added >= cap:
                    break
            time.sleep(0.5)
    return out
