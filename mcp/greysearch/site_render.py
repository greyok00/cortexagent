#!/usr/bin/env python3
"""
site_render: shared static-site renderer for Master Guides and course pages.

The research output stage and the course builder render through ONE
implementation: the same dark single-flow page, the same chart extractor, the
same semantic image gate, and the same link policy. The guide site builder and
the course builder both import this module; the renderer is shared, not owned
by either side.

Design rules honored from the corpus (RESEARCH-BASE-PROMPT §10): media kept
topical, tables never collapsed, code never truncated, sources preserved;
the site is accessible (skip link, landmarks, alt text, AA contrast, no
motion), and DATA NOT CAPTURED statements are kept verbatim, marking honest
gaps as such.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import html as html_lib
import os
import posixpath
import re
from image_gate import (STOCK_ALT_RE, shared_junk_reason)
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0")

KIT_SRC = Path(os.environ.get("GREYOK_KIT_DIR",
                              Path(__file__).resolve().parent
                              / "assets" / "kit-source"))

def ensure_kit(out_dir) -> bool:
    """Install the kit's theme.css + picker script into a built site.

    Copies are derived, not verbatim: @font-face blocks are stripped (the
    site keeps its own serif/sans identity, so kit fonts would only 404),
    and the picker script gains 'master' in its valid set + default so a
    site opens looking exactly as it does now, themes one click away.
    Idempotent: an existing install is left alone.
    """
    try:
        kit_dir = Path(out_dir) / "assets" / "kit"
        for fname in ("screens.ui.css", "screens.ui.js"):
            src = KIT_SRC / fname
            if src.is_file():
                dest = kit_dir / fname
                if not dest.exists() or dest.read_bytes() != src.read_bytes():
                    kit_dir.mkdir(parents=True, exist_ok=True)
                    dest.write_text(src.read_text())
        fresh_src = (KIT_SRC / "theme.css").is_file() and (
            KIT_SRC / "site-kit.js").is_file()
        if fresh_src and (kit_dir / "theme.css").exists() \
                and (kit_dir / "site-kit.js").exists() \
                and ((kit_dir / "theme.css").read_bytes()
                     == (KIT_SRC / "theme.css").read_bytes()):
            return False
        kit_dir.mkdir(parents=True, exist_ok=True)
        theme_css = re.sub(r"@font-face\s*\{[^{}]*\}\s*", "",
                           (KIT_SRC / "theme.css").read_text())
        (kit_dir / "theme.css").write_text(theme_css)
        picker_js = (KIT_SRC / "site-kit.js").read_text()
        picker_js = picker_js.replace("const DEFAULT = 'polaroid';",
                                      "const DEFAULT = 'master';")
        picker_js = picker_js.replace(
            "    return DEFAULT;\n  }",
            "    const baked = document.documentElement"
            ".getAttribute('data-theme');\n"
            "    return (baked && VALID.has(baked)) ? baked : DEFAULT;\n  }",
            1)
        picker_js = picker_js.replace("'neutral', 'polaroid',",
                                      "'master', 'neutral', 'polaroid',", 1)
        picker_js = picker_js.replace(
            "if (!nav || nav.querySelector('.themepick')) return;",
            "return; /* site ships its own picker */")
        picker_js = picker_js.replace(
            "document.querySelectorAll('figure')",
            "document.querySelectorAll('figure.feature, figure.imgfig')")
        (kit_dir / "site-kit.js").write_text(picker_js)
        return True
    except OSError:
        return False

CSS = """
:root{
 /* Greyok site-kit bridge: every color reads its --el-* theme token, with the
    master palette as fallback so the page renders correctly even before the
    kit stylesheet loads or when a theme is not picked. */
 --bg:var(--el-bg,
 --muted:var(--el-ink-soft,
 --hairline:var(--el-line,
 --panel:var(--el-panel,
 --t1:var(--el-panel,
 --t3:var(--el-panel-3,
 --code-bg:var(--el-line-2,
 --accent:var(--el-accent,
 --shell:97%;--maxw:2240px;--prose:1520px;
 --serif:Georgia,"Iowan Old Style","Times New Roman",serif;
 --sans:"Helvetica Neue",Helvetica,Arial,ui-sans-serif,system-ui,sans-serif;
}
/* The site's own palette, registered as a kit theme so the picker can always
   come back to exactly this look. Loaded after theme.css, so it wins. */
html[data-theme="master"]{
 --el-bg:
 --el-line:
 --el-ink:
 --el-on-accent:
 --el-accent:
 --el-accent-soft:rgba(201,168,76,.14);
 --el-ok:
 --el-focus-ring:rgba(201,168,76,.55);
 --fig-filter:saturate(.62) contrast(1.08) brightness(.68)
}
/* Kit themes get their photos clean; only the master dark look dims them. */
html:not([data-theme="master"]){--fig-filter:saturate(.62) contrast(1.08)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}

/* ---- professional-document polish --------------------------------------- */
/* Document framing: a cover masthead, tighter heading rhythm, elegant
   figures + bibliography, all via theme tokens so every kit theme keeps it. */
main{padding-top:44px}
h1{font-size:clamp(1.9rem,4.2vw,2.6rem);line-height:1.14;margin:6px 0 4px;
   letter-spacing:-.01em}
div.kicker{font-size:11px;letter-spacing:.34em;color:var(--el-accent);
   font-weight:600;display:flex;align-items:center;gap:12px}
div.kicker::after{content:"";flex:1;height:1px;background:var(--el-line)}
h2{font-size:clamp(1.4rem,2.6vw,1.85rem);margin:48px 0 12px;padding-bottom:8px;
   border-bottom:1px solid var(--el-line);position:relative}
h2::before{counter-increment:docsec;content:counter(docsec);
   color:var(--el-accent);font-family:var(--serif);font-style:italic;
   margin-right:14px;font-size:.85em}
h2 + p:first-of-type{color:var(--el-ink)}
body{counter-reset:docsec}
.themewrap{opacity:.85}
details.sources{border:1px solid var(--el-line);border-radius:10px;
   background:var(--el-panel);margin:26px 0;padding:0}
details.sources summary{padding:12px 16px;letter-spacing:.18em;
   text-transform:uppercase;font-size:11px;color:var(--el-ink-soft)}
details.sources[open] summary{border-bottom:1px solid var(--el-line)}
details.sources ol,details.sources ul{padding:14px 18px 18px}
details.sources li{margin-bottom:8px;line-height:1.55;
   padding-left:2em;text-indent:-2em}
table{border-collapse:collapse;font-size:.94rem}
th{font-family:var(--sans);font-size:.8rem;letter-spacing:.08em;
   text-transform:uppercase;color:var(--el-ink-soft)}
td,th{padding:8px 12px}
table.data,div.tablewrap table{width:100%}
tr:nth-child(even) td{background:color-mix(in oklab, var(--el-panel-2), transparent 55%)}
figure.feature{border:0;border-radius:12px;overflow:hidden;
   box-shadow:0 1px 3px rgba(0,0,0,.35)}
figure.feature figcaption{font-size:.8rem;color:var(--el-ink-soft);
   padding:10px 14px;background:var(--el-panel)}
figcaption.tcap{font-weight:600;letter-spacing:.02em}
.lede{border-left:3px solid var(--el-accent);padding:18px 22px;
   border-radius:0 10px 10px 0;font-family:var(--serif);
   font-size:1.06rem;line-height:1.65}
body{margin:0;background:var(--bg);color:var(--ink);
 font:20px/1.8 var(--serif);overflow-x:hidden;
 zoom:var(--page-zoom,1)}
h1,h2,h3{font-family:var(--serif);font-weight:400;color:var(--ink);
 overflow-wrap:anywhere}
h1{font-size:clamp(44px,5.8vw,78px);line-height:1.02;letter-spacing:-.02em;
 margin:.34em 0 .45em}
h2{font-size:clamp(34px,4.2vw,54px);line-height:1.08;letter-spacing:-.015em;
 margin:0 0 .55em}
h3{font-size:clamp(24px,2.3vw,32px);line-height:1.25;margin:1.6em 0 .5em}
h4,h5,h6{font-family:var(--sans);font-size:12.5px;font-weight:600;
 letter-spacing:.18em;text-transform:uppercase;color:var(--gold);
 margin:1.6em 0 .5em}
p{margin:.9em 0}
.skip{position:absolute;left:-9999px}
.skip:focus{left:16px;top:16px;z-index:99;background:
 padding:10px 16px;border:1px solid var(--gold);font:600 10.5px/1 var(--sans);
 letter-spacing:.16em;text-transform:uppercase}

/* ---- masthead --------------------------------------------------------- */
header.top{position:sticky;top:0;z-index:50;
 background:color-mix(in srgb,var(--bg) 94%,transparent);
 border-bottom:1px solid var(--hairline);
 -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
.topin{width:var(--shell);max-width:var(--maxw);margin:0 auto;
 padding:18px 0;display:flex;align-items:center;justify-content:space-between;
 gap:24px;font-family:var(--sans)}
.wordmark{font-family:var(--serif);font-weight:400;font-size:19px;line-height:1;
 letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}
.wordmark a{color:var(--ink);font:inherit;letter-spacing:inherit;
 text-transform:inherit;text-decoration:none}
.topin a{color:var(--muted);text-decoration:none;font-size:10.5px;
 letter-spacing:.15em;text-transform:uppercase}
.topin a:hover{color:var(--ink)}
nav.tabs{display:flex;gap:22px;margin-left:auto;margin-right:18px}
nav.tabs a{padding:4px 0;border-bottom:1px solid transparent;
 color:var(--muted);transition:color .3s,border-color .3s}
nav.tabs a.active{color:var(--gold);border-bottom-color:var(--gold)}

/* Generated svg text cards and drawn covers are not photographs, so the
   kit's figure numbering stays off them. */
figure.feature:has(img[src$=".svg"]) .fignum,
figure.imgfig:has(img[src$=".svg"]) .fignum{display:none}
/* ---- theme picker (greyok site-kit) ------------------------------------ */
.themewrap select{background:transparent;border:1px solid var(--hairline);
 color:var(--muted);font:600 10.5px/1 var(--sans);letter-spacing:.12em;
 text-transform:uppercase;padding:7px 9px;cursor:pointer;
 min-width:9.5em}
.themewrap select:hover,.themewrap select:focus-visible{color:var(--ink);
 border-color:var(--gold)}
.themewrap select option{background:var(--bg);color:var(--ink);
 text-transform:none;letter-spacing:normal;font-size:13px}

/* ---- shell ------------------------------------------------------------ */
main,.col{width:var(--shell);max-width:var(--maxw);margin:0 auto;padding:0 0}
main.col,section{min-width:0}
section{overflow-wrap:anywhere}
section>*{max-width:100%}
main>p,main>ul,main>ol,main>blockquote,.lede,
section>p,section>ul,section>ol,section>blockquote{max-width:var(--prose)}

/* ---- page head -------------------------------------------------------- */
.kicker{font:600 10.5px/1 var(--sans);letter-spacing:.24em;
 text-transform:uppercase;color:var(--gold);margin-top:56px}
.sub{color:var(--muted);font:400 16.5px/1.65 var(--sans);letter-spacing:.01em;
 margin:.2em 0 1.4em;max-width:150ch}

/* ---- feature image ---------------------------------------------------- */
figure.feature{margin:30px 0 38px;border:1px solid var(--hairline);
 background:var(--t1)}
figure.feature img{width:100%;height:auto;aspect-ratio:16/10;object-fit:cover;
 display:block;margin:0;background:var(--code-bg);
 filter:var(--fig-filter,saturate(.62) contrast(1.08) brightness(.68))}
figure.feature figcaption{display:flex;align-items:center;gap:12px;
 padding:12px 16px;border-top:1px solid var(--hairline);
 font:500 9.5px/1.5 var(--sans);letter-spacing:.16em;text-transform:uppercase;
 color:var(--muted)}
figure.feature figcaption .frule{display:inline-block;width:44px;height:1px;
 background:var(--gold);flex:none}

/* ---- prose panels ----------------------------------------------------- */
.lede{border-left:1px solid var(--gold);background:var(--t2);padding:28px 34px;
 font-size:17.5px;line-height:1.7;margin:0 0 34px}
.lede blockquote{margin:0;padding:0;border-left:0;background:transparent}
blockquote{margin:1.5em 0;padding:18px 24px;border-left:1px solid var(--gold);
 background:var(--t2)}
a{color:var(--gold);overflow-wrap:anywhere}
a:focus-visible,button:focus-visible,summary:focus-visible,details:focus-visible{
 outline:2px solid var(--gold);outline-offset:3px}
.sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;
 overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
/* Body photos fill the column: the natural-size centered look read as a
   postage stamp on wide screens. Tall shots crop instead of towering. */
main img,section img{width:100%;height:auto;display:block;margin:28px auto;
 background:var(--code-bg);max-height:88vh;object-fit:cover}
video,iframe[src*="youtube"],iframe[src*="youtu.be"],iframe[src*="vimeo"],
iframe[src*="soundcloud"],iframe[src*="spotify"]{display:none!important}
/* Narration is part of the lesson, not chrome. */
figure.audiofig{margin:28px 0 32px;border:1px solid var(--hairline);
 background:var(--t2);padding:20px 24px}
figure.audiofig audio{width:100%;display:block}
figure.audiofig figcaption{margin-top:12px;font:500 10.5px/1.6 var(--sans);
 letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.narr{font:600 10.5px/1 var(--sans);letter-spacing:.22em;
 text-transform:uppercase;color:var(--gold);margin-bottom:10px}
p,li,td,th,figcaption,.tsub,.bl,.bv{overflow-wrap:anywhere}

/* ---- tables ----------------------------------------------------------- */
table{border-collapse:collapse;margin:24px 0;font-size:15.5px;
 font-family:var(--sans)}
.tablewrap table{width:100%}
th,td{border-top:1px solid var(--hairline);padding:15px 20px;text-align:left;
 vertical-align:top;overflow-wrap:break-word}
th:first-child,td:first-child{white-space:nowrap}
th{background:var(--t2);font-weight:600;font-size:11.5px;letter-spacing:.14em;
 text-transform:uppercase;color:var(--gold)}
tr:nth-child(even) td{background:color-mix(in srgb,var(--ink) 3%,transparent)}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
.tablewrap table{display:table;margin:24px 0}

/* ---- code ------------------------------------------------------------- */
pre{background:var(--code-bg);
 color:color-mix(in srgb,var(--ink) 84%,var(--code-bg));
 padding:20px;border:1px solid var(--hairline);
 font-size:14px;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;
 white-space:pre;overflow-wrap:normal;word-break:normal}
pre code{white-space:pre;overflow-wrap:normal;word-break:normal}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
p code,td code,li code{background:var(--t2);padding:1px 6px;font-size:14.5px;
 overflow-wrap:anywhere;word-break:break-all}

/* ---- sections: staggered editorial bands ------------------------------ */
.seck{font-family:var(--sans);font-size:11px;font-weight:600;
 letter-spacing:.2em;text-transform:uppercase;color:var(--gold);margin:0 0 14px}
section{padding:60px 64px 30px;border-top:1px solid var(--hairline);
 margin-top:56px;scroll-margin-top:80px}
/* Prose fills the padded box instead of hugging the left edge. */
section>p,section>ul,section>ol,section>blockquote,
section>h2,section>h3,section>.seck{max-width:none}
section:first-of-type{border-top:0}
section:nth-of-type(odd){background:var(--t1)}
section:nth-of-type(even){background:var(--t2)}
nav.toc{display:flex;flex-wrap:wrap;gap:8px 26px;margin:0 0 14px;
 padding:16px 0;border-top:1px solid var(--hairline);
 border-bottom:1px solid var(--hairline);font-family:var(--sans)}
nav.toc a{padding:4px 0;border-bottom:1px solid transparent;font-size:10.5px;
 font-weight:500;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
 text-decoration:none;transition:color .3s,border-color .3s}
nav.toc a:hover,nav.toc a:focus-visible{color:var(--ink);border-bottom-color:var(--gold)}
nav.toc .n{color:var(--gold);font-family:var(--serif);font-style:italic;
 font-size:12px;letter-spacing:0;margin-right:8px}

/* ---- module cards ----------------------------------------------------- */
.mcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
 gap:18px;margin:26px 0}
.mcard{display:block;border:1px solid var(--hairline);padding:22px;
 color:var(--ink);text-decoration:none;
 transition:border-color .35s ease,transform .35s ease}
.mcard:nth-child(5n+1){background:var(--t1)}
.mcard:nth-child(5n+2){background:var(--t2)}
.mcard:nth-child(5n+3){background:var(--t3)}
.mcard:nth-child(5n+4){background:var(--t2)}
.mcard:nth-child(5n+5){background:var(--t1)}
.mcard:hover,.mcard:focus-visible{border-color:var(--gold);
 transform:translateY(-2px)}
/* module cards on the course map carry the module's own main image */
.mcard.mcard-photo{padding:0}
.mcard.mcard-photo>*:not(.mcover){padding-left:22px;padding-right:22px}
.mcard.mcard-photo .mcard-num{padding-top:16px}
.mcard.mcard-photo h3{margin:.15em 0 .4em 22px}
.mcover{border-bottom:1px solid var(--hairline);background:var(--code-bg)}
.mcover img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;
 margin:0;filter:var(--fig-filter,saturate(.62) contrast(1.08))}
.mcard.mcard-photo p.msum{font-size:15px;color:var(--ink);line-height:1.62}
.mcard h3{margin:.2em 0 .45em;font-size:22px;line-height:1.24}
.mcard p{margin:.3em 0;color:var(--muted);font-size:14.5px;
 font-family:var(--sans);line-height:1.55}
.mcard p strong{color:var(--ink);font-weight:600}
.mcard .mcard-num{font:600 10px/1 var(--sans);letter-spacing:.2em;
 text-transform:uppercase;color:var(--gold)}

/* ---- glossary --------------------------------------------------------- */
.glossary{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
 gap:18px;margin:26px 0}
.term{border:1px solid var(--hairline);padding:22px;background:var(--t1)}
.term:nth-child(4n+2){background:var(--t2)}
.term:nth-child(4n+3){background:var(--t2)}
.term:nth-child(4n+4){background:var(--t3)}
.term h3{margin:0 0 .4em;font-size:21px;color:var(--gold)}
.term p{font-size:15.5px;line-height:1.62}

/* ---- sources / bibliography ------------------------------------------ */
details.sources{border:1px solid var(--hairline);background:var(--t2);
 padding:18px 22px;margin:26px 0}
details.sources summary{cursor:pointer;font-family:var(--sans);
 font-weight:600;color:var(--gold);font-size:11px;letter-spacing:.18em;
 text-transform:uppercase}
details.sources summary:hover{color:var(--ink)}
details.sources[open] summary{margin-bottom:12px}
details.sources p{font-family:var(--sans);font-size:14.5px;
 line-height:1.6;color:var(--muted);margin:.4em 0}
details.sources ul,details.sources ol{margin:0;padding-left:22px}
details.sources li{font-family:var(--sans);font-size:14.5px;
 line-height:1.6;margin:.34em 0}

/* ---- figures ---------------------------------------------------------- */
figure.diagram{background:var(--t1);border:1px solid var(--hairline);
 padding:20px;margin:28px 0}
figure.diagram svg{width:100%;height:auto;display:block}
figure.imgfig{margin:28px 0;border:1px solid var(--hairline);background:var(--t1)}
figure.imgfig img{margin:0;width:100%;
 filter:var(--fig-filter,saturate(.62) contrast(1.08) brightness(.68))}
figure.imgfig figcaption,figure.diagram figcaption{
 font-family:var(--sans);font-size:12px;line-height:1.55;color:var(--muted);
 padding:12px 16px;margin:0;text-align:left;border-top:1px solid var(--hairline)}
figure.diagram figcaption{border-top:0;padding:12px 0 0}
figure.chart{background:var(--t1);border:1px solid var(--hairline);
 padding:24px 26px;margin:28px 0;font-family:var(--sans)}
figure.chart figcaption{font-family:var(--serif);font-weight:400;font-size:21px;
 margin:0 0 16px;letter-spacing:-.01em}
.chartrow{display:grid;grid-template-columns:230px 1fr 84px;gap:14px;
 align-items:center;margin:10px 0;font-size:15px}
.chartrow .bl{color:var(--muted);text-align:right}
.chartrow .track{background:var(--code-bg);height:20px;display:block;overflow:hidden;
 border-top:1px solid var(--hairline-soft);border-bottom:1px solid var(--hairline-soft)}
.chartrow .fill{background:var(--gold);height:100%;display:block}
.chartrow .bv{color:var(--ink);font-weight:600;font-size:15px}

/* ---- teaching charts -------------------------------------------------- */
figure.teach{margin:30px 0;background:var(--t1);border:1px solid var(--hairline);
 padding:24px 26px}
figure.teach .tcap{font-family:var(--serif);font-weight:400;
 font-size:22px;letter-spacing:-.01em;margin:0 0 6px}
figure.teach .tsub{font-family:var(--sans);font-size:12px;letter-spacing:.02em;
 color:var(--muted);margin:0 0 20px}
.teach .bars{display:flex;flex-direction:column;gap:11px}
.teach .bar{display:grid;grid-template-columns:minmax(160px,280px) 1fr 110px;
 gap:16px;align-items:center;font-family:var(--sans);font-size:15px}
.teach .bar .bl{color:var(--muted);text-align:right;line-height:1.3}
.teach .bar .bt{background:var(--code-bg);height:22px;display:flex;overflow:visible;
 min-width:2px;border-top:1px solid var(--hairline-soft);
 border-bottom:1px solid var(--hairline-soft)}
.teach .bar .bf{background:var(--gold);height:100%;display:block}
.teach .bar .bf.neg{background:var(--neg)}
.teach .divwrap{position:relative}
.teach .divwrap::before{content:"";position:absolute;left:50%;top:0;bottom:0;
 width:1px;background:var(--hairline)}
.teach .bar .bt{position:relative}
.teach .bar .bv{color:var(--ink);font-weight:600;font-size:15px;
 font-variant-numeric:tabular-nums}
.teach .statrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 gap:14px;margin:6px 0 4px}
.teach .stat{background:var(--t2);border:1px solid var(--hairline);
 padding:16px 18px;font-family:var(--sans)}
.teach .stat .sl{font-size:10.5px;color:var(--muted);text-transform:uppercase;
 letter-spacing:.14em;margin-bottom:8px}
.teach .stat .sv{font-size:34px;font-weight:400;letter-spacing:-.02em;
 font-family:var(--serif);font-variant-numeric:tabular-nums}
.teach .stat .sd{font-size:12.5px;color:var(--muted);margin-top:4px}
.teach .tnote{font-family:var(--sans);font-size:12px;color:var(--muted);
 margin:16px 0 0}
.teach details{margin-top:14px}
.teach details summary{cursor:pointer;color:var(--muted);font-size:12px;
 font-family:var(--sans);letter-spacing:.06em}
.teach details summary:hover{color:var(--ink)}

/* ---- module navigation ------------------------------------------------- */
.modnav{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:56px 0 8px;
 padding-top:24px;border-top:1px solid var(--hairline);
 font-family:var(--sans);font-size:11px;letter-spacing:.08em}
.modnav a{border:1px solid var(--hairline);padding:10px 16px;color:var(--ink);
 text-decoration:none;background:var(--t1);transition:border-color .3s,color .3s}
.modnav a:hover,.modnav a:focus-visible{border-color:var(--gold);color:var(--gold)}
.modnav .map{color:var(--muted)}
.modnav .disabled{color:var(--muted);padding:10px 4px}

/* ---- footer ------------------------------------------------------------ */
footer{border-top:1px solid var(--hairline);margin-top:70px;background:var(--t1)}
footer .col{padding:24px 0 48px;color:var(--muted);font:500 10px/1.6 var(--sans);
 letter-spacing:.16em;text-transform:uppercase;display:flex;
 justify-content:space-between;gap:18px;flex-wrap:wrap}
footer a{color:var(--muted);text-decoration:none}
footer a:hover{color:var(--gold)}
.hint{color:var(--muted);font-size:13px}

/* ---- print ------------------------------------------------------------- */
@media print{
 /* Theme-faithful print: the PDF must carry the CHOSEN theme (an earlier
    block force-overrode every palette to white/black).
    Text is re-inked to solid print colors from the ACTIVE theme tokens so
    contrast survives on paper, but the palette itself stays the theme's. */
 html{scroll-behavior:auto}
 /* The screen zoom knob (body{zoom:var(--page-zoom)}) must never reach the
    paper: Chromium print-to-PDF with a zoom<1 body lays the content flush
    at the margin box and glyphs shear at the page's left edge. Print has
    its own scaling; clamp to 1. */
 body{zoom:1 !important}
 body{font-size:11pt;line-height:1.5;
  background:var(--el-bg);color:var(--el-ink) !important}
 * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
 .skip,header.top,nav.tabs,nav.toc,footer,.modnav{display:none!important}
 /* A 0 print padding parks every first glyph flush against the PDF margin
    box (kicker, h1, image credit sheared at the edge). The .3in inner
    gutter keeps type fully inside the margin box. */
 main,.col{width:100%!important;max-width:none!important;padding:0 .3in !important}
 main>p,main>ul,main>ol,main>blockquote,.lede,
 section>p,section>ul,section>ol,section>blockquote{max-width:none}
 a{color:var(--el-accent);text-decoration:underline}
 a[href^="http"]::after{content:" (" attr(href) ")";font-size:90%;
  word-break:break-all;font-weight:400}
 .lede,blockquote,details.sources,figure.teach,figure.diagram,
 figure.feature,figure.imgfig,figure.chart{border-color:var(--el-line)}
 .lede, section { background: var(--el-panel) !important;
  color: var(--el-ink) !important; }
 section{background:var(--el-panel)!important}
 pre{background:var(--el-panel-2);color:var(--el-ink);white-space:pre-wrap;
  overflow:visible}
 .tablewrap{overflow:visible}
 table,figure,pre,blockquote,details.sources{break-inside:avoid}
 th,td{border-top:1px solid var(--el-line)}
}

/* ---- mobile: every guide and course is mobile-clean ----- */
@media (max-width:720px){
 body{font-size:17px;line-height:1.65}
 main,.col,.topin{width:100%;max-width:none;padding-left:18px;padding-right:18px}
 .topin{flex-wrap:wrap;gap:10px;padding-top:14px;padding-bottom:14px}
 .topin>a:last-child{display:none}
 nav.tabs{margin-left:auto;margin-right:0}
 h1{font-size:clamp(30px,9vw,42px)}
 h2{font-size:clamp(24px,6.4vw,32px)}
 h3{font-size:21px}
 section{padding:38px 18px 16px;margin-top:36px}
 .lede{padding:20px 20px;font-size:16px}
 .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
 .tablewrap table{width:100%;min-width:720px}
 /* Never break words inside table cells: a narrow column with
    overflow-wrap:break-word turns "documented" into "document ed". */
 th,td{overflow-wrap:normal;word-break:normal;hyphens:none}
 .mcards,.glossary{grid-template-columns:1fr}
 figure.feature{margin:22px 0 28px}
 figure.feature figcaption{font-size:9px;padding:10px 12px}
 .teach .bar{grid-template-columns:1fr 84px;
  grid-template-areas:"lbl lbl" "trk val";gap:6px 12px}
 .teach .bar .bl{grid-area:lbl;text-align:left}
 .teach .bar .bt{grid-area:trk}
 .teach .bar .bv{grid-area:val}
 .teach .tcap{font-size:18px}
 .teach .tsub{font-size:12px}
 .teach .stat .sv{font-size:26px}
 .chartrow{grid-template-columns:110px 1fr 56px;gap:8px;font-size:12.5px}
 nav.toc{gap:8px 16px}
 nav.toc a{font-size:10px;padding:5px 0}
 th:first-child,td:first-child{white-space:normal}
 pre{font-size:12.5px;padding:14px}
 footer .col{flex-direction:column;gap:8px}
 .modnav a{padding:10px 14px}
}
"""

SHELL = """<!doctype html>
<html lang="en" data-theme="%%THEME%%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<meta name="description" content="%%DESC%%">
<script>
/*greyok-theme-bootstrap*/try{var t=localStorage.getItem('el-theme');
/* no stored pick = the author's baked data-theme STANDS (the bootstrap must
   not force 'master' over every built theme) */
if(t&&/^[a-z][a-z-]*$/.test(t))document.documentElement.dataset.theme=t;
var z=localStorage.getItem('el-zoom');
if(!z||!/^(60|70|80|90|100|110)$/.test(z))z='90';
document.documentElement.style.setProperty('--page-zoom',(Number(z)+20)/100);
}catch(e){
/* leave the baked attr in place */}</script>
<link rel="stylesheet" href="%%KITCSS%%">
<link rel="stylesheet" href="%%KITSRC%%assets/kit/screens.ui.css">
<style>%%CSS%%</style>
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="top"><div class="topin">
  <span class="wordmark"><a href="%%HUB%%" style="color:inherit">Master Research</a></span>
  %%TABS%%
  <label class="themewrap themepick"><span class="sr-only">Theme</span>
  <select data-theme-picker id="theme-picker" aria-label="Color theme">%%THEMEOPTS%%</select></label>
  <label class="themewrap"><span class="sr-only">Page zoom</span>
  <select id="zoom-picker" aria-label="Page zoom">%%ZOOMOPTS%%</select></label>
  <a href="%%HUB%%">&larr; Course hub</a>
</div></header>
<main id="content" class="col">%%BODY%%</main>
<footer><div class="col"><span>Updated %%WHEN%%.</span>
<a href="%%HUB%%">Course hub &rarr;</a></div></footer>
<script src="%%KITJS%%" defer></script>
<script src="%%KITSRC%%assets/kit/screens.ui.js" defer></script>
<script>
// greyok zoom control: page-zoom on <body>, persisted, no reflow flash
(function(){
  var sel = document.getElementById('zoom-picker');
  if(!sel) return;
  var apply = function(v){
    if(!/^(30|40|50|60|70|80|90|100)$/.test(v)) v = '50';
    document.documentElement.style.setProperty('--page-zoom',(Number(v)+20)/100);
    try{ localStorage.setItem('el-zoom', v); }catch(e){}
    if(sel.value !== v) sel.value = v;
  };
  sel.addEventListener('change', function(){ apply(sel.value); });
  var cur;
  try{ cur = localStorage.getItem('el-zoom'); }catch(e){}
  apply(cur || '50');
})();
</script>
</body>
</html>"""

def theme_options(theme: str = "master") -> str:
    """Picker options with the BUILT theme marked selected. The kit's
    switcher applies the picker's value at load, so if the attribute and the
    picker disagree, the picker wins and would wipe the chosen theme; the
    pre-selected option keeps the two in agreement."""
    t = (theme or "master").strip()
    out = []
    for th in KIT_THEMES:
        label = th.capitalize() if th != "master" else "Master (site)"
        sel = " selected" if th == t else ""
        out.append(f'<option value="{th}"{sel}>{label}</option>')
    return "".join(out)

KIT_THEMES = ["obsidian", "master", "neutral", "polaroid", "cockpit", "cockpit-paper",
              "console", "compact", "casebook", "agent-paper", "agent-pulse",
              "agent-history", "terminal", "swiss",
              "bespoke", "torque", "umami", "aurora"]

ZOOM_LEVELS = [30, 40, 50, 60, 70, 80, 90, 100]
ZOOM_OPTS = "".join(
    f'<option value="{z}"{" selected" if z == 50 else ""}>{z}%</option>'
    for z in ZOOM_LEVELS)

IMG_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMG_ANY_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
H2_RE = re.compile(r"^##\s+(?!#)(.*)$")

SPEC_HDR_RE = re.compile(
    r"typeof|specification|content categor|permitted|implicit|dom interface"
    r"|wrapper|return value|aria role|search coverage|media contact"
    r"|tag omission|permitted parents|permitted content|event id|event ids"
    r"|process id|thread id|parent process id|primary evidence|key events"
    r"|telemetry|channel", re.I)
DASHBOARD_HDR_RE = re.compile(r"(?i)\b(metric|value|reading|status|level|score)\b")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
TSV_ROW_RE = re.compile(r"^[^\t|\n]{1,80}\t[^\t|\n]+$")
NUM_RE = re.compile(r"^[+-]?\$?#?[\d,]*(\.\d+)?\s*%?$")

def _clean_seps(block_lines):
    """The publisher flattens markdown tables to tab-separated rows in some
    guides (header<TAB>row...). Normalize those to pipe tables so the chart
    extractor sees them."""
    if not any(TSV_ROW_RE.match(ln) for ln in block_lines):
        return block_lines
    if any(TABLE_ROW_RE.match(ln) for ln in block_lines):
        return block_lines
    out = []
    for ln in block_lines:
        if TSV_ROW_RE.match(ln):
            cells = [c.strip() for c in ln.split("\t")]
            out.append("| " + " | ".join(cells) + " |")
            if len(out) == 1:
                out.append("| " + " | ".join(["---"] * len(cells)) + " |")
        else:
            out.append(ln)
    return out

def _units(values: list[str]) -> set[str]:
    """Unit markers present in a column's cells ($, %, x, currency, durations).
    More than one distinct unit means the column is a dashboard readout, not
    a comparable series, so it never becomes a teaching chart."""
    units: set[str] = set()
    for v in values:
        if "$" in v:
            units.add("$")
        if "%" in v:
            units.add("%")
        if re.search(r"\d\s*x\b", v, re.I):
            units.add("x")
        m = re.search(r"\b(btc|eth|usd|eur|days?|weeks?|months?|years?)\b", v, re.I)
        if m:
            units.add(m.group(1).lower())
    return units

_STRICT_NUM_CELL = re.compile(
    r"^[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|[kKmMbBxX])?$"
    r"|^[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(?:ms|s|sec|secs|min|mins|hr|hrs|hours?|"
    r"days?|weeks?|months?|years?|[kKmMbB]B?|GB|TB|MB)$", re.I)

def _tbl_num(v: str):
    """Parse a cell to float. Handles $0.02, 70-95% (low end), 1,284, +3.2%,
    and compound cells like '-33.48 (-6.33%)' (first number wins)."""
    v = v.strip()
    m = re.search(r"([+-]?\$?\d[\d,]*(?:\.\d+)?)\s*%?", v)
    if m:
        return float(m.group(1).replace(",", "").replace("$", ""))
    return None

def _parse_md_table(block_lines):
    rows = []
    for ln in block_lines:
        m = TABLE_ROW_RE.match(ln)
        if not m:
            return None
        cells = [c.strip() for c in m.group(1).split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows or None

def _find_chartable_table(block_lines):
    """Return (label_col, value_col, header, rows) if this table block is
    teachable numeric data, else None. Conservative: spec sheets, mixed
    prose tables, dashboard snapshots, and >14-row dumps never become charts."""
    rows = _parse_md_table(_clean_seps(block_lines))
    if not rows or not (3 <= len(rows) <= 15):
        return None
    header = rows[0]
    if not (2 <= len(header) <= 6):
        return None
    if any(SPEC_HDR_RE.search(h) for h in header):
        return None
    if any(len(r) != len(header) for r in rows[1:]):
        return None
    for ci in range(len(header) - 1, 0, -1):
        cells = [r[ci] for r in rows[1:] if ci < len(r)]
        strict = [c for c in cells if _STRICT_NUM_CELL.match(c.strip())]
        if len(strict) < 0.7 * len(cells):
            continue
        vals = [_tbl_num(c) for c in cells]
        nums = [v for v in vals if v is not None]
        if len(nums) >= 3 and len(nums) >= 0.7 * (len(rows) - 1):
            if max(nums) > 0 or min(nums) < 0:
                if DASHBOARD_HDR_RE.search(header[0] + " " + header[ci]):
                    return None
                if len(_units([r[ci] for r in rows[1:]])) > 1:
                    return None
                return 0, ci, header, rows
    return None

def chart_is_teachable(block_lines: list[str]) -> bool:
    """True when this table block would render as a teaching chart."""
    return _find_chartable_table(block_lines) is not None

def _fmt_val(v: float, is_pct: bool) -> str:
    if is_pct:
        return f"{v:g}%"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v:,.0f}"
    return f"{v:g}"

def _chart_html(label_col, val_col, header, rows, chart_title):
    """Render one horizontal-bar teaching chart from a parsed table.
    Sequential single hue (the site accent), direct value labels in ink,
    bars ≤24px with 4px rounded data-end, source table in a details view."""
    data = []
    is_pct = "%" in header[val_col] or any("%" in r[val_col] for r in rows[1:])
    is_money = "$" in header[val_col] or any("$" in r[val_col] for r in rows[1:])
    for r in rows[1:]:
        v = _tbl_num(r[val_col])
        if v is None:
            continue
        label = re.sub(r"[*_`]", "", r[label_col]).strip() or "n/a"
        data.append((label, v, r[val_col].strip()))
    if not data:
        return "", 0
    diverging = any(v < 0 for _, v, _ in data) and any(v > 0 for _, v, _ in data)
    vmax = max(abs(v) for _, v, _ in data) or 1
    bars = []
    for label, v, raw in data:
        w = max(abs(v) / vmax * 100, 0.5)
        val_txt = raw if raw else _fmt_val(v, is_pct)
        if diverging and v < 0:
            bars.append(
                f"<div class='bar'><span class='bl'>{label}</span>"
                f"<span class='bt'><span class='bf neg' "
                f"style='width:{w:.1f}%;margin-left:auto'></span></span>"
                f"<span class='bv'>{val_txt}</span></div>")
        elif diverging:
            bars.append(
                f"<div class='bar'><span class='bl'>{label}</span>"
                f"<span class='bt'><span class='bf' "
                f"style='width:{w:.1f}%'></span></span>"
                f"<span class='bv'>{val_txt}</span></div>")
        else:
            bars.append(
                f"<div class='bar'><span class='bl'>{label}</span>"
                f"<span class='bt'><span class='bf' style='width:{w:.1f}%'></span></span>"
                f"<span class='bv'>{val_txt}</span></div>")
    basis = ""
    if diverging:
        basis = ": diverging scale, centered on zero (red = negative, green = positive)"
    elif is_pct:
        total = sum(v for _, v, _ in data)
        if 95 <= total <= 105:
            basis = ": shares of a whole (bars sized to the largest)"
        else:
            basis = ": percentage comparison (bars sized to the largest)"
    elif is_money:
        basis = ": cost comparison (bars sized to the highest price)"
    else:
        basis = ": bars sized to the largest value"
    sub = ((f"{header[val_col]} by {header[label_col]}" if header[label_col]
            else header[val_col]) + basis)
    bars_cls = "bars divwrap" if diverging else "bars"
    return (f"<figure class='teach' role='img' aria-label='{chart_title}: {sub}'>"
            f"<figcaption class='tcap'>{chart_title}</figcaption>"
            f"<div class='tsub'>{sub} ({len(data)} entries, drawn to scale)</div>"
            f"<div class='{bars_cls}'>{''.join(bars)}</div>"
            f"</figure>"), len(data)

def inject_charts(md_text: str, section_head: str = "",
                  max_charts: int = 99):
    """Find chartable tables in this markdown and emit chart HTML blocks.
    Returns (new_md, chart_html_list, n_charts, n_rows_rendered). The table
    itself is REMOVED from the markdown (it lives inside the chart's details);
    non-teachable tables pass through untouched. Stops charting once
    max_charts have been emitted. Handles both pipe tables and the
    publisher's tab-separated flattened tables."""
    lines = md_text.split("\n")
    out, charts, n_charts, n_rows = [], [], 0, 0
    last_h3 = ""
    i, n = 0, len(lines)
    while i < n:
        if lines[i].startswith("### "):
            last_h3 = lines[i][4:].strip()
        if TABLE_ROW_RE.match(lines[i]) or TSV_ROW_RE.match(lines[i]):
            j = i
            while j < n and (TABLE_ROW_RE.match(lines[j]) or TSV_ROW_RE.match(lines[j])):
                j += 1
            block = lines[i:j]
            found = _find_chartable_table(block)
            if found and n_charts < max_charts:
                lc, vc, header, rows = found
                shead = re.sub(r"^\d+\.\s*", "", last_h3 or section_head).strip()
                ctitle = (f"{header[vc]} - {shead}" if shead
                          and shead.lower() not in header[vc].lower()
                          else header[vc])
                html, nrows = _chart_html(lc, vc, header, rows, ctitle)
                if html:
                    out.append(html)
                    charts.append(html)
                    n_charts += 1
                    n_rows += nrows
                    i = j
                    continue
            out.extend(block)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), charts, n_charts, n_rows

def slugify(text: str, fallback: str = "section") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or fallback)[:50]

def split_sections(md_text: str):
    """Split on '## ' headings; returns (intro_md, [(heading, body_md)])."""
    intro, sections = [], []
    head, body = None, []
    for line in md_text.split("\n"):
        m = H2_RE.match(line)
        if m:
            if head:
                sections.append((head, body))
            head, body = m.group(1).strip(), []
        elif head is not None:
            body.append(line)
        else:
            intro.append(line)
    if head:
        sections.append((head, body))
    return "\n".join(intro).strip(), [(h, "\n".join(b).strip()) for h, b in sections]

JUNK_RE = re.compile(
    r"(license|licence|mediawiki|powered by|logo|badge|icon|donat|flag|banner"
    r"|/static/|/w/skins|commons.wikimedia|site-logo|favicon|captcha)", re.I)

BAD_HOST_RE = re.compile(
    r"^(?:www\.)?(?:bleepingcomputer\.com/forums|twitter\.com/intent"
    r"|x\.com/intent|facebook\.com/sharer|linkedin\.com/shareArticle"
    r"|pinterest\.com/pin|reddit\.com/submit|cisco\.com/content/dam/cisco-cdc/site"
    r"|venturebeat\.com/_next/image|medium\.com/_/stat)", re.I)
AVATAR_RE = re.compile(r"(default_large|profile/|avatar|gravatar|/avatars?/|"
                       r"_normal\.|_mini\.|favicon)", re.I)

def _image_is_junk(src: str, alt: str) -> str:
    return shared_junk_reason(src, alt, _DIAGRAM_WORDS)

_JUNK_IMG_WORDS = re.compile(
    r"(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|placeholder|"
    r"spacer|pixel|tracking|advertisement|\bad\b|adsense|hero image|"
    r"stock photo|stock image|decorative|divider|separator|arrow|bullet|"
    r"social|share|follow|comment|loading|spinner|thumbnail|"
    r"profile photo|author photo|generic|unsplash|pexels|shutterstock|"
    r"getty|freepik|lorem|sample|default|cover image|background image)")
_STOCK_ALT = STOCK_ALT_RE  # shared definition (image_gate)
_DIAGRAM_WORDS = re.compile(
    r"(?i)(diagram|flowchart|flow chart|architecture|schematic|wiring|"
    r"circuit|blueprint|wireframe|mockup|screenshot|screen shot|figure|"
    r"fig\.?\s*\d|chart|graph|plot|timeline|infographic|setup|install|"
    r"dashboard|control panel|terminal|cli|interface|step \d|process|"
    r"workflow|pipeline|data flow|network map|topology|anatomy|breakdown|"
    r"comparison|matrix)")

def _stopwords() -> set:
    return {
        "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
        "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
        "how", "its", "may", "new", "now", "old", "see", "two", "way", "who",
        "with", "from", "that", "this", "what", "when", "your", "than", "then",
        "into", "over", "such", "use", "used", "using", "via", "per",
    }

def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(t) > 3 and t not in _stopwords()}

def gate_section_images(md_body: str, section_heading: str,
                        max_images: int = 12):
    """Apply the semantic image gate to one section's markdown. Returns
    (new_md, kept, dropped) where dropped is a list of {src, alt, reason}.
    An image survives only when it is diagram-shaped OR its alt/caption has
    meaningful token overlap with the section's own objective, and it is not
    logo/avatar/stock/ad/social/hero chrome. At most max_images are kept."""
    kept, dropped = [], []
    heading_tokens = _tokens(section_heading)
    body_tokens = _tokens(md_body)
    objective = heading_tokens | body_tokens

    def _repl(m):
        alt, src = m.group(1) or "", m.group(2)
        junk_reason = _image_is_junk(src, alt)
        if junk_reason:
            dropped.append({"src": src, "alt": alt, "reason": junk_reason,
                            "full": m.group(0)})
            return ""
        if len(kept) >= max_images:
            dropped.append({"src": src, "alt": alt, "reason": "image cap",
                            "full": m.group(0)})
            return ""
        if JUNK_RE.search(alt) or JUNK_RE.search(src) \
           or BAD_HOST_RE.search(src) or AVATAR_RE.search(src):
            dropped.append({"src": src, "alt": alt,
                            "reason": "chrome/asset pattern", "full":
                            m.group(0)})
            return ""
        probe = (alt + " " + src).lower()
        if _JUNK_IMG_WORDS.search(alt):
            if not _DIAGRAM_WORDS.search(alt):
                dropped.append({"src": src, "alt": alt,
                                "reason": "junk alt (logo/stock/ad)",
                                "full": m.group(0)})
                return ""
        if _STOCK_ALT.match(alt) and not _DIAGRAM_WORDS.search(probe):
            dropped.append({"src": src, "alt": alt,
                            "reason": "generic stock alt, no diagram shape",
                            "full": m.group(0)})
            return ""
        if _DIAGRAM_WORDS.search(probe):
            kept.append({"src": src, "alt": alt})
            return m.group(0)
        if objective:
            probe_tokens = _tokens(probe)
            overlap = len(objective & probe_tokens)
            if overlap >= 2 or (overlap >= 1 and len(probe_tokens) <= 3):
                kept.append({"src": src, "alt": alt})
                return m.group(0)
            dropped.append({"src": src, "alt": alt,
                            "reason": "no overlap with section objective",
                            "full": m.group(0)})
            return ""
        return m.group(0) if _DIAGRAM_WORDS.search(probe) else ""

    new_md = IMG_ANY_RE.sub(_repl, md_body)
    for d in dropped:
        full = d.pop("full", None)
        if not full:
            continue
        new_md = _remove_credit_block(md_body, new_md, full)
    return new_md, kept, dropped

CREDIT_LINE_RE = re.compile(r"^\*Image:[^\n]*\*\s*$")
CREDIT_OPEN_RE = re.compile(r"^\*Image:")
CREDIT_CLOSE_RE = re.compile(r"\*\s*$")
_MD_STRUCT_RE = re.compile(r"^(?:#|\||!\[|[-+] |\d+\. |```|>)")

def _credit_block_after(md_text: str, img_full: str) -> list[str] | None:
    """Return the "*Image: ...*" provenance credit block (list of raw lines,
    leading blank separators EXCLUDED, from just after img_full's STANDALONE
    md line), or None, including when the image sits inline inside prose.

    The credit may span MULTIPLE lines with blanks inside the "*...*" span,
    e.g. "Software:/The Tcpdump team/Screenshot:/blank/VulcanSphere, BSD via
    Wikimedia Commons.*". The block ends at the line that closes the "*...*"
    emphasis, is bounded at 15 lines, and aborts (with what was gathered so
    far dropped only if it is a complete block) at structural markdown; real
    prose after a stray "*Image:" is never eaten."""
    pos = md_text.find(img_full)
    if pos < 0:
        return None
    line_start = md_text.rfind("\n", 0, pos) + 1
    lines = md_text[line_start:].split("\n")
    if not lines or lines[0].strip() != img_full.strip():
        return None
    rest = lines[1:]
    n_skip = 0
    while n_skip < len(rest) and not rest[n_skip].strip():
        n_skip += 1
    if n_skip >= len(rest) or not CREDIT_OPEN_RE.match(rest[n_skip].strip()):
        return None
    block = []
    stop = n_skip + 15
    i = n_skip
    while i < stop and not _MD_STRUCT_RE.match(rest[i].strip()):
        block.append(rest[i])
        if CREDIT_CLOSE_RE.search(rest[i].strip()):
            return block
        i += 1
    return None

def _remove_credit_block(md_body: str, new_md: str, img_full: str) -> str:
    """Delete the paired credit block of a dropped image from new_md, where
    md_body is the pre-sub text the block was found against. The block must
    still sit line-by-line in new_md (only image substitutions happened)."""
    block = _credit_block_after(md_body, img_full)
    if not block:
        return new_md
    stripped = [ln.strip() for ln in block]
    lines = new_md.split("\n")
    opener = stripped[0]
    for i, ln in enumerate(lines):
        if ln.strip() != opener:
            continue
        if [l.strip() for l in lines[i:i + len(block)]] == stripped:
            del lines[i:i + len(block)]
            return "\n".join(lines)
    return new_md

def normalize_credit_blocks(md_text: str) -> str:
    """Collapse MULTI-line "*Image: ...*" provenance credit blocks into one
    line each. A scraper-wrapped caption such as "Tcpdump 4.9.3 screenshot -
    Software:/The Tcpdump team/blank/VulcanSphere, BSD via Wikimedia
    Commons.*" embeds a blank line inside the "*...*" span, and markdown
    emphasis may not span a blank line, so the caption otherwise prints as
    raw text with literal asterisks beside a KEPT image. Internal newlines
    and blank lines become single spaces; the block stays where the image
    put it. Single-line credits pass through unchanged (idempotent)."""
    lines = md_text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if CREDIT_OPEN_RE.match(s) and not CREDIT_CLOSE_RE.search(s):
            block = [s]
            j = i + 1
            stop = min(n, i + 15)
            closed = False
            while j < stop and not _MD_STRUCT_RE.match(lines[j].strip()):
                t = lines[j].strip()
                block.append(t)
                if CREDIT_CLOSE_RE.search(t):
                    j += 1
                    closed = True
                    break
                j += 1
            merged = " ".join(x for x in block if x)
            if closed and CREDIT_CLOSE_RE.search(merged):
                out.append(merged)
                i = j
                continue
            out.append(lines[i])
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)

def _drop_image_and_credit(md_text: str, img_full: str) -> str:
    """Remove one md image occurrence; when the image's standalone line hosts
    it, the immediately-following "*Image: ...*" provenance credit goes too,
    single- OR multi-line: a scraper-wrapped multi-line credit must ship with
    the dropped image, never as an orphaned raw-text caption with literal
    asterisks.
    An image dropped at build time must not leave an orphaned credit paragraph
    behind it: a pick that died at build must not ship its credit plus a
    stray "!" remnant without the image."""
    pos = md_text.find(img_full)
    if pos < 0:
        return md_text
    line_start = md_text.rfind("\n", 0, pos) + 1
    line = md_text[line_start:].split("\n")[0]
    if line.strip() != img_full.strip():
        return md_text[:pos] + md_text[pos + len(img_full):]
    lines = md_text[line_start:].split("\n")
    rest = lines[1:]
    block = _credit_block_after(md_text, img_full)
    if block:
        n_skip = 0
        while n_skip < len(rest) and not rest[n_skip].strip():
            n_skip += 1
        for k, blk_ln in enumerate(block):
            idx = n_skip + k
            if idx < len(rest) and rest[idx].strip() == blk_ln.strip():
                continue
            break
        else:
            del rest[n_skip:n_skip + len(block)]
    return md_text[:line_start] + "\n".join(rest)

def download_images(md_text: str, assets_dir: Path, limit: int, keep_remote: bool,
                    src_dir: Path | None = None):
    """Best-effort download of the guide's images (topical because the guide
    itself is topical); downloaded URLs are rewritten to local asset paths.
    Non-topical assets (license/logo/banner junk the corpus's anti-garbage
    law 3 forbids) are skipped and counted, never embedded.

    src_dir lets a guide-side RELATIVE path resolve: the portal build step
    copies a chosen confirm-grid candidate beside the md; such a local
    source is copied into assets, never re-fetched from the network, so a
    user-approved pick can never fail on a second download.

    An image that is dropped (junk) or whose download fails is removed from
    the md TOGETHER with its immediately-following "*Image: ...*" credit
    line: an orphaned credit (or a bare "!" remnant) must never ship.

    Non-authority media is scraper chrome: anything that matches BAD_HOST_RE or
    AVATAR_RE is forum avatars, share buttons, site header art, not guide
    media. It is dropped entirely, never embedded, and counted."""
    urls, seen = [], set()
    skipped_junk = 0
    md_text = normalize_credit_blocks(md_text)
    junk_full_matches = []
    match_of: dict[str, str] = {}
    for m in IMG_ANY_RE.finditer(md_text):
        u = m.group(2)
        alt = m.group(1) or ""
        if JUNK_RE.search(alt) or JUNK_RE.search(u) \
           or BAD_HOST_RE.search(u) or AVATAR_RE.search(u):
            skipped_junk += 1
            junk_full_matches.append(m.group(0))
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)
            if u not in match_of:
                match_of[u] = m.group(0)
    report = {"found": len(urls), "downloaded": 0,
              "failed_or_kept_remote": 0, "skipped_nontopical": skipped_junk}

    def fetch(u: str):
        name = hashlib.sha1(u.encode()).hexdigest()[:16]
        for ext in (".png", ".jpg", ".webp", ".gif", ".svg", ".avif", ".img"):
            cached = assets_dir / f"{name}{ext}"
            if cached.exists() and cached.stat().st_size > 128:
                return u, cached.name
        dest = assets_dir / f"{name}.img"
        if src_dir and not re.match(r"(?i)^[a-z][a-z0-9+.\-]+://", u):
            try:
                local = src_dir / u
                if not local.is_file():
                    return None
                data = local.read_bytes()
            except Exception:
                return None
            if len(data) < 128:
                return None
            dest = dest.with_suffix(local.suffix or ".img")
            dest.write_bytes(data)
            return u, dest.name
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read(4_000_000)
                ctype = (r.headers.get("Content-Type") or "").split(";")[0]
            if not ctype.startswith("image/") or len(data) < 128:
                return None
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                   "image/gif": "gif", "image/svg+xml": "svg",
                   "image/avif": "avif"}.get(ctype)
            dest = dest.with_suffix(f".{ext or 'img'}")
            dest.write_bytes(data)
            return u, dest.name
        except Exception:
            return None

    mapping = {}
    targets = [] if keep_remote else urls[:limit]
    if targets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            for res in ex.map(fetch, targets):
                if res:
                    mapping[res[0]] = res[1]
                    report["downloaded"] += 1
    report["failed_or_kept_remote"] = len(targets) - report["downloaded"]
    for u, fname in mapping.items():
        md_text = md_text.replace(f"]({u})", f"](assets/img/{fname})")
    dropped_fulls = set(junk_full_matches)
    dropped_fulls.update(match_of[u] for u in targets if u not in mapping)
    for full in dropped_fulls:
        while full in md_text:
            md_text = _drop_image_and_credit(md_text, full)
    return md_text, report

LEVEL_RE = re.compile(
    r"^\**\s*(?:eli5|undergrad|grad|phd|implementation)\s*[:\-–]?\s*\**", re.I)

HTML_TAGS = {"a", "p", "b", "i", "em", "strong", "code", "pre", "ul", "ol", "li",
             "table", "thead", "tbody", "tr", "td", "th", "div", "span", "figure",
             "figcaption", "img", "br", "hr", "sup", "sub", "details", "summary",
             "h1", "h2", "h3", "h4", "h5", "h6",
             "svg", "g", "path", "rect", "text", "tspan", "line", "circle",
             "ellipse", "polyline", "polygon", "defs", "marker", "title", "desc",
             "lineargradient", "radialgradient", "stop", "use", "symbol"}
TYPE_TOKEN_RE = re.compile(r"<([a-zA-Z][\w-]{0,30})>")

CODE_LABEL_RE = re.compile(
    r"\n(CSS|HTML|JavaScript|JS|Python|Bash|Shell|JSON|YAML|SQL|TypeScript|TS)\s*\n\s*Copy\s*\n",
    re.I)

AUTHORITY_A_RE = re.compile(
    r"<a\s+[^>]*href=\"(https?://(?:www\.)?(?:"
    r"(?:[a-z]+\.)?gov(?:/[a-z]{2})?|(?:[a-z]+\.)?mil"
    r"|nist\.gov|nist\.org|iso\.org|ietf\.org|w3\.org"
    r"|en\.wikipedia\.org|wikipedia\.org"
    r"|arxiv\.org|acm\.org|ieee\.org|doi\.org"
    r"|mitre\.org|attack\.mitre\.org"
    r"|sec\.gov|ftc\.gov|fcc\.gov|justice\.gov"
    r"|europol\.europa\.eu|interpol\.int|who\.int"
    r"|irs\.gov|ssa\.gov|consumerfinance\.gov"
    r"|ec\.europa\.eu|europa\.eu|icann\.org"
    r"|azleg\.gov|azcourts\.gov|azsos\.gov|azdhs\.gov"
    r"|courts\.state\.[a-z]+\.us|ca\.courts\.ca\.gov"
    r"|law\.cornell\.edu|casetext\.com|justia\.com|law\.justia\.com"
    r"|congress\.gov|govinfo\.gov|uscode\.house\.gov"
    r"|legis\.laws\.com|statelaws\.findlaw\.com"
    r"))[^\"]*\"[^>]*>(.*?)</a>",
    re.I | re.S)
ANY_A_RE = re.compile(r"<a\s+[^>]*href=\"(https?://[^\"]*)\"[^>]*>(.*?)</a>",
                      re.I | re.S)

_SOURCES_HEAD_RE = re.compile(
    r"(?i)\b(?:primary sources|sources|references|citations|bibliography)\b")

def _is_sources_heading(head: str) -> bool:
    return bool(_SOURCES_HEAD_RE.search(head or ""))

LEVEL_LABEL_RE = re.compile(
    r"\*\*(?:Executive Brief|ELI5|Undergrad|Grad|PhD|Implementation)"
    r"(?:[^:*]|\*(?!\*))*\*\*", re.I)
LEVEL_LINE_RE = re.compile(
    r"^\s*(?:>\s*)?\*\*(?:ELI5|Undergrad|Grad|PhD|Implementation)\b[^*]*\*\*\s*:?",
    re.I | re.M)
SECTION_SYMBOL_RE = re.compile(r"§\s*")

def unwrap_external_links(html: str) -> str:
    """Unwrap every external <a> to its anchor text (legacy --no-scrub path)."""
    return re.sub(
        r"<a\b[^>]*href=[\"'](?:[a-z]+:)?//[^\"']*[\"'][^>]*>(.*?)</a>",
        r"\1", html, flags=re.S | re.I)

_BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_PROTECTED_BLOCK_RE = re.compile(
    r"(<a\b.*?</a>|<code\b.*?</code>|<pre\b.*?</pre>)", re.I | re.S)
_TAG_SPLIT_RE = re.compile(r"(<[^>]*>)")

def _autolink_text_node(text: str) -> str:
    def repl(match):
        url = match.group(0)
        trail = ""
        while url and url[-1] in ".,;:!?)]}\"'":
            trail = url[-1] + trail
            url = url[:-1]
        if url in ("http://", "https://") or not url:
            return match.group(0)
        href = html_lib.escape(url, quote=True)
        label = html_lib.escape(url)
        return (f"<a href=\"{href}\" rel=\"noopener noreferrer\">{label}</a>"
                f"{trail}")
    return _BARE_URL_RE.sub(repl, text)

def autolink_bare_urls(html_text: str) -> str:
    """Turn bare http(s) URLs in rendered HTML into links.

    Existing anchors, inline code, and pre blocks are protected so a URL is
    linked exactly once and never inside an attribute value.
    """
    parts = _PROTECTED_BLOCK_RE.split(html_text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(part)
            continue
        for token in _TAG_SPLIT_RE.split(part):
            out.append(token if token.startswith("<")
                       else _autolink_text_node(token))
    return "".join(out)

def sources_details(html_body: str, label: str = "Sources") -> str:
    """Wrap a rendered Sources section in one compact collapsed <details>.

    The visible summary is "Sources (N)"; the body is a short linked list.
    Bare URLs are autolinked first, so a raw-URL list becomes clickable
    without any APA-style bibliography formatting.
    """
    body = autolink_bare_urls(html_body).strip()
    n_items = len(re.findall(r"<li\b", body, re.I))
    if not n_items:
        n_items = len(re.findall(
            r"<a\b[^>]*href=[\"']https?://", body, re.I))
    if not body:
        body = "<p>No sources recorded.</p>"
    return (f"<details class='sources' open><summary>{label} ({n_items})</summary>"
            f"{body}</details>")

def add_table_captions(html_text: str,
                       default_heading: str = "") -> str:
    """Add a visually hidden <caption> from the nearest preceding heading.

    ``default_heading`` supplies the section H2 when a table sits directly
    under it (the H2 is rendered outside the section body by the document
    renderer). The source table keeps its own heading context when copied,
    printed, or reached by a screen reader.
    """
    out, pos, last_heading = [], 0, default_heading
    token_re = re.compile(
        r"<h([1-6])\b[^>]*>.*?</h\1>|<table\b[^>]*>", re.I | re.S)
    for match in token_re.finditer(html_text):
        out.append(html_text[pos:match.start()])
        token = match.group(0)
        if token.lower().startswith("<table"):
            heading = re.sub(r"<[^>]+>", "", last_heading)
            heading = re.sub(r"\s+", " ", html_lib.unescape(heading)).strip()
            caption = html_lib.escape(heading) if heading else "Table"
            out.append(f"{token}<caption class='sr-only'>Table: "
                       f"{caption}</caption>")
        else:
            last_heading = token
            out.append(token)
        pos = match.end()
    out.append(html_text[pos:])
    return "".join(out)

def add_external_rel(html_text: str) -> str:
    """Give every external anchor rel="noopener noreferrer" (consistency)."""
    def repl(match):
        tag = match.group(0)
        if re.search(r"\brel=", tag, re.I):
            return tag
        return tag[:-1] + " rel=\"noopener noreferrer\">"
    return re.sub(r"<a\b[^>]*href=[\"']https?://[^>]*>", repl,
                  html_text, flags=re.I)

def rewrite_internal_links(html_text: str,
                           page_rel: str = "index.html") -> str:
    """Resolve internal links at build time for any page depth.

    * Root-relative ``course/...`` links (the source of the infostealers
      broken-link bug) are resolved from the site root, not the page dir.
    * Directory-form links gain an explicit ``index.html`` so ``file://``
      browsing works (no server-side index magic).
    * Fragments and query strings are preserved; external schemes, anchors,
      and protocol-relative URLs are untouched.
    """
    page_dir = posixpath.dirname(page_rel.replace("\\", "/"))

    def repl(match):
        pre, quote, href = match.group(1), match.group(2), match.group(3)
        if not href or href.startswith(("#", "?")) or href.startswith("//"):
            return match.group(0)
        low = href.lower()
        if low.startswith(("http:", "https:", "mailto:", "tel:",
                           "javascript:", "data:")):
            return match.group(0)
        base, hash_sep, fragment = href.partition("#")
        path, query_sep, query = base.partition("?")
        if not path:
            return match.group(0)
        path = html_lib.unescape(path)
        if path.startswith("/"):
            target = path.lstrip("/")
        elif path == "course" or path.startswith("course/"):
            target = path
        elif page_dir:
            target = posixpath.normpath(posixpath.join(page_dir, path))
        else:
            target = posixpath.normpath(path)
        if target == ".":
            target = ""
        last = target.rstrip("/").rsplit("/", 1)[-1]
        if target.endswith("/") or (last and "." not in last):
            target = (target.rstrip("/") + "/index.html") if target \
                else "index.html"
        new = posixpath.relpath(target, page_dir) if (page_dir and target) \
            else (target or "index.html")
        return (f"{pre}{quote}{new}{query_sep}{query}"
                f"{hash_sep}{fragment}{quote}")
    html_text = re.sub(r"(<img\b[^>]*\bsrc=)([\"'])(.*?)(\2)",
                       repl, html_text, flags=re.I | re.S)
    return re.sub(r"(<a\b[^>]*\bhref=)([\"'])(.*?)(\2)",
                  repl, html_text, flags=re.I | re.S)

class MarkdownRenderer:
    """Renders one page's markdown, carrying page-wide dedupe state.

    One instance per document: `seen_blocks` and `collapsed` span the lede,
    the intro, and every section so the publisher's repeated reading-level
    prose is collapsed once, not per section.
    """

    def __init__(self, *, keep_links: bool = False,
                 heading_context: str = ""):
        self.keep_links = keep_links
        self.seen_blocks: set[str] = set()
        self.collapsed = 0
        self.heading_context = heading_context

    def dedupe_blocks(self, text: str) -> str:
        blocks = re.split(r"\n\s*\n", text)
        kept = []
        for b in blocks:
            norm = re.sub(r"\s+", " ", b.strip()).lower()
            norm = LEVEL_RE.sub("", norm).strip()
            if len(norm) >= 60 and norm in self.seen_blocks:
                self.collapsed += 1
                continue
            self.seen_blocks.add(norm)
            kept.append(b)
        return "\n\n".join(kept)

    def render(self, text: str, keep_links: bool | None = None) -> str:
        """keep_links: None = the instance default; True/False overrides for
        one block (the sources section calls with True so citations stay
        clickable no matter their hostname)."""
        kl = self.keep_links if keep_links is None else keep_links
        import markdown

        text = LEVEL_LABEL_RE.sub("", text)
        text = LEVEL_LINE_RE.sub("", text)
        text = re.sub(r"^\s*(?:>\s*)?\*\*Executive Brief\.\*\*\s*", "> ", text,
                      flags=re.I | re.M)
        text = SECTION_SYMBOL_RE.sub("", text)
        def _escape_bare(m):
            return m.group(0) if m.group(1).lower() in HTML_TAGS \
                else f"&lt;{m.group(1)}&gt;"

        def _escape_outside_inline_code(chunk: str) -> str:
            spans = re.split(r"(`[^`\n]*`)", chunk)
            for j in range(0, len(spans), 2):
                spans[j] = TYPE_TOKEN_RE.sub(_escape_bare, spans[j])
            return "".join(spans)

        parts = re.split(r"(^[ \t]*```[^\n]*\n.*?^[ \t]*```[ \t]*$)",
                         text, flags=re.M | re.S)
        for i in range(0, len(parts), 2):
            parts[i] = _escape_outside_inline_code(parts[i])
        text = "".join(parts)
        text = CODE_LABEL_RE.sub("\n```\n", text)
        eng = markdown.Markdown(extensions=["tables", "fenced_code"])
        html = eng.convert(self.dedupe_blocks(text))
        html = add_table_captions(html, self.heading_context)
        html = re.sub(r"<th\b(?![^>]*\bscope=)", "<th scope=\"col\"", html)
        def _svg_block(m):
            raw = html_lib.unescape(m.group(1))
            raw = re.sub(r"<script\b.*?</script>", "", raw, flags=re.I | re.S)
            raw = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", raw, flags=re.I)
            raw = re.sub(r"javascript:", "", raw, flags=re.I)
            return f"<figure class='diagram'>{raw}</figure>"
        html = re.sub(r"<pre><code class=\"language-svg\">(.*?)</code></pre>",
                      _svg_block, html, flags=re.S)
        def _img_fig(m):
            img_tag, alt = m.group(1), m.group(2)
            if not alt.lower().startswith("figure"):
                return m.group(0)
            return (f"<figure class='imgfig'>{img_tag}"
                    f"<figcaption>{alt}</figcaption></figure>")
        html = re.sub(r"<p>\s*(<img[^>]*alt=\"([^\"]*)\"[^>]*>)\s*</p>",
                      _img_fig, html, flags=re.I)
        html = re.sub(r"<(audio|video)\b[^>]*>.*?</\1>", "", html,
                      flags=re.I | re.S)
        html = re.sub(r"<(audio|video)\b[^>]*/?>", "", html, flags=re.I)
        html = re.sub(
            r"<iframe[^>]*(?:youtube|youtu\.be|vimeo|soundcloud|spotify|podcast)"
            r"[^>]*>.*?</iframe>", "", html, flags=re.I | re.S)
        html = re.sub(r"<table>", "<div class='tablewrap'><table>", html)
        html = re.sub(r"</table>", "</table></div>", html)
        if not kl:
            def _unwrap_non_authority(m):
                if AUTHORITY_A_RE.match(m.group(0)):
                    return m.group(0)
                return m.group(2)
            html = ANY_A_RE.sub(_unwrap_non_authority, html)
        return html

def render_markdown(text: str, *, keep_links: bool = False):
    """Render one markdown block. Returns (html, collapsed_block_count).
    keep_links=True leaves every external link live; the default keeps only
    authority/direct-source links and unwraps the rest."""
    renderer = MarkdownRenderer(keep_links=keep_links)
    html = renderer.render(text)
    return html, renderer.collapsed

SECTION_KICKERS = {
    "recommendation": "The short answer",
    "before you begin": "Prerequisites",
    "steps": "Procedure",
    "verify it worked": "Verification",
    "troubleshooting": "When it fails",
    "visuals": "Figures",
    "sources": "References",
}

def _tabs_html(active: str, guide_href: str, course_href: str | None) -> str:
    def tab(label: str, href: str, key: str) -> str:
        cls = "tab active" if active == key else "tab"
        return (f"<a class='{cls}' href='{html_lib.escape(href, quote=True)}'>"
                f"{label}</a>")
    tabs = [tab('Guide', guide_href, 'guide')]
    if course_href:
        tabs.append(tab('Course', course_href, 'course'))
    return ("<nav class='tabs' aria-label='Views'>"
            f"{''.join(tabs)}</nav>")

def render_document(md_text: str, *, title: str, hub: str, when: str,
                    subtitle: str = "",
                    max_images: int = 12, max_charts: int = 99,
                    keep_links: bool = False,
                    kicker_label: str = "Research Guide",
                    scrub_stats: dict | None = None,
                    unwrap_all_links: bool = False,
                    data_not_captured: bool = False,
                    drop_heading: bool = True,
                    theme: str = "master",
                    active: str = "guide",
                    guide_href: str = "#",
                    course_href: str | None = None,
                    stats: dict | None = None,
                    page_rel: str = "index.html",
                    description: str = "",
                    bottom_html: str = "",
                    feature_src: str = "",
                    feature_alt: str = "",
                    feature_caption: str = "") -> str:
    """Render a full single-flow page from markdown, wrapped in SHELL.

    The page grammar mirrors the approved guide layout: kicker + H1, the
    executive brief as the lede, in-page TOC chips, numbered sections with
    semantic kickers, teaching charts, per-section image gating, and a visible
    "Research limitations" part when the gates removed content. `stats`, when
    passed, is filled with render counts for the caller's build log.
    """
    renderer = MarkdownRenderer(keep_links=keep_links)

    md_text = normalize_credit_blocks(md_text)

    if drop_heading:
        md_text = re.sub(r"^#\s+.*$", "", md_text, count=1, flags=re.M)

    intro_md, sections = split_sections(md_text)

    image_gate_stats = {"kept": 0, "dropped": 0, "dropped_detail": []}
    gated_sections = []
    for head, body in sections:
        gated_body, kept, dropped = gate_section_images(
            body, head, max_images=max_images)
        image_gate_stats["kept"] += len(kept)
        image_gate_stats["dropped"] += len(dropped)
        image_gate_stats["dropped_detail"].extend(
            [{**d, "section": head[:60]} for d in dropped])
        gated_sections.append((head, gated_body))
    sections = gated_sections

    limitations_items: list = []
    if scrub_stats:
        for qs in scrub_stats.get("quarantined_sections") or []:
            limitations_items.append(
                f"Section removed as off-topic: **{qs.get('section', '?')}** "
                f"(topic overlap {qs.get('overlap', '?')})")
        for d in image_gate_stats["dropped_detail"][:20]:
            limitations_items.append(
                f"Image removed from **{d.get('section', '?')}**: "
                f"`{d.get('src', '')[:80]}` ({d.get('reason', '?')})")
        if len(image_gate_stats["dropped_detail"]) > 20:
            limitations_items.append(
                f"… and {len(image_gate_stats['dropped_detail']) - 20} more "
                "gated images")
    if data_not_captured and limitations_items:
        limitations_items.insert(
            0, "This guide is incomplete BY DESIGN: the relevance gate removed "
               "or refused the pages listed below rather than padding the guide.")

    toc = "".join(
        f"<a href='#{slugify(h)}'><span class='n'>{i:02d}</span>{h}</a>"
        for i, (h, _) in enumerate(sections, 1))
    brief_lines = [ln for ln in intro_md.split("\n") if ln.lstrip().startswith(">")]
    rest_lines = [ln for ln in intro_md.split("\n") if not ln.lstrip().startswith(">")]
    brief_md = "\n".join(brief_lines).strip()
    rest_md = "\n".join(rest_lines).strip()
    parts = [f"<div class='kicker'>{kicker_label}</div>\n<h1>{title}</h1>"]
    if subtitle:
        parts.append(f"<p class='sub'>{subtitle}</p>")
    if feature_src:
        alt = html_lib.escape(feature_alt or title, quote=True)
        src = html_lib.escape(feature_src, quote=True)
        caption = (f"<figcaption><span class='frule'></span>"
                   f"{html_lib.escape(feature_caption)}</figcaption>"
                   if feature_caption else "")
        parts.append(
            f"<figure class='feature'><img src='{src}' alt='{alt}' "
            f"loading='eager'>{caption}</figure>")
    renderer.heading_context = title
    if brief_md:
        parts.append(f"<div class='lede'>{renderer.render(brief_md)}</div>")
    if sections:
        parts.append(f"<nav class='toc' aria-label='In this guide'>{toc}</nav>")
    if rest_md:
        parts.append(renderer.render(rest_md))

    chart_stats = {"charts": 0, "rows": 0}
    for head, body in sections:
        body2, _, n_charts, n_rows = inject_charts(
            body, head, max_charts=max_charts)
        chart_stats["charts"] += n_charts
        chart_stats["rows"] += n_rows
        renderer.heading_context = head
        body_html = renderer.render(
            body2, keep_links=True if _is_sources_heading(head) else None)
        if unwrap_all_links and not _is_sources_heading(head):
            body_html = unwrap_external_links(body_html)
        if _is_sources_heading(head):
            label = re.sub(r"^\s*(?:\d+(?:\.\d+)?\.?\s+)?\s*", "", head).strip()
            body_html = sources_details(body_html, label)
        kicker = SECTION_KICKERS.get(head.strip().lower(), "")
        kicker_html = f"<div class='seck'>{kicker}</div>" if kicker else ""
        parts.append(
            f"<section id='{slugify(head)}'>{kicker_html}"
            f"<h2>{head}</h2>{body_html}</section>")

    if limitations_items:
        lim_html = "<ul>" + "".join(f"<li>{li}</li>" for li in limitations_items) + "</ul>"
        parts.append(
            f"<section id='research-limitations'><div class='seck'>Honest gaps"
            f"</div><h2>Research limitations</h2>"
            f"<p>The relevance gate and the site's image gate removed the "
            f"following; nothing below was used to write this guide, and no "
            f"generic filler was substituted.</p>{lim_html}</section>")

    if bottom_html:
        parts.append(bottom_html)

    body = "\n".join(parts)
    body = rewrite_internal_links(body, page_rel)
    body = add_external_rel(body)
    desc = description or subtitle or title
    _page_dir = posixpath.dirname(page_rel.replace("\\", "/"))
    kit_prefix = "../" * len([p for p in _page_dir.split("/") if p]) \
        if _page_dir else ""
    page = (SHELL
            .replace("%%TITLE%%", title)
            .replace("%%DESC%%", html_lib.escape(desc, quote=True))
            .replace("%%CSS%%", CSS)
            .replace("%%KITCSS%%", kit_prefix + "assets/kit/theme.css")
            .replace("%%KITJS%%", kit_prefix + "assets/kit/site-kit.js")
            .replace("%%KITSRC%%", kit_prefix)
            .replace("%%THEMEOPTS%%", theme_options(theme))
            .replace("%%THEME%%", (theme or "master").strip())
            .replace("%%ZOOMOPTS%%", ZOOM_OPTS)
            .replace("%%HUB%%", hub)
            .replace("%%TABS%%", _tabs_html(active, guide_href, course_href))
            .replace("%%BODY%%", body)
            .replace("%%WHEN%%", when))

    if hub.startswith("#") or not hub:
        page = re.sub(r'<a[^>]+href="%s"[^>]*>.*?</a>' % re.escape(hub),
                      "", page, flags=re.S)

    if stats is not None:
        stats.update({
            "sections": len(sections),
            "collapsed": renderer.collapsed,
            "charts": chart_stats["charts"],
            "rows": chart_stats["rows"],
            "kept": image_gate_stats["kept"],
            "dropped": image_gate_stats["dropped"],
            "dropped_detail": image_gate_stats["dropped_detail"],
            "limitations": len(limitations_items),
        })
    return page
