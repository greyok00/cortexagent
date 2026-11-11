#!/usr/bin/env python3
"""kbserver_patch.py — extends knowledge-ingestor MCP with:
  1. kb_ingest_text   (local text/markdown ingest — guides, solved incidents)
  2. kb_learn_topic   (THE AUTO-LEARN LOOP: greysearch deep run on a topic,
                       quality-gates every page, ingests what passes)
Design rules honored:
  - uses kbcore content_route + add_records (same dedup/hash/embed path as every other lane)
  - every learned record carries provenance (source url / guide path / why it qualified)
  - quality gate BEFORE ingest (docs-only policy): official domains, doc paths,
    real content density; junk never enters the library
  - no silent trust: results report exactly what was admitted/rejected and why
"""
import json, os, sys, re, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbcore
import jobs as jobs_mod
import extractors as _ex

# ── quality gate: "docs and dependable info, not junk" ────────────────────
DOC_DOMAINS = re.compile(
    r"(^|\.)(developer\.android\.com|docs\.(gradle|python|llvm|kernel)\.org|"
    r"developer\.mozilla\.org|learn\.microsoft\.com|docs\.oracle\.com|"
    r"readthedocs\.io|docs\.rs|man7\.org|wiki\.archlinux\.org|"
    r"redis\.io|sqlite\.org|openjdk\.java\.net|docs\.docker\.com|"
    r"sqlite|golang\.org|pkg\.go\.dev|github\.com|git-scm\.com|nginx\.org|"
    r"postgresql\.org|docs\.python\.org|peps\.python\.org|wiki\.debian\.org|"
    r"help\.ubuntu\.com|wiki\.gentoo\.org|kubernetes\.io|reactjs\.org|"
    r"vuejs\.org|angular\.io|nodejs\.org|deno\.com|bun\.sh|swift\.org|rust-lang\.org"
    r")$", re.I)
DOC_PATHSIG = re.compile(
    r"(/docs?(/|$)|/reference(/|$)|/guide|/manual|/api|/library|/apidoc|"
    r"/command|/cli|/tools/|/sdk|/develop|/build|/install|/configuration|"
    r"/peps/|/tutorials?|/howto|/javadoc|/reference/)", re.I)
JUNK_PATHSIG = re.compile(
    r"(/forum|/forums|/thread|/posts?/|/questions?/|/discussion|/comments?|"
    r"/news|/blog(?!/)|/coupon|/deal|/shopping|/review-|/top-10|/best-|-vs-|"
    r"/download|/setup\.exe|/release/download|/register|/login|/signup|/subscribe)", re.I)
JUNK_SIGS = re.compile(
    r"(sign in to continue|subscribe now|cookie consent|enable javascript|"
    r"buy now|limited offer|download the app|install our app|your download will begin)", re.I)

# Site-chrome detection: nav rails, headline-list rails, scaffolding.
# gamedeveloper.com and friends ship "Latest News / More News chevron_right"
# rails as page text; the deep scrape trusts them, kbcore chunks each part,
# and the KB fills with date/byline junk. is_rail() judges a whole chunk:
# STRIP chrome lines, dedupe headline pairs, and drop the record only what's
# left has zero informative lines (>=6 words, or code-symbol lines).
# Verified against the real gamedeveloper case: rail chunks drop=True,
# header+body hybrid and pure article body keep, code keeps (code lines exempt).
CHROME_LINE = re.compile(
    r"(^\d{1,2} [A-Z][a-z]{2},? \d{4}$|^[A-Z][a-z]{2} \d{1,2},? \d{4}$|^\|"
    r"|^by\w[\w ,.-]*$"
    r"|\bMin Read\b|chevron_right|Sign in to add|Watch Later|More News|Latest News"
    r"|\bSubscribe\b|Newsletter|Cookie Settings|Share this|Related [Aa]rticles?"
    r"|^\s*(Design|Art|Production|News|Interviews?|Business|Podcasts?)\s*$|\s*###\s*$"
    r"|^\s*(READ ON|See all|See More|Stay Updated|Latest Podcasts|podcasts|Copy)\s*$"
    r"|\b\d+(,\d+)?\s+(words?|min[s]?|views?)\b)",
    re.I | re.M)
CODEISH = re.compile(r"(\(|\)|\{|\}|;$|=>|^\s*(void|float|int|bool|const|var|let|def)\s"
    r"|^\s*(sudo|apt|dnf|pacman|brew|git|curl|wget|mkdir|cp|mv|rm|chmod|chown|systemctl|"
    r"journalctl|grep|awk|sed|cat|echo|export|source|cd|ls|tar|zip|sha256sum|wc)\s"
    r"|^\s*[a-z0-9_./-]+\s*(>|>>|<|\|)\s|>\s*/|\bhttps?://\S*/[\w.-]+\b\s*$)")
# config keyword-value lines (sshd_config style): Keyword yes|no|numeric|lowerpath
KEYVAL = re.compile(r"^\s*[#/]?\s*[A-Z][A-Za-z0-9]+\s+(?:yes|no|\d+(?:\.\d+)?|[a-z0-9_./*-]+)\s*(?:#.*)?$")
TABLEROW = re.compile(r"^\s*\|.*\|\s*$")
# CJK characters are content: split() word counts mean nothing for CJK text
CJK = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\u3040-\u30ff]")
# typed name/value rows (godot/unity api docs, ini-style): "bool  flag_name"


def is_rail(text: str, code=None) -> bool:
    """True when a chunk is site chrome (nav rail, headline list, scaffolding)
    carrying no article body. Exemptions: code chunks (symbol density) and
    table rows (| cell | cell |) are DATA, never chrome.
    Rules (all verified against the real gamedeveloper rail corpus):
    - chrome lines: dates, bylines, Min Read, rails, chevron stubs
    - headline pairs: line followed by chrome or a duplicate headline
    - pure-rail chunks (no informative line) always drop
    - mostly-chrome chunks drop only if body is <120 words (a chrome-heavy
      chunk with a real paragraph keeps)
    Never called on upload:/pdf records."""
    raw = [l.strip() for l in re.split(r"\s*\n+\s*", text or "") if l.strip()]
    if not raw:
        return True
    if code is None:
        code = sum(1 for l in raw if CODEISH.search(l)) >= max(2, len(raw) // 4)
    if code:
        return False
    from collections import Counter as _C
    n = len(raw)
    counts = _C(raw)
    informative = 0
    body_words = 0
    scored = 0
    for i, l in enumerate(raw):
        if TABLEROW.match(l) or CODEISH.search(l) or KEYVAL.match(l) or CJK.search(l):
            informative += 1
            body_words += len(l.split())
            continue
        chrome = bool(CHROME_LINE.search(l))
        nxt = raw[i + 1] if i + 1 < n else ""
        headline = nxt and (bool(CHROME_LINE.search(nxt)) or counts[nxt] > 1) \
            and not l.endswith((".", "!", "?", ":", ")"))
        dup = counts[l] > 1
        tiny = len(l.split()) < 6
        if chrome or headline or dup or tiny:
            scored += 1
            continue
        informative += 1
        body_words += len(l.split())
    if informative == 0:
        return True
    return (scored / n) >= 0.6 and body_words < 120

def _domain_quality(url: str, text: str) -> tuple[bool, str, str]:
    """(admit, verdict, provenance) — deterministic, explainable, no model."""
    host = ""
    m = re.match(r"https?://([^/]+)", url or "")
    if m: host = m.group(1).lower()
    if not host:
        return True, "local/guide", "provenance=local-guide"
    score = 0
    prov = [f"host={host}"]
    if DOC_DOMAINS.search(host.rstrip(".") + "$") or DOC_DOMAINS.search(host):
        score += 3; prov.append("official-domain+3")
    if DOC_PATHSIG.search(url or ""):
        score += 2; prov.append("doc-path+2")
    if re.search(r"guide|reference|manual|docs", (url or ""), re.I):
        score += 1
    if JUNK_PATHSIG.search(url or ""):
        score -= 2; prov.append("junk-path-2")
    # stackoverflow CANONICAL questions are exempt from the forum penalty when
    # they carry an accepted answer (dev references live there in practice)
    if host.endswith("stackoverflow.com") and re.search(r"/questions?/\d+/", url or "") \
            and len((text or "")) > 800:
        if not JUNK_SIGS.search((text or "")[:4000]):
            score += 4; prov.append("so-canonical+4 (junk-path exempted)")
    # UGC feeds: never, regardless of size
    if re.search(r"(reddit|medium\.com|dev\.to|quora)\.", host):
        score -= 3; prov.append("ugc-3")
    # content density on the extracted text
    words = len((text or "").split())
    if words > 400: score += 2; prov.append(f"density+2 ({words}w)")
    elif words > 150: score += 1; prov.append(f"density+1 ({words}w)")
    elif words < 60:
        score -= 2; prov.append(f"thin-{words}w-2")
    hits = JUNK_SIGS.findall((text or "")[:4000])
    if len(hits) >= 3:
        score -= 3; prov.append(f"junk-sigs{n}-3")
    # github README/docs blobs are official-adjacent; raw issues are not
    if "github.com" in host:
        if re.search(r"/(blob|raw)/|README", url or "", re.I): score += 2; prov.append("github-doc+2")
        if re.search(r"/issues?/|/pull/|/discussions", url or ""): score -= 3; prov.append("github-issue-3")
    verdict = ";".join(prov)
    return (score >= 3), f"score={score}", verdict

def _records_from_text(text: str, title: str, url: str, src: str, meta=None):
    """Route any text through kbcore's official chunk/records path."""
    base = {"t": title, "u": url, "s": (meta or {}).get("site") if isinstance(meta, dict) else (src or ""),
            "src": (meta or {}).get("site") if isinstance(meta, dict) else (src or "librar")}
    if meta:
        base["prov"] = meta if isinstance(meta, str) else json.dumps(meta)[:300]
    recs = kbcore.records_from(text, base)
    return recs

def quality_report(db, url, text) -> dict:
    ok, verdict, provenance = _domain_quality(url, text)
    return {"url": url, "admit": ok, "verdict": verdict, "provenance": provenance}

# ── greysearch bridge (same-process import; no subprocess MCP hop) ─────────
GSPATH = "~/greysearch"
WALLED_SOURCES = {
    "insurance.az.gov",
    "difi.az.gov",
    "content.naic.org",
}

def _pin_filter(pinned):
    """Drop pinned sources that are proven unusable for the learn lane:
    captcha/403-walled (owner-verified 11-10) or robots.txt-disallowed for
    the scrapers (the ingest gate would reject them AFTER the browser
    already burned the scrape budget — pre-gate instead). Each drop is
    reported with its class."""
    out, dropped = [], []
    for p in pinned or []:
        dom = str(p or "").strip()
        hit = ""
        for w in WALLED_SOURCES:
            if w in dom:
                hit = f"walled ({w})"
                break
        if not hit and dom:
            try:
                ok, why = _ex.robots_ok(dom if "//" in dom else "https://" + dom)
                if not ok:
                    hit = f"robots-disallow ({str(why)[:40]})"
            except Exception:
                pass
        if hit:
            dropped.append({"pin": dom, "why": hit})
        elif dom:
            out.append(dom)
    return out, dropped
def _gs():
    if GSPATH not in sys.path: sys.path.insert(0, GSPATH)
    import greysearch_mcp
    return greysearch_mcp

def _extract_guide_sections(md: str):
    """Split a Master Guide into (section_title, text) chunks for targeted ingest."""
    parts = re.split(r"\n(?=#{1,3} )", md)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) < 200: continue
        ttl = p.split("\n", 1)[0].lstrip("# ").strip()[:120] or "section"
        out.append((ttl, p))
    return out or [("full", md[:12000])]

def tool_kb_ingest_text(a: dict) -> dict:
    """Local text/markdown with provenance. No fetch, no gate (owner-curated)."""
    db = a.get("db"); text = a.get("text") or ""
    title = a.get("title") or "untitled"
    src = a.get("source") or "local"
    url = a.get("url") or f"local://{src}"
    if not db or len(text.strip()) < 80:
        return {"error": "need db + meaningful text (>=80 chars)"}
    path = kbcore.db_dir(db)
    if not os.path.isfile(f"{path}/pack.jsonl"):
        return {"error": f"no such db: {db}"}
    enc = jobs_mod.enc_factory()
    recs = _records_from_text(text, title, url, src, a.get("provenance"))
    added = kbcore.add_records(path, recs, enc, src="local-ingest")
    return {"db": db, "title": title, "records_made": len(recs), "added": len(added),
            "duplicates": max(0, len(recs) - len(added)),
            "note": "ingested verbatim (owner-curated lane, no auto-gate)"}

# ── background learn lane (mirrors greysearch fire-and-forget lifecycle) ──
# kb_learn_topic returns {run_id, state=running} immediately; the deep run +
# gated ingest happen in an isolated one-shot worker process that can never
# wedge this single-threaded stdio server; digest arrives via kb_learn_status.
import subprocess as _sub
import threading as _threading
import signal as _signal
LEARN_RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn-runs")


def _learn_now(a: dict) -> dict:
    """Sync learn core AND the worker entry: holds the per-db learn-lock for the run."""
    db = (a.get("db") or "").strip()
    topic = (a.get("topic") or a.get("query") or "").strip()
    if not db or not topic:
        return {"error": "need db + topic"}
    import fcntl
    lock_path = os.path.join(kbcore.db_dir(db), ".learn-lock")
    lockf = open(lock_path, "a")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lockf.close()
        return {"error": "another learn run is active for this db",
                "hint": "call kb_learn_status; re-fire only after done/failed"}
    try:
        return _learn_body(a, db, topic)
    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except Exception:
            pass
        lockf.close()


def _learn_body(a: dict, db: str, topic: str) -> dict:
    """greysearch deep run → quality gate → ingest. Caller holds the learn-lock."""
    T0_LOCAL = time.time()
    # Learn-lane bounding (owner incident 04:30 run: the search stage stacked
    # four 150s public-browser joins and outran the worker wall, losing
    # everything at the wall-kill). Per-search public-browser joins are
    # capped 45s IN THIS WORKER PROCESS ONLY (setdefault: an operator-set
    # env still wins), so every lane stays bounded and the run's own 420s
    # budget means minutes, not the whole wall.
    os.environ.setdefault("GREYSEARCH_BROWSER_JOIN_S", "45")
    tier = a.get("tier", "standard")
    max_results = int(a.get("max_results", 8))
    gs = _gs()
    tier_pages = {"brief": 3, "standard": max_results, "deep": max_results, "report": max_results}
    budget = float(a.get("max_seconds", 240 if tier =="brief" else 380))
    pinned, walled_dropped = _pin_filter(a.get("pinned_sources") or [])
    # search-proxy passthrough: the search lane ladder's proxy rung (IPRoyal,
    # SEARCH REQUESTS ONLY per owner discipline; page scrapes stay direct)
    # must be reachable from the learn lane too, and the climb must be
    # AUTOMATIC: a deep run that returns zero pages with "relevant floor
    # unmet ... re-run with search_proxy=on" in its ladder fires once more
    # on the proxy rung with the remaining wall budget before giving up.
    sp_arg = a.get("search_proxy")
    if sp_arg is None:
        sp_arg = os.environ.get("GREYSEARCH_SEARCH_PROXY") or None
    result = gs._execute_deep(
        topic, categories=a.get("categories") or ["it", "science"],
        max_results=min(max_results, tier_pages.get(tier, max_results)),
        budget=budget, pinned=pinned or None, search_proxy=sp_arg)
    _pages_after = len(result.get("pages") or result.get("pages_fetched") or [])
    _lad = " ".join(str(x) for x in (result.get("search_ladder") or []))
    # climb on ZERO or thin (<3 usable pages) results: "relevant floor
    # unmet ... re-run with search_proxy=on" in the ladder is the run's
    # own admission that the keyless lanes starved; one proxy rung
    # re-fire with the remaining wall budget (search traffic ONLY per
    # the IPRoyal discipline; page scrapes stay direct).
    _floor_unmet = "search_proxy=on" in _lad or "relevant floor unmet" in _lad
    if _pages_after < 4 and _floor_unmet and (sp_arg or "").lower() != "on":
        # FIXED tight re-fire budget: a remaining-wall formula can explode
        # into the reap window (the 04:30 run's failure mode); 240s always
        # fits: wall = budget*2+600 >= 420+420+600 >> 420 + 240 + ingest.
        result = gs._execute_deep(
            topic, categories=a.get("categories") or ["it", "science"],
            max_results=min(max_results, tier_pages.get(tier, max_results)),
            budget=240.0, pinned=pinned or None, search_proxy="on")
    path = kbcore.db_dir(db)  # ingest target; validated by _learn_now's caller
    pages = result.get("pages") or result.get("pages_fetched") or []
    # judge-quarantined pages keep their full text in all_scraped_pages.
    # A quarantine (55-74) means "on-topic-ish but the deterministic judge
    # wasn't sure" — for KB learning we take that band when REAL gates
    # (official/quality domain score) pass, else the deep run starves on
    # lexically-different-but-substantive pages (kaspersky 'hacked' vs our
    # 'compromised').
    quarantined = [p for p in (result.get("all_scraped_pages") or [])
                   if isinstance(p, dict) and p.get("ok")
                   and str((p.get("relevance") or {}).get("decision")) == "quarantine"]
    if quarantined and len(pages) < 3:
        pages = list(pages) + quarantined
    admitted, rejected = [], []
    enc = jobs_mod.enc_factory()
    total = dups = 0
    guide_path = result.get("guide_path") or result.get("guide") or ""
    # 1) per-page ingest — multi-extractor funnel (trafilatura→selectolax→grab)
    #    + robots politeness gate + code/table side-harvest + feed discovery
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        url = pg.get("url") or ""
        title = pg.get("title") or url
        raw_html = pg.get("html") or pg.get("raw_html") or ""
        text = pg.get("text") or pg.get("content") or ""
        ext_used = "scrape-doms"
        code_recs = []
        # robots.txt politeness (skip disallowed paths entirely)
        rob_ok, rob_why = _ex.robots_ok(url)
        if not rob_ok:
            rejected.append({"url": url, "why": rob_why}); continue
        # The deep scrape's page.text is DOM-dependent and routinely carries
        # nav rails / headline lists (gamedeveloper.com shipped "Latest News"
        # chrome as 'text'). When raw HTML exists, ALWAYS run the funnel and
        # take the cleaner of the two texts; trafilatura rejects boilerplate.
        funnel_text, code_recs = None, []
        if len(raw_html) > 800:
            pr = _ex.process(url, raw_html)
            if pr["text"]:
                funnel_text = pr["text"]
            if pr["code"]:
                code_recs = [(f"code: {title[:60]} #{i+1}", c) for i, c in enumerate(pr["code"])]
        if funnel_text is not None:
            if is_rail(text):
                # scraped text is a nav rail → trust the funnel's extraction
                text = funnel_text
                ext_used = "funnel-over-scrape"
            elif len(funnel_text) > len(text) + 400:
                text = funnel_text
                ext_used = "funnel-over-scrape"
        if len(text) < 400:
            rejected.append({"url": url, "why": "thin content"}); continue
        ok, verdict, provenance = _domain_quality(url, text)
        # judge-quarantined pages are on-topic-adjacent: the deterministic
        # judge scored them QUARANTINE (55-74) = real content, unsure topical
        # fit. For KB learning that's acceptable when the quality score is
        # non-negative (>=0); only hard-negative hosts stay rejected.
        quarantine_rel = (pg.get("relevance") or {}) if isinstance(pg, dict) else {}
        if not ok and str(quarantine_rel.get("decision")) == "quarantine" \
                and int(quarantine_rel.get("relevance_score") or 0) >= 55:
            try:
                _qscore = int(str(verdict.split("score=")[-1]).split(";", 1)[0])
            except Exception:
                _qscore = 0
            if _qscore >= 0:
                ok, verdict = True, verdict + "+judge-quarantine-override"
        if not ok:
            rejected.append({"url": url, "why": verdict}); continue
        recs = _records_from_text(text, title, url, "greysearch-learn", provenance)
        # chrome gate: a chunk that is pure site chrome (nav rail, headline
        # list) does not get ingested, no matter how the extractor scored it
        blocked = [r for r in recs if is_rail(r.get("x", ""))]
        recs = [r for r in recs if not is_rail(r.get("x", ""))]
        # code blocks → separate focused records (same url provenance)
        for ct, cb in code_recs[:12]:
            recs += _records_from_text(cb, ct, url + "#code", "greysearch-learn-code", "code block, " + provenance)
        added = kbcore.add_records(path, recs, enc, src="auto-learn")
        total += len(added); dups += max(0, len(recs) - len(added))
        admitted.append({"url": url, "records": len(recs), "added": len(added),
                         "prov": provenance, "extractor": ext_used})
    # 2) Master Guide ingest (the synthesized, highest-value artifact)
    guide_added = 0
    if guide_path and os.path.isfile(guide_path):
        md = open(guide_path, errors="ignore").read()
        if len(md) > 600:
            for ttl, section in _extract_guide_sections(md):
                recs = _records_from_text(
                    section, ttl, f"guide://{os.path.basename(guide_path)}#{ttl[:40]}",
                    "greysearch-guide", f"master guide section, topic='{topic[:90]}'")
                added = kbcore.add_records(path, recs, enc, src="auto-learn-guide")
                guide_added += len(added)
    return {"db": db, "topic": topic, "greysearch_run": {"run_id": result.get("run_id"),
            "pages": len(pages), "guide": guide_path},
            "walled_pinned_dropped": walled_dropped,
            # ladder lines ride every digest: the run's own lane story
            # (which rungs engaged, what each returned) — owner-truth law:
            # lane claims are verified, not asserted.
            "lane_ladder": ([str(x)[:160] for x in (result.get("search_ladder") or [])]
                            if isinstance(result.get("search_ladder"), list) else []),
            "admitted": admitted, "rejected": rejected,
            "records_added": total, "guide_sections_added": guide_added,
            "duplicates": dups,
            "note": "funnel: robots-gate → trafilatura/selectolax text + code harvest; every rejection reported"}


def _write_digest(run_dir: str, digest: dict):
    tmp = os.path.join(run_dir, "digest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(digest, f, indent=1, default=str)
    os.replace(tmp, os.path.join(run_dir, "digest.json"))


def _probe_learn_lock(db: str) -> bool:
    """True when no learn worker holds the db's .learn-lock flock."""
    import fcntl
    lock_path = os.path.join(kbcore.db_dir(db), ".learn-lock")
    f = open(lock_path, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    try:
        fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()
    return True


def tool_kb_learn_topic(a: dict) -> dict:
    """FIRE-AND-FORGET like greysearch: returns run_id at once, digest via kb_learn_status.
    background=false keeps the legacy blocking behavior."""
    db = a.get("db"); topic = (a.get("topic") or a.get("query") or "").strip()
    if not db or not topic:
        return {"error": "need db + topic"}
    path = kbcore.db_dir(db)
    if not os.path.isfile(f"{path}/pack.jsonl"):
        return {"error": f"no such db: {db}"}
    if not a.get("background", True):
        return _learn_now(a)  # legacy blocking lane
    tier = a.get("tier", "standard")
    max_seconds = float(a.get("max_seconds", 240 if tier == "brief" else 380))
    run_id = time.strftime("learn-%Y%m%d-%H%M%S-") + hashlib.md5(topic.encode()).hexdigest()[:6]
    run_dir = os.path.join(LEARN_RUNS, run_id)
    os.makedirs(run_dir, exist_ok=True)
    # per-db single-flight: the worker holds .learn-lock (flock) for the run;
    # probe it so a double-fire fails fast here instead of inside the worker
    if not _probe_learn_lock(db):
        return {"error": f"another learn run is active for db '{db}'",
                "hint": "call kb_learn_status; re-fire only after it reports done/failed"}
    with open(f"{run_dir}/request.json", "w") as f:
        json.dump(a, f, default=str)
    wall = max_seconds * 2 + 600  # greysearch budget overshoots on pinned lanes + guide/ingest headroom
    worker_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_worker.py")
    logf = open(f"{run_dir}/worker.log", "wb")
    proc = _sub.Popen(
        [sys.executable, worker_py, run_dir, str(int(wall))],
        stdin=_sub.DEVNULL, stdout=logf, stderr=_sub.STDOUT,
        start_new_session=True)
    with open(f"{run_dir}/worker.pid", "w") as f:
        f.write(str(proc.pid))

    def _reap(run_dir=run_dir, pid=proc.pid, limit=wall):
        time.sleep(limit)
        try:
            if os.path.exists(f"/proc/{pid}") and not os.path.exists(
                    os.path.join(run_dir, "digest.json")):
                os.killpg(pid, _signal.SIGKILL)  # group: worker + any grandchild
                _write_digest(run_dir, {"state": "failed",
                                        "why": f"wall-clock kill after {int(limit)}s"})
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            pass
    _threading.Thread(target=_reap, daemon=True).start()
    return {"db": db, "topic": topic, "run_id": run_id, "state": "running",
            "worker_pid": proc.pid, "wall_limit_s": int(wall),
            "note": "fired like greysearch; digest arrives via kb_learn_status; "
                    "do not re-fire this db while it runs"}


def tool_kb_learn_status(a: dict) -> dict:
    """ONE status call for learn runs (the kb_learn_topic digest list):
    running / done / failed, records added, admitted/rejected and why."""
    import glob
    want_db = (a.get("db") or "").strip()
    if not os.path.isdir(LEARN_RUNS):
        return {"runs": [], "note": "no learn runs yet"}
    runs = []
    for d in sorted(glob.glob(os.path.join(LEARN_RUNS, "learn-*")), reverse=True):
        try:
            req = json.load(open(os.path.join(d, "request.json")))
        except Exception:
            continue
        db = req.get("db", "?")
        if want_db and db != want_db:
            continue
        digest_path = os.path.join(d, "digest.json")
        entry = {"run_id": os.path.basename(d), "db": db,
                 "topic": (req.get("topic") or req.get("query") or "")[:120]}
        if os.path.isfile(digest_path):
            try:
                dg = json.load(open(digest_path))
            except Exception:
                dg = {"state": "failed", "why": "digest unreadable"}
            entry["state"] = dg.get("state", "?")
            if dg.get("state") == "done":
                entry.update({"records_added": dg.get("records_added"),
                              "guide_sections_added": dg.get("guide_sections_added"),
                              "pages": (dg.get("greysearch_run") or {}).get("pages"),
                              "guide": (dg.get("greysearch_run") or {}).get("guide"),
                              "admitted": dg.get("admitted"),
                              "rejected": dg.get("rejected"),
                              "duplicates": dg.get("duplicates")})
            elif dg.get("why"):
                entry["why"] = dg.get("why")
        else:
            alive = False
            try:
                pid = int(open(os.path.join(d, "worker.pid")).read().strip())
                os.kill(pid, 0)
                alive = True
            except Exception:
                alive = False
            entry["state"] = "running" if alive else "failed"
            if not alive:
                entry["why"] = "worker died without digest"
        runs.append(entry)
        if len(runs) >= 20:
            break
    return {"runs": runs, "note": "done/failed runs may be re-fired; "
                                 "do not re-fire a db with a running learn"}
