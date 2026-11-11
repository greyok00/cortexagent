"""site_guardrails.py: quality gate for Greysearch site output.

A site is only reported as built cleanly when every check passes. Failures
downgrade the site entry to a warning; they never crash or block the Master
Guide.

Checks: index present, title + H1 + readable paragraphs, no broken internal
links/anchors, no missing local image files, no nav-link walls,
and per-page size sanity.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAX_PAGE_BYTES = 3 * 1024 * 1024
_LONG_TEXT_PARAS = 2
_NAV_WALL_LINKS = 30

def _text_of(html: str) -> str:
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
                 flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", txt)

# MD_SECTION_MIN_WORDS: a published section whose prose is shorter than
# this is a stub; surfaced warn-only (a section cut is always the scrub's
# decision, never this check's).
MD_SECTION_MIN_WORDS = 120

_SOURCES_HEAD_RE = re.compile(
    r"(primary sources|related research|sources\b|references\b|"
    r"citations\b)", re.I)

def check_site(out: Path, scrub_stats: dict | None = None,
               md_source: str | None = None) -> dict:
    """Quality gate for the built site. ``ok`` is decided by the
    failure-grade families that have always been here; the warn-only
    families ("warn": true; scrub_quarantined and the md checks) SURFACE
    guide-content facts without regressing the verdict; promoting a family
    to failure-grade later is a caller decision."""
    out = Path(out)
    checks: dict = {}

    def _add(name: str, ok: bool, note: str, warn: bool = False) -> None:
        entry = {"pass": bool(ok), "note": note}
        if warn:
            entry["warn"] = True
        checks[name] = entry

    index = out / "index.html"
    if not index.exists() or index.stat().st_size < 200:
        _add("index_present", False, "index.html missing or empty")
        return {"ok": False, "checks": checks}
    html = index.read_text(errors="ignore")
    n_bytes = index.stat().st_size
    _add("index_present", True, f"{n_bytes} bytes")

    _add("size_sane", n_bytes <= _MAX_PAGE_BYTES,
         f"{n_bytes} bytes (cap {_MAX_PAGE_BYTES})")

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    h1s = re.findall(r"<h1[ >]", html)
    paras = [re.sub(r"<[^>]+>", " ", seg)
             for seg in re.split(r"</p>", html)]
    good_paras = len([p for p in paras if len(" ".join(p.split())) > 120])
    total_chars = len(" ".join("".join(paras).split()))
    _add("title", bool(title and title.group(1).strip()),
         (title.group(1)[:60] if title else "missing"))
    _add("h1", len(h1s) >= 1, f"{len(h1s)} H1 element(s)")
    _add("readable_text", good_paras >= _LONG_TEXT_PARAS or total_chars > 2000,
         f"{good_paras} paragraphs >120 chars (need {_LONG_TEXT_PARAS}; "
         f"{total_chars} total chars)")

    broken, anchors = [], set(re.findall(r'id="([^"]+)"', html))
    for href in re.findall(r'href="([^"]+)"', html):
        if href.startswith(("http", "mailto:", "//")):
            continue
        frag = ""
        path = href
        if "#" in href:
            path, frag = href.split("#", 1)
        if path and not (out / path).exists():
            broken.append(href)
        elif frag and frag not in anchors:
            broken.append(href)
    _add("internal_links", len(broken) == 0,
         "all internal links resolve" if not broken
         else f"{len(broken)} broken (first: {broken[:2]})")

    missing_imgs = []
    n_imgs = 0
    for img in re.findall(r'<img[^>]+src="([^"]+)"', html):
        if img.startswith(("http", "data:", "//")):
            continue
        n_imgs += 1
        if not (out / img).exists():
            missing_imgs.append(img)
    src_imgs = 0
    if out.name.endswith("_site"):
        src = out.parent / (out.name[:-len("_site")] + ".md")
        if src.exists():
            src_imgs = len(
                re.findall(r"^!\[", src.read_text(errors="ignore"), re.M))
    _add("images", (len(missing_imgs) == 0) and
         (src_imgs == 0 or n_imgs > 0),
         f"{n_imgs} local imgs referenced on page, {len(missing_imgs)} missing, "
         f"{src_imgs} markdown-image refs in source")

    nav_clusters = re.findall(
        r"<nav.*?</nav>|<aside.*?</aside>", html, re.S | re.I) or []
    worst = 0
    for cluster in nav_clusters:
        n = len(re.findall(r"<a[ >]", cluster))
        txt = len(_text_of(cluster).strip())
        if txt < 1200:
            worst = max(worst, n)
    _add("no_nav_wall", worst < _NAV_WALL_LINKS,
         f"largest light nav cluster: {worst} links (cap {_NAV_WALL_LINKS})")

    # ---- warn-only families: they never decide "ok" ----
    if scrub_stats is not None:
        quar = scrub_stats.get("quarantined_sections") or []
        offt = scrub_stats.get("offtopic_sections") or []
        dropped = int(scrub_stats.get("dropped_sections") or 0)
        nav_runs = int(scrub_stats.get("nav_runs") or 0)
        junk_imgs = int(scrub_stats.get("junk_imgs") or 0)
        _add("scrub_quarantined", True,
             f"scrub removed {len(quar)} off-topic section(s), flagged "
             f"{len(offt)} near-miss section(s), dropped {dropped} "
             f"link-farm section(s), {nav_runs} nav runs, {junk_imgs} "
             "junk image(s)", warn=True)
    if isinstance(md_source, str):
        md = md_source
        h1s = re.findall(r"^#\s+\S", md, re.M)
        _add("md_h1_present", len(h1s) >= 1,
             f"{len(h1s)} level-1 heading(s) in the markdown source",
             warn=True)
        srcs = re.findall(
            r"^\s*##+\s*(?:\d+(?:\.\d+)?\.?\s+)?"
            r"(?:primary sources|related research|sources\b|references\b|"
            r"citations\b)", md, re.M | re.I)
        _add("md_sources_block", len(srcs) >= 1,
             f"{len(srcs)} sources-shaped heading(s) in the markdown "
             "source", warn=True)
        n_secs = 0
        short = []
        cur = None
        for line in md.split("\n"):
            mh = re.match(r"^#{1,3}\s+(.*\S)\s*$", line)
            if mh:
                if cur is not None:
                    n_secs += 1
                    if (cur["words"] < MD_SECTION_MIN_WORDS
                            and not _SOURCES_HEAD_RE.search(cur["head"])):
                        short.append((cur["head"][:48], cur["words"]))
                cur = {"head": mh.group(1), "words": 0}
            elif cur is not None:
                cur["words"] += len(re.findall(r"[A-Za-z]{2,}", line))
        if cur is not None:
            n_secs += 1
            if (cur["words"] < MD_SECTION_MIN_WORDS
                    and not _SOURCES_HEAD_RE.search(cur["head"])):
                short.append((cur["head"][:48], cur["words"]))
        _add("md_section_floors", True,
             (f"{len(short)} of {n_secs} published section(s) below "
              f"{MD_SECTION_MIN_WORDS} words, none cut "
              f"(shortest: {short[:2]})") if short else
             (f"0 of {n_secs} published section(s) below "
              f"{MD_SECTION_MIN_WORDS} words"), warn=True)
        markers = list(re.finditer(r"DATA NOT CAPTURED", md))
        loose = sum(1 for m in markers
                    if not re.search(r"^[-*]\s|\b(because|not available|"
                                     r"omitted|limited)\b",
                                     md[m.end():m.end() + 220], re.I))
        _add("md_data_not_captured_disclosed", True,
             f"{len(markers)} data-not-captured marker(s) in the source; "
             f"{loose} without a stated reason nearby", warn=True)

    ok = all(c["pass"] for c in checks.values() if not c.get("warn"))
    return {"ok": ok, "checks": checks}