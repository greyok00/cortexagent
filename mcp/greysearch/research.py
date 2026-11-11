#!/usr/bin/env python3
"""research.py: full-run CLI for the Greysearch engine.

One command, no MCP and no model: the same deterministic engine the MCP
server and portal drive. Writes the Master Guide (+ themed site, + optional
PDF) into guides/<date>/ (or --write-guide-to), prints a compact digest,
and exits 0 only when the run accepted at least one source.

    python3 research.py "why do cars rust" [--tier brief] [--pdf]
        [--max-pages N] [--max-seconds S] [--theme X] [--no-site]
        [--write-guide-to DIR]

Exit 0 = >=1 accepted source. Exit 1 = capture failed; the skip reasons are
printed and the run-report.json beside the guide explains every rejection.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

REPO = Path(__file__).resolve().parent

_TIER_CAPS = {"brief": (3, 240.0), "standard": (4, 300.0),
              "deep": (6, 420.0), "report": (8, 540.0)}

def _parse_args(argv=None):
    ap = ArgumentParser(description="Greysearch full-run CLI (LLM-free)")
    ap.add_argument("query", help="Research question")
    ap.add_argument("--tier", default="standard", choices=sorted(_TIER_CAPS),
                    help="brief 3/240s, standard 4/300s, deep 6/420s, report 8/540s")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="override the tier's page cap")
    ap.add_argument("--max-seconds", type=float, default=0.0,
                    help="override the tier's wall-clock budget")
    ap.add_argument("--theme", default="master",
                    help="theme for the site build (default: master)")
    ap.add_argument("--pdf", action="store_true",
                    help="render the built site to PDF")
    ap.add_argument("--no-site", action="store_true",
                    help="write the Master Guide only, skip the site build")
    ap.add_argument("--write-guide-to", default="",
                    help="override the guide output dir (default guides/<date>/)")
    a = ap.parse_args(argv)
    tier_pages, tier_budget = _TIER_CAPS[a.tier]
    if not a.max_pages:
        a.max_pages = tier_pages
    if not a.max_seconds:
        a.max_seconds = tier_budget
    return a

def _exit_code(result: dict) -> int:
    """0 iff the run accepted at least one source."""
    return 0 if (result or {}).get("sources") else 1

def main(argv=None) -> int:
    a = _parse_args(argv)
    max_pages, budget = a.max_pages, a.max_seconds

    from greysearch_mcp import _execute_deep, _attach_guide, _resolve_guide_path

    write_path = _resolve_guide_path(a.write_guide_to or None, a.query)
    started = time.time()
    try:
        result = _execute_deep(a.query, None, max_pages, budget)
    except Exception as e:
        print(json.dumps({"ok": False,
                          "error": f"{type(e).__name__}: {str(e)[:200]}"},
                         indent=2))
        return 1

    result = _attach_guide(result, a.query, write_path)
    result["elapsed_s"] = round(time.time() - started, 1)
    result["tier"] = a.tier

    guide_path = Path(result.get("master_guide", {}).get("path",
                                                          write_path))
    site_out = pdf_path = None
    if not a.no_site and guide_path.is_file():
        site_dir = guide_path.with_name(guide_path.stem + "_" + a.tier + "_site")
        _builder_py = REPO / "greysearch_site_builder.py"
        if _builder_py.is_file():
            _cmd = [sys.executable, str(_builder_py)]
        else:
            _cmd = [sys.executable, "-c",
                    "import sys; sys.path.insert(0, %r); "
                    "import greysearch_site_builder as m; sys.exit(m.render())"
                    % str(REPO)]
        pr = subprocess.run(
            _cmd + [str(guide_path), "-o", str(site_dir),
                    "--theme", a.theme, "--title", f"{a.query[:100]}",
                    "--max-images", "40"],
            capture_output=True, text=True, timeout=240, cwd=str(REPO))
        site_ok = (site_dir / "index.html").is_file()
        if site_ok:
            site_out = str(site_dir)
            if a.pdf:
                try:
                    import pdf_export
                    pdf_path = pdf_export.render_pdf(
                        str(site_dir / "index.html"),
                        str(site_dir.with_suffix(".pdf")))
                except Exception as pe:
                    result.setdefault("warnings", []).append(
                        f"pdf failed: {str(pe)[:160]}")
        else:
            result.setdefault("warnings", []).append(
                "site build failed: " + (pr.stderr or "")[-200:])

    digest = {
        "query": a.query,
        "tier": a.tier,
        "pages_ok": len(result.get("pages_fetched", [])),
        "skipped": len(result.get("skipped_pages", [])),
        "accepted": len(result.get("sources", [])),
        "elapsed_s": result.get("elapsed_s"),
        "guide": result.get("master_guide", {}).get("path"),
        "run_report": result.get("run_report_path"),
        "site": site_out,
        "pdf": pdf_path,
        "skip_reasons": [(s.get("reason") if isinstance(s, dict) else s) or ""
                         for s in (result.get("skipped_pages") or [])],
    }
    try:
        import browser_session as _bs
        _bs.drop_all_connections()
    except Exception:
        pass
    print(json.dumps(digest, indent=2))
    return _exit_code(result)

if __name__ == "__main__":
    sys.exit(main())