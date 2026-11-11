#!/usr/bin/env python3
"""page_clean.py: normalize a scraped page BEFORE any semantic processing.

Every page is cleaned once, here, so the relevance judge, the fact extractor,
and the publisher all see the same chrome-free main content. Pure functions
over the scrape-result dict: no browser, no network, no imports beyond the
stdlib.

Extracted per page:
  canonical_url      final URL after redirects (query/fragment stripped)
  title              <title> or H1 fallback
  meta_description   meta[name=description] / og:description
  h1, h2s            headings already captured by the scraper (plus HTML fallback)
  body_text          main article/body text, paragraph-preserving, chrome-stripped
  excerpt            first 1500-2000 chars of cleaned body (judge input window)
  boilerplate_ratio  0-1 estimate of navigation/cookie/footer share
  images             image candidates with nearby caption/alt/context text
  duplicate_ratio    share of repeated text blocks (nav menus repeated per page)

Stripped before anything else: navigation menus, cookie notices, newsletter
forms, footer blocks, repeated menu scaffolding, social widgets, related-post
modules, and duplicate text blocks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

_COOKIE_LINE = re.compile(
    r"(?i)^\s*(?:we us(?:e|es) cookies?|this (?:website|site) uses cookies?|"
    r"accept all cookies?|cookie (?:policy|notice|consent|settings)|"
    r"manage (?:cookie )?preferences|your privacy choices|privacy & cookies)"
    r"\b[^\n]{0,200}$")

# "our website uses cookies" chrome ('Our website uses cookies to improve
# your experience. Learn more') is the same banner family with a different
# opener, but "our site uses cookies" ALSO opens real prose (the guard below
# discusses the article's own preference feature, and carries consent words),
# so this family strips only when the line carries a banner CTA (learn more /
# accept / manage / dismiss / a privacy or cookie policy pointer); prose
# about the article has none of those.
_COOKIE_CTA_LINE = re.compile(
    r"(?i)^\s*(?:this|our|the) (?:website|web\s?site|site|page) uses? cookies?\b"
    r"[^\n]{0,240}?\b(?:learn more|read more|more info(?:rmation)?|"
    r"privacy policy|cookie policy|accept(?: all|ed)?|manage|dismiss|agree|"
    r"opt(?:ing)?[- ](?:in|out))\b[^\n]{0,40}$")

# consent-banner confirmation buttons render as their own line ("Got It")
# next to the banner text, and never as prose (a sentence never continues as
# a bare line of exactly this); scraper output has been seen carrying the
# pair 'WE USES COOKIES' + 'Got It' inside one kept block.
_GOTIT_LINE = re.compile(r"(?i)^\s*got it\s*!?$")

# multi-sentence consent paragraphs (consent overlays flattened into one
# ~250-char line) dodge _COOKIE_LINE's {0,200} tail cap; a line that OPENS
# with the cookie sentence is consent text even when long, but only if it
# carries a consent noun; prose that merely mentions cookies keeps its
# length-based protection. Real pages carry such blocks: the PBS opener
# "We use cookies to enhance your web experience, ... Click Cookie Settings
# ... Privacy Policy" (247 chars) once survived as page paragraph 0.
_CONSENT_SENT = re.compile(
    r"(?i)^\s*we us(?:e|es) cookies?\b[^\n]{0,500}$")
_CONSENT_VOCAB = re.compile(
    r"(?i)\b(?:privacy|consent|preferen|cookie settings|policy|marketing|"
    r"audience)\b")

_NEWSLETTER_LINE = re.compile(
    r"(?i)^\s*(?:subscribe (?:to (?:our )?(?:newsletter|updates)|now)|"
    r"sign up for (?:our )?newsletter|join our (?:newsletter|mailing list)|"
    r"get (?:the latest|weekly) (?:news|updates) (?:in your inbox|by email)|"
    r"your email address|enter your email)\b[^\n]{0,200}$")

_FOOTER_LINE = re.compile(
    r"(?i)^\s*(?:©|\(c\)|copyright\b|all rights reserved|powered by|"
    r"terms of (?:use|service)|privacy policy|cookie policy|"
    r"advertise with us|contact us|about us|careers|press|"
    r"follow us(?: on)?|share this (?:article|page|post)|"
    r"leave (?:your )?feedback|join press pass\b\.?)[^\n]{0,200}$")

_SOCIAL_LINE = re.compile(
    r"(?i)^\s*(?:share (?:this|on)|tweet|pin it|share via|"
    r"(?:facebook|twitter|x|linkedin|reddit|pinterest|whatsapp|telegram|"
    r"instagram|youtube|tiktok)\s*(?:share|follow|\|))\b[^\n]{0,160}$")

# 'Share <article title> · <section> · <date>' is a social-gateway line the
# page re-derives from its own title; the two '·' separators are the
# signature (prose like "Share your story with the group · see the
# anthology" carries one and survives. Example seen in the wild: "Share Why
# offshore wind turbines can't handle the toughest hurricanes · Science ·
# Jun 23").
_SHARE_TITLE = re.compile(
    r"(?i)^\s*share\s+[^·\n]{3,140}\s·\s[^·\n]{0,60}\s·\s.{1,24}$")

_SKIP_TO = re.compile(
    r"(?i)^\s*(?:skip|jump) to [a-z].{0,36}$"
    r"|skip to (?:search|footer|content|main content|navigation)")

_NAV_LINE = re.compile(
    r"(?i)^\s*(?:skip to (?:main )?content|skip to navigation|"
    r"jump to (?:content|navigation|search)|back to top|"
    r"main menu|open menu|close menu|toggle navigation|"
    r"table of contents|on this page)\b[^\n]{0,160}$")

_RELATED_LINE = re.compile(
    r"(?i)^\s*(?:related (?:articles?|posts?|reading|stories)|"
    r"you may also like|recommended (?:for you|articles?|posts?)|"
    r"trending now|most (?:read|popular)|editor'?s picks?|"
    r"more (?:from|stories|articles?)|see also)\b\s*:?\s*$")

_LOGIN_LINE = re.compile(
    r"(?i)^\s*(?:sign in|log in|login|log on|create (?:free )?account|"
    r"sign up|register|subscribe|get started|start free trial|"
    r"buy now|add to cart|shop now|order now)\b[^\n]{0,160}$")

_TOGGLE_SUBSECTION = re.compile(r"(?i)^\s*toggle\b.*\bsubsections?\b")

_SALES_LINE = re.compile(
    r"(?i)\b(?:get the report|book a (?:demo|call)|download now|"
    r"start your free\b|try (?:our|it) [\w' -]{0,30}\b(?:free|now)\b|"
    r"ready to (?:audit|protect|get|try)\b)")

_NAVVERB_STUB = re.compile(
    r"(?i)^(?:why|about|jobs?|contact|products?|pricing|blog|open|check|"
    r"get|book|try|download|learn|faqs?|support|services?|solutions?|"
    r"resources?|company|careers|login|sign in|search|menu)\b[^.?!:,;]{0,24}$")

_CREDIT_LINE = re.compile(
    r"(?i)(fotolia|getty images|istockphoto|shutterstock|alamy|dreamstime|"
    r"depositphotos|adobe stock|123rf|bigstock|credit[s]?:)")

_BANNER_CTA_LINE = re.compile(
    r"(?i)\b(?:wiki loves\b|gagnez\b|photographiez\b|"
    r"win (?:an|a|our) (?:award|prize|medal)\b|"
    r"make (?:a )?donation\b|donate (?:today|now|monthly)\b)")

_BREADCRUMB_LINE = re.compile(r"[^\n>]{1,60} > [^\n>]{1,60} > ")

_BETA_UPSELL = re.compile(
    r"(?i)\bjoin (?:the|our) (?:beta|waitlist|program|list)\b"
    r"|\bjoin us (?:on|for|in) (?:discord|slack|reddit|the beta)\b"
    r"|\bearly access\b.{0,40}\bjoin\b")

_EVENT_PROMO = re.compile(
    r"(?i)\bis hitting the road\b"
    r"|\bjoin us for (?:drinks|coffee|dinner|an evening|lunch)\b"
    r"|\bfind your city\b"
    r"|\bbook your (?:seat|spot|table)\b"
    r"|\brsvp\b")

_BOT_LINE = re.compile(
    r"(?i)(just a moment|checking your browser|please verify you are human|"
    r"enable javascript|ddos protection by|attention required|"
    r"access denied|you have been blocked|captcha)")

_NAV_GLUE_PREFIX = re.compile(
    r"(?i)^(?:(?:forums?|what's new|search forums?|new posts|members?|"
    r"latest activity|search|menu|home|contact|faq|help|guest|announcements|"
    r"unread posts?|log ?in|register|login)\s+){2,}")

_GREETING_PREFIX = re.compile(
    r"(?i)^hello (?:guest|user|there|everyone)[.,!]?\s*")

_FORUM_META = re.compile(
    r"(?i)\battachments?:?\s+\S+\.(?:zip|gz|log|txt|png|jpe?g)\s*[-. ]?\s*[\d.]*\s*[KMG]?B?\b"
    r"|(?:sort by (?:date|oldest|newest|votes|views|replies|title)\s*){1,}"
    r"|\bviews?:\s*[\d,]+(?:\s*[-/|]\s*\d+)?\b"
    r"|\brepl(?:ies|y) count\b:?\s*[\d,]+\b"
    r"|\b\d+\s*(?:KB|MB|B)\s*[-·.]\s*views?:\s*[\d,]+"
    r"|\bjump to\b\s*$")

def _strip_forum_meta(text: str) -> str:
    """Strip forum metadata chips from every line."""
    return "\n".join(_FORUM_META.sub(" ", ln) for ln in text.split("\n"))

def _strip_nav_glue(text: str) -> str:
    """Strip leading nav-term glue + greeting prefixes from every line."""
    for _ in range(2):
        text = "\n".join(_NAV_GLUE_PREFIX.sub("", ln)
                         for ln in text.split("\n"))
        text = "\n".join(_GREETING_PREFIX.sub("", ln)
                         for ln in text.split("\n"))
        text = "\n".join(re.sub(r"(?i)\s*hello (?:guest|user|there|everyone)\s*[.,!]?",
                                " ", ln) for ln in text.split("\n"))
        text = _strip_forum_meta(text)
    return text

_MENU_ITEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/\-'().,%]{1,60}$")

_META_DESC_RE = re.compile(
    r"<meta[^>]+(?:name|property)=[\"'](?:description|og:description|"
    r"twitter:description)[\"'][^>]+content=[\"']([^\"']{0,500})[\"']",
    re.I | re.S)
_CANONICAL_RE = re.compile(
    r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)[\"']",
    re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

EXCERPT_MIN = 1500
EXCERPT_MAX = 2000

# Named gating constant. MIN_MAIN_CHARS is the accepted-corpus floor: a
# page whose cleaned main text is shorter than this is too thin to feed the
# guide (relevance.py's THIN_PAGE_CHARS imports this value so 800 has exactly
# one source of truth; the deterministic judge also applies its thin penalty
# at the same floor).
MIN_MAIN_CHARS = 800

# Named gating constant. Pages whose boilerplate share (navigation, cookie
# banners, footers, near-duplicate blocks; see _boilerplate_ratio) reaches
# this ratio are dropped before judging instead of being scored: there is no
# main content left to read. Consumed by research_integration during
# scrape-cleaning.
BOILERPLATE_KILL_RATIO = 0.85

def _strip_tags(html: str) -> str:
    return _TAG_RE.sub(" ", html or "")

def _norm_ws(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _strip_nav_glue(text.strip())

def _split_blocks(text: str) -> List[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]

def _is_chrome_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) > 400:
        return False
    if len(s) < 200 and _SALES_LINE.search(s):
        return True
    if len(s) < 200 and _BANNER_CTA_LINE.search(s):
        return True
    if _BREADCRUMB_LINE.search(s):
        return True
    if len(s) < 200 and _BETA_UPSELL.search(s):
        return True
    if len(s) < 200 and _EVENT_PROMO.search(s):
        return True
    return bool(_COOKIE_LINE.match(s) or _GOTIT_LINE.match(s)
                or _NEWSLETTER_LINE.match(s)
                or _COOKIE_CTA_LINE.match(s)
                or (_CONSENT_SENT.match(s) and _CONSENT_VOCAB.search(s))
                or _SHARE_TITLE.match(s)
                or _FOOTER_LINE.match(s) or _SOCIAL_LINE.match(s)
                or _NAV_LINE.match(s) or _SKIP_TO.search(s) or _CREDIT_LINE.search(s)
                or _RELATED_LINE.match(s) or _TOGGLE_SUBSECTION.match(s)
                or _LOGIN_LINE.match(s) or _BOT_LINE.search(s))

def _navverb_short(line: str) -> bool:
    """A short (< 25 chars), punctuation-free, nav-verb-leading line such as
    'Why Valimail' or 'Check My Domain': nav residue, not prose."""
    s = (line or "").strip()
    if not (4 <= len(s) < 25):
        return False
    if re.search(r"[.?!:;,]", s):
        return False
    return bool(_NAVVERB_STUB.match(s))

def _drop_menu_runs(lines: List[str]) -> List[str]:
    """Drop runs of >= 3 consecutive short menu-item lines (nav scaffolding
    that innerText flattens into a list), plus runs of >= 2 short TitleCase
    nav-verb lines ('Check My Domain' / 'Why Valimail' / 'Open Why Valimail')
    that contain stopwords and so are invisible to the >= 3 detector (a known
    defect of the first detector). Both cases need a RUN, so standalone short
    lines survive."""
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        if _MENU_ITEM.match(lines[i].strip()) and not re.search(
                r"\b(is|are|was|were|the|and|of|to|with|how|what|why|for|in|on)\b",
                lines[i], re.I):
            j = i
            while j < n and _MENU_ITEM.match(lines[j].strip()) and not re.search(
                    r"\b(is|are|was|were|the|and|of|to|with|how|what|why|for|in|on)\b",
                    lines[j], re.I):
                j += 1
            if j - i >= 3:
                i = j
                continue
        if _navverb_short(lines[i]):
            j = i
            while j < n and _navverb_short(lines[j]):
                j += 1
            if j - i >= 2:
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out

def _dedupe_blocks(blocks: List[str]) -> tuple[List[str], float]:
    """Remove duplicate text blocks (repeated menus/modules). Returns the kept
    blocks and the duplicate share (0-1)."""
    if not blocks:
        return blocks, 0.0
    seen: set[str] = set()
    kept: List[str] = []
    dup_chars = 0
    for b in blocks:
        key = re.sub(r"\s+", " ", b).strip().lower()
        if len(key) >= 40 and key in seen:
            dup_chars += len(b)
            continue
        if len(key) >= 40:
            seen.add(key)
        kept.append(b)
    dup_ratio = (dup_chars / max(sum(len(b) for b in blocks), 1)) if blocks else 0.0
    return kept, min(dup_ratio, 1.0)

def _boilerplate_ratio(raw_text: str, kept_text: str) -> float:
    """Estimate the chrome share: (raw - kept) / raw, floored at the duplicate
    share so repeated modules count as boilerplate too."""
    raw_len = len(raw_text or "")
    if raw_len <= 0:
        return 1.0
    removed = max(raw_len - len(kept_text), 0)
    return min(removed / raw_len, 1.0)

def _excerpt_of(body: str) -> str:
    body = (body or "").strip()
    if len(body) <= EXCERPT_MAX:
        return body
    cut = body[:EXCERPT_MAX]
    para = cut.rfind("\n\n")
    if para > EXCERPT_MIN:
        cut = cut[:para]
    elif cut.rfind(". ") > EXCERPT_MIN:
        cut = cut[:cut.rfind(". ") + 1]
    return cut.strip()

def _img_context(text: str, src: str, window: int = 600) -> str:
    """Nearby text for an image: the alt is usually empty, so take the text
    block(s) surrounding any URL mention, else the closest preceding heading +
    following paragraph."""
    if not text:
        return ""
    blocks = _split_blocks(text)
    ctx: List[str] = []
    for i, b in enumerate(blocks):
        if src and src in b:
            continue
        stem = re.sub(r"[^a-z0-9]+", " ", (urlparse(src).path.rsplit("/", 1)[-1]
                                          if src else "").lower()).strip()
        if stem and len(stem) >= 6 and stem in b.lower():
            ctx.append(b[:window])
    if ctx:
        return " ".join(ctx)[:window]
    for b in blocks:
        if len(b) > 120:
            return b[:window]
    return ""

def clean_page(scrape: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one scrape-result dict. Input is the dict returned by
    research_scrape / PatchrightScraper.fetch_url (text, raw_text, html,
    title, headings, images, metadata, final_url...). Output is a NEW dict;
    the input is never mutated."""
    raw_text = scrape.get("raw_text") or scrape.get("text") or ""
    text = scrape.get("text") or raw_text
    html = scrape.get("html") or ""
    metadata = scrape.get("metadata") or {}

    lines = text.split("\n")
    kept_lines = [ln for ln in lines if not _is_chrome_line(ln)]
    kept_lines = _drop_menu_runs(kept_lines)
    text = _norm_ws("\n".join(kept_lines))
    blocks = _split_blocks(text)
    blocks, dup_ratio = _dedupe_blocks(blocks)
    body = _norm_ws("\n\n".join(blocks))
    bp_ratio = max(_boilerplate_ratio(raw_text, body), dup_ratio if blocks else 0.0)

    final_url = scrape.get("final_url") or scrape.get("url") or ""
    canonical = final_url
    if html:
        m = _CANONICAL_RE.search(html[:200_000])
        if m:
            canonical = urljoin(final_url, m.group(1))
    if canonical:
        p = urlparse(canonical)
        canonical = f"{p.scheme}://{p.netloc}{p.path}".rstrip("/") or canonical

    title = (scrape.get("title") or "").strip()
    meta_desc = ""
    if html:
        m = _META_DESC_RE.search(html[:200_000])
        if m:
            meta_desc = _strip_tags(m.group(1)).strip()
    if not meta_desc and isinstance(metadata, dict):
        meta_desc = str(metadata.get("description") or "").strip()

    h1 = ""
    h2s: List[str] = []
    scraped_headings = scrape.get("headings") or []
    if scraped_headings:
        for h in scraped_headings:
            lvl = (h.get("level") or "").upper()
            t = (h.get("text") or "").strip()
            if not t:
                continue
            if lvl == "H1" and not h1:
                h1 = t
            elif lvl == "H2":
                h2s.append(t)
    if not h1 and html:
        m = _H1_RE.search(html[:200_000])
        if m:
            h1 = _norm_ws(_strip_tags(m.group(1)))
    if not h1:
        h1 = title
    if not h2s and html:
        h2s = [_norm_ws(_strip_tags(m.group(1)))
               for m in list(_H2_RE.finditer(html[:200_000]))[:20]]
        h2s = [h for h in h2s if h]

    images_out: List[Dict[str, Any]] = []
    for img in scrape.get("images") or []:
        src = (img.get("src") or "").strip()
        if not src.startswith("http"):
            continue
        alt = (img.get("alt") or "").strip()
        cap = (img.get("caption") or img.get("title") or "").strip()
        images_out.append({
            "src": src,
            "alt": alt,
            "caption": cap,
            "context": _img_context(body, src),
            "w": img.get("w", 0) or 0,
            "h": img.get("h", 0) or 0,
        })

    return {
        "canonical_url": canonical,
        "url": scrape.get("url") or final_url,
        "final_url": final_url,
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "h2s": h2s[:20],
        "body_text": body,
        "excerpt": _excerpt_of(body),
        "boilerplate_ratio": round(bp_ratio, 3),
        "duplicate_ratio": round(dup_ratio, 3),
        "images": images_out,
        "n_links": len(scrape.get("links") or []),
        "n_tables": len(scrape.get("tables") or []),
        "main_chars": len(body),
    }

def is_thin(cleaned: Dict[str, Any], min_chars: int = MIN_MAIN_CHARS) -> bool:
    """Thin-content test used before judging: a page with almost no main text
    cannot teach anything and must not consume judge budget."""
    return int(cleaned.get("main_chars") or 0) < min_chars

if __name__ == "__main__":
    import json as _json
    demo = {
        "url": "https://example.com/post?a=1#frag",
        "final_url": "https://example.com/post?a=1",
        "title": "Demo Page",
        "text": ("We use cookies to improve your experience. Accept all cookies.\n"
                 "Home\nProducts\nPricing\nAbout\nContact\n"
                 "Skip to content\n"
                 "This is the first real paragraph of the article and it is long "
                 "enough to count as main content for the cleaner.\n\n"
                 "This is the second paragraph with the actual teaching material.\n\n"
                 "© 2026 Example Corp. All rights reserved.\n"
                 "Subscribe to our newsletter\nFollow us on Twitter"),
        "raw_text": "",
        "html": "<html><head><meta name=\"description\" content=\"A demo page\">"
                "<link rel=\"canonical\" href=\"https://example.com/post\">"
                "</head><body><h1>Demo Page</h1></body></html>",
        "headings": [{"level": "H1", "text": "Demo Page"}],
        "images": [{"src": "https://example.com/diagram.png", "alt": "diagram",
                    "w": 800, "h": 400}],
        "links": [], "tables": [], "metadata": {},
    }
    demo["raw_text"] = demo["text"]
    print(_json.dumps(clean_page(demo), indent=2)[:1800])
