#!/usr/bin/env python3
"""kit_build.py — assemble the offline site kit from the ui-framework, in one file.

The kit is for static documents (a study, a report, a case pack), not for apps. It adds
one thing the framework does not have: a bridge that renames the framework's tokens into
the names a document stylesheet already uses. With that bridge in place, a page written
against --paper / --ink / --copper re-skins itself when `data-theme` changes, and no page
stylesheet has to be rewritten to gain theming.

Outputs, all in this directory:
    theme.css    @font-face (self-hosted, relative urls) + tokens + themes + the bridge
    site-kit.js  the theme switcher, a picker that wires itself up, and figure numbering

Both are meant to be inlined into a page's own <style>/<script>, so a site stays one
self-contained file plus a fonts/ folder. Re-run this after any ui-framework change.

Run:  python3 kit_build.py
"""
import os
import sys

# pathlib.Path.home() rather than a hard-coded path: this gets copied between machines
# and projects, and a baked-in home directory is a leak waiting to happen.
import pathlib
FW = str(pathlib.Path.home() / 'ui-framework')
HERE = os.path.dirname(os.path.abspath(__file__))

BRIDGE = """
/* ── document bridge ─────────────────────────────────────────────────────────
   A document stylesheet should not have to know the framework's names. These aliases
   point the names a study already uses at the framework's tokens, so `data-theme` on
   <html> re-skins the whole document with no other change.

   --copper-deep is mixed toward --el-ink rather than being a fixed darker shade: on a
   light theme that darkens it for contrast on paper, and on a dark theme it lightens it,
   which is the same requirement solved once instead of twice per theme.            */
:root{
  --paper:       var(--el-bg);
  --card:        var(--el-panel);
  --ink:         var(--el-ink);
  --ink-soft:    var(--el-ink-soft);
  --line:        var(--el-line);
  --copper:      var(--el-accent);
  --copper-deep: color-mix(in oklab, var(--el-accent) 85%, var(--el-ink));
  --bond:        var(--el-fail);
  --go:          var(--el-ok);

  /* Prose stays a serif on purpose. The framework's themes vary their display and mono
     faces and their whole palette, radii and density — which is where a theme's
     personality actually lives — but a legal document's body face is a legibility
     decision, not a theme decision, so it is pinned here and named once. */
  --serif: 'Source Serif 4', Georgia, 'Times New Roman', serif;
  --cond:  var(--el-font-display), 'Arial Narrow', sans-serif;
  --mono:  var(--el-font-mono), ui-monospace, Menlo, monospace;
}

/* A figure is a figure in every theme: the frame follows the theme, the type voice does
   not, because a chart label has to stay legible against whatever palette is active.  */
.fig{margin:1.6rem 0 1.9rem}
.fig .lead{font:400 .98rem/1.65 var(--serif);color:var(--ink-soft);margin:0 0 .7rem;max-width:56ch}
.fig .frame{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.9rem .8rem .7rem}
.fig svg{display:block;width:100%;height:auto}
.fig figcaption{font:400 .86rem/1.6 var(--el-font-mono),ui-monospace,monospace;
  color:var(--ink-soft);margin:.7rem 0 0;max-width:76ch;text-align:left;font-style:normal}
.fig figcaption b{color:var(--ink)}
.fig .fignum,.fignum{font:600 .68rem/1 var(--el-font-mono),ui-monospace,monospace;
  letter-spacing:.14em;text-transform:uppercase;color:var(--copper-deep);display:block;margin-bottom:.35rem}

/* The theme picker that site-kit.js injects into a <nav>. It sits in the nav because that
   is the one element every page of every site in the kit already has.               */
.themepick{margin-left:auto;display:flex;align-items:center;padding:4px 0}
/* No visible "Theme" word: a 10-item nav plus a labelled picker wrapped to two lines at
   1280px, which pushed the page down for no gain. The word is kept for a screen reader
   and the select is width-capped so the longest theme name cannot widen it again.      */
.vhide{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* currentColor, not a fixed grey: the kit goes into sites whose nav bar may be dark,
   light, or themed, and a hard-coded control colour is unreadable on at least one of
   them. Inheriting means the picker always matches the nav it sits in.               */
.themepick select{font:500 .76rem/1 var(--el-font-mono),ui-monospace,monospace;
  background:transparent;color:inherit;border:1px solid color-mix(in oklab,currentColor 42%,transparent);
  border-radius:4px;padding:5px 6px;cursor:pointer;max-width:118px}
.themepick select option{background:var(--el-panel);color:var(--el-ink)}
.themepick.float{position:fixed;top:8px;right:10px;z-index:99;background:var(--el-panel);
  border:1px solid var(--el-line);border-radius:6px;padding:4px 6px}
.themepick select:focus{outline:none;border-color:var(--copper)}
"""


def read(name):
    p = os.path.join(FW, name)
    if not os.path.isfile(p):
        sys.exit(f'missing {p} — the kit is built from the ui-framework checkout')
    return open(p, encoding='utf-8').read()


def main():
    fonts = open(os.path.join(HERE, 'fonts.css'), encoding='utf-8').read()
    parts = [
        '/* Generated by kit_build.py — do not hand-edit. */\n',
        read('fonts.css') if os.path.isfile(os.path.join(FW, 'fonts.css')) else fonts,
        '\n', read('tokens.css'), '\n', read('themes.css'), '\n', BRIDGE,
    ]
    out = os.path.join(HERE, 'theme.css')
    open(out, 'w', encoding='utf-8').write(''.join(parts))

    switcher = read('theme-switcher.js')
    # The framework defaults to 'neutral', which is a dark app palette. A study is read on
    # paper stock, so the kit's default is the cream/copper one; the user's own pick in
    # localStorage still wins, and every other theme is still in the picker.
    switcher = switcher.replace("const DEFAULT = 'neutral';",
                                "const DEFAULT = 'polaroid';  // kit default (doc paper)")
    js = [switcher, '\n', '''
/* ── kit add-ons, appended to the framework's switcher ────────────────────────
   1. A picker that injects itself. The kit is inlined into hundreds of generated pages,
      so nothing may depend on hand-editing each one: if the page has the nav the kit
      expects, the picker appears in it, and every page of every site gains the switcher
      at once.
   2. Figure numbering. The reference page numbered its figures ("Figure 2") because a
      caption is much easier to refer to when it has a name. Numbers are assigned in
      document order at load, so a page that gains a figure renumbers itself.          */
(function () {
  function picker() {
    // Fall through the shapes a site actually has. The study and the kit's own pages use
    // <nav class="main">, but a site that never went through the kit often has a bare
    // <nav> or only a <header>; without the fallbacks the picker would silently not appear
    // on exactly the sites the kit is being added to. Last resort is a small fixed chip,
    // which is worse-looking but never invisible.
    var nav = document.querySelector('nav.main .wrap') || document.querySelector('nav.main')
           || document.querySelector('header nav') || document.querySelector('nav')
           || document.querySelector('header') || document.body;
    if (!nav || nav.querySelector('.themepick')) return;
    var float = (nav === document.body);
    var wrap = document.createElement('span');
    wrap.className = 'themepick' + (float ? ' float' : '');
    var lab = document.createElement('label');
    lab.className = 'vhide';
    lab.textContent = 'Theme';
    var sel = document.createElement('select');
    sel.id = 'theme-picker';
    sel.setAttribute('aria-label', 'Theme');
    (window.elTheme ? elTheme.list() : ['neutral']).forEach(function (t) {
      var o = document.createElement('option');
      o.value = t; o.textContent = t;
      sel.appendChild(o);
    });
    sel.value = (document.documentElement.dataset.theme || 'neutral');
    sel.addEventListener('change', function () { elTheme.apply(sel.value); });
    wrap.appendChild(lab); wrap.appendChild(sel);
    nav.appendChild(wrap);
  }
  function numberFigures() {
    var i = 0;
    document.querySelectorAll('figure').forEach(function (f) {
      if (f.querySelector(':scope > .fignum')) return;
      i++;
      var s = document.createElement('span');
      s.className = 'fignum';
      s.textContent = 'Figure ' + i;
      f.insertBefore(s, f.firstChild);
    });
  }
  function run() { picker(); numberFigures(); }
  document.addEventListener('DOMContentLoaded', run);
  if (document.readyState !== 'loading') run();
})();
''']
    out = os.path.join(HERE, 'site-kit.js')
    open(out, 'w', encoding='utf-8').write(''.join(js))
    for f in ('theme.css', 'site-kit.js'):
        print(f'{f}: {os.path.getsize(os.path.join(HERE, f)):,} bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
