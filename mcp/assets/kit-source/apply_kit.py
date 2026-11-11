#!/usr/bin/env python3
"""apply_kit.py — put the theme kit into a site that was already built.

The rights-study site gets the kit from its own build script. Every other site here is a
folder of finished HTML, so this is the equivalent step for them: it inlines the kit's
theme, sets the starting theme, adds the picker script, copies the self-hosted fonts, and
maps *that site's own* variable names onto the framework's tokens.

The last part is the one that needs judgement. The framework exposes --el-bg, --el-ink,
--el-accent. A site almost never uses those names; report-navigator says --bg, --text and
--accent, and RESEARCH-PSYCH says --bg, --ink and --gold. So the kit's shared bridge
handles documents written against the study's names, and this file carries one small,
auditable alias table per site for the names it actually uses. Writing those aliases is
what makes the theme picker do something instead of just appearing.

What it does NOT do: remap colours a site hard-codes outside its :root block (a stray
#fff, an rgba() shadow). Those keep their literal value in every theme. The aliases cover
the palette a site actually varies; the strays are reported per site so the gap is visible
rather than assumed away.

Idempotent: a page already carrying the marker is skipped, so re-running is safe.

Usage:
    python3 apply_kit.py --list              # what would be touched
    python3 apply_kit.py --site report-navigator
    python3 apply_kit.py --all
    python3 apply_kit.py --site X --revert   # take the kit back out
"""
import argparse
import os
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()

MARK = '<!-- site-kit: applied -->'
OPEN = '<!-- site-kit: begin -->'
CLOSE = '<!-- site-kit: end -->'

# One entry per site. `pages` is a list of globs relative to the site root; `default` is
# the theme the site opens in — the study's cream paper for documents, the framework's own
# dark for apps that were already dark, because a theme picker should not change a working
# site's look before it is touched. `alias` maps the site's own variable names onto
# framework tokens; a name absent from the map keeps its literal value in every theme.
# Case-Playbook's layout keeps colours the token bridge cannot reach: the hero is a
# gradient, and the top bar, footer, table header, quote box and a dozen text rules are
# literals written for a light page. The nearest-token matcher further down gets these
# wrong — it cannot repaint a gradient at all, so the hero stayed the old light-theme navy
# band on a dark page, and it mapped the rest by brightness. Each rule below says what the
# colour is FOR, in theme tokens, so the page follows the picker instead of fighting it.
CASE_PLAYBOOK_LAYOUT_EXTRA = '''\
/* Layout surfaces, re-pointed at theme tokens so every theme repaints them. */
.topbar{background:var(--el-panel-2);color:var(--el-ink);border-bottom:1px solid var(--el-line)}
.brand{color:var(--el-ink)}
.brand span{color:var(--accent-text)}
.fig .fignum,.fignum{color:var(--accent-text)}
/* These read --brand / --brand-2 as TEXT in styles.css. --brand stays raw because it
   also fills buttons and the numbered circles; text gets the contrast-safe accent. */
.kicker,.tl .tl-date,.case dt,dl.defs dt,ul.check li::before{color:var(--accent-text)}
/* The kit's own caption rule reaches for the raw ink-soft through the legacy bridge
   (--ink-soft), which lands at 4.33:1 on polaroid's cream panel. Ask for --muted instead. */
.fig figcaption{color:var(--muted)}
nav.menu a{color:var(--muted)}
nav.menu a:hover{background:var(--el-panel-3);color:var(--el-ink)}
nav.menu a.active{background:var(--el-accent-soft);color:var(--el-ink)}
.hero{background:linear-gradient(135deg,var(--el-panel-2) 0%,var(--el-panel) 65%,var(--el-bg) 100%);
  color:var(--el-ink);border-bottom:1px solid var(--el-line)}
.hero h1{color:var(--el-ink)}
.hero p.sub{color:var(--muted)}
.hero .kicker{background:var(--el-accent-soft);border-color:var(--el-accent);color:var(--accent-text)}
p.lede{color:var(--muted)}
/* Bare links in body copy have no rule of their own, so they were falling through to the
   browser default blue. The more specific nav/footer/button rules still win over this. */
a{color:var(--accent-text)}
.num{color:var(--el-on-accent)}
table.t th{background:var(--el-panel-2);color:var(--el-ink);border-bottom:1px solid var(--el-line)}
table.t tr:nth-child(even) td{background:var(--el-panel-2)}
.tl .tl-item::before{background:var(--el-panel)}
.tl p{color:var(--muted)}
.qbox{background:var(--el-panel-2);border-color:var(--el-line);color:var(--el-ink)}
.src{color:var(--muted)}
.case .cite{color:var(--muted)}
dl.defs dd{color:var(--el-ink)}
ol.steps p{color:var(--el-ink)}
ol.steps li::before{color:var(--el-on-accent)}
ol.steps li::after{background:var(--el-line)}
footer{background:var(--el-panel-2);color:var(--muted);border-top:1px solid var(--el-line)}
footer a{color:var(--accent-text)}
footer .fine{color:var(--muted)}
.pill{background:var(--el-panel-2);border-color:var(--el-line);color:var(--muted)}
a.btn{color:var(--el-on-accent)}
a.btn.ghost{background:var(--el-panel);color:var(--accent-text);border-color:var(--el-accent)}
.crumb{color:var(--muted)}
/* Callout borders: a wash of the status colour, so the four stay four colours. */
.co-do{border-color:color-mix(in oklab, var(--el-fail) 40%, var(--el-line))}
.co-why{border-color:color-mix(in oklab, var(--el-info) 40%, var(--el-line))}
.co-good{border-color:color-mix(in oklab, var(--el-ok) 40%, var(--el-line))}
.co-warn{border-color:color-mix(in oklab, var(--el-warn) 40%, var(--el-line))}
/* Secondary text sitting on a tinted wash needs to be a step brighter than on a plain
   panel: the wash lifts the background toward the text colour and eats the margin. */
.co-do .src,.co-why .src,.co-good .src,.co-warn .src,
.co-do figcaption,.co-why figcaption,.co-good figcaption,.co-warn figcaption,
.co-do .lead,.co-why .lead,.co-good .lead,.co-warn .lead
{color:color-mix(in oklab, var(--muted) 72%, var(--el-ink))}
/* A status colour used as text ON a wash of that same status colour loses its margin:
   red-on-pale-red and blue-on-pale-blue sit around 4.2:1 in the lighter themes. Mixing a
   quarter of the way to the ink keeps the hue recognisable and clears the floor. */
.co-do .co-title,.b-bad{color:var(--bad)}
.co-why .co-title,.b-info{color:var(--info)}
.co-good .co-title,.b-good{color:var(--good)}
.co-warn .co-title,.b-warn{color:var(--warn)}
@media print{.hero{background:var(--el-panel-2)}}
'''

# Paper rules for the legal binder pages: on screen they follow the theme (umami), but a
# court copy is paper, and paper stays light ink-on-white in every theme.
LEGAL_SYSTEM_EXTRA = '''\
/* Two text rules were written as near-black literals for a light page; the nearest-token
   stray matcher mapped them onto dark panel tokens, which vanish on umami. They are
   secondary prose, so the correct token is ink-soft in every theme. */
.lead{color:var(--el-ink-soft)}
.verify{color:var(--el-ink-soft)}
@media print {
  [data-theme="umami"] {
    --el-bg: #ffffff; --el-panel: #ffffff; --el-panel-2: #f2f2f2; --el-panel-3: #e5e5e5;
    --el-line: #d8d8d8; --el-line-2: #b8b8b8; --el-line-strong: #000000;
    --el-ink: #000000; --el-ink-soft: #333333; --el-mute: #555555;
    --el-accent: #7a1f1f; --el-accent-soft: rgba(122,31,31,0.10);
    --el-overlay: rgba(0,0,0,.4);
  }
  body { background: #fff; color: #000; }
}'''

SITES = {
    'report-navigator': dict(
        root=HOME / 'report-navigator', pages=['index.html'], default='neutral',
        alias={'bg': 'bg', 'card': 'panel', 'card2': 'panel-2', 'text': 'ink',
               'muted': 'ink-soft', 'accent': 'accent', 'border': 'line',
               'green': 'ok', 'amber': 'warn', 'red': 'fail'}),
    # `*/index.html`: the four case folders. `*.html` alone reached only the root pages,
    # so the case pages were being themed by hand — which is how they ended up with two
    # local contrast patches on top of a broken alias instead of a working theme.
    'Case-Playbook': dict(
        root=HOME / 'Desktop/Case-Playbook', pages=['*.html', '*/index.html'],
        default='neutral',
        alias={'bg': 'bg', 'card': 'panel', 'ink': 'ink',
               'brand': 'accent', 'brand-2': 'accent-hover', 'accent': 'accent',
               'line': 'line', 'radius': 'r-md',
               # Secondary text and accent text are pulled a quarter of the way toward the
               # ink. The kit's own ink-soft sits at ~4.3:1 on the light themes (polaroid,
               # cockpit-paper) and accent-as-text drops to 2.8:1 there. Mixing toward ink
               # raises contrast on light panels AND dark ones, so one rule serves all
               # fifteen themes; the hue survives, so "muted" still reads as muted.
               'muted': 'color-mix(in oklab, var(--el-ink-soft) 78%, var(--el-ink))',
               'ink-soft': 'color-mix(in oklab, var(--el-ink-soft) 78%, var(--el-ink))',
               'accent-text': 'color-mix(in oklab, var(--el-accent) 58%, var(--el-ink))',
               # A status colour is used as TEXT in this site — in badges, in callout titles,
               # in timeline dates, and in three legend labels written as inline
               # style="color:var(--warn)". No stylesheet rule can outrank an inline style, so
               # the contrast mix has to live in the token itself, not in the rules that read
               # it. Halfway to the ink keeps the hue recognisable at every theme's contrast.
               'good': 'color-mix(in oklab, var(--el-ok) 50%, var(--el-ink))',
               'warn': 'color-mix(in oklab, var(--el-warn) 50%, var(--el-ink))',
               'bad': 'color-mix(in oklab, var(--el-fail) 50%, var(--el-ink))',
               'info': 'color-mix(in oklab, var(--el-info) 50%, var(--el-ink))',
               # Derived washes: a status colour mixed into the panel. Kept light, because a
               # heavier wash lifts the panel toward the text and eats the contrast the token
               # above just bought. The tint comes from the raw --el-* colour, so "against you"
               # still reads as red and "warning" still reads as amber in all fifteen themes.
               'good-bg': 'color-mix(in oklab, var(--el-ok) 12%, var(--el-panel))',
               'warn-bg': 'color-mix(in oklab, var(--el-warn) 12%, var(--el-panel))',
               'bad-bg': 'color-mix(in oklab, var(--el-fail) 11%, var(--el-panel))',
               'info-bg': 'color-mix(in oklab, var(--el-info) 11%, var(--el-panel))'},
        extra=CASE_PLAYBOOK_LAYOUT_EXTRA),
    'tutor-assistant': dict(
        root=HOME / 'tutor-assistant', pages=['index.html', 'dist/index.html'], default='neutral',
        alias={'bg': 'bg', 'bg-secondary': 'panel', 'bg-tertiary': 'panel-2',
               'text': 'ink', 'text-muted': 'ink-soft', 'text-h': 'ink',
               'heading': 'ink', 'accent': 'accent', 'accent-bg': 'accent-soft',
               'accent-border': 'accent', 'border': 'line', 'success': 'ok',
               'code-bg': 'panel-2', 'shadow': 'shadow-2'}),
    'survey-bot': dict(
        root=HOME / 'survey-bot', pages=['public/*.html'], default='neutral',
        alias={'bg': 'bg', 'bg-secondary': 'panel', 'bg-tertiary': 'panel-2',
               'text': 'ink', 'text-muted': 'ink-soft', 'primary': 'accent',
               'primary-dark': 'accent-hover', 'border': 'line', 'success': 'ok',
               'danger': 'fail', 'warning': 'warn', 'info': 'info',
               'radius': 'r-md'}),
    'tactica': dict(
        root=HOME / 'Documents/tactica', pages=['index.html', 'dist/index.html'], default='neutral',
        alias={'bg': 'bg', 'fg': 'ink'}),
    'RESEARCH-PSYCH': dict(
        root=HOME / 'Desktop/Research/RESEARCH-PSYCH/site', pages=['*.html', 'dossiers/*.html'],
        default='polaroid',
        alias={'bg': 'bg', 'ink': 'ink', 'gold': 'accent'}),
    # NOT here on purpose: ~/downloadedwebsites is an HTTrack archive of third-party pages
    # (skipthegames.com, escortalligator.com) kept as a preserved copy. Injecting our theme
    # and a fonts/ folder into someone else's archived page edits the artifact, which is
    # the opposite of what an archive is for. Add it back only on an explicit request.
    'codex-twitch-cohost': dict(
        root=HOME / 'codex-twitch-cohost', pages=['index.html', 'public/*.html'],
        default='neutral', alias={'bg': 'bg', 'text': 'ink', 'accent': 'accent'}),
    'tactics-rpg-threejs': dict(
        root=HOME / 'Documents/tactics-rpg-threejs', pages=['index.html', 'dist/index.html'],
        default='neutral', alias={'bg': 'bg', 'fg': 'ink'}),
    # Legal Preparation System (M02 wreck binder · M03 GEICO binder · pro se package).
    # User directive 2026-09-28: umami, never the old standalone light theme. The binder
    # pages keep light paper for print via the extra block; the screen follows umami.
    'legal-system': dict(
        root=HOME / 'Desktop/Legal',
        pages=['index.html', 'PRODUCTION-MAP-2026-09-28.html',
               '02-WRECK-CASE/BINDER/*.html', 'GEICO-BAD-FAITH-LAWSUIT/BINDER/*.html',
               'PRO-SE-PACKAGE/*.html',
               '02-WRECK-CASE/M02-SOURCE-AUDIT-AND-CORRECTIONS-REGISTER-2026-09-28.html'],
        default='umami',
        alias={'bg': 'bg', 'soft': 'panel', 'ink': 'ink', 'dim': 'mute',
               'line': 'line', 'accent': 'accent'},
        extra=LEGAL_SYSTEM_EXTRA),
    # Consolidated platform audit (six lanes, ~220 platforms verified 2–3 Oct 2026).
    # site.css is written entirely against --el-* tokens — no literal colours anywhere —
    # so there is no per-site bridge to maintain: the alias map is empty on purpose and
    # the theme picker re-skins all seven pages directly.
    'verified-platforms': dict(
        root=HOME / 'Desktop/verified-platforms', pages=['*.html'],
        default='neutral', alias={}),
}



def alias_block(alias, theme, extra=''):
    """The per-site half of the bridge: this site's names → framework tokens.

    Emitted last in <head>, after the site's own stylesheet, because `:root{--bg:#12141a}`
    and `:root{--bg:var(--el-bg)}` have the same specificity and the later one wins. Put it
    first and the site's literal palette would quietly beat the theme.
    """
    if not alias and not extra:
        return ''
    # A bare name is a framework token (`ink` becomes var(--el-ink)). Anything else is
    # taken as a complete CSS value, which is how a site asks for a derived fill that the
    # framework has no token for — the four status washes are a mix of a status colour and
    # the panel, so they stay four different colours instead of collapsing into one.
    def value(v):
        return f'var(--el-{v})' if re.fullmatch(r'[a-z0-9-]+', v) else v
    rows = '\n'.join(f'  --{k}: {value(v)};' for k, v in sorted(alias.items()))
    head = (f'/* This site\'s own variable names, pointed at the theme\'s tokens. */\n'
            f'[data-theme]{{\n{rows}\n}}\n') if alias else ''
    return (f'<style id="site-kit-alias" data-site-kit="alias">\n' + head + extra +
            '</style>\n')


# ── stray colours ────────────────────────────────────────────────────────────
# A site's :root is not where all its colours live. report-navigator keeps its palette
# there, then hard-codes `.banner.rule{background:#16202e}` further down. Alias the tokens
# and the page turns cream while those two banners stay night-blue with dark text — the
# worst outcome, because it looks broken rather than unthemed. So: find every literal
# colour in a site's CSS, match it to the nearest token in the theme the site opens in, and
# emit an override with the same selector. A literal the default theme has no close match
# for is left alone and reported, never guessed at. The 60/441 ceiling on "close" is a
# deliberate compromise: tighter and a site's own decorative text colour (report-navigator
# writes its disclaimer in a muted gold) stays literal and turns unreadable against the
# paper theme; looser and the site's *default* look drifts from what its author chose.
# Every match is printed with its distance, so the drift is visible, not hidden.

RGB_RE = re.compile(r'#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b|rgba?\(([^)]+)\)')


def parse_rgb(v):
    """→ (r,g,b) for a literal colour, or None if it is not a plain opaque colour."""
    v = v.strip()
    m = RGB_RE.fullmatch(v)
    if not m:
        return None
    if m.group(1):
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    parts = [p.strip() for p in m.group(2).replace('/', ',').split(',')]
    if len(parts) > 3 and float(parts[3]) < 1:      # translucent: not a palette colour
        return None
    try:
        return tuple(int(round(float(p.rstrip('%')))) if '%' not in p else
                     int(round(float(p.rstrip('%')) * 2.55)) for p in parts[:3])
    except ValueError:
        return None


def theme_colors(theme):
    """The --el-* colour tokens as they resolve in `theme`, nearest-name first."""
    def block(text, sel):
        m = re.search(re.escape(sel) + r'\s*\{([^}]*)\}', text, re.S)
        return m.group(1) if m else ''
    base = block((HERE / 'theme.css').read_text(encoding='utf-8').split('@layer el-themes')[0],
                 ':root,\n[data-theme="neutral"]')
    own = block((HERE / 'theme.css').read_text(encoding='utf-8'), f'[data-theme="{theme}"]')
    vals = {}
    for decl in (base + own).split(';'):
        if ':--' not in decl.replace(' ', '') and '--' not in decl:
            continue
        name, _, value = decl.partition(':')
        name = name.strip()
        if name.startswith('--el-'):
            vals[name] = value.strip()
    return {k: parse_rgb(v) for k, v in vals.items() if parse_rgb(v)}


def media_spans(css_text):
    """Character ranges covered by an @media block, by matching its braces."""
    spans = []
    for m in re.finditer(r'@media[^{]*\{', css_text):
        depth, i = 1, m.end()
        while i < len(css_text) and depth:
            if css_text[i] == '{':
                depth += 1
            elif css_text[i] == '}':
                depth -= 1
            i += 1
        spans.append((m.start(), i))
    return spans


def special_token(prop, rgb):
    """White and black are not palette colours, they are roles, and nearest-colour matching
    gets the role backwards: `#fff` in a site is almost always text sitting on the accent,
    and matching it to the ink token would paint that text dark on a dark accent. This
    returns the token the role calls for, or None to fall through to colour matching."""
    r, g, b = rgb
    p = prop.split('-')[0]
    if r > 246 and g > 246 and b > 246:                     # white
        return {'color': '--el-on-accent', 'fill': '--el-on-accent',
                'stroke': '--el-on-accent', 'border': '--el-line',
                'background': '--el-panel'}.get(p)
    if r < 12 and g < 12 and b < 12:                        # black
        return {'color': '--el-ink', 'fill': '--el-ink', 'stroke': '--el-ink',
                'border': '--el-line', 'background': '--el-bg'}.get(p)
    return None


def stray_overrides(css_text, theme, limit=60, skip_props=()):
    """Override rules for every literal colour in `css_text` that a token can stand in for.

    Only non-nested blocks are rewritten (`selector { … }`). A colour inside an @media
    query is skipped: hoisting it out would apply it above the breakpoint, which is a
    different change than theming.
    """
    palette = theme_colors(theme)
    if not palette:
        return '', []
    inside = media_spans(css_text)
    rules, report = [], []
    for m in re.finditer(r'([^{}@]+)\{([^{}]*)\}', css_text):
        if any(s <= m.start() < e for s, e in inside):
            continue
        selector, body = m.group(1).strip(), m.group(2)
        decls = []
        for decl in body.split(';'):
            prop, _, value = decl.partition(':')
            rgb = parse_rgb(value)
            if not prop.strip() or not rgb:
                continue
            if prop.strip() in skip_props:
                continue        # the alias table already decided this one, on purpose
            prop = prop.strip()
            best, dist = None, 1e9
            role = special_token(prop, rgb)
            if role:
                best, dist = role, 0          # a role match is exact; no search needed
            for token, trgb in (palette.items() if best is None else ()):
                d = sum((a - b) ** 2 for a, b in zip(rgb, trgb)) ** .5
                if d < dist:
                    best, dist = token, d
            if best and dist <= limit:
                decls.append(f'{prop}: var({best})')
                report.append((selector, prop, value.strip(), best, round(dist)))
        if decls:
            rules.append(f'{selector}{{' + ';'.join(decls) + '}')
    return ('\n'.join(rules)), report


def strip_kit(html):
    """Remove everything this script added, marker block and aliases both."""
    html = re.sub(re.escape(OPEN) + r'.*?' + re.escape(CLOSE) + r'\s*', '', html, flags=re.S)
    # `[^>]*` after the id: the injected tags carry a second attribute (data-site-kit=…),
    # and a regex expecting `id="…">` matched neither the stylesheet nor the script — a
    # revert that silently left the kit in the page, which then got applied a second time.
    html = re.sub(r'<style[^>]*id="site-kit-[^"]*"[^>]*>.*?</style>\s*', '', html, flags=re.S)
    html = re.sub(r'<script[^>]*id="site-kit-js"[^>]*>.*?</script>\s*', '', html, flags=re.S)
    html = re.sub(r'\s*' + re.escape(MARK), '', html)
    html = re.sub(r'<html lang="([^"]*)" data-theme="[^"]*"', r'<html lang="\1"', html)
    return html


def apply_to_file(path, theme_css, kit_js, theme, alias, revert=False, extra_css=''):
    html = path.read_text(encoding='utf-8')
    if revert:
        new = strip_kit(html)
        if new != html:
            path.write_text(new, encoding='utf-8')
            return 'reverted'
        return 'nothing to revert'
    if MARK in html:
        return 'already applied'
    if '</head>' not in html or '</body>' not in html:
        return 'SKIPPED — not a complete HTML document'
    if re.search(r'<html[^>]*data-theme=', html):
        return 'SKIPPED — page already has its own data-theme'

    head_open = '<head>'
    if head_open not in html:
        head_open = re.search(r'<head[^>]*>', html).group(0)
    head_css = (f'<style id="site-kit-theme" data-site-kit="theme">\n{theme_css}\n</style>\n')
    js = f'<script id="site-kit-js" data-site-kit="js">{kit_js}</script>\n'
    # The kit's own default is the study's paper theme; a site can open on a different one.
    if theme != 'polaroid':
        js = js.replace("const DEFAULT = 'polaroid';",
                        f"const DEFAULT = '{theme}';", 1)
    new = html.replace(head_open, head_open + '\n' + head_css, 1)
    new = new.replace('</head>', alias_block(alias, theme, extra_css) + '</head>', 1)
    new = new.replace('</body>', MARK + '\n' + js + '</body>', 1)
    m = re.search(r'<html\b[^>]*>', new)
    tag = m.group(0)
    new = new.replace(tag, tag[:-1] + f' data-theme="{theme}">', 1)
    path.write_text(new, encoding='utf-8')
    return 'applied'


def site_css(site, pages):
    """Every stylesheet the site's own pages depend on, plus their inline <style> blocks."""
    texts = {}
    for p in pages:
        html = p.read_text(encoding='utf-8')
        for m in re.finditer(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', html):
            href = re.search(r'href=["\']([^"\']+)["\']', m.group(0))
            if not href or href.group(1).startswith(('http', '//', 'data:')):
                continue
            f = (p.parent / href.group(1)).resolve()
            if f.is_file() and f not in texts:
                texts[f] = f.read_text(encoding='utf-8', errors='replace')
        for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
            if 'data-site-kit' in m.group(0):
                continue        # the kit's own stylesheet, already applied
            texts.setdefault(f'{p}#inline', m.group(1))
    return texts


def pages_for(site):
    root = site['root']
    found = []
    for pat in site['pages']:
        if '*' in pat:
            found += sorted(root.glob(pat))
        else:
            p = root / pat
            if p.is_file():
                found.append(p)
    # A recursive glob can pick up vendor trees (three.js docs, node_modules, build
    # output). Nothing outside the site's own pages is ever written.
    skip = ('node_modules', '/.git/', '/target/', '/docs/threejs/')
    out = []
    for p in found:
        if any(k in str(p) for k in skip):
            continue
        if p not in out:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--revert', action='store_true')
    a = ap.parse_args()

    names = list(SITES) if a.all else ([a.site] if a.site else [])
    if a.list or not names:
        for n, s in SITES.items():
            print(f'{n:24s} {len(pages_for(s)):4d} page(s)  default={s["default"]}  '
                  f'{str(s["root"]).replace(str(HOME), "~")}')
        return 0
    for n in names:
        if n not in SITES:
            sys.exit(f'unknown site {n!r} — see --list')
        s = SITES[n]
        theme_css = (HERE / 'theme.css').read_text(encoding='utf-8')
        kit_js = (HERE / 'site-kit.js').read_text(encoding='utf-8')
        pages = pages_for(s)
        strays_css, stray_report = '', []
        for src, text in site_css(s, pages).items():
            css, rep = stray_overrides(text, s['default'], limit=s.get('stray_limit', 60),
                                       skip_props={f'--{k}' for k in s['alias']} |
                                                  {f'--el-{v}' for v in s['alias'].values()})
            if css:
                strays_css += ('\n/* Colours this site hard-coded outside its palette, '
                               'matched to the nearest theme token. */\n' + css + '\n')
            stray_report += [(str(src).replace(str(HOME), '~'),) + r for r in rep]
        tally = {}
        for p in pages:
            r = apply_to_file(p, theme_css, kit_js, s['default'], s['alias'],
                              a.revert, strays_css + s.get('extra', ''))
            tally[r] = tally.get(r, 0) + 1
        if not a.revert:
            shutil.copytree(HERE / 'fonts', s['root'] / 'fonts', dirs_exist_ok=True)
        print(f'{n}: ' + ', '.join(f'{v} {k}' for k, v in sorted(tally.items())))
        if stray_report:
            worst = max(r[5] for r in stray_report)
            print(f'  strays mapped: {len(stray_report)} hard-coded colour(s), '
                  f'worst match distance {worst}/60')
            for i, (src, sel, prop, val, tok, dist) in enumerate(stray_report):
                if i == 12:
                    print(f'    … and {len(stray_report) - 12} more')
                    break
                print(f'    {val:>9} -> {tok:<16} {prop:<11} {sel[:44]}')
            unmapped = [x for x in re.finditer(r'(#[0-9A-Fa-f]{6})', '')]
        else:
            print('  strays mapped: none')
    return 0


if __name__ == '__main__':
    sys.exit(main())
