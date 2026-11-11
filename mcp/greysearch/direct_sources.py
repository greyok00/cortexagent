#!/usr/bin/env python3
"""direct_sources.py: tier C of the source coverage ladder.

Tier A is the engine ladder (searxng_integrated: the local SearXNG roster,
the public instance pool, the paced google/bing browser rungs); tier B is
the keyless structured-API rungs (searx_fallback: ddg-html, wikipedia API,
github API, archive-org); tier D is the wayback rescue. THIS module is
tier C, the direct tier: generic keyless readers a run's named-site
catalog drives. Nothing here holds a key and nothing here ever rides the
search proxy.

Three readers over one transport. rss_atom() parses RSS 2.0 and Atom with
the stdlib ElementTree (namespace-agnostic local-name matching, a summary
slice, no new dependency). sitemap_walk() parses sitemap.xml and one
level of sitemap index files into capped URL rows. forum_json() reads the
Discourse .json pattern (latest.json, plus forum_topic_json() for one
topic page) into the same normalized row shape. The single transport is
site_fetch(): a plain GET with a constant UA, a per-domain politeness
timestamp dict (3 s spacing) and an opener built over ProxyHandler({}),
so a direct read can never pick up a proxy from the process env.

Two contracts on top: discover(base) tries the bounded common feed paths
(/feed, /rss, /atom.xml, /sitemap.xml, /feed.xml) in order, stays on the
first hit and records every path it tried; read_catalog(catalog) walks a
run's named-site catalog entries ({site, kind: rss|sitemap|forum|page,
url optional}) against the readers, shapes the rows the way pool rows
look with the tier attribution (tier "direct-catalog", engine name = the
site's host), and records the digest lines "direct catalog: <site> <kind>
+N" (+0 with a short reason on failure). Nothing in the tier raises: a
failed read is an honest +0 record, and the caller's deadline stops the
walk. load_catalog_env() reads GREYSEARCH_SITE_CATALOG, the optional env
path to the catalog JSON. coverage_manifest() returns the machine-
readable manifest of everything the ladder can reach (tiers A through D,
the instance pool source, the catalog contract) for consumers and
digests.

Env knobs, read at call time, junk or negative values fall back to the
named default: GREYSEARCH_DIRECT_POLITENESS_S (3.0 s per-domain
spacing), GREYSEARCH_DIRECT_TIMEOUT_S (12.0 s per GET),
GREYSEARCH_DIRECT_MAX_BYTES (262144 B body cap),
GREYSEARCH_DIRECT_ROWS_MAX (40 rows per entry), GREYSEARCH_SITEMAP_MAX
(500 sitemap entries), GREYSEARCH_CATALOG_MAX (12 catalog entries per
lane run) and GREYSEARCH_SITE_CATALOG (the catalog path). Tests inject
the fetch and the clock; the suite never touches the network and never
opens a browser.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional
from xml.etree import ElementTree

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) greysearch-direct/1.0 "
              "(direct catalog tier; polite)")
FEED_PATHS = ("/feed", "/rss", "/atom.xml", "/sitemap.xml", "/feed.xml")
CATALOG_KINDS = ("rss", "sitemap", "forum", "page")
CATALOG_TIER = "direct-catalog"
CATALOG_ENV = "GREYSEARCH_SITE_CATALOG"
SUMMARY_SLICE = 300
TITLE_SLICE = 200

POLITENESS_DEFAULT_S = 3.0
TIMEOUT_DEFAULT_S = 12.0
MAX_BYTES_DEFAULT = 262144
ROWS_MAX_DEFAULT = 40
SITEMAP_MAX_DEFAULT = 500
CATALOG_MAX_DEFAULT = 12
SEARX_INSTANCES_JSON = "https://searx.space/data/instances.json"

_POLITENESS_LOCK = threading.Lock()
_LAST_SEEN: Dict[str, float] = {}
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TOPIC_PATH_RE = re.compile(r"/t/[^/]+/\d+(?:/.*)?$")


def _env_float(name: str, default: float) -> float:
    try:
        v = float(str(os.environ.get(name, "") or default).strip() or default)
    except (TypeError, ValueError):
        v = float(default)
    return v if v >= 0 else float(default)


def _env_int(name: str, default: int) -> int:
    try:
        v = int(str(os.environ.get(name, "") or default).strip() or default)
    except (TypeError, ValueError):
        v = int(default)
    return v if v > 0 else int(default)


def politeness_s() -> float:
    return _env_float("GREYSEARCH_DIRECT_POLITENESS_S", POLITENESS_DEFAULT_S)


def fetch_timeout_s() -> float:
    return _env_float("GREYSEARCH_DIRECT_TIMEOUT_S", TIMEOUT_DEFAULT_S)


def body_bytes_cap() -> int:
    return _env_int("GREYSEARCH_DIRECT_MAX_BYTES", MAX_BYTES_DEFAULT)


def rows_cap() -> int:
    return _env_int("GREYSEARCH_DIRECT_ROWS_MAX", ROWS_MAX_DEFAULT)


def sitemap_cap() -> int:
    return _env_int("GREYSEARCH_SITEMAP_MAX", SITEMAP_MAX_DEFAULT)


def catalog_entry_cap() -> int:
    return _env_int("GREYSEARCH_CATALOG_MAX", CATALOG_MAX_DEFAULT)


def _direct_opener() -> urllib.request.OpenerDirector:
    """The tier's ONLY opener: an OpenerDirector built over an EMPTY
    ProxyHandler, so a direct read never picks up a proxy from the process
    env (an empty proxies dict binds no proxy_open methods, so no Proxy
    Handler even rides the chain; proxying is only ever ProxyHandler's
    job). The tier's readers route every fetch through site_fetch, which
    routes through this opener; the search proxy serves search requests
    only and this tier is direct by definition."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _direct_open(url: str, timeout: float):
    return _direct_opener().open(
        urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}),
        timeout=timeout)


def politeness_at() -> Dict[str, float]:
    """Read-only copy of the per-domain last-hit timestamps."""
    with _POLITENESS_LOCK:
        return dict(_LAST_SEEN)


def politeness_reset() -> None:
    """Empty the per-domain politeness state (tests, lane resets)."""
    with _POLITENESS_LOCK:
        _LAST_SEEN.clear()


def domain_of(url: Any) -> str:
    try:
        return urllib.parse.urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""


def site_fetch(url: str,
               *,
               timeout: float = 0.0,
               max_bytes: int = 0,
               open_call: Optional[Callable[[str, float], Any]] = None,
               sleeper: Optional[Callable[[float], Any]] = None,
               clock: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """One plain direct GET: the tier's ONLY transport, and the choke point
    every direct reader routes through unless the caller injects its own
    fetch. Never proxied (empty ProxyHandler opener); one constant UA;
    spaced behind the domain's last hit in this process by the
    politeness_s() gap. Timeout, body cap, sleeper and clock are
    injectable for offline tests. Never raises; a failed GET is an honest
    record ({ok: False, error}); the body is decoded utf-8 with replace and
    capped so a huge page never runs the lane past its budget."""
    opener = open_call or _direct_open
    sleep = sleeper if sleeper is not None else time.sleep
    clock2 = clock if clock is not None else time.time
    want_timeout = float(timeout) if timeout and float(timeout) > 0 \
        else fetch_timeout_s()
    cap = int(max_bytes) if max_bytes and int(max_bytes) > 0 else body_bytes_cap()
    dom = domain_of(url)
    waited = 0.0
    pol = politeness_s()
    if dom and pol > 0:
        with _POLITENESS_LOCK:
            last = _LAST_SEEN.get(dom, 0.0)
            now = clock2()
            gap = last + pol - now
            if gap > 0:
                waited = gap
                sleep(gap)
            _LAST_SEEN[dom] = clock2()
    status = 0
    body = ""
    error = ""
    capped = False
    try:
        resp = opener(url, want_timeout)
        try:
            status = int(getattr(resp, "status", 0) or 0)
        except Exception:
            status = 0
        raw = resp.read(cap + 1) if cap > 0 else resp.read()
        try:
            resp.close()
        except Exception:
            pass
        if cap > 0 and len(raw) > cap:
            capped = True
            raw = raw[:cap]
        body = raw.decode("utf-8", "replace")
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:120]}"
    return {"ok": bool(status == 200 and not error),
            "status": status, "body": body, "url": str(url or ""),
            "domain": dom, "error": error, "waited_s": round(waited, 2),
            "capped": capped}


def _local(tag: Any) -> str:
    t = str(tag or "")
    return t.rsplit("}", 1)[-1].rsplit(":", 1)[-1].strip()


def _text(el: Any) -> str:
    if el is None:
        return ""
    try:
        return "".join(el.itertext()).strip()
    except Exception:
        return ""


def _strip_html(s: Any) -> str:
    if not s:
        return ""
    t = _TAG_RE.sub(" ", str(s))
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _slice(s: Any, n: int) -> str:
    return str(s or "")[:max(0, int(n))]


def _parse_bytes(body: Any) -> ElementTree.Element:
    return ElementTree.fromstring(str(body or "").encode("utf-8", "replace"))


def _readers_fetch(fetch: Optional[Any]) -> Callable[..., Dict[str, Any]]:
    return fetch if fetch is not None else site_fetch


def rss_atom(url: str,
             *,
             fetch: Optional[Any] = None,
             summary_slice: int = SUMMARY_SLICE) -> Dict[str, Any]:
    """RSS 2.0 and Atom via the stdlib ElementTree, namespace-agnostic by
    local tag name: rss/channel/item and feed/entry, link of the item or
    the entry's alternate (or first) link, description or the content
    module's encoded payload for RSS, summary or content for Atom. Rows
    carry {title, url, summary} with the summary sliced; capped by
    rows_cap(). Parse failures and non-feed XML are honest records, never
    raises."""
    f = _readers_fetch(fetch)
    fr = f(url, timeout=fetch_timeout_s())
    if not fr.get("ok"):
        return {"ok": False, "kind": "", "url": str(url), "rows": [],
                "error": str(fr.get("error") or f"http {fr.get('status')}")}
    try:
        root = _parse_bytes(fr.get("body"))
    except Exception as e:
        return {"ok": False, "kind": "", "url": str(url), "rows": [],
                "error": f"parse failed: {type(e).__name__}"}
    root_name = _local(root.tag)
    rows: List[Dict[str, Any]] = []
    want = rows_cap()
    if root_name == "rss":
        kind = "rss"
        channel = root
        for child in list(root):
            if _local(child.tag) == "channel":
                channel = child
                break
        for item in list(channel):
            if len(rows) >= want:
                break
            if _local(item.tag) != "item":
                continue
            fields = {_local(c.tag): c for c in list(item)}
            rows.append({
                "title": _slice(_text(fields.get("title")), TITLE_SLICE),
                "url": _text(fields.get("link")).strip(),
                "summary": _slice(
                    _strip_html(_text(fields.get("description"))
                                or _text(fields.get("encoded"))),
                    summary_slice)})
    elif root_name == "feed":
        kind = "atom"
        for entry_el in list(root):
            if len(rows) >= want:
                break
            if _local(entry_el.tag) != "entry":
                continue
            title = ""
            link_alt = ""
            link_any = ""
            summary = ""
            for child in list(entry_el):
                name = _local(child.tag)
                if name == "title" and not title:
                    title = _text(child)
                elif name == "link":
                    href = str(child.get("href") or "").strip()
                    rel = str(child.get("rel") or "").strip()
                    if not href:
                        continue
                    if not link_any:
                        link_any = href
                    if rel in ("", "alternate") and not link_alt:
                        link_alt = href
                elif name in ("summary", "content") and not summary:
                    summary = _text(child)
            rows.append({
                "title": _slice(title, TITLE_SLICE),
                "url": link_alt or link_any,
                "summary": _slice(_strip_html(summary), summary_slice)})
    else:
        return {"ok": False, "kind": "", "url": str(url), "rows": [],
                "error": f"not a feed ({root_name or 'unknown'})"}
    rows = [r for r in rows if r.get("url") or r.get("title")]
    return {"ok": bool(rows), "kind": kind, "url": str(url), "rows": rows,
            "error": "" if rows else "no entries"}


def sitemap_walk(url: str,
                 *,
                 fetch: Optional[Any] = None,
                 cap: Optional[int] = None) -> Dict[str, Any]:
    """sitemap.xml or sitemap index, parsed via the stdlib ElementTree and
    capped: an index is followed exactly one level (a level-two index is
    recorded as skipped, never descended) and the gathered entry count
    stops at cap (sitemap_cap() unless overridden) with capped=True when
    the source kept more. Rows carry the same {title, url, summary} shape
    with empty text fields; failures and non-sitemap XML are honest
    records, never raises."""
    f = _readers_fetch(fetch)
    want = int(cap) if cap and int(cap) > 0 else sitemap_cap()
    fr = f(url, timeout=fetch_timeout_s())
    base = {"ok": False, "kind": "", "url": str(url), "urls": [],
            "rows": [], "capped": False}
    if not fr.get("ok"):
        base["error"] = str(fr.get("error") or f"http {fr.get('status')}")
        return base
    try:
        root = _parse_bytes(fr.get("body"))
    except Exception as e:
        base["error"] = f"parse failed: {type(e).__name__}"
        return base
    root_name = _local(root.tag)
    if root_name == "urlset":
        kind = "sitemap"
    elif root_name == "sitemapindex":
        kind = "sitemap-index"
    else:
        base["error"] = f"not a sitemap ({root_name or 'unknown'})"
        return base
    urls: List[str] = []
    capped = False
    skipped: List[str] = []

    def _loc(el: Any) -> str:
        for child in list(el):
            if _local(child.tag) == "loc":
                return _text(child)
        return ""

    if kind == "sitemap":
        for child in list(root):
            if _local(child.tag) != "url":
                continue
            if len(urls) >= want:
                capped = True
                break
            loc = _loc(child).strip()
            if loc:
                urls.append(loc)
    else:
        child_urls: List[str] = []
        for child in list(root):
            if _local(child.tag) != "sitemap":
                continue
            loc = _loc(child).strip()
            if loc:
                child_urls.append(loc)
        for sloc in child_urls:
            if len(urls) >= want:
                capped = True
                break
            sub = f(sloc, timeout=fetch_timeout_s())
            if not sub.get("ok"):
                skipped.append(sloc)
                continue
            try:
                sub_root = _parse_bytes(sub.get("body"))
            except Exception:
                skipped.append(sloc)
                continue
            if _local(sub_root.tag) != "urlset":
                skipped.append(sloc)
                continue
            for child in list(sub_root):
                if _local(child.tag) != "url":
                    continue
                if len(urls) >= want:
                    capped = True
                    break
                loc = _loc(child).strip()
                if loc:
                    urls.append(loc)
    rows = [{"title": "", "url": u, "summary": ""} for u in urls]
    return {"ok": bool(urls), "kind": kind, "url": str(url), "urls": urls,
            "rows": rows, "capped": bool(capped), "skipped": skipped,
            "error": "" if urls else "no entries"}


def _base_url(base: str) -> str:
    b = str(base or "").strip().rstrip("/")
    if b and "://" not in b:
        b = "https://" + b
    return b


def forum_json(base: str,
               *,
               fetch: Optional[Any] = None,
               cap: Optional[int] = None) -> Dict[str, Any]:
    """The Discourse .json pattern at a named forum base: latest.json read
    into normalized rows ({title, url, summary}), capped by rows_cap(). A
    base that already names an endpoint is honored: a path ending .json is
    read as given, a /t topic path gets .json appended, any other base
    gets /latest.json. Not a raised failure when the base is not a
    Discourse: the record says what came back."""
    f = _readers_fetch(fetch)
    b = _base_url(base)
    path = urllib.parse.urlparse(b).path or ""
    if path.endswith(".json"):
        url = b
    elif _TOPIC_PATH_RE.search(path):
        url = b + ".json"
    else:
        url = b + "/latest.json"
    fr = f(url, timeout=fetch_timeout_s())
    if not fr.get("ok"):
        return {"ok": False, "kind": "forum", "url": url, "rows": [],
                "error": str(fr.get("error") or f"http {fr.get('status')}")}
    try:
        data = json.loads(fr.get("body"))
    except Exception as e:
        return {"ok": False, "kind": "forum", "url": url, "rows": [],
                "error": f"parse failed: {type(e).__name__}"}
    return _forum_rows(b, url, data, cap)


def _forum_rows(b: str, url: str, data: Any,
                cap: Optional[int]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"ok": False, "kind": "forum", "url": url,
                "rows": [], "error": "unexpected forum json shape"}
    want = int(cap) if cap and int(cap) > 0 else rows_cap()
    topics = ((data.get("topic_list") or {}).get("topics")) or []
    rows: List[Dict[str, Any]] = []
    for t in topics:
        if len(rows) >= want:
            break
        if not isinstance(t, dict) or not t.get("id"):
            continue
        slug = str(t.get("slug") or "").strip() or "topic"
        rows.append({
            "title": _slice(str(t.get("title") or t.get("fancy_title") or ""),
                            TITLE_SLICE),
            "url": f"{b}/t/{slug}/{t.get('id')}",
            "summary": _slice(_strip_html(str(t.get("excerpt") or "")),
                              SUMMARY_SLICE)})
    return {"ok": bool(rows), "kind": "forum", "url": url, "rows": rows,
            "error": "" if rows else "no topics"}


def forum_topic_json(base: str,
                     topic_ref: Any,
                     *,
                     fetch: Optional[Any] = None,
                     cap: Optional[int] = None) -> Dict[str, Any]:
    """One Discourse topic page's .json (the topic pattern endpoint):
    normalized rows, one per post_stream post, each carrying the topic
    title, the post's own /t/<slug>/<id>[/<post_number>] URL and a blurb
    slice. Capped by rows_cap(); failures are honest records."""
    f = _readers_fetch(fetch)
    b = _base_url(base)
    tref = str(topic_ref or "").strip().strip("/")
    if not tref:
        return {"ok": False, "kind": "forum", "url": b, "rows": [],
                "error": "no topic ref"}
    path = urllib.parse.urlparse(tref).path or ""
    if path and path != tref:
        url = tref if path.endswith(".json") else tref + ".json"
    else:
        url = f"{b}/t/{tref}.json" if ".json" not in tref \
            else f"{b}/t/{tref}"
    fr = f(url, timeout=fetch_timeout_s())
    if not fr.get("ok"):
        return {"ok": False, "kind": "forum", "url": url, "rows": [],
                "error": str(fr.get("error") or f"http {fr.get('status')}")}
    try:
        data = json.loads(fr.get("body"))
    except Exception as e:
        return {"ok": False, "kind": "forum", "url": url, "rows": [],
                "error": f"parse failed: {type(e).__name__}"}
    if not isinstance(data, dict):
        return {"ok": False, "kind": "forum", "url": url, "rows": [],
                "error": "unexpected forum json shape"}
    want = int(cap) if cap and int(cap) > 0 else rows_cap()
    topic = data.get("topic") if isinstance(data.get("topic"), dict) else {}
    topic_id = str(topic.get("id") or "")
    slug = str(topic.get("slug") or "").strip() or "topic"
    title = _slice(str(topic.get("title") or data.get("title") or ""),
                   TITLE_SLICE)
    posts = ((data.get("post_stream") or {}).get("posts")) or []
    rows: List[Dict[str, Any]] = []
    for p in posts:
        if len(rows) >= want:
            break
        if not isinstance(p, dict):
            continue
        num = str(p.get("post_number") or "").strip()
        tail = f"/{num}" if num else ""
        if topic_id:
            u = f"{b}/t/{slug}/{topic_id}{tail}"
        else:
            u = tref if str(tref).startswith("http") else url
        rows.append({
            "title": _slice(str(p.get("title") or title), TITLE_SLICE),
            "url": u,
            "summary": _slice(
                _strip_html(str(p.get("blurb") or p.get("cooked") or "")),
                SUMMARY_SLICE)})
    return {"ok": bool(rows), "kind": "forum", "url": url, "rows": rows,
            "error": "" if rows else "no posts"}


def page_fetch(url: str,
               *,
               fetch: Optional[Any] = None) -> Dict[str, Any]:
    """The plain polite fetch of a named page: the site's own listing or
    search page, read direct, one row shaped {title, url, summary} from
    the page title and a stripped-tags body slice. The tier never parses
    search results out of foreign markup here; the row is the page's own
    honest evidence."""
    f = _readers_fetch(fetch)
    fr = f(url, timeout=fetch_timeout_s())
    if not fr.get("ok"):
        return {"ok": False, "kind": "page", "url": str(url), "rows": [],
                "error": str(fr.get("error") or f"http {fr.get('status')}")}
    m = _TITLE_RE.search(fr.get("body") or "")
    title = _strip_html(m.group(1)) if m else ""
    text = _strip_html(fr.get("body") or "")
    rows: List[Dict[str, Any]] = []
    if title or text:
        rows.append({"title": _slice(title, TITLE_SLICE), "url": str(url),
                     "summary": _slice(text, SUMMARY_SLICE)})
    return {"ok": bool(rows), "kind": "page", "url": str(url),
            "rows": rows, "error": "" if rows else "empty page"}


def discover(base: str,
             *,
             fetch: Optional[Any] = None) -> Dict[str, Any]:
    """Bounded feed-path discovery for one named site: the FEED_PATHS list
    is tried in order, every fetch keeps the tier's per-domain politeness,
    and the FIRST path that reads into entries wins (honest tried-records
    ride the result). The sitemap path asks the sitemap reader, the feed
    paths ask the feed reader; anything else is a miss named the same
    way."""
    f = _readers_fetch(fetch)
    b = _base_url(base)
    tried: List[Dict[str, Any]] = []
    for path in FEED_PATHS:
        url = b + path
        if path.startswith("/sitemap"):
            res = sitemap_walk(url, fetch=f)
        else:
            res = rss_atom(url, fetch=f)
        rows = list(res.get("rows") or [])
        tried.append({"url": url, "ok": bool(rows), "n": len(rows),
                      "kind": str(res.get("kind") or "")})
        if rows:
            return {"ok": True, "url": url, "kind": str(res.get("kind") or ""),
                    "rows": rows, "tried": tried, "error": ""}
    return {"ok": False, "url": "", "kind": "", "rows": [], "tried": tried,
            "error": "no feed path returned entries"}


def host_of(site: str) -> str:
    host = domain_of(_base_url(site))
    if host.startswith("www."):
        host = host[4:]
    return host


def _attributed(row: Dict[str, Any], host: str) -> Dict[str, Any]:
    url = str(row.get("url") or "")
    return {"title": _slice(row.get("title"), TITLE_SLICE),
            "url": url,
            "snippet": _slice(_strip_html(row.get("summary")),
                              SUMMARY_SLICE),
            "domain": domain_of(url) or host,
            "tier": CATALOG_TIER,
            "engine": host}


def _catalog_entry(entry: Dict[str, Any],
                   fetch: Optional[Any]) -> Dict[str, Any]:
    site = str(entry.get("site") or "").strip()
    kind = str(entry.get("kind") or "").strip().lower()
    url = str(entry.get("url") or "").strip()
    f = _readers_fetch(fetch)
    rows: List[Dict[str, Any]] = []
    if kind == "page":
        target = url or _base_url(site)
        fr = page_fetch(target, fetch=f)
        rows = list(fr.get("rows") or [])
        return {"rows": rows, "reason": "" if rows else
                str(fr.get("error") or "no entries")}
    if not url:
        disc = discover(site, fetch=f)
        url = str(disc.get("url") or "")
        rows = list(disc.get("rows") or [])
        if not url:
            return {"rows": [], "reason": str(disc.get("error")
                                              or "no feed path")}
    if kind == "rss":
        fr = rss_atom(url, fetch=f)
    elif kind == "sitemap":
        fr = sitemap_walk(url, fetch=f)
    else:
        fr = forum_json(url, fetch=f)
    rows = list(fr.get("rows") or [])
    return {"rows": rows,
            "reason": "" if rows else str(fr.get("error") or "no entries")}


def read_catalog(catalog: Any,
                 *,
                 fetch: Optional[Any] = None,
                 deadline_ts: Optional[float] = None,
                 entry_cap: Optional[int] = None,
                 sleeper: Optional[Callable[[float], Any]] = None,
                 clock: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """Walk a run's named-site catalog against the tier C readers and
    return {ok, rows, lines, skipped, entries_tried, entries_ok}. Each
    entry is {site, kind: rss|sitemap|forum|page, url optional}; a URL is
    read directly with that kind's reader, a site without one goes through
    discover() and the first winning feed path. Rows come back with the
    tier attribution (tier "direct-catalog", engine name = the site's
    host, domain = the row's own host), deduped inside the lane, and the
    per-entry digest lines use the fixed shape "direct catalog: <site>
    <kind> +N" (+0 with a short reason when an entry read empty or
    failed). The caller's deadline_ts stops the walk between entries
    (budget reached, the entries left unattempted are recorded); nothing
    in here raises, so a lane failure can never take a run down."""
    rows: List[Dict[str, Any]] = []
    lines: List[str] = []
    skipped: List[Dict[str, Any]] = []
    seen: set = set()
    want = int(entry_cap) if entry_cap and int(entry_cap) > 0 \
        else catalog_entry_cap()
    clock2 = clock if clock is not None else time.time
    tried = 0
    ok_entries = 0
    entries = [c for c in list(catalog or []) if isinstance(c, dict)]
    for entry in entries[:want]:
        site = str(entry.get("site") or "").strip()
        kind = str(entry.get("kind") or "").strip().lower()
        host = host_of(site) if site else ""
        label = host or site or "?"
        if deadline_ts is not None and clock2() >= float(deadline_ts):
            lines.append(f"direct catalog: {label} {kind or '?'} "
                         "+0 (budget reached)")
            skipped.append({"site": label, "kind": kind,
                            "reason": "budget reached"})
            break
        if kind not in CATALOG_KINDS:
            lines.append(f"direct catalog: {label} {kind or '?'} "
                         "+0 (unknown kind)")
            skipped.append({"site": label, "kind": kind,
                            "reason": "unknown kind"})
            continue
        if not site:
            lines.append(f"direct catalog: ? {kind} +0 (no site)")
            skipped.append({"site": "?", "kind": kind,
                            "reason": "no site given"})
            continue
        try:
            got = _catalog_entry(entry, fetch)
        except Exception as e:
            got = {"rows": [], "reason": f"{type(e).__name__}: "
                                         f"{str(e)[:60]}"}
        reason = str(got.get("reason") or "")
        tried += 1
        if reason:
            short = re.sub(r"\s+", " ", reason)[:80].strip()
            lines.append(f"direct catalog: {label} {kind} +0 ({short})")
            skipped.append({"site": label, "kind": kind, "reason": short})
            continue
        added = 0
        for r in got.get("rows") or []:
            if not isinstance(r, dict):
                continue
            u = str(r.get("url") or "")
            if not u or u in seen:
                continue
            seen.add(u)
            rows.append(_attributed(r, host or domain_of(u)))
            added += 1
        if added:
            lines.append(f"direct catalog: {label} {kind} +{added}")
            ok_entries += 1
        else:
            lines.append(f"direct catalog: {label} {kind} "
                         "+0 (no new urls)")
            skipped.append({"site": label, "kind": kind,
                            "reason": "no new urls"})
    if len(entries) > want:
        lines.append(f"direct catalog: lane cap {want} reached "
                     f"({len(entries) - want} entries unattempted)")
        skipped.append({"reason": f"catalog cap {want} reached",
                        "unattempted": len(entries) - want})
    return {"ok": bool(rows), "rows": rows, "lines": lines,
            "skipped": skipped, "entries_tried": tried,
            "entries_ok": ok_entries}


def load_catalog_env(env: str = CATALOG_ENV) -> List[Dict[str, Any]]:
    """The run's catalog file when it rides the env instead of the call:
    GREYSEARCH_SITE_CATALOG names a path to a JSON file holding either a
    bare list of {site, kind, url} entries or {"catalog": [...]}. Absent
    or unreadable path or the wrong shape means NO catalog (an empty
    list), never an error; the call-side site_catalog of research_deep
    wins and this is only ever consulted when no catalog came with the
    call."""
    path = str(os.environ.get(env, "") or "").strip()
    if not path:
        return []
    try:
        with open(os.path.expanduser(path), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("catalog"), list):
        return [c for c in data["catalog"] if isinstance(c, dict)]
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    return []


def coverage_manifest() -> Dict[str, Any]:
    """The machine-readable manifest of everything the ladder can reach:
    tiers A through D with what each tier's own modules read, the
    instance pool source (the searx.space registry data file first, the
    static harvest and the html scrape as its fallbacks), and the
    catalog contract. Consumers and digests read this instead of
    hand-writing tier lists."""
    registry_url = SEARX_INSTANCES_JSON
    static_trio: List[str] = []
    try:
        import searxng_integrated as _si
        registry_url = str(getattr(_si, "SEARX_SPACE_DATA_URL",
                                   SEARX_INSTANCES_JSON))
        static_trio = [str(u) for u in
                       tuple(getattr(_si, "_OWNER_INSTANCES", ()) or ())]
    except Exception:
        static_trio = []
    return {
        "engine": "greysearch",
        "tiers": {
            "A": {"name": "search engines",
                  "reach": ["searxng local roster (full engine set)",
                            "public searxng instances (paced rotation)",
                            "google browser rung (paced)",
                            "bing browser rung (paced)"]},
            "B": {"name": "keyless structured apis",
                  "reach": ["ddg-html (captcha-prone fallback)",
                            "wikipedia-api", "github-api", "archive-org"]},
            "C": {"name": "direct site access",
                  "module": "direct_sources",
                  "reach": ["rss", "atom", "sitemap",
                            "sitemap index (one level)",
                            "discourse json (latest + topic)",
                            "named page fetch",
                            "bounded feed-path discovery"],
                  "never_proxied": True},
            "D": {"name": "dead links",
                  "reach": ["wayback machine rescue"]},
        },
        "instance_pool_source": {
            "primary": registry_url,
            "fallbacks": (static_trio +
                          ["searx_fallback registry harvest",
                           "searx.space html scrape"]),
            "preflight": ("run-start /healthz pings set the run's "
                          "instance rotation order"),
        },
        "catalog_contract": {
            "shape": "list of dicts {site, kind: rss|sitemap|forum|page, "
                     "url optional}",
            "param": "site_catalog (research_deep run kwarg)",
            "env": CATALOG_ENV,
            "reader": "direct_sources.read_catalog",
            "tier": CATALOG_TIER,
            "attribution": "engine name = the site's host",
            "digest_line": "direct catalog: <site> <kind> +N",
            "failure_line": "direct catalog: <site> <kind> +0 (<reason>)",
            "entries_per_run": catalog_entry_cap(),
        },
        "direct_knobs": {
            "GREYSEARCH_DIRECT_POLITENESS_S": politeness_s(),
            "GREYSEARCH_DIRECT_TIMEOUT_S": fetch_timeout_s(),
            "GREYSEARCH_DIRECT_MAX_BYTES": body_bytes_cap(),
            "GREYSEARCH_DIRECT_ROWS_MAX": rows_cap(),
            "GREYSEARCH_SITEMAP_MAX": sitemap_cap(),
            "GREYSEARCH_CATALOG_MAX": catalog_entry_cap(),
        },
        "modules": ["searxng_integrated", "searx_fallback",
                    "direct_sources", "research_integration"],
    }
