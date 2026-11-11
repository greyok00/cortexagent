#!/usr/bin/env python3
"""works_library: the Works shelf backend for the Greysearch portal.

Every finished artefact this station produced - built HTML sites, printed
PDFs, master-guide markdown, polished sets - is indexed here with a host
census and a heuristic keyword census (no embedding model, no GPU). The
shelf serves the Works page (dark obsidian theme, same tokens as Station /
Run ledger / Library).

Layout under data/works/:
  index.json         {"works":[work...]}   - the shelf, newest first
  <id>/site/...      copied build output   - served read-only by the portal
  <id>/meta.json     per-work ledger row    - rebuilds of the same run land here

The indexer is deliberately soft-fail: any unreadable artefact is skipped
with a note, never a traceback that could take the portal route down.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
WORKS_ROOT = REPO / "data" / "works"
GUIDES_ROOT = REPO / "guides"

_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
_STOP = set("""the and for with that this from are was were has have had its
their there then than them they you your ours our not but can could should
would will shall may might must about into over under out off all also any
because been before being between both during each else even ever every few
first found get got help here how http https just like made make many more
most much need new next non none nor now off once one only other page pages
pdf site sites some such take than thing think this those three through too
two use used using very want well what when where which while who whom why
will within without world www com org net html htm your yours per via etc
see seen says said sources source guide guides section sections part parts
""".split())


def _hosts_of(text: str) -> list[str]:
    seen = {}
    for h in _HOST_RE.findall(text or ""):
        h = h.lower().removeprefix("www.")
        if h and h not in seen:
            seen[h] = True
    return list(seen)[:24]


def _keywords(md_text: str, limit: int = 18) -> list[tuple[str, int]]:
    """Heuristic census: lowercased word frequency minus stopwords, plus a
    small boost for capitalized-in-source runs (likely proper nouns that
    survived the round trip through markdown)."""
    counts: dict[str, int] = {}
    words = _WORD_RE.findall(md_text or "")
    total = 0
    for w in words:
        lw = w.lower()
        if lw in _STOP:
            continue
        counts[lw] = counts.get(lw, 0) + 1
        total += 1
    if not total:
        return []
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(w, n) for w, n in ranked[:limit] if n >= 2]


def _id_for(base: str) -> str:
    """Sortable, filesystem-safe, unique: date + slug + short digest."""
    day = time.strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    slug = slug[:44].strip("-") or "work"   # strip AFTER truncation too:
    digest = ""                             # a 44-char cut must not end in '-'
    for i in range(40):
        cand = f"w-{day}-{slug}{digest}"
        if not (WORKS_ROOT / cand).exists():
            return cand
        digest = "-" + os.urandom(2).hex()
    return f"w-{day}-{slug}-{os.urandom(4).hex()}"


def _meta_of(site_dir: Path) -> dict:
    """Read the guardrails/manifest the site build already wrote."""
    info = {}
    for name in ("guardrails.json", "manifest.json"):
        p = site_dir / name
        try:
            if p.is_file():
                info.update(json.loads(p.read_text()))
        except Exception:
            pass
    return info


def ingest_build(guide_path: str, build: dict, run_meta: dict | None = None,
                 set_name: str = "") -> dict | None:
    """Called by the portal after a successful /api/build: copies the built
    site (+ zip + pdf) into the Works shelf and appends a shelf row.
    Returns the work row, or None when there is nothing to shelve."""
    site = build.get("site")
    if not site:
        return None
    site_dir = Path(site)
    if not (site_dir / "index.html").is_file():
        return None
    try:
        WORKS_ROOT.mkdir(parents=True, exist_ok=True)
        wdir = WORKS_ROOT / _id_for(Path(guide_path).stem)
        if wdir.exists():  # duplicate stamp; extremely unlikely
            return None
        shutil.copytree(site_dir, wdir / "site", dirs_exist_ok=False)
        for extra in ("zip", "pdf"):
            p = build.get(extra)
            if p and Path(p).is_file():
                shutil.copy2(p, wdir / Path(p).name)

        md_path = Path(guide_path)
        md_text = ""
        try:
            md_text = md_path.read_text(errors="replace")
        except Exception:
            pass
        hosts = _hosts_of(md_text)
        kws = _keywords(md_text)
        guard = _meta_of(wdir / "site")
        row = {
            "id": wdir.name,
            "created": int(time.time()),
            "day": time.strftime("%Y-%m-%d"),
            "kind": "site",
            "title": (run_meta or {}).get("title") or md_path.stem
                     .replace("-", " "),
            "query": (run_meta or {}).get("query") or "",
            "run_id": (run_meta or {}).get("run_id") or "",
            "set_name": set_name or "",
            "theme": build.get("theme") or "",
            "refined": bool(build.get("refined_source", "").startswith
                            ("model")),
            "bytes": sum(f.stat().st_size for f in wdir.rglob("*")
                         if f.is_file()),
            "pdf": (wdir / (site_dir.stem + ".pdf")).name
                   if (wdir / (site_dir.stem + ".pdf")).is_file() else "",
            "zip": site_dir.stem + ".zip" if
                   (wdir / (site_dir.stem + ".zip")).is_file() else "",
            "guardrails": bool(guard),
            "hosts": hosts,
            "keywords": [[w, n] for w, n in kws],
            "sources": len(hosts),
        }
        _meta_write(wdir, row)
        idx = _index_read()
        idx.setdefault("works", []).insert(0, row)
        _index_write(idx)
        return row
    except Exception:
        return None


def _meta_write(wdir: Path, row: dict) -> None:
    (wdir / "meta.json").write_text(json.dumps(row, indent=1))


def _index_read() -> dict:
    p = WORKS_ROOT / "index.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"works": []}


def _index_write(idx: dict) -> None:
    WORKS_ROOT.mkdir(parents=True, exist_ok=True)
    p = WORKS_ROOT / "index.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=1))
    os.replace(tmp, p)


def shelf_data() -> dict:
    """Everything the Works page needs: rows + censuses. Soft-fail."""
    idx = _index_read()
    works = idx.get("works") or []
    # heal: drop rows whose site dir vanished, re-add rows for site dirs
    # not yet on the shelf (post-restart drift, manual builds)
    known = {w.get("id") for w in works}
    healed = False
    if WORKS_ROOT.is_dir():
        for wdir in sorted(WORKS_ROOT.iterdir()):
            if not wdir.is_dir() or wdir.name in known:
                continue
            try:
                meta = json.loads((wdir / "meta.json").read_text())
                works.insert(0, meta)
                healed = True
            except Exception:
                continue
    works = [w for w in works if (WORKS_ROOT / w.get("id", "")
                                  / "site" / "index.html").is_file()]
    if healed or len(works) != len(idx.get("works") or []):
        _index_write({"works": works})

    cat_counts: dict[str, int] = {}
    host_counts: dict[str, int] = {}
    kw_counts: dict[str, int] = {}
    for w in works:
        cat_counts[w.get("theme") or "unthemed"] = \
            cat_counts.get(w.get("theme") or "unthemed", 0) + 1
        for h in w.get("hosts") or []:
            host_counts[h] = host_counts.get(h, 0) + 1
        for kw, n in w.get("keywords") or []:
            kw_counts[kw] = kw_counts.get(kw, 0) + n
    hosts = sorted(host_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kws = sorted(kw_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    return {
        "works": works,
        "count": len(works),
        "themes": cat_counts,
        "hosts": hosts[:24],
        "keywords": [[k, n] for k, n in kws],
        "pdfs": sum(1 for w in works if w.get("pdf")),
        "zips": sum(1 for w in works if w.get("zip")),
        "bytes": sum(w.get("bytes", 0) for w in works),
    }


def open_work(wid: str) -> tuple[Path, str] | tuple[None, str]:
    """Resolve a shelf id to the site dir that the portal may serve.
    Returns (dir, '') on success or (None, reason)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", wid or ""):
        return None, "bad id"
    wdir = WORKS_ROOT / wid
    site = wdir / "site"
    if not (site / "index.html").is_file():
        return None, "unknown work"
    return site, ""


def work_pdf(wid: str) -> Path | None:
    site, _ = open_work(wid)
    if not site:
        return None
    pdfs = sorted(site.parent.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def work_zip(wid: str) -> Path | None:
    site, _ = open_work(wid)
    if not site:
        return None
    zips = sorted(site.parent.glob("*.zip"))
    return zips[0] if zips else None


def search_works(q: str) -> list[dict]:
    """Heuristic substring/keyword match over the shelf (title, query,
    set name, host, keyword). No index server, no model."""
    ql = (q or "").strip().lower()
    if not ql:
        return []
    terms = [t for t in re.split(r"\s+", ql) if t]
    out = []
    for w in shelf_data()["works"]:
        hay = " ".join([
            w.get("title", ""), w.get("query", ""), w.get("set_name", ""),
            w.get("theme", ""), w.get("id", ""),
            " ".join(w.get("hosts") or []),
            " ".join(k for k, _ in w.get("keywords") or []),
        ]).lower()
        if all(t in hay for t in terms):
            out.append(w)
    return out
