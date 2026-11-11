#!/usr/bin/env python3
"""
greysearch publisher - Master Guide is the DEFAULT output for every greysearch
run.

- No cross-section duplication: a page's full text appears in section 2 only,
  never again as fake "steps" in section 4. The overview and brief are
  synthesized from the run's findings (scored, source-attributed sentences)
  instead of cloning section 2's first page.
- Honest emptiness: a section with no data says DATA NOT CAPTURED. Steps are
  only filled from procedure-shaped content actually present in the sources,
  never fabricated from unrelated prose.
- write_to: render + write the guide file directly (the web output default
  fires inside the pipeline, not left to caller discretion).

Usage:
  md = publish(title=..., executive_brief=..., overview=..., ...)
  md = publish_from_greysearch(title="...", greysearch_result=<greysearch dict>,
                               write_to="/path/guide.md")
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

NOT_CAPTURED = "DATA NOT CAPTURED"


def _atomic_write_text(path, text: str) -> None:
    """Write through tmp + os.replace: a reader never sees a half guide,
    and a killed writer can no longer truncate an existing one. Identical
    bytes to the previous direct write_text."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)

MASTER_GUIDE_TEMPLATE = """# {title}

> **Executive Brief:** {executive_brief}

---

## 1. Deep-Dive Overview & Context
{overview}

## 2. Full Technical & Feature Breakdown
{breakdown}

## 3. Comparative Data & Specs
{comparative}

## 4. Complete Actionable Steps / Execution Guide
{steps}

## 5. Primary Sources & Media Links
{sources}
"""

_CODE_INCOMPLETE = re.compile(r"#\s*TODO|//\s*\.\.\.|\.\.\.\s*rest of code|#\s*add logic here")

_NAV_LINE = re.compile(
    r"(?i)(skip to content|open our|about us|our etfs|merch\b|contact|"
    r"subscribe|tune into|sign in|log in|menu\b|invest now|open education|"
    r"\b×\b|cookie|accept all)")

def _trim_leading_nav(text: str) -> str:
    """Drop leading short nav/widget lines from a page's text until the first
    real paragraph. Body prose keeps everything; only header junk (menus,
    'Skip to content' banners) is dropped."""
    lines = (text or "").split("\n")
    i = 0
    broke = False
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        words = len(s.split())
        navish = bool(_NAV_LINE.search(s))
        if words >= 9 and len(s) >= 60 and not navish:
            broke = True
            break
        if words < 9 and (navish or len(s) < 40):
            continue
        broke = True
        break
    out = "\n".join(lines[i:]) if broke else ""
    return out.strip() or (text or "").strip()

_SEARX_NAV_LABELS = {
    "about", "donate", "preferences", "searxng", "source code",
    "issue tracker", "engine stats", "public instances",
}
_SEARX_NAV_URL = re.compile(
    r"(?:^https?://searx\.space(?:/|$)"
    r"|/preferences(?:$|[?#])"
    r"|/search#[^ ]*$"
    r"|/stats(?:$|[?#])"
    r"|/info/[a-z]{2}/about(?:$|[?#]))", re.I)

def _drop_search_engine_nav(links: List[Dict[str, str]]) -> List[Dict[str, str]]:
    labels = {(l.get("text") or "").strip().lower() for l in links}
    url_hits = [l for l in links if _SEARX_NAV_URL.search(l.get("href") or "")]
    by_label = len(labels & _SEARX_NAV_LABELS) >= 4
    if not by_label and len(url_hits) < 2:
        return links
    instance_hosts = set()
    for l in url_hits:
        m = re.match(r"https?://([^/]+)", l.get("href") or "", re.I)
        if m and m.group(1).lower() != "searx.space":
            instance_hosts.add(m.group(1).lower())

    def chrome(l):
        text = (l.get("text") or "").strip().lower()
        href = l.get("href") or ""
        m = re.match(r"https?://([^/]+)", href, re.I)
        host = m.group(1).lower() if m else ""
        return (text in _SEARX_NAV_LABELS or host == "searx.space"
                or (host in instance_hosts and _SEARX_NAV_URL.search(href)))

    return [l for l in links if not chrome(l)]

def _md_links(links: List[Dict[str, str]], limit: int = 80) -> str:
    """Render links as [text](url). limit=0 means all (nav noise is capped at
    80 so a source's menu bar can't bury the guide)."""
    items = _drop_search_engine_nav(links)
    items = items if not limit else items[:limit]
    return "\n".join(f"- [{(l.get('text') or l.get('href'))[:120]}]({l['href']})"
                     for l in items if l.get("href"))

def _md_images(images: List[Dict[str, str]], limit: int = 0) -> str:
    items = images if not limit else images[:limit]
    return "\n".join(f"![{i.get('alt') or 'image'}]({i['src']})" for i in items if i.get("src"))

_IMG_EMOJI_ALT = re.compile(r"^:[\w-]+:$")
_IMG_CHROME = re.compile(
    r"(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|"
    r"placeholder|spacer|pixel|tracking|advertisement|\bad\b|social|share)")

def _content_images(images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only content-class images from a source page: known real pixel
    dimensions, not svg/emoji/logo/ad class, no wide-short banner aspect.

    A dimensionless image (missing or zero w/h) is now a FAIL, not a pass:
    a 20px Wikidata footer icon arrived with no recorded w/h, skipped every
    size check, and shipped uncredited into a built site. An unmeasured image
    cannot be verifiably content-class, so it is dropped; the confirm grid
    remains the intentional image path. (This gate only ever sees RAW
    source-page images; chosen confirm-grid candidates reach the guide via
    _insert_chosen_images, never here.)"""
    kept: List[Dict[str, Any]] = []
    for im in images:
        src = (im.get("src") or "").strip()
        alt = (im.get("alt") or "").strip()
        if not src.startswith("http"):
            continue
        if src.lower().endswith(".svg"):
            continue
        if _IMG_EMOJI_ALT.match(alt) or "emoji" in src.lower():
            continue
        if _IMG_CHROME.search(alt + " " + src):
            continue
        w, h = int(im.get("w") or 0), int(im.get("h") or 0)
        if not (w and h):
            continue
        if w < 200 and h < 200:
            continue
        if h < 450 and w / h >= 2.8:
            continue
        kept.append(im)
    return kept

def _md_videos(videos: List[Dict[str, str]]) -> str:
    return "\n".join(f"- [{v.get('title') or v['src']}]({v['src']})" for v in videos if v.get("src"))

def _md_audios(audios: List[Dict[str, str]]) -> str:
    """Render audio elements as HTML audio controls or markdown links."""
    items = audios
    return "\n".join(f'<audio controls><source src="{a["src"]}" type="audio/mpeg"></audio> {a.get("title", "")}' for a in items if a.get("src"))

def _md_pdfs(pdfs: List[Dict[str, str]]) -> str:
    """Render PDFs as markdown links."""
    items = pdfs
    return "\n".join(f"- [{a.get('title') or a['src']}]({a['src']})" for a in items if a.get("src"))

def _md_canvases(canvases: List[Dict[str, int]]) -> str:
    """Note canvas elements (cannot be rendered directly in markdown)."""
    items = canvases
    if not items:
        return ""
    return "\n".join(f"- Canvas {i.get('width',0)}x{i.get('height',0)}" for i in items)

def _md_iframes(iframes: List[Dict[str, str]]) -> str:
    """Render iframes as HTML embed (use with caution)."""
    items = iframes
    return "\n".join(f'<iframe src="{i["src"]}" title="{i.get("title","")}" width="560" height="315"></iframe>' for i in items if i.get("src"))

def _md_table(table: Dict[str, Any]) -> str:
    """Reconstruct a full Markdown table: every row/column, never collapsed."""
    rows = table.get("rows") or []
    if not rows:
        return ""
    header = [str(h).replace("\n", " ").replace("|", "\\|") for h in rows[0]]
    sep = ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(sep) + " |"]
    for r in rows[1:]:
        r = (list(r) + [""] * len(header))[:len(header)]
        cells = [str(c).replace("\n", " ").replace("|", "\\|") for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    if table.get("caption"):
        lines.append(f"\n*{table['caption']}*")
    return "\n".join(lines)

def _clean_prose(text: str) -> str:
    """Strip CSS/attribute noise while PRESERVING paragraph structure."""
    text = re.sub(r'\s(?:class|style|id)\s*=\s*"[^"]*"', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

BREAKDOWN_PROSE_CAP = 40_000

_TRUNCATION_NOTE = (
    "*[Truncated: this section shows the first {kept:,} of {total:,} "
    "characters; the cut lands at the last clean paragraph or word "
    "boundary; the full source text remains in the run report JSON beside "
    "the guide.]*")

def _cap_section_prose(text: str, cap: int = BREAKDOWN_PROSE_CAP) -> str:
    """Cap one breakdown section's prose at `cap` chars with a visible
    truncation note (never silent). Boundaries are deterministic."""
    if not text or len(text) <= cap:
        return text
    total = len(text)
    cut = text[:cap]
    para = cut.rfind("\n\n")
    if para > cap // 2:
        cut = cut[:para]
    else:
        sp = cut.rfind(" ")
        if sp > cap // 2:
            cut = cut[:sp]
    kept = len(cut.strip())
    return cut.strip() + "\n\n" + _TRUNCATION_NOTE.format(kept=kept, total=total)

def _paragraphs(text: str, count: int = 2) -> List[str]:
    """First N paragraph blocks from paragraph-preserving page text."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    out = []
    for b in blocks:
        if len(out) >= count:
            break
        if len(b) > 120:
            out.append(b)
    return out

def _is_stepish(paragraph: str) -> bool:
    """Procedure-shaped paragraph: numbered/step-led, not a topic paragraph."""
    head = paragraph.strip().lower()
    if re.match(r"^(step\s+\d+|\d+[\).:]\s|\d+\.\d+\s)", head):
        return True
    if re.match(r"^(first|second|third|next|then|finally|after\s+that|to\s+start|begin\s+by|start\s+by)\b", head):
        return True
    return False

_BRIEF_SKIP_TO = re.compile(
    r"(?i)skip to (?:search|footer|content|navigation)")

def _nav_chain(s: str) -> bool:
    """A glued mega-menu line: a run of mostly-Capitalized
    fragments with no sentence punctuation. Real prose is lowercase-heavy
    and carries periods."""
    words = s.split()
    if len(words) < 8 or len(s) > 400:
        return False
    caps = sum(1 for w in words if w[:1].isupper() or w.isupper())
    has_period = bool(re.search(r"\.\s", s))
    return caps >= len(words) * 0.6 and not has_period

from page_clean import _strip_nav_glue

def _clean_brief_text(text: str) -> str:
    """Strip scraped chrome out of any prose destined for the brief/overview.
    The preferred input is the page's CLEANED text (page_clean); this is the
    safety net for raw page text that still carries nav/cookie/footer lines."""
    out = _clean_prose(text or "")
    lines = []
    for ln in out.split("\n"):
        s = ln.strip()
        if s and (_NAV_LINE.search(s) or _is_chrome_line(s)):
            continue
        if s and (len(s) <= 400 and
                  (_BRIEF_SKIP_TO.search(s) or _nav_chain(s))):
            continue
        lines.append(ln)
    return _strip_nav_glue(_clean_prose("\n".join(lines)))

_CHROME_LINE = re.compile(
    r"(?i)(we use cookies?|accept all cookies?|cookie (policy|notice|consent)|"
    r"all rights reserved|subscribe (to our )?newsletter|follow us on|"
    r"share this (article|page|post)|skip to (main )?content|"
    r"sign in|log in|create (free )?account|back to top|"
    r"just a moment|checking your browser|enable javascript)")

def _is_chrome_line(s: str) -> bool:
    return bool(_CHROME_LINE.search(s)) and len(s) < 220

_RFC822_DATE = re.compile(
    r"(?i)\b(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]{0,6},\s+)?"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]{0,7}\.?\s+"
    r"\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s+(?:[+-]\d{4}|[A-Z]{2,5})\b")

_MAIL_FIELD_LINE = re.compile(
    r"(?im)^(?:subject|from|to|cc|bcc|date|message-id|reply-to|"
    r"mailing-list|list-[a-z-]+|delivered-to|in-reply-to|references|"
    r"x-[a-z-]+|content-[a-z-]+)\s*:.*$")

_MAIL_REPLY_WROTE = re.compile(
    r"(?i)\bon\s+(?:[a-z]{3},\s+)?\d{1,2}\s+[a-z]{3}\.?\s+\d{4}"
    r"[^.\n]{0,120}?\bwrote:\s*")

_MAIL_GREETING = re.compile(
    r"^[ \t]*[A-Z][A-Za-z'.-]+(?:\s+[A-Z]\.)?(?:\s+"
    r"[A-Z][A-Za-z'-]+)+,\s+")

_MAIL_HEADER_SHAPE = re.compile(
    r"(?i)\b(?:re|fwd|fw|aw|es)\s*:|\[(?:bug|patch|rfc)\s*#?\d+\]|"
    r"\bmessage-id\b|\bdelivered-to\b|\bwrote\s*:")

_CONSENT_GLUE = re.compile(
    r"(?i)(?:i|we|you|\s)*"
    r"(?:do\s+not\s+|(?:don't|dont)\s+)?"
    r"(?:agree|decline|accept(?:\s+all)?|reject(?:\s+all)?|"
    r"manage\s+(?:my\s+)?preferences?|change\s+my\s+preferences?|"
    r"customize|cookie\s+(?:settings|preferences)?)"
    r"(?=(?-i:[A-Z]))")

_MAIL_CONSENT_TAIL = re.compile(
    r"(?i)\b(?:i|we)\s+(?:agree|decline|accept(?:\s+all)?)\b|"
    r"\b(?:change|manage|customize)\s+(?:my\s+)?preferences\b|"
    r"\b(?:accept|reject)\s+all\b|"
    r"\bcookie\s+(?:settings|preferences)\b")

_REPO_STAR_BREADCRUMB = re.compile(
    r"(?i)(?:^|\s)/\s+[^()\n/]{2,80}\(\s*\d+\s*\)\s*stars?\s*\d*")
_REPO_STAR_PLAIN = re.compile(
    r"(?i)\(?\s*\d+\s*\)?\s*stars?\s*\d*(?:\s*\(\s*\d+\s*\))?(?=\s*(?:·|history))")
_REPO_HISTORY = re.compile(
    r"(?i)\(\s*\d+\s*\)\s*·\s*history\s+\d+\s+commits?\b")
_REPO_FOLDERS_BLOCK = re.compile(
    r"(?i)folders\s+and\s+files\b"
    r"(?:[\s\S]{0,600}?\binitial\s+commit\b)+"
    r"(?:\s+[a-z][\w.\-/]{0,39}(?=\s+[a-z]))?")
_REPO_TABLE_HEAD = re.compile(
    r"(?i)\bname\s+last\s+commit\s+message(?:\s+last\s+commit"
    r"\s+(?:date|time))?\b")
_POSTED_ON_BULLET = re.compile(
    r"(?i)\bposted\s+on\s+[a-z]+\.?\s+(?:\d{1,2}\s*,?\s*)?\d{4}\s*[•·]\s*")

_ADJACENT_DUP = re.compile(r"(\b[^.!?\n]{12,120})\1")

_GLUE_ATTR = re.compile(
    r"\*{0,2}\(\s*per\s+[a-z0-9.\-]+\.[a-z]{2,}\s*\)\*{0,2}", re.IGNORECASE)

def _strip_mail_header_junk(text: str) -> str:
    """Cut mailing-list/list-archive header shapes (class 1). A leading
    "[Bug N] Re: <subject> <names> <RFC-822 date>" run is removed from the
    start through the date (plus a glued name greeting right after it);
    reply quotes ("On <date>, <name> wrote:"), RFC header field lines and
    any further RFC-822 date tokens go once the header shape is confirmed.
    No-op on text with no header shape (so no gating damage)."""
    if not _MAIL_HEADER_SHAPE.search(text):
        return text
    date = _RFC822_DATE.search(text[:400])
    lede_cut = False
    out = text
    if date:
        head = text[:date.end()]
        if _MAIL_HEADER_SHAPE.search(head):
            rest = text[date.end():].lstrip()
            rest = _MAIL_GREETING.sub("", rest, count=1)
            out = rest
            lede_cut = True
    out = _MAIL_REPLY_WROTE.sub(" ", out)
    out = _MAIL_FIELD_LINE.sub(" ", out)
    if lede_cut:
        out = _RFC822_DATE.sub(" ", out)
    return out

def _strip_consent_glue(text: str) -> str:
    """Remove glued cookie/consent banner runs (class 2): consent words
    jammed together with NO whitespace between them ("I agreeI declineChange
    my preferences"). A glued token is followed immediately by a capital
    letter; plain prose ("I agree with you") never matches. Once glue is
    confirmed the tail sweep also removes the trailing banner phrases."""
    if not re.search(r"(?i)\b(?:agree|decline|preferences|accept|reject|"
                     r"customize|consent|cookie)\b", text):
        return text
    glued, n = _CONSENT_GLUE.subn(" ", text)
    if n == 0:
        return text
    glued = _MAIL_CONSENT_TAIL.sub(" ", glued)
    return glued

def _strip_repo_chrome(text: str) -> str:
    """Remove repo/file-listing UI chrome glued in front of prose
    (class 3): star/commit counters, "Folders and files", the file-table
    header and its "<file> Initial commit" rows, each with its own marker
    so clean text is untouched."""
    if not ("folder" in text.lower() and "files" in text.lower()
            and ("initial commit" in text.lower()
                 or "last commit message" in text.lower()
                 or _REPO_STAR_BREADCRUMB.search(text))):
        return text
    out = _REPO_STAR_BREADCRUMB.sub(" ", text)
    out = _REPO_STAR_PLAIN.sub(" ", out)
    out = _REPO_HISTORY.sub(" ", out)
    out = re.sub(r"(?i)\bfolders\s+and\s+files\b", " ", out)
    out = _REPO_FOLDERS_BLOCK.sub(" ", out)
    out = _REPO_TABLE_HEAD.sub(" ", out)
    out = re.sub(r"(?i)(?:\s+[\w.\-/]{1,40}\s+initial\s+commit\b)+", " ", out)
    return out

def _strip_page_glue(text: str) -> str:
    """All page-glue scrubs (mailing-list header shapes, glued consent
    runs, repo chrome, posted-on bullets), plus the adjacent-duplicate-title
    collapse. Each scrub no-ops on text without its markers. The duplicate collapse
    runs only when a glue scrub actually changed the text (chrome glue is
    what makes a page's title appear in one run twice)."""
    out = _strip_mail_header_junk(text)
    out = _strip_consent_glue(out)
    out = _strip_repo_chrome(out)
    out = _POSTED_ON_BULLET.sub(" ", out)
    if out != text:
        out = _ADJACENT_DUP.sub(r"\1", out)
        out = re.sub(r"[•·|\[\]]", " ", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()

def _has_glue_markers(text: str) -> bool:
    """Cheap marker check for the page-glue scrubs (so _strip_refs_junk keeps
    its fast pass-through for genuinely clean text)."""
    low = text.lower()
    if ("folders" in low and "files" in low
            and ("initial commit" in low or "last commit message" in low)):
        return True
    if (any(w in low for w in ("agree", "decline", "preferences", "accept",
                               "reject", "customize", "consent", "cookie"))):
        return True
    if ("wrote:" in low or "message-id" in low or "delivered-to" in low
            or "posted on" in low):
        return True
    if _RFC822_DATE.search(text):
        return True
    return False

_BARE_FOOTNOTE = re.compile(
    r"\s*\[\s*(?:\d+|note\s+\d+|[a-z])\s*\]", re.IGNORECASE)

_JUMP_BACKLINK_QUOTED = re.compile(
    r'(?is)\bjump up to:?\s*(?:[a-z]\s+){0,4}"[^"]*"\s*[.,;]?\s*')
_JUMP_BACKLINK_BARE = re.compile(r"(?im)\bjump up to:?.*$")
_JUMP_ARROW_LINE = re.compile(r"(?m)^\^.*$")

def _strip_refs_junk(text: str) -> str:
    """Remove references-section junk from scraped text (Wikipedia style and
    friends): bare footnote markers "[25]" / "[note 3]" / "[a]",
    "(citation needed)", and the entire "Jump up to: \"Title\"." backlink
    segment. Page-glue scrubs follow the same pass (mailing-list header
    shapes, glued cookie/consent banner runs, repo/file-listing chrome). Prose
    before the marker is kept; junk-only passages come back near-empty (the
    caller decides to drop them). Pass-through on text with no junk markers
    so the clean path is untouched."""
    if not text:
        return ""
    low = text.lower()
    if ("jump up to" not in low and "citation needed" not in low and
            not _BARE_FOOTNOTE.search(text) and not _has_glue_markers(text)):
        return text
    out = _JUMP_BACKLINK_QUOTED.sub(" ", text)
    out = _JUMP_BACKLINK_BARE.sub(" ", out)
    out = _JUMP_ARROW_LINE.sub(" ", out)
    out = _BARE_FOOTNOTE.sub("", out)
    out = re.sub(r"(?i)\(\s*citation needed\s*\)", " ", out)
    out = _strip_page_glue(out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()

_MIN_SALVAGE = 40

def _refs_candidate(raw: str) -> Optional[str]:
    """Refs-junk scrub + chrome clean + gutted check for ONE (unglued)
    candidate text. Returns None when the scrub left the text gutted (a
    near-empty remainder is page junk, not prose) so the synthesizer falls
    back to the next finding / honest line."""
    scrubbed = _strip_refs_junk(raw)
    cleaned = _clean_brief_text(scrubbed)
    if scrubbed != raw and len("".join(cleaned.split())) < _MIN_SALVAGE:
        return None
    return cleaned

def _brief_candidate(text: str) -> Optional[str]:
    """Junk-scrub + clean a brief candidate, plus the attribution-glue gate
    (class 4): a candidate whose text itself carries "(per domain)"
    attribution tails is a GLUE of several unrelated fragments, not one
    finding. Multiple tails -> the candidate is reduced to its best single
    usable fragment (the rest is the synthesis failure); a single recycled
    tail is stripped as junk; no tails -> plain scrub path, byte
    for byte. None => drop the finding for the next one / honest line."""
    raw = text or ""
    if _GLUE_ATTR.search(raw):
        frags = [f for f in _GLUE_ATTR.split(raw) if f.strip()]
        if len(frags) >= 2:
            best: Optional[str] = None
            for frag in frags:
                cand = _refs_candidate(frag)
                if cand and (best is None or len(cand) > len(best)):
                    best = cand
            return best
        raw = _GLUE_ATTR.sub(" ", raw)
    return _refs_candidate(raw)

_LANE_NOTE_KEYS = ("proxy mode off", "search proxy")
_LANE_KEY_CAP = 40

def _lane_states(result: Dict[str, Any]) -> List[str]:
    """Per-lane final states collapsed from the run's OWN ladder records: the
    LAST record for each lane key wins (a lane states its own final truth),
    the proxy-mode note lines are dropped (mode facts, not lane facts), and
    records without a short lane prefix stay out of the sentence. The blurb
    therefore names only lanes that actually ran, and when the ladder record
    is absent (old result dicts) the sentence is empty, so the live
    line falls back to wording that names no lane at all."""
    states: Dict[str, str] = {}
    order: List[str] = []
    for rec in (result.get("search_ladder") or []):
        text = str(rec).strip()
        key, sep, _rest = text.partition(":")
        key = key.strip()
        if not sep or not key or key in _LANE_NOTE_KEYS or len(key) > _LANE_KEY_CAP:
            continue
        if key not in states:
            order.append(key)
        states[key] = text
    return [states[k] for k in order]

def _lane_summary_text(result: Dict[str, Any]) -> str:
    """The "; "-joined per-lane state body for one run, or "" when the run's
    result carries no ladder record."""
    return "; ".join(_lane_states(result))

def _synthesize_brief(result: Dict[str, Any]) -> str:
    """Executive brief synthesized from the run's scored findings (never from
    one page's raw text alone, and never from references-section junk: bare
    footnote markers, "Jump up to:" backlinks and citation titles are
    scrubbed; a gutted finding is skipped for the next one; with nothing
    usable the brief is the honest NOT_CAPTURED line)."""
    findings = result.get("findings") or []
    pages = result.get("pages_fetched") or []
    parts: List[str] = []
    for f in findings:
        if len(parts) >= 4:
            break
        cand = _brief_candidate(f.get("text", ""))
        if not cand:
            continue
        dom = (f.get("source_domains") or [""])[0]
        src = f" *(per {dom})*" if dom else ""
        parts.append(f"{cand}{src}")
    if not parts and pages:
        clean = pages[0].get("clean") or {}
        raw = _trim_leading_nav(clean.get("body_text")
                                or _page_clean_filtered_fallback(pages[0]))
        scrubbed = _strip_refs_junk(raw)
        paras = _paragraphs(_clean_brief_text(scrubbed), 1)
        if paras and (scrubbed == raw or
                      len("".join(paras[0].split())) >= _MIN_SALVAGE):
            para = paras[0]
            if _GLUE_ATTR.search(para):
                para = _brief_candidate(para) or ""
            if para:
                parts.append(para)
    if parts:
        body = " ".join(parts[:3])
        n_pages = len(pages)
        _lanes = _lane_summary_text(result)
        _lane_clause = (f" Search lanes this run: {_lanes}." if _lanes
                        else "")
        body += (f"\n\nAssembled live from {n_pages} accepted source(s) and a "
                 f"headless browser, filtered by the two-stage relevance "
                 f"gate.{_lane_clause} Every section carries its source;")
        base = _clean_prose(body)
    else:
        base = (f"{NOT_CAPTURED}: the research run returned no accepted source "
                f"text. See the run's skipped_pages / run-report fields for "
                f"exactly which pages were rejected or quarantined, and why.")
    return base

def _synthesize_overview(result: Dict[str, Any]) -> str:
    """Overview from findings across sources (not a clone of page one)."""
    findings = result.get("findings") or []
    pages = result.get("pages_fetched") or []
    paras: List[str] = []
    if findings:
        lead, support = [], []
        for f in findings[:6]:
            cand = _brief_candidate(f.get("text", "")) or _clean_brief_text(
                f.get("text", ""))
            dom = (f.get("source_domains") or [""])[0]
            line = f"{cand} ({dom})"
            (lead if not lead else support).append(line)
        if lead:
            paras.append(lead[0])
        if support:
            paras.append(" ".join(support[:4]))
    if not paras and pages:
        clean = pages[0].get("clean") or {}
        raw = _trim_leading_nav(clean.get("body_text")
                                or _page_clean_filtered_fallback(pages[0]))
        paras = _paragraphs(_clean_brief_text(raw), 2)
    if not paras:
        paras.append(f"{NOT_CAPTURED}: full prose for this topic was not captured.")
    searches = result.get("searches") or []
    if searches:
        lanes = "; ".join(f"{s.get('category')}: {s.get('n', 0)} results" for s in searches[:3])
        _run_lanes = _lane_summary_text(result)
        paras.append(f"Search coverage for this run, {lanes}."
                     + (f" Lanes engaged this run: {_run_lanes}."
                        if _run_lanes else ""))
    combined = "\n\n".join(paras)
    return combined

def _page_clean_filtered_fallback(page: Dict[str, Any]) -> str:
    """Raw page text pushed through the SAME page_clean chrome-strip the
    primary (clean record) path gets: nav menus, cookie banners, footer
    blocks and glued menu runs are removed; paragraph structure is kept.
    On any error the result is empty (fail-closed): raw chrome text is
    never allowed to land in the guide untouched. Import is local so the
    publisher stays import-light."""
    raw = page.get("text", "") or ""
    if not raw:
        return ""
    try:
        import page_clean
        cleaned = page_clean.clean_page({
            "text": raw,
            "raw_text": page.get("raw_text", "") or raw,
            "url": page.get("url", "") or "",
        })
        return cleaned.get("body_text", "") or ""
    except Exception:
        return ""

def extract_steps_from_sources(breakdown_proses: List[str]) -> List[Dict[str, str]]:
    """Pull procedure-shaped paragraphs from source text. Returns [] when the
    sources contained no procedures; section 4 then honestly reports it."""
    steps: List[Dict[str, str]] = []
    for prose in breakdown_proses:
        for para in re.split(r"\n\s*\n", prose or ""):
            p = _clean_prose(para).strip()
            if len(p) > 200 and _is_stepish(p):
                title = p.split(".")[0].split("\n")[0][:80]
                if not steps or p[:80].lower() != steps[-1]["title"].lower():
                    steps.append({"title": title, "detail": p})
    return steps[:20]

def publish(title: str,
            executive_brief: str,
            overview: str,
            breakdown_sections: List[Dict[str, Any]],
            comparative_tables: List[Dict[str, Any]],
            steps: List[Dict[str, str]],
            sources: List[Dict[str, str]],
            extra_images: Optional[List[Dict[str, str]]] = None,
            write_to: Optional[str] = None) -> str:
    """Render a Master Guide; `write_to` writes the .md file and returns md."""
    b_parts: List[str] = []
    for sec in breakdown_sections:
        heading = (sec.get("heading") or "Source").replace("\n", " ")
        b_parts.append(f"### {heading}\n")
        prose = _cap_section_prose(_trim_leading_nav(_clean_prose(sec.get("prose", ""))))
        if prose:
            b_parts.append(prose + "\n\n")
        for img in _content_images(sec.get("images", []) or []):
            if img.get("src"):
                b_parts.append(f"![{img.get('alt') or heading[:60]}]({img['src']})\n")
        for tbl in sec.get("tables", []) or []:
            part = _md_table(tbl)
            if part:
                b_parts.append(part + "\n\n")
        for code in sec.get("code_blocks", []) or []:
            body = (code or "").strip()
            if body and not _CODE_INCOMPLETE.search(body):
                b_parts.append(f"```\n{body}\n```\n")
        links = _md_links(sec.get("links") or [])
        if links:
            b_parts.append(links + "\n\n")

        for audio in sec.get("audios", []) or []:
            if audio.get("src"):
                b_parts.append(_md_audios([audio]) + "\n\n")
        for pdf in sec.get("pdfs", []) or []:
            if pdf.get("src"):
                b_parts.append(_md_pdfs([pdf]) + "\n\n")
        for canvas in sec.get("canvases", []) or []:
            if canvas:
                b_parts.append(_md_canvases([canvas]) + "\n\n")
        for iframe in sec.get("iframes", []) or []:
            if iframe.get("src"):
                b_parts.append(_md_iframes([iframe]) + "\n\n")

    c_parts: List[str] = []
    seen_tables = set()
    for t in comparative_tables:
        key = ",".join((t.get("caption") or ""), ) + "|" + ",".join(
            (t.get("rows") or [[""]])[0] if t.get("rows") else [])
        if key in seen_tables:
            continue
        seen_tables.add(key)
        rendered = _md_table(t)
        if rendered:
            if t.get("caption"):
                c_parts.append(f"**{t['caption']}**\n")
            c_parts.append(rendered + "\n\n")

    s_parts: List[str] = []
    if steps:
        for i, step in enumerate(steps, 1):
            detail = _clean_prose(step.get("detail") or "")
            s_parts.append(f"{i}. **{step.get('title') or f'Step {i}'}**\n{detail}\n")
    else:
        s_parts.append(f"{NOT_CAPTURED}: no procedure-shaped steps were present "
                       f"in the captured sources. Steps are never fabricated from "
                       f"unrelated prose.")

    src_parts: List[str] = []
    for s in sources or []:
        url = (s.get("url") or "").strip()
        name = (s.get("name") or url).strip()
        if url.startswith("http"):
            src_parts.append(f"- [{name}]({url})")
        elif name:
            src_parts.append(f"- {name} (no URL recorded)")

    if extra_images:
        media_links = _md_images(extra_images)
        if media_links:
            src_parts.append("\n**Retained media:**\n" + media_links)
    videos: List[Dict[str, str]] = []
    for sec in breakdown_sections or []:
        videos.extend(sec.get("videos") or [])
    if videos:
        src_parts.append("\n**Video sources:**\n" + _md_videos(videos))

    rendered = MASTER_GUIDE_TEMPLATE.format(
        title=title,
        executive_brief=_clean_prose(executive_brief).strip() or f"{NOT_CAPTURED}.",
        overview=_clean_prose(overview).strip(),
        breakdown="\n\n".join(b_parts).strip(),
        comparative="\n\n".join(c_parts).strip() if c_parts else
        f"**No comparative tables captured.** All table data: {NOT_CAPTURED}.",
        steps="\n".join(s_parts).strip(),
        sources="\n".join(src_parts).strip() if src_parts else f"- {NOT_CAPTURED}",
    )
    if write_to:
        _atomic_write_text(write_to, rendered)
    return rendered

def publish_from_greysearch(title: str,
                            executive_brief: Optional[str],
                            greysearch_result: Dict[str, Any],
                            write_to: Optional[str] = None,
                            output_spec: Optional[Dict[str, Any]] = None) -> str:
    """Build the Master Guide from a greysearch result. Full per-page text goes
    to section 2 exactly once (no §2/§4 duplication); overview and brief are
    synthesized from the run's findings; steps only from real procedures.

    Relevance-gated: ONLY accepted pages may contribute
    prose, tables, steps, citations, or images. A page contributes when its
    relevance decision is "accept"; pages with no relevance record (old result
    dicts) are treated as accepted for back-compat. Quarantined and rejected
    pages are NEVER blended; they are listed (URL + reason) in a Research
    limitations section so a thin run is visibly incomplete rather than padded.
    """
    breakdown_sections: List[Dict[str, Any]] = []
    comparative_tables: List[Dict[str, Any]] = []
    sources: List[Dict[str, str]] = []
    skipped_notes: List[str] = []

    all_pages = (greysearch_result.get("pages_fetched", [])
                 + (greysearch_result.get("all_scraped_pages") or []))
    seen_urls: set = set()
    pages: List[Dict[str, Any]] = []
    for p in all_pages:
        u = p.get("url") or ""
        if u and u in seen_urls:
            continue
        if u:
            seen_urls.add(u)
        rel = p.get("relevance") or {}
        if rel.get("decision") not in (None, "accept"):
            continue
        pages.append(p)

    rr = greysearch_result.get("run_report") or {}
    skipped_pages = rr.get("skipped_pages")
    if skipped_pages is None:
        skipped_pages = ([(q if isinstance(q, dict) else {"url": str(q)})
                          for q in (greysearch_result.get("quarantined_pages") or [])]
                         + [(q if isinstance(q, dict) else {"url": str(q)})
                            for q in (greysearch_result.get("rejected_pages") or [])]
                         + [(s if isinstance(s, dict) else {"url": str(s)})
                            for s in (greysearch_result.get("skipped_pages") or [])])
    for s in skipped_pages:
        url = s.get("url") or ""
        decision = s.get("decision") or "skipped"
        reason = s.get("reason") or ""
        if url:
            skipped_notes.append(f"- **{decision}**: {url}"
                                 + (f" ({reason})" if reason else ""))

    for page in pages:
        heading = (page.get("title") or page.get("url") or "Untitled")[:140]
        clean = page.get("clean") or {}
        prose = clean.get("body_text") or _page_clean_filtered_fallback(page)
        rel = page.get("relevance") or {}
        allowed = rel.get("allowed_content") or []
        images = page.get("images", [])
        tables = page.get("tables", [])
        code_blocks = page.get("code_blocks", [])
        if "images" not in allowed and rel.get("decision") == "accept":
            images = [im for im in images
                      if not re.search(
                          r"(?i)(logo|icon|avatar|badge|banner|button|sprite|"
                          r"favicon|placeholder|spacer|pixel|tracking|"
                          r"advertisement|\bad\b|social|share)",
                          (im.get("alt") or "") + " " + (im.get("src") or ""))]
        images = _content_images(images)
        breakdown_sections.append({
            "heading": heading,
            "prose": prose,
            "images": images,
            "links": page.get("links", []),
            "tables": tables,
            "code_blocks": code_blocks,
            "videos": page.get("videos", []),
            "audios": page.get("audios", []),
            "pdfs": page.get("pdfs", []),
            "canvases": page.get("canvases", []),
            "iframes": page.get("iframes", []),
            "source_url": page.get("url", ""),
        })
        for t in page.get("tables", []) or []:
            if t.get("rows"):
                comparative_tables.append(t)
        if page.get("url"):
            prov = f"{heading}"
            sc = rel.get("relevance_score")
            if sc is not None:
                prov += f" (relevance {sc})"
            sources.append({"name": prov, "url": page["url"]})
        for pdf in page.get("pdfs", []):
            if isinstance(pdf, dict) and pdf.get("src"):
                sources.append({"name": f"PDF: {pdf.get('title', 'PDF')} ", "url": pdf["src"]})

    limitations_md = ""
    if skipped_notes:
        qw = rr.get("quality_warnings") or []
        # Name the gate that actually ran (assist-moved pages
        # carry "assist": "llm" on the page record; this counts them from the
        # run report so untouched pages stay "deterministic judge").
        _ja = (greysearch_result.get("judge_assist")
               or rr.get("judge_assist") or {})
        _ja_n = int(_ja.get("moved") or 0)
        _gate_name = (
            "The relevance gate (deterministic pre-filter + deterministic "
            "relevance judge with opt-in model-assisted band tie-breaks: "
            f"{_ja_n} page(s) moved)"
            if _ja_n
            else "The two-stage relevance gate (deterministic pre-filter + "
                 "deterministic relevance judge)")
        lines = ["## Research limitations",
                 _gate_name + " removed or quarantined the following pages; "
                 "they do NOT contribute any prose, facts, tables, citations, "
                 "or images to this guide.", ""]
        lines += skipped_notes[:40]
        if len(skipped_notes) > 40:
            lines.append(f"- … and {len(skipped_notes) - 40} more "
                         "(see the run report JSON next to this guide).")
        if qw:
            lines += ["", "**Quality warnings:**"] + [f"- {w}" for w in qw[:10]]
        limitations_md = "\n".join(lines)

    audited_facts = ""
    if output_spec and output_spec.get("brief"):
        brief = output_spec["brief"]
        facts = output_spec.get("facts") or []
        if facts:
            audited_facts = "\n\n**Audited key facts**\n\n" + "\n".join(
                f"- {f}" for f in facts)
    else:
        brief = executive_brief or _synthesize_brief(greysearch_result)
    overview = _synthesize_overview(greysearch_result)
    steps = extract_steps_from_sources([s["prose"] for s in breakdown_sections])

    ladder = greysearch_result.get("ladder_lane") or greysearch_result.get("fill_lane")
    if ladder:
        sources.append({"name": f"search lanes used: {ladder}", "url": ""})

    md = publish(
        title=title,
        executive_brief=brief + audited_facts,
        overview=overview,
        breakdown_sections=breakdown_sections,
        comparative_tables=comparative_tables,
        steps=steps,
        sources=sources,
        write_to=write_to,
    )
    if limitations_md:
        # heading-agnostic: the sources section is located the way the
        # scrubber and the site renderer do (primary sources / sources /
        # references / citations, optional numbered prefix stripped) so a
        # template whose numbering shifts can never misplace the block.
        # Related research is excluded on purpose: that section is
        # appended after publish and never exists here yet.
        _src_head = re.compile(
            r"(?im)^(##\s*(?:\d+(?:\.\d+)?\.?\s+)?"
            r"(?:primary sources|sources|references|citations)\b[^\n]*)$")
        _m = _src_head.search(md)
        if _m:
            md = (md[:_m.start(1)] + limitations_md + "\n\n---\n\n"
                  + md[_m.start(1):])
        else:
            md = md.rstrip() + "\n\n---\n\n" + limitations_md + "\n"
        if write_to:
            _atomic_write_text(write_to, md)
    return md

if __name__ == "__main__":
    demo = {"pages_fetched": [{"title": "Demo Source", "url": "https://example.com/article",
                               "text": "First paragraph of a real article.\n\n"
                                       "Step 1: install the package with pip install demo-tool.\n\n"
                                       "Step 2: run demo-tool --init to create the config.",
                               "tables": [{"caption": "Demo spec", "rows": [["Field", "Value"],
                                                                          ["latency", "10ms"]]}],
                               "images": [{"src": "https://example.com/diagram.png", "alt": "diagram"}],
                               "links": [{"href": "https://example.com/docs", "text": "docs"}],
                               "code_blocks": [], "videos": []}],
                       "findings": [{"text": "Demo finding sentence for the brief.",
                                     "source_domains": ["example.com"], "source_urls": [],
                                     "tier": "unlisted", "score": 2}],
                       "searches": []}
    md = publish_from_greysearch("Demo Guide", None, demo, write_to="/tmp/demo-guide.md")
    print(md[:1500])