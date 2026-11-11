#!/usr/bin/env python3
"""guide_scrub.py: navigation-chrome scrubber for Master Guide markdown.

Guides must not carry giant nav-link lists; links stay only where they lead to
a direct source. The full-page captures drag site navigation (chart menus,
footer link farms, biblio-tool babble, share buttons, screenshot marketing
images) into the guide text. This module removes that chrome:

  A. nav-link-storm runs: >=5 consecutive short punctuation-less lines
     (menu-item lists) are dropped wholesale
  B. glued nav residue: inside executive-brief lines, the tail from the first
     commerce/navigation anchor ("Join Now", "API licensing", ...) is cut
  C. footer/boilerplate junk lines (copyright, zoom hints, subscribe nags,
     share rows, "What is X?" biblio babble, pricing rows)
  D. lines that are only a bare URL outside the sources/related sections
  E. junk screenshot/logo/banner image lines
  F. related-research/link-farm sections are dropped entirely. Sources /
     Primary Sources / References / Citations are CITATIONS, not a link wall:
     those blocks are protected verbatim (bare URLs and links included) and
     restored untouched after the scrub.

  G. content-level chrome (a guide must not keep links pointing at sections
     that do not exist, so dead section stubs are scrubbed too):
     - navbox/TOC dumps: "show History", "show Hacker culture", "vte ...",
       "Authority control databases", "Contents hide (Top)", "Part of a
       series on", "Jump to content / Main page / Contents" link rows
     - marketing CTA blocks: "Get the guide/report", "Read the report",
       "Subscribe", newsletter signup forms, "Watch the webinar/podcast",
       "Listen to", "Explore ... solutions/services", "Request a quote",
       "Free demo", "Take the next step"
     - sponsored/ad blocks: "AD FEATURED", "SPONSORED", "SCHOOL NAME PROGRAM
       MORE INFO", degree-program spam tables
     - image-alt spam: consecutive lines that are just an image's alt text
       repeated (Wikipedia/Wikimedia pattern: "Computer security - Wikipedia"
       five times)
     - Wikipedia "edit" suffixes glued to headings: "Historyedit",
       "Vulnerabilities and attacksedit" -> "History", "Vulnerabilities and attacks"
     - "This page was last edited on ... at ... (UTC). Page was rendered with
       Parsoid. Text is available under the Creative Commons..." footer
     - off-topic drift: a section whose token overlap with the guide's own
       title is near zero is quarantined out of the output and recorded in
       stats, so off-topic scraped content cannot reach the published site

Protected everywhere (verbatim): headings, tables, code fences, and the H1.
Sites/links policy at build time lives in greysearch_site_builder.py (link
unwrap). The original guide is left byte-identical unless this CLI is run
with --write (it then saves a .md.orig next to each file first).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BRIEF_CUT_ANCHORS = (
    "Join Now", "API licensing", "Make us preferred", "Sign In", "Sign Up",
    "Create Free Account", "Create Account", "INVEST NOW", "Invest Now",
    "Access Chart Alerts", "Faster Updating Charts", "Tradingview Indicators",
    "Need this data in your product", "Documentation Copy page",
    "Open Our ETFs", "Our ETFs Open", "Skip to content", "Skip to main content",
    "Original Article", "Make us preferred on Google", "Subscribe Now",
    "Log In", "Start Free", "Get Started", "View PDF", "Focus to learn more",
    "Show source table", "Image Source", "Learn More", "Watch Now",
)
LEVEL_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:eli5|undergrad|grad|phd|implementation)\b[^\n]*$", re.I)
EXEC_RE = re.compile(
    r"^\s*(?:>\s*)?\*\*(?:Executive Brief|ELI5|Undergrad|Grad|PhD|Implementation)"
    r"(?:[^*]*)?\*\*", re.I)

def _nav_line(s: str) -> bool:
    t = s.strip()
    if not (4 <= len(t) <= 90):
        return False
    if re.match(r"^[#>|!]|^\s*[-*+] |^\s*\d+\.\s", t):
        return False
    if t.endswith((".", "!", "?", ";", ":", ")")) and ":" not in t[:-1]:
        return False
    if re.search(r"\[[^\]]+\]\(", t) or re.match(r"^https?://", t):
        return True
    if re.match(r"^[A-Z0-9¢₿$'\"“ \-–—/&,:%().+]+$", t) and not re.search(
        r"\b(\w+ing|\w+ed)\b", t):
        return False
    return True

JUNK_LINE_RE = re.compile(
    r"^(\s*)(©|copyright\b|all rights reserved|loading\s*\.*$|powered by\b"
    r"|make us preferred\b|zoom in with\b|zoom in on\b|reset: double click"
    r"|need this data in your product|access chart alerts|faster updating charts"
    r"|private tradingview indicators|insight reports|subscription term"
    r"|current plan|upgrade\b|log in$|sign in$|sign up$|create free account$"
    r"|newsletter\b|skip to (main )?content$|original article$|image source$"
    r"|view pdf$|view pdf html|focus to learn more$|learn more$|cancel anytime"
    r"|about us\b|advertise\b|cookie policy|privacy policy|terms of (use|service)"
    r"|editorial process|careers$|contact us$|follow us\b|investing simulator"
    r"|banking$|personal finance$|economy$|reviews$|dictionary$|skip to main"
    r"|what is (the |connected |litmaps |alphaxiv |dagshub |gotitpub |huggingface )"
    r"|what are (smart citations|influence flowers|mathjax)?|bibliographic (and |explorer |tools)"
    r"|literature and citation|export bibtex|cite as\b|submission history"
    r"|current browse context|< prev|next >|new \| recent|report issue"
    r"|member institutions|research conducted for educational|simons foundation"
    r"|\d+ (free|free ) bitcoin charts|100\+ free bitcoin charts"
    r"|your view of this chart is limited|subscribe here\.?$"
    r"|view the (bitcoin )?fear ?\&? ?greed|charts\.bitbo\.io$|bitbo news$"
    r"|free basic charts|macro suite|portfolio tools|complete access"
    r"|alerts —|alerts\b ?—|downloadable data|university suite|api licensing"
    r"|\[?skip to main content\]?\(.*\)|^top picks?$|^buy btc\b|best sites to buy"
    r"|mcp ask your|terminal every btc|unlock \d+\+? private charts"
    r"|make.{0,12}google|original article)",
    re.I)

URL_RE = re.compile(r"https?://\S+")

NESTED_LINK_IN_ANCHOR_RE = re.compile(
    r"(?<!\!)\[[^\]]{0,300}\n-?\s*\[[^\]]{1,40}\][^\]]{0,800}\]"
    r"\(https?://[^)]+\)")

def _only_url(s: str) -> bool:
    t = URL_RE.sub("", s)
    return len(re.sub(r"[\s\|\-\(\)\[\]\.>,•*~`#]", "", t)) <= 16

JUNK_IMG_RE = re.compile(
    r"!\[\s*([^\]]*?)\b(?:screenshot|screen shot|banner|nav|menu|subscribe|"
    r"logo|powered by|buy now|join now|free trial|get started|promo)\b"
    r"[^\]]*\]?\(",
    re.I)
JUNK_IMG_URL_RE = re.compile(
    r"https?://[^)]*(?:/icons?/|/img/icons/|_1px\.|favicon|sprite|placeholder"
    r"|/buttons?/|/banners?/|loading|spinner|tracking|pixel\.|1x1"
    r"|default[_-]?(image|img|avatar|profile|user|thumb))", re.I)

SCHEME_RE = re.compile(r"(?i)^[a-z][a-z0-9+.\-]+://")
IMG_SRC_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CREDIT_OPEN_RE = re.compile(r"^\*Image:")
_CREDIT_CLOSE_RE = re.compile(r"\*\s*$")
_MD_STRUCT_RE = re.compile(r"^(?:#|\||!\[|[-+] |\d+\. |```|>)")

def _img_src_of(ln: str) -> str | None:
    """The paren-target (src) of an md image within ln, or None."""
    m = IMG_SRC_RE.search(ln)
    return m.group(1) if m else None

def _drop_paired_credit(lines: list, img_idx: int) -> int:
    """After a standalone image line at lines[img_idx] is dropped, also drop
    its paired "*Image: ...*" provenance credit, which may span one or many
    lines: the scraper can wrap a figure caption across lines with a blank
    inside the "*...*" span, e.g. "Software:/The Tcpdump team/Screenshot:/
    blank/VulcanSphere, BSD via Wikimedia Commons.*". Returns the next loop
    index. Bounded at 15 lines and aborts at structural markdown, so real
    prose following a stray opening "*Image:" can never be eaten."""
    n = len(lines)
    i = img_idx + 1
    while i < n and not lines[i].strip():
        i += 1
    if i >= n or not _CREDIT_OPEN_RE.match(lines[i].strip()):
        # no credit block follows: the caller's loop must STILL advance
        # past the junk image line itself; returning img_idx would re-test
        # that same line forever (a bare credit-less junk image once spun
        # scrub_guide_md for minutes before this guard existed); never
        # return a value the caller has already used
        return img_idx + 1
    blk = i
    stop = min(n, i + 15)
    j = i
    while j < stop and not _MD_STRUCT_RE.match(lines[j].strip()):
        j += 1
        if _CREDIT_CLOSE_RE.search(lines[j - 1].strip()):
            del lines[blk:j]
            return blk
    # no credit block follows: the caller's loop must STILL advance past
    # the junk line itself; returning img_idx would re-test the same line
    # forever (a bare credit-less junk image once spun scrub_guide_md for
    # minutes before this guard existed); never return a value the caller
    # has already used
    return img_idx + 1

def _is_local_img_line(ln: str) -> bool:
    """True when ln's md image src is a scheme-less LOCAL path (a chosen
    confirm-grid candidate copied beside the md, or a guide-author asset)."""
    src = _img_src_of(ln)
    return bool(src) and not SCHEME_RE.match(src)

PROTECT_HEAD_RE = re.compile(
    r"^\s*##?\s*(?:\d*\.?\s*)?(primary sources|related research|sources\b)", re.I)
KEEP_URL_SECTION_RE = re.compile(
    r"(?i)^\s*(?:#+\s*)?(?:\d+(?:\.\d+)?\.?\s+)?"
    r"(?:primary sources|sources|references|citations)\b[^\n]{0,60}$")
DROP_SECTION_RE = re.compile(
    r"^\s*##?\s*(?:\d*\.?\s*)?(primary sources|related research|sources\b"
    r"|references\b|citations\b|external links\b|further reading\b"
    r"|see also\b|bibliography\b)", re.I)

# Named gating constants for the off-topic quarantine: these rules edit
# PUBLISHED SITE content. A guide section whose body words barely overlap the
# guide's own title tokens (and whose heading doesn't either) is quarantined
# out of the site by _quarantine_offtopic_sections and listed in the Research
# limitations block. Sections shorter than OFFTOPIC_MIN_SECTION_WORDS are
# exempt (too little text to judge); the stop-word tuple keeps generic guide
# words out of the title-token set.
OFFTOPIC_MIN_SECTION_WORDS = 80
OFFTOPIC_BODY_OVERLAP_FLOOR = 0.02
OFFTOPIC_HEADING_OVERLAP_FLOOR = 0.15
OFFTOPIC_STOP_TOKENS = {"guide", "master", "research", "everything", "complete",
                        "ultimate", "introduction", "overview", "what", "your",
                        "with", "from", "into"}
PROSE_UNWRAP_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:personiq\.io|tracerfy\.com|proptream\.com"
    r"|batchleads\.com|skipgenie\.com|thatsthem\.com|beenverified\.com"
    r"|spokeo\.com|intelius\.com|truthfinder\.com|whitepages\.com"
    r"|fastpeoplesearch\.com|peekyou\.com|pipl\.com|linkedin\.com"
    r"|facebook\.com|twitter\.com|x\.com|instagram\.com|reddit\.com"
    r"|youtube\.com|tiktok\.com|pinterest\.com)\b", re.I)
H2_H3_RE = re.compile(r"^\s*##+ ")

TABLE_RE = re.compile(r"^\s*\|")
FENCE_RE = re.compile(r"^\s*```")

def _protect_keep_sections(md_text: str) -> tuple[str, list[tuple[str, str]]]:
    """Swap each sources/references/citations block (heading + body, up to the
    next markdown heading) for a placeholder. The block is restored verbatim
    after the chrome scrub, so its bare URLs and links stay intact."""
    lines = md_text.split("\n")
    out: list[str] = []
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if KEEP_URL_SECTION_RE.match(lines[i].strip()):
            j, fence = i + 1, False
            while j < len(lines):
                if FENCE_RE.match(lines[j]):
                    fence = not fence
                elif not fence and H2_H3_RE.match(lines[j]):
                    break
                j += 1
            block = "\n".join(lines[i:j])
            placeholder = f"#KEEP-URL-SECTION-{len(blocks)}#"
            blocks.append((placeholder, block))
            out.append(placeholder)
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), blocks

def _restore_keep_sections(txt: str,
                           blocks: list[tuple[str, str]]) -> str:
    for placeholder, block in blocks:
        txt = txt.replace(placeholder, block)
    return txt

def scrub_guide_md(md_text: str) -> tuple[str, dict]:
    stats = {"nav_runs": 0, "run_lines": 0, "brief_cuts": 0, "junk_lines": 0,
             "bare_urls": 0, "junk_imgs": 0, "dropped_sections": 0,
             "source_links_kept": 0, "article_links_unwrapped": 0,
             "article_menu_links_dropped": 0, "content_chrome": 0,
             "edit_suffix": 0, "alt_spam": 0, "offtopic_sections": []}
    md_text, keep_blocks = _protect_keep_sections(md_text)
    lines = md_text.split("\n")
    out: list[str] = []
    protected = False
    dropped = False
    fence = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if FENCE_RE.match(ln):
            fence = not fence
            out.append(ln)
            i += 1
            continue
        if fence:
            out.append(ln)
            i += 1
            continue
        if H2_H3_RE.match(ln):
            protected = False
            dropped = False
            if DROP_SECTION_RE.match(ln):
                dropped = True
                stats["dropped_sections"] += 1
                i += 1
                continue
            if _is_bot_challenge_section(ln, lines[i+1:i+8]):
                dropped = True
                stats["dropped_sections"] += 1
                i += 1
                continue
            if PROTECT_HEAD_RE.match(ln):
                protected = True
            out.append(ln)
            i += 1
            continue
        if dropped or protected:
            i += 1
            continue
        if TABLE_RE.match(ln):
            j = i
            while j < len(lines) and TABLE_RE.match(lines[j]):
                j += 1
            if _is_navbox_table(lines[i:j]):
                stats["content_chrome"] += j - i
                i = j
                continue
            out.append(ln)
            i += 1
            continue

        if _nav_line(ln):
            j = i
            while j < len(lines) and _nav_line(lines[j]):
                j += 1
            if j - i >= 5:
                stats["nav_runs"] += 1
                stats["run_lines"] += j - i
                i = j
                continue

        if _is_local_img_line(ln):
            out.append(ln)
            i += 1
            continue
        if JUNK_IMG_RE.match(ln):
            stats["junk_imgs"] += 1
            i = _drop_paired_credit(lines, i)
            continue
        if ln.strip().startswith("![") and JUNK_IMG_URL_RE.search(ln):
            stats["junk_imgs"] += 1
            i = _drop_paired_credit(lines, i)
            continue

        if EXEC_RE.match(ln):
            cut = _brief_cut(ln)
            if cut is not None:
                stats["brief_cuts"] += 1
                out.append(ln[:cut].rstrip())
                i += 1
                continue

        s = ln.strip()
        if s and JUNK_LINE_RE.match(s):
            stats["junk_lines"] += 1
            i += 1
            continue

        if s and (NAVBOX_LINE_RE.match(s) or MARKETING_CTA_RE.search(s)
                  or WIKI_FOOTER_RE.search(s)):
            stats["content_chrome"] += 1
            i += 1
            continue

        if re.search(r"\w{3,}edit\b", ln):
            ln = re.sub(r"(\w)edit\b", r"\1", ln)
            stats["edit_suffix"] += 1

        if URL_RE.search(s) and _only_url(s) and not IMG_SRC_RE.search(s):
            # the alt text of a short-captioned remote image ("![Corey
            # Mcmullen](https://...jpg)") is <=16 leftover chars, so this
            # bare-URL rule once read the whole image line as a bare link
            # and deleted real content images, dropping the photographer
            # credit with them; md image lines get their own junk branches
            # above, so anything still standing here is content, never a
            # bare URL
            stats["bare_urls"] += 1
            i += 1
            continue

        out.append(ln)
        i += 1

    txt = "\n".join(out)
    txt = re.sub(
        r"(?<!\!)\[[^\]]{300,20000}\]\((https?://[^)]+)\)",
        lambda m: "" if (IMG_HOST_RE.search(m.group(1))
                         or ASSET_LINK_RE.search(m.group(1)))
        else m.group(0),
        txt)

    txt = "\n".join(out)
    txt = _strip_alt_spam(txt, stats)

    txt = _quarantine_offtopic_sections(txt, stats)

    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = _strip_article_section_links(txt, stats)
    txt = _restore_keep_sections(txt, keep_blocks)
    stats["source_links_kept"] = len(re.findall(
        r"\[[^\]]+\]\(https?://[^)]+\)", txt))
    return txt, stats

ARTICLE_H3_RE = re.compile(
    r"^###\s+.+\s[|—–-]\s*[A-Z][^|—–]{2,40}\s*$")
ARTICLE_H3_LONG_RE = re.compile(
    r"^###\s+.{50,200}$")

def _is_article_h3(ln: str) -> bool:
    if not ln.startswith("###"):
        return False
    if ARTICLE_H3_RE.match(ln):
        return True
    if ARTICLE_H3_LONG_RE.match(ln):
        t = ln[3:].strip()
        if not re.search(r"[.!?]\s*$", t) and not t.endswith(":"):
            return True
    t = ln[3:].strip()
    if 10 <= len(t) <= 49 and not re.search(r"[.!?]\s*$", t):
        if re.search(r"\b(ETF|ETFs|Bitcoin|BTC|MSTY|NVDY|Yield|Strategy|Schedule"
                     r"|Analysis|Comparison|Dashboard|Charts?|Indicators?|Guide"
                     r"|Data|Price|Yield|Holdings|Performance|Portfolio)\b", t):
            return True
        if re.match(r"^(Just a moment|Page Not Found|Attention Required"
                     r"|Access Denied|503|404)\b", t, re.I):
            return True
    return False

BOT_CHALLENGE_RE = re.compile(
    r"^(This website uses a security service|Ray ID:|Performance and Security "
    r"by Cloudflare|Just a moment|Checking your browser|Please verify you "
    r"are human|DDoS protection|Enable JavaScript)", re.I)

NAVBOX_LINE_RE = re.compile(
    r"^(show\s+(History|Hacker culture|Conferences|Cybercrime|Hacking tools"
    r"|Practice sites|Malware|Cybersecurity domains|Groups|Publications"
    r"|Computer science|Information security)|vte\b|Authority control databases"
    r"|Part of a series on|Contents hide|Jump to (content|navigation|search)"
    r"|Main page$|^Contents$|Categories:)", re.I)
NAVBOX_VOCAB_CELL = re.compile(
    r"^(show|vte|hide|contents|edit|talk|view|history|jump to|main page"
    r"|categories|special pages|printable version|permanent link"
    r"|page information|cite this page|wikidata item|authority control"
    r"|software|freeware|operating systems|common features|part of a series"
    r"|computer hacking|computer security|computer science|information security"
    r"|process management|interrupts|memory management|file system"
    r"|device drivers|networking|security|input/output"
    r"|\{\{.*\}\}|\[\[.*\]\]|←|→|‹|›|\s*)$", re.I)

def _is_navbox_table(block_lines) -> bool:
    """True when a consecutive run of table rows is a navbox (Wikipedia
    'show | vte' scaffolding): >=3 rows and >=70% of cells are navbox vocab."""
    rows = 0
    vocab_cells = 0
    total_cells = 0
    for ln in block_lines:
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows += 1
        for c in cells:
            total_cells += 1
            if NAVBOX_VOCAB_CELL.match(c):
                vocab_cells += 1
    return rows >= 3 and total_cells > 0 and vocab_cells / total_cells >= 0.7
NAVBOX_ROW_RE = re.compile(
    r"^\s*\|(?=\s*(?:show\s+\w|vte\b|Hide\b|Contents\b|edit\b|talk\b"
    r"|view\b|history\b|Jump to|Main page|Categories\b|Authority control"
    r"|Special pages|Printable version|Permanent link|Page information"
    r"|Cite this page|Wikidata item|\[edit\]))",
    re.I)
NAVBOX_VOCAB = re.compile(
    r"^(show|vte|hide|contents|edit|talk|view|history|jump to|main page"
    r"|categories|special pages|printable version|permanent link"
    r"|page information|cite this page|wikidata item|authority control"
    r"|software|freeware|operating systems|common features|part of a series"
    r"|computer hacking|computer security|computer science|information security"
    r"|process management|interrupts|memory management|file system"
    r"|device drivers|networking|security|input/output"
    r"|\{\{.*\}\}|\[\[.*\]\]|←|→|‹|›)$", re.I)
MARKETING_CTA_RE = re.compile(
    r"(Get the (guide|report)|Read the (report|guide|article)|Subscribe\b"
    r"|newsletter|Watch the (webinar|latest|podcast)|Listen to|Explore (IBM|"
    r"Fortinet|our|Cisco).{0,40}(solutions|services|security)|Request a (quote|"
    r"demo)|Free demo|Take the next step|Learn fast from expert|Join security "
    r"leaders|All fields required|Your subscription will be delivered|unsubscribe "
    r"link|cookie preferences|Accept All|More options|SCHOOL NAME.*PROGRAM"
    r"|MORE INFO|Southern New Hampshire|UC Berkeley School of Information"
    r"|AD FEATURED|SPONSORED|Sponsored Ad|ONLINE PROGRAMS|ONLINE BACHELOR"
    r"|ONLINE MASTER|ONLINE PHD|BOOTCAMPS|CERTIFICATIONS\b.*AZURE"
    r"|RESOURCE CENTER|INDUSTRIES$|PODCAST|WEBINAR|On-demand webinars"
    r"|Editors$|Staff (Editor|Writer)|Written by|Last updated:"
    r"|Would your team catch|Join (security leaders|thousands)"
    r"|CommunityShare knowledge|DeveloperAccess digital|DocumentationUnderstand"
    r"|ImplementationDrive|TrainingDevelop|Technology Lifecycle"
    r"|First name|Last name|Business email|We appreciate your feedback"
    r"|SUBMIT$|Terms & Conditions|Your Privacy Choices"
    r"|Holy See|Sint Maarten|I consent to receive"
    r"|PRODUCTS\s+MSSP|PARTNERS\s+TRUST|REQUEST A QUOTE"
    r"|CONNECT WITH US|Of Interest|Explore .* (solutions|services)"
    r"|Discover (IBM|Fortinet)|Read the latest|Footnotes$"
    r"|GFG App on (Play|App) Store|App on (Play|App) Store"
    r"|Corporate & Communications Address|Registered Address"
    r"|Trending Technologies|POTD |DSA |GATE "
    r"|accessibility_testing_methods|major_cyber_attacks"
    r"|AD FEATURED CYBERSECURITY|ONLINE PROGRAMS Master"
    r"|Why readers trust|500,000\+ annual visitors"
    r"|750\+ cybersecurity degree|80\+ expert contributors"
    r"|50\+ free career|^Podcast |^PODCAST"
    r"|Written by Steven Bowcut|With over 30 years of experience"
    r"|This guide is intended to provide an introduction"
    r"|Beginning with a few of the relevant terms"
    r"|The challenge of securing personal information"
    r"|Motivated by politics, social activism, or greed, threat actors"
    r"|This evolving threat landscape has also fueled growth"
    r"|But a more pertinent question|Services$"
    r"|Watch the latest|Security Intelligence \| \d+"
    r"|Learn more about (cyber|phishing|ethical)"
    r"|About cookies on this site|Our websites require some cookies"
    r"|Explore every facet|The 2026 Guide to Cybersecurity"
    r"|Cybersecurity guide Cybersecurity in the era"
    r"|Editors$|Staff Editor$|Staff Writer$|Senior AI Advocate"
    r"|Matthew Kosinski|Bryan Clark|Mark Scapicchio"
    r"|Alexandra Jonker|Gregg Lindemulder"
    r"|Explore tutorials|Expand your skills"
    r"|IAM explainer|What is identity and access management"
    r"|Cost of a Data Brereach|Cost of a Data Breach Report 2026"
    r"|KuppingerCole report|TEI report|Gartner Market Guide"
    r"|On-demand webinars|Security tutorials|Cybersecurity guide"
    r"|Take the next step|Discover IBM|Explore IBM"
    r"|CommunityShare|DeveloperAccess|DocumentationUnderstand"
    r"|ImplementationDrive|TrainingDevelop|Technology Lifecycle"
    r"|IBM Cloud platform|Access subject matter experts"
    r"|IBM Guardium|Protect your most critical data"
    r"|Transform your security|Transform your business"
    r"|A light bulb with an explosion"
    r"|IBM-Guardium-Data-Protection-Social-Asset"
    r"|Can you trust your recovery strategy"
    r"|Smarter AI governance|governance and security into drivers"
    r"|See why KuppingerCole ranks"
    r"|The total economic impact|Discover the benefits and ROI"
    r"|Access this Gartner|AI TRiSM|trust for all AI use cases"
    r"|Follow clear steps|complete tasks and learn how"
    r"|Explained: How It Works|identity and access management \(IAM\)"
    r"|Cybersecurity statistics|Cybersecurity Mesh|Cyber Insurance"
    r"|What is a Cyber|What is Cyber Safety|What is Cyber Attack"
    r"|IT vs OT|AI Cybersecurity|Privacy Policy$|cookie preferences"
    r"|Back to top|Can't find what you're looking for"
    r"|Useful links|GCHQ MI5|Was this article helpful"
    r"|Yes$|No$|Home X LinkedIn|Instagram Threads RSS"
    r"|CyberGlossary|Multi-Layered Defense"
    r"|2026 THREAT LANDSCAPE|2026 Global Threat Landscape"
    r"|Key Takeaways|Download Now|Click to See Larger"
    r"|A rising challenge|Build core skills|With IBM SkillsBuild"
    r"|The different types of cybersecurity|types of cyberattacks"
    r"|most common types of cyberattacks|Common cybersecurity myths"
    r"|Myth #|myths persist|cybersecurity best practices"
    r"|Data security tools$|Identity and access management$"
    r"|Attack surface management$|Threat detection and response$"
    r"|Disaster recovery$|Managed security$|10 cybersecurity best practices"
    r"|How to choose the right cybersecurity"
    r"|Converge key networking|single source of threat intelligence"
    r"|single-pane-of-glass|Hybrid Mesh Firewall"
    r"|Fortinet's cybersecurity platform|Fortinet Security Fabric"
    r"|Secure Networking:|Security Operations:|FortiSASE"
    r"|Rising cyber threats put your cloud"
    r"|Cybersecurity FAQs|How can businesses ensure"
    r"|How often should an organization|What cybersecurity regulations"
    r"|Cybersecurity Resources|Cyber Threat Intelligence"
    r"|What is Cyber Safety|IT vs OT Cybersecurity"
    r"|Please fill out the form|knowledgeable representative"
    r"|A complex networking and application infrastructure"
    r"|Understanding the criteria for a cyber threat"
    r"|Six cyber threats|Essential cybersecurity components"
    r"|Key cybersecurity technologies|Cybersecurity infographic"
    r"|Cyber resilience lifecycle|What is Cybersecurity\?$"
    r"|fortinet security fabric pillar|Click to See Larger Image"
    r"|Diagram showing the six core domains"
    r"|How training and managed services|FortiAI applies"
    r"|Automated threat detection:|Autonomous incident response:"
    r"|Behavioral analytics:|AI-powered threat intelligence:"
    r"|Agentic AI and autonomous|Post-quantum cryptography"
    r"|Regulatory acceleration|Platform convergence"
    r"|Cybersecurity workforce gap|How AI is transforming"
    r"|Strategic cybersecurity tools|Advanced cybersecurity solutions"
    r"|Data loss prevention \(DLP\)|Endpoint detection and response \(EDR\)"
    r"|Intrusion prevention systems \(IPS\)|Next-generation firewalls"
    r"|Secure access service edge|SASE combines"
    r"|Security information and event management"
    r"|Security orchestration, automation|SOAR platforms"
    r"|Emerging trends driving cybersecurity"
    r"|Key cybersecurity trends shaping"
    r"|Fortinet's analysis of AI|skills-based hiring"
    r"|Cybersecurity certification programs|Cybersecurity awareness"
    r"|Managed cybersecurity services|hybrid of both"
    r"|MDR, or managed detection|XDR, or extended detection"
    r"|MSSPs give organizations|hybrid environments, including"
    r"|Use frequent, periodic data backups|Implement multi-factor"
    r"|Provide ongoing cybersecurity training|Use proper password hygiene"
    r"|Leverage encryption software|Regularly update software"
    r"|Limit user privileges|Develop an incident response plan"
    r"|Segment the network|Conduct regular security audits"
    r"|Also read through this elaborate checklist"
    r"|Spotting and preventing cyberthreats|harden U.S. government"
    r"|Cybersecurity isn't a singular solution"
    r"|Network security safeguards communication"
    r"|Information security, or InfoSec|Cloud security refers"
    r"|Endpoint security focuses|Application security refers"
    r"|Zero trust security is|Zero trust is a modern"
    r"|Operational technology \(OT\)|IoT security also focuses"
    r"|Identity security and access management"
    r"|AI security is an emerging|AI governance is becoming"
    r"|In this context, AI security refers"
    r"|Critical infrastructure security protects"
    r"|Network security focuses on preventing"
    r"|Application security \(AppSec\)|Modern application development"
    r"|Cloud security secures an organization"
    r"|Information security \(InfoSec\) protects"
    r"|Identity security focuses on protecting"
    r"|discover, analyze, remediate and monitor"
    r"|continuous discovery, analysis, remediation"
    r"|Security information and event management \(SIEM\)"
    r"|managed detection and response combines"
    r"|extended detection and response takes"
    r"|firewall management to more advanced"
    r"|consistent coverage and faster response"
    r"|threat intelligence, security tooling"
    r"|threat actors online$.Financial Times"
    r"|National Cyber Force|National Cyber Strategy of the United"
    r"|University Libraries UNT|white house$|US gov\."
    r"|Executive Order on Improving|full text\) White"
    r"|National security strategy.*PDF"
    r"|Biden Adviser On Cyber Threats"
    r"|NPR\. Executive Order|NPR\.|Kelly, Mary Louise"
    r"|Sanger, David \(5 June|Barrett, Devlin|Zengerle, Patricia"
    r"|Risen, Tom|Liptak, Kevin|Gallagher, Sean"
    r"|Davis, Michelle|Perlroth, Nicole|Newman, Lily"
    r"|Seipel, Hubert|Riley, Michael|Elgin, Ben"
    r"|Matlack, Carol|Rosenblatt, Seth|Cowley, Stacy"
    r"|Sanger, David E|Neumann, P. G|Dillingham, Gerald"
    r"|Kang, Cecilia|Checkoway, Stephen|Greenberg, Andy"
    r"|Kirk, Jeremy|Kaiser Health News|The Daily Beast"
    r"|Backman, Melvin|Palilery, Jose|Pagliery, Jose"
    r"|Turton, W\.|Finkle, Jim|Cesar, Alan|Kuchler, Hannah"
    r"|Kruse, CB|Singh, Jatinder|Krishnan, Anant"
    r"|Schectman, Joel|Bing, Christopher|Branch, Jordan"
    r"|Costigan, Sean|Hennessy, Michael|Chwan-Hwa"
    r"|Fuller, Christopher|Bob, Yonah|Lee, Newton"
    r"|Lin, Tom C\.|Cole, Jeffrey|Schariati, Marzieh"
    r"|Montagnani, Maria|Calder, Alan|Johnson, A\."
    r"|Foreman, Park|Oppliger, Rolf|Woodie, Alex"
    r"|Walkowski, Debbie|Jannsen, Cory|Irwin, Luke"
    r"|Souppaya, Murugiah|Scarfone, Karen|Stoneburner, G"
    r"|Ferraiolo, D\.F|Sandhu, R;|Abreu, Vilmar"
    r"|Harrison, J\.|Hassija, Vikas|Tomlinson, Ray"
    r"|Neumann, A\. J|Yost, Jeffrey|Misa, Thomas"
    r"|Greene, James|Cook, James|Anderson, Nate"
    r"|Bright, Peter|Scannell, Kara|Lazar, Ari"
    r"|York, Dan|Butterfield, Andrew|Marcel, Sébastien"
    r"|Gallagher, Sean|Lim, Joo S|Arcos Sergio"
    r"|Millman, Renee|Treglia, J|Delia, M"
    r"|Reimers, Karl|Andersson, David|Schlienger, Thomas"
    r"|Teufel, Stephanie|Walker, John|Caldwell, Tracey"
    r"|Kaljulaid, Kersti|Kuchler, Hannah|Clearfield, Chris"
    r"|Vermesan, Ovidiu|Friess, Peter|Sztyber-Betley"
    r"|Sanghavi, Alok|Bullard, Brittany|Oltsik, Jon"
    r"|Robinson, Terry|de Silva, Richard|Verton, Dan"
    r"|Largent, Jonathan|Leswing, April|Thompson, Zan)"
    r"|Pauli, Darren|Cook, James|Lee, Timothy"
    r"|Zetter, Kim|Reals, Tucker|Nakashima, Ellen"
    r"|Overland, Indra|Maness, Ryan|Valeriano, Brandon"
    r"|Bullard, Brittany|Clayton, Mark|Bumgarner, John"
    r"|Shachtman, Noah|Lynn, William|Warrell, Helen"
    r"|Sengupta, Kim|Targett, Edward|Jun, Kwanwoo"
    r"|Sternstein, Aliya|Elias, Bart|Cesar, Alan"
    r"|Cashell, B|Gordon, Lawrence|Loeb, Martin"
    r"|Sanger, David E|Barrett, Devlin|Risen, Tom"
    r"|Zengerle, Patricia|Davis, Michelle|Perlroth, Nicole"
    r"|Treglia, J|ROhM|Crime$|Computer Crime"
    r"|HBGary|Anonymous hack|LulzSec|Antisec"
    r"|WikiLeaks|Guccifer|DCLeaks|Fancy Bear"
    r"|Cozy Bear|Energetic Bear|Sandworm|Turla"
    r"|APT28|APT29|Equation Group|Carbanak"
    r"|FIN7|FIN8|TA505|Wizard Spider"
    r"|Conti |Ryuk |REvil |Sodinokibi"
    r"|DarkSide|BlackMatter|LockBit"
    r"|ALPHV|BlackCat|Clop|Cl0p"
    r"|Play ransomware|Royal ransomware"
    r"|Akira |Qilin |RansomHub"
    r"|Medusa |Hunters International"
    r"|DragonForce|Gentlemen|Palo Alto"
    r"|Unit 42|Mandiant|Google Threat"
    r"|Recorded Future|CrowdStrike |SentinelOne"
    r"|Microsoft Threat|Volexity|ESET |Bitdefender"
    r"|Kaspersky|Symantec|McAfee|Trellix"
    r"|Palo Alto Networks|Check Point|Fortinet"
    r"|Zscaler|SentinelOne|Carbon Black"
    r"|Vectra AI|Darktrace|ExtraHop"
    r"|Nozomi Networks|Claroty|Dragos"
    r"|Tenable|Qualys|Rapid7"
    r"|Cisco Talos|IBM X-Force|Google Cloud"
    r"|Unit 42 Cloud|Threat Intelligence Index"
    r"|Cost of a Data Breach Report"
    r"|X-Force Threat Intelligence Index"
    r"|Threat Intelligence Index 2026"
    r"|Cost of a Data Breach 2026"
    r"|IBM X-Force®"
    r"|Guardium®"
    r"|FortiAI|FortiSASE|FortiEDR|FortiXDR"
    r"|Security Fabric|Hybrid Mesh Firewall"
    r"|Gartner Magic Quadrant"
    r"|Gartner Peer Insights"
    r"|Forrester Wave|KuppingerCole Leadership"
    r"|IDC MarketScape|Omdia|451 Research"
    r"|Forrester TEI|total economic impact"
    r"|Return on Investment|ROI of"
    r"|benchmark against|compared to industry"
    r"|best-in-class|leading provider"
    r"|market leader|leader in the"
    r"|recognized as a leader|positioned as a leader"
    r"|named a leader|leader for the"
    r"|customers worldwide|enterprises globally"
    r"|trusted by millions|used by millions"
    r"|over \d+ (million|billion) customers"
    r"|more than \d+ (million|billion)"
    r"|industry-leading|award-winning"
    r"|cutting-edge|state-of-the-art"
    r"|robust|comprehensive|end-to-end"
    r"|scalable|flexible|powerful solution"
    r"|seamless integration|plug-and-play"
    r"|transform your|revolutionize your"
    r"|unlock the power|leverage the power"
    r"|take your security to the next level"
    r"|stay ahead of threats|stay one step ahead"
    r"|peace of mind|sleep soundly"
    r"|protect what matters most"
    r"|your trusted partner|partner with us"
    r"|get started today|start your free trial"
    r"|sign up now|contact us today"
    r"|request a demo|schedule a call"
    r"|speak with an expert|talk to sales"
    r"|pricing starts at|plans start at"
    r"|per month\)|per year\)|per user"
    r"|billed annually|billed monthly"
    r"|no credit card required"
    r"|14-day free trial|30-day free trial"
    r"|cancel anytime|money-back guarantee"
    r"|terms and conditions apply"
    r"|all rights reserved"
    r"|© 20\d\d|©\d{4}|&copy;", re.I)
WIKI_EDIT_SUFFIX_RE = re.compile(r"\bedit\b(?=\s|$)", re.I)
WIKI_FOOTER_RE = re.compile(
    r"This page was (last edited|last modified) on|Page was rendered with "
    r"Parsoid|Text is available under the Creative Commons|additional terms "
    r"may apply|Wikipedia® is a registered trademark|By using this site, you "
    r"agree to the Terms of Use", re.I)

def _is_bot_challenge_section(heading: str, next_lines: list[str]) -> bool:
    """A section whose heading is a challenge-page title OR whose first
    non-blank lines are Cloudflare/bot-check boilerplate."""
    if re.match(r"^##+\s*(Just a moment|Page Not Found|Attention Required"
                r"|Access Denied|404|503)\b", heading, re.I):
        return True
    for ln in next_lines[:6]:
        s = ln.strip()
        if s and BOT_CHALLENGE_RE.match(s):
            return True
    return False
MENU_LINK_RE = re.compile(
    r"^\s*[-*]?\s*(?<!\!)\[[^\]]{1,60}\]\(https?://[^)]+\)\s*$")
MULTILINE_MENU_LINK_RE = re.compile(
    r"\[([^\]]{1,40}?)\s*\n\s*[^\]]{0,200}\]\(https?://[^)]+\)")
NAV_LIST_LINK_RE = re.compile(
    r"^\s*[-*]\s*(?<!\!)\[(?:https?://[^\]|]{5,80}|[A-Z][A-Za-z &/]{2,30})\]"
    r"\((https?://[^)]+)\)\s*$")
MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(https?://[^)]+\)")
ASSET_LINK_RE = re.compile(
    r"https?://[^)]*(?:wp-admin|wp-content|wp-includes|favicon\.ico"
    r"|/assets?/|/static/|/img/|/images/|/icons?/|/logos?/|/thumbs?/"
    r"|cloudflare\.com/\?utm|\.svg\b|\.ico\b|google-analytics|googletagmanager"
    r"|doubleclick|/cdn-cgi/|admin-ajax)", re.I)
MARKETING_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:binance\.com|coinbase\.com|coingecko\.com"
    r"|coindesk\.com|investopedia\.com|tradingview\.com|bitbo\.io"
    r"|charts\.bitbo\.io|lookintobitcoin\.com|myplaniq\.com"
    r"|portfolioslab\.com|dividend\.com|etfdb\.com|stockanalysis\.com"
    r"|finance\.yahoo\.com|nasdaq\.com|seekingalpha\.com"
    r"|graniteshares\.com|yieldmaxetfs\.com|bebooja\.com|weeklyyield\.com"
    r"|wisesheets\.io|fintel\.io|marketbeat\.com|simplywall\.st"
    r"|zacks\.com|fool\.com|thestreet\.com|benzinga\.com"
    r"|morningstar\.com|dividenddata\.com|defenseworld\.net"
    r"|yieldmaxcalc\.com|stockhouse\.com"
    r"|etftrends\.com|etfdb\.com|dividend\.com|nasdaq\.com)\b", re.I)
NEWSWIRE_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:globenewswire\.com|businesswire\.com"
    r"|prnewswire\.com|accesswire\.com|newswire\.ca|marketwatch\.com"
    r"|seekingalpha\.com|benzinga\.com|thestreet\.com|fool\.com"
    r"|zacks\.com|streetinsider\.com|investing\.com)\b", re.I)
CF_PRIVACY_RE = re.compile(
    r"https?://(?:www\.)?cloudflare\.com/(?:privacypolicy|privacy-policy|legal)",
    re.I)
AUTHORITY_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"(?:[a-z]+\.)?gov(?:/[a-z]{2})?\b"
    r"|(?:[a-z]+\.)?mil\b"
    r"|nist\.gov|nist\.org|iso\.org|ietf\.org|w3\.org"
    r"|en\.wikipedia\.org|wikipedia\.org"
    r"|arxiv\.org|acm\.org|ieee\.org|doi\.org"
    r"|mitre\.org|attack\.mitre\.org|cisa\.gov"
    r"|sec\.gov|ftc\.gov|fcc\.gov|justice\.gov"
    r"|europol\.europa\.eu|interpol\.int|who\.int"
    r"|irs\.gov|ssa\.gov|consumerfinance\.gov"
    r"|ec\.europa\.eu|europa\.eu"
    r"|us-cert\.circl\.lu|icann\.org"
    r"|azleg\.gov|azcourts\.gov|azsos\.gov|azdhs\.gov"
    r"|courts\.state\.[a-z]+\.us|ca\.courts\.ca\.gov"
    r"|law\.cornell\.edu|casetext\.com|justia\.com|law\.justia\.com"
    r"|congress\.gov|govinfo\.gov|uscode\.house\.gov"
    r"|azleg\.gov|legis\.laws\.com|statelaws\.findlaw\.com"
    r")", re.I)
IMG_HOST_RE = re.compile(
    r"https?://(?:storage\.googleapis\.com|static\.|assets\.|dynamic-assets\."
    r"|asset-metadata-service|images\.|thumb\.|cdn\.|media\.)"
    r"|s3\.amazonaws\.com|\.png\b|\.jpg\b|\.jpeg\b|\.webp\b|\.gif\b", re.I)

def _strip_article_section_links(txt: str, stats: dict) -> str:
    """Inside scraped-article sections (H3 page-title headings), drop
    menu-style markdown links and unwrap prose links to their anchor text."""
    txt = re.sub(
        r"\[(?:GraniteShares|YieldMax|Leverage Shares|Roundhill|Defiance"
        r"|ProShares)[^\]]{0,80}\n\s*[^\]]{10,200}\]\(https?://[^)]+\)",
        "", txt)
    def _junk_anchor(m):
        anchor, url = m.group(1), m.group(2)
        if IMG_HOST_RE.search(url) or ASSET_LINK_RE.search(url):
            return ""
        first_line = anchor.split("\n")[0].strip()
        return first_line
    txt = re.sub(
        r"(?<!\!)\[([^\]]{0,200})(?:\n- \[|\n\d+\.|\n#|\|)[^\]]{0,600}\]"
        r"\((https?://[^)]+)\)",
        _junk_anchor, txt)
    txt = MULTILINE_MENU_LINK_RE.sub(lambda m: m.group(1).strip(), txt)
    txt = MD_LINK_RE.sub(
        lambda m: m.group(1) if PROSE_UNWRAP_HOST_RE.search(m.group(0))
        else m.group(0),
        txt)
    lines = txt.split("\n")
    out = []
    in_article = False
    unwrapped = 0
    dropped = 0
    for ln in lines:
        if re.match(r"^##+ ", ln):
            in_article = _is_article_h3(ln)
            out.append(ln)
            continue
        def _drop_chrome(m):
            url = m.group(0)
            if ASSET_LINK_RE.search(url) or MARKETING_HOST_RE.search(url):
                return ""
            if NEWSWIRE_HOST_RE.search(url) or CF_PRIVACY_RE.search(url):
                return m.group(1)
            if IMG_HOST_RE.search(url):
                return m.group(1) if m.group(1).strip() else ""
            return url
        ln = MD_LINK_RE.sub(_drop_chrome, ln)
        if not in_article:
            out.append(ln)
            continue
        if MENU_LINK_RE.match(ln) or NAV_LIST_LINK_RE.match(ln):
            dropped += 1
            continue
        def _unwrap(m):
            if AUTHORITY_HOST_RE.search(m.group(0)):
                return m.group(0)
            nonlocal unwrapped
            unwrapped += 1
            return m.group(1)
        out.append(MD_LINK_RE.sub(_unwrap, ln))
    stats["article_links_unwrapped"] = unwrapped
    stats["article_menu_links_dropped"] = dropped
    return "\n".join(out)

def _strip_alt_spam(txt: str, stats: dict) -> str:
    """Drop repeated short alt-text lines. Scraped pages repeat an image's
    alt text as a plain line many times (Wikipedia footer pattern:
    'Computer security - Wikipedia' x5). Keep the first occurrence only."""
    lines = txt.split("\n")
    out = []
    seen_recent: dict[str, int] = {}
    dropped = 0
    for ln in lines:
        s = ln.strip()
        if (s and not s.startswith(("#", "|", ">", "!", "-", "*", "`"))
                and "](http" not in s and 10 <= len(s) <= 90):
            key = s.lower()
            if seen_recent.get(key, 0) >= 1 and len(out) > 3:
                dropped += 1
                continue
            seen_recent[key] = seen_recent.get(key, 0) + 1
        else:
            seen_recent.clear()
        out.append(ln)
    stats["alt_spam"] = dropped
    return "\n".join(out)

def _flag_offtopic_sections(txt: str, stats: dict, title: str = "") -> None:
    """Flag sections whose content barely overlaps the guide topic. Kept for
    back-compat (report-only); the enforcement path is
    _quarantine_offtopic_sections, which removes them."""
    kept = {"offtopic_sections": []}
    _quarantine_offtopic_sections(txt, kept, enforce=False)
    stats.setdefault("offtopic_sections", []).extend(kept["offtopic_sections"])

def _quarantine_offtopic_sections(txt: str, stats: dict, title: str = "",
                                  enforce: bool = True) -> str:
    """Quarantine (remove) sections whose content barely overlaps the guide
    topic, so off-topic scraped content can never reach the final site.

    A section whose token overlap with the guide's own title is near zero
    (and whose heading doesn't overlap either) is scraped off-topic content,
    e.g. an MDN CSS page inside a ransomware guide. Off-topic sections are
    scrubbed, not merely reported: with enforce=True (the default) the
    section (headings, prose, tables, and images) is REMOVED and recorded in
    stats["quarantined_sections"] so the caller can list it in a Research
    limitations block. The intro (text before the first "## " heading) is
    never quarantined.

    Returns the (possibly shortened) text. Signature-compatible with the old
    flag-only helper's inputs; stats gains a new key."""
    stats.setdefault("quarantined_sections", [])
    if not title:
        pass
    m = re.search(r"^#\s+(.*)$", txt, re.M)
    if not m:
        return txt
    title_tokens = set(re.findall(r"[a-z]{4,}", m.group(1).lower()))
    if not title_tokens:
        return txt
    title_tokens -= OFFTOPIC_STOP_TOKENS
    if not title_tokens:
        return txt
    lines = txt.split("\n")
    blocks: list = []
    cur_head, cur = None, []
    for ln in lines:
        if re.match(r"^## ", ln):
            if cur_head is not None or cur:
                blocks.append((cur_head, cur))
            cur_head, cur = ln, []
        else:
            cur.append(ln)
    if cur_head is not None or cur:
        blocks.append((cur_head, cur))
    out_lines: list = []
    for head, body in blocks:
        if head is None:
            out_lines.extend(body)
            continue
        words = []
        for ln in body:
            words += re.findall(r"[a-z]{4,}", ln.lower())
        section_stat = {"section": head.lstrip("#").strip()[:80]}
        if DROP_SECTION_RE.match(head) or PROTECT_HEAD_RE.match(head):
            out_lines.append(head)
            out_lines.extend(body)
            continue
        if len(words) < OFFTOPIC_MIN_SECTION_WORDS:
            out_lines.append(head)
            out_lines.extend(body)
            continue
        toks = set(words)
        overlap = len(toks & title_tokens) / max(len(title_tokens), 1)
        htoks = set(re.findall(r"[a-z]{4,}", head.lower())) - OFFTOPIC_STOP_TOKENS
        hover = len(htoks & title_tokens) / max(len(htoks), 1) if htoks else 0
        section_stat["overlap"] = round(overlap, 3)
        if (overlap < OFFTOPIC_BODY_OVERLAP_FLOOR
                and hover < OFFTOPIC_HEADING_OVERLAP_FLOOR):
            stats["offtopic_sections"].append(section_stat)
            if enforce:
                stats["quarantined_sections"].append(section_stat)
                continue
        out_lines.append(head)
        out_lines.extend(body)
    return "\n".join(out_lines)

def _brief_cut(line: str):
    for a in BRIEF_CUT_ANCHORS:
        k = line.find(a)
        if k != -1:
            if k >= 40:
                return k
    return None

def _cli(argv: list[str]) -> int:
    ap = __import__("argparse").ArgumentParser(
        description="Scrub nav chrome from Master Guides (--write to save; "
                    "creates <file>.orig backups)")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    for f in argv and args.files:
        p = Path(f)
        if not p.exists():
            print(f"  ! missing: {p}")
            continue
        md = p.read_text(errors="replace")
        new, stats = scrub_guide_md(md)
        if args.write:
            orig = p.with_suffix(p.suffix + ".orig")
            if not orig.exists():
                orig.write_text(md)
            p.write_text(new)
        print(f"  {p.name}: runs={stats['nav_runs']}({stats['run_lines']}L) "
              f"briefcuts={stats['brief_cuts']} junk={stats['junk_lines']} "
              f"urls={stats['bare_urls']} imgs={stats['junk_imgs']} "
              f"dropped={stats['dropped_sections']}s "
              f"unwrapped={stats['article_links_unwrapped']} "
              f"menu_dropped={stats['article_menu_links_dropped']} "
              f"links_left={stats['source_links_kept']}")
    return 0

if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))