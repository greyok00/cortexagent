"""pdf_export.py: print a built site's index.html to PDF.

Uses a one-shot patchright headless Chromium, dies with the process: no
browser held open, no slot browser touched, nothing resident. The PDF
carries the exact themed rendering (print backgrounds on).
"""

from __future__ import annotations

from pathlib import Path

A4_WIDTH = "8.27in"
A4_HEIGHT = "11.69in"

def render_pdf(html_path: str, out_pdf: str | None = None,
               timeout_ms: int = 60000) -> str | None:
    """Return the pdf path on success, None on any failure (soft policy:
    a missing PDF never fails a build that already validated)."""
    html = Path(html_path)
    out = Path(out_pdf) if out_pdf else html.with_suffix(".pdf")
    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chromium", headless=True)
            try:
                page = browser.new_page()
                page.goto(html.resolve().as_uri(), timeout=timeout_ms,
                          wait_until="load")
                page.emulate_media(media="print")
                page.pdf(path=str(out), width=A4_WIDTH, height=A4_HEIGHT,
                         print_background=True, margin={
                             "top": "0.6in", "bottom": "0.6in",
                             "left": "0.5in", "right": "0.5in"})
            finally:
                browser.close()
        return str(out) if out.is_file() and out.stat().st_size > 1000 else None
    except Exception:
        return None

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: pdf_export.py SITE/index.html [OUT.pdf]"); sys.exit(2)
    p = render_pdf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(p or "pdf failed (see guardrails; build still stands)")