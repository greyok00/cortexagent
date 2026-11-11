#!/usr/bin/env python3
"""
greysearch_site_builder: STANDALONE output stage:
turns finished Master Guides into complete static websites. Deliberately NOT
part of greysearch_mcp.py / the research server (running processes must not
be touched); it post-processes the guide files they produce.

Usage:
  python3 greysearch_site_builder.py GUIDE.md [-o OUT_DIR] [--title "T"]
                                     [--max-images N] [--keep-remote]

Reads the guide's Master Guide schema (H1 title, blockquote executive brief,
numbered `
"Part 01…" cards in staggered tints, images inline on the left, executive
brief in the lede, in-page TOC chips). The shared renderer lives in
site_render.py (the course builder uses the same one); this file is the
guide CLI around it.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

import site_render

def render() -> int:
    ap = argparse.ArgumentParser(description="Master Guide -> full static website")
    ap.add_argument("guide", help="Master Guide .md file")
    ap.add_argument("-o", "--out", default="",
                    help="Site output dir (default: <guide-stem>_site beside the guide)")
    ap.add_argument("--title", default="", help="Site title override")
    ap.add_argument("--max-images", type=int, default=200,
                    help="Images to download (default 200; 0 disables)")
    ap.add_argument("--keep-remote", action="store_true",
                    help="Never download; embed all images by their remote URL")
    ap.add_argument("--theme", default="master",
                    help="grey kit theme applied as the page default")
    ap.add_argument("--no-scrub", action="store_true",
                    help="Skip the nav-chrome scrub (guide_scrub.py)")
    a = ap.parse_args()


    guide = Path(a.guide)
    md_text = guide.read_text(errors="replace")
    scrub_stats = None
    if not a.no_scrub:
        try:
            from guide_scrub import scrub_guide_md
            md_text, scrub_stats = scrub_guide_md(md_text)
        except Exception:
            scrub_stats = None

    m = re.search(r"^#\s+(.*)$", md_text, re.M)
    title = a.title or (m.group(1).strip() if m else guide.stem.replace("-", " "))

    out = Path(a.out) if a.out else guide.with_name(guide.stem + "_site")
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets" / "img"
    assets.mkdir(parents=True, exist_ok=True)
    site_render.ensure_kit(out)

    try:
        import photos
        if "*Image:" not in md_text:
            q = (photos.keywords(title, 4)
                 or photos.keywords(title, 2) or title)
            ph = photos.find_photo(q)
            if not (ph and ph.get("url")):
                hits = [h for h in photos.searx_image_hits(q, 6) if h.get("url")]
                ph = hits[0] if hits else None
            if ph and ph.get("url"):
                md_text = photos.insert_photo(md_text, ph, title)
    except Exception:
        pass

    md_text, img_report = site_render.download_images(
        md_text, assets, a.max_images, a.keep_remote,
        src_dir=guide.parent)

    when = os.popen("date -u '+%Y-%m-%d %H:%M UTC'").read().strip()
    title = title.replace("Master Guide — ", "").strip()
    hub = ""

    stats: dict = {}
    html = site_render.render_document(
        md_text, title=title, hub=hub, when=when,
        max_images=10**9, max_charts=10**9,
        scrub_stats=scrub_stats,
        unwrap_all_links=(scrub_stats is None),
        data_not_captured=("DATA NOT CAPTURED" in md_text),
        drop_heading=not a.title,
        stats=stats,
        theme=a.theme,
    )

    for stale in out.glob("*.html"):
        stale.unlink()
    (out / "index.html").write_text(html)

    guard = {"ok": False, "checks": {}}
    try:
        from site_guardrails import check_site
        guard = check_site(out, scrub_stats=scrub_stats,
                           md_source=md_text)
        n_ok = sum(1 for c in guard["checks"].values() if c["pass"])
        print(f"  guardrails: {n_ok}/{len(guard['checks'])} checks passed"
              f" ({'OK' if guard['ok'] else 'FAILED'})")
        for name, chk in guard["checks"].items():
            if not chk["pass"]:
                print(f"    ✗ {name}: {chk['note']}")
        (out / "guardrails.json").write_text(
            __import__("json").dumps(guard, indent=1))
    except Exception as ge:
        print(f"  guardrails: gate error (non-fatal): {ge}")

    print(f"✓ site written: {out}")
    print(f"  pages: 1 flowing guide ({stats['sections']} numbered parts, "
          f"{stats['collapsed']} exact-duplicate blocks collapsed)")
    print(f"  images: found={img_report['found']} downloaded={img_report['downloaded']} "
          f"failed_or_kept_remote={img_report['failed_or_kept_remote']} "
          f"skipped_nontopical={img_report['skipped_nontopical']} "
          f"gated_kept={stats['kept']} gated_dropped={stats['dropped']}")
    print(f"  charts: {stats['charts']} teaching charts from "
          f"{stats['rows']} data rows (source tables kept in-page)")
    if stats["limitations"]:
        print(f"  research-limitations block rendered ({stats['limitations']} items)")
    return 0

if __name__ == "__main__":
    # Availability probe only: markdown is imported by the renderers that
    # need it (site_render); here we just fail fast with the real remedy.
    if importlib.util.find_spec("markdown") is None:
        sys.exit("python markdown module required (pip install markdown)")
    sys.exit(render())
