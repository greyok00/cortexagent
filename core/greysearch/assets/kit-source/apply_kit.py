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
CASE_PLAYBOOK_LAYOUT_EXTRA = "/* Layout surfaces, re-pointed at theme tokens so every theme repaints them. */\n.topbar{background:var(--el-panel-2);color:var(--el-ink);border-bottom:1px solid var(--el-line)}\n.brand{color:var(--el-ink)}\n.brand span{color:var(--accent-text)}\n.fig .fignum,.fignum{color:var(--accent-text)}\n/* These read --brand / --brand-2 as TEXT in styles.css. --brand stays raw because it\n   also fills buttons and the numbered circles; text gets the contrast-safe accent. */\n.kicker,.tl .tl-date,.case dt,dl.defs dt,ul.check li::before{color:var(--accent-text)}\n/* The kit's own caption rule reaches for the raw ink-soft through the legacy bridge\n   (--ink-soft), which lands at 4.33:1 on polaroid's cream panel. Ask for --muted instead. */\n.fig figcaption{color:var(--muted)}\nnav.menu a{color:var(--muted)}\nnav.menu a:hover{background:var(--el-panel-3);color:var(--el-ink)}\nnav.menu a.active{background:var(--el-accent-soft);color:var(--el-ink)}\n.hero{background:linear-gradient(135deg,var(--el-panel-2) 0%,var(--el-panel) 65%,var(--el-bg) 100%);\n  color:var(--el-ink);border-bottom:1px solid var(--el-line)}\n.hero h1{color:var(--el-ink)}\n.hero p.sub{color:var(--muted)}\n.hero .kicker{background:var(--el-accent-soft);border-color:var(--el-accent);color:var(--accent-text)}\np.lede{color:var(--muted)}\n/* Bare links in body copy have no rule of their own, so they were falling through to the\n   browser default blue. The more specific nav/footer/button rules still win over this. */\na{color:var(--accent-text)}\n.num{color:var(--el-on-accent)}\ntable.t th{background:var(--el-panel-2);color:var(--el-ink);border-bottom:1px solid var(--el-line)}\ntable.t tr:nth-child(even) td{background:var(--el-panel-2)}\n.tl .tl-item::before{background:var(--el-panel)}\n.tl p{color:var(--muted)}\n.qbox{background:var(--el-panel-2);border-color:var(--el-line);color:var(--el-ink)}\n.src{color:var(--muted)}\n.case .cite{color:var(--muted)}\ndl.defs dd{color:var(--el-ink)}\nol.steps p{color:var(--el-ink)}\nol.steps li::before{color:var(--el-on-accent)}\nol.steps li::after{background:var(--el-line)}\nfooter{background:var(--el-panel-2);color:var(--muted);border-top:1px solid var(--el-line)}\nfooter a{color:var(--accent-text)}\nfooter .fine{color:var(--muted)}\n.pill{background:var(--el-panel-2);border-color:var(--el-line);color:var(--muted)}\na.btn{color:var(--el-on-accent)}\na.btn.ghost{background:var(--el-panel);color:var(--accent-text);border-color:var(--el-accent)}\n.crumb{color:var(--muted)}\n/* Callout borders: a wash of the status colour, so the four stay four colours. */\n.co-do{border-color:color-mix(in oklab, var(--el-fail) 40%, var(--el-line))}\n.co-why{border-color:color-mix(in oklab, var(--el-info) 40%, var(--el-line))}\n.co-good{border-color:color-mix(in oklab, var(--el-ok) 40%, var(--el-line))}\n.co-warn{border-color:color-mix(in oklab, var(--el-warn) 40%, var(--el-line))}\n/* Secondary text sitting on a tinted wash needs to be a step brighter than on a plain\n   panel: the wash lifts the background toward the text colour and eats the margin. */\n.co-do .src,.co-why .src,.co-good .src,.co-warn .src,\n.co-do figcaption,.co-why figcaption,.co-good figcaption,.co-warn figcaption,\n.co-do .lead,.co-why .lead,.co-good .lead,.co-warn .lead\n{color:color-mix(in oklab, var(--muted) 72%, var(--el-ink))}\n/* A status colour used as text ON a wash of that same status colour loses its margin:\n   red-on-pale-red and blue-on-pale-blue sit around 4.2:1 in the lighter themes. Mixing a\n   quarter of the way to the ink keeps the hue recognisable and clears the floor. */\n.co-do .co-title,.b-bad{color:var(--bad)}\n.co-why .co-title,.b-info{color:var(--info)}\n.co-good .co-title,.b-good{color:var(--good)}\n.co-warn .co-title,.b-warn{color:var(--warn)}\n@media print{.hero{background:var(--el-panel-2)}}\n"
LEGAL_SYSTEM_EXTRA = '/* Two text rules were written as near-black literals for a light page; the nearest-token\n   stray matcher mapped them onto dark panel tokens, which vanish on umami. They are\n   secondary prose, so the correct token is ink-soft in every theme. */\n.lead{color:var(--el-ink-soft)}\n.verify{color:var(--el-ink-soft)}\n@media print {\n  [data-theme="umami"] {\n    --el-bg: #ffffff; --el-panel: #ffffff; --el-panel-2: #f2f2f2; --el-panel-3: #e5e5e5;\n    --el-line: #d8d8d8; --el-line-2: #b8b8b8; --el-line-strong: #000000;\n    --el-ink: #000000; --el-ink-soft: #333333; --el-mute: #555555;\n    --el-accent: #7a1f1f; --el-accent-soft: rgba(122,31,31,0.10);\n    --el-overlay: rgba(0,0,0,.4);\n  }\n  body { background: #fff; color: #000; }\n}'
SITES = {'report-navigator': dict(root=HOME / 'report-navigator', pages=['index.html'], default='neutral', alias={'bg': 'bg', 'card': 'panel', 'card2': 'panel-2', 'text': 'ink', 'muted': 'ink-soft', 'accent': 'accent', 'border': 'line', 'green': 'ok', 'amber': 'warn', 'red': 'fail'}), 'Case-Playbook': dict(root=HOME / 'Desktop/Case-Playbook', pages=['*.html', '*/index.html'], default='neutral', alias={'bg': 'bg', 'card': 'panel', 'ink': 'ink', 'brand': 'accent', 'brand-2': 'accent-hover', 'accent': 'accent', 'line': 'line', 'radius': 'r-md', 'muted': 'color-mix(in oklab, var(--el-ink-soft) 78%, var(--el-ink))', 'ink-soft': 'color-mix(in oklab, var(--el-ink-soft) 78%, var(--el-ink))', 'accent-text': 'color-mix(in oklab, var(--el-accent) 58%, var(--el-ink))', 'good': 'color-mix(in oklab, var(--el-ok) 50%, var(--el-ink))', 'warn': 'color-mix(in oklab, var(--el-warn) 50%, var(--el-ink))', 'bad': 'color-mix(in oklab, var(--el-fail) 50%, var(--el-ink))', 'info': 'color-mix(in oklab, var(--el-info) 50%, var(--el-ink))', 'good-bg': 'color-mix(in oklab, var(--el-ok) 12%, var(--el-panel))', 'warn-bg': 'color-mix(in oklab, var(--el-warn) 12%, var(--el-panel))', 'bad-bg': 'color-mix(in oklab, var(--el-fail) 11%, var(--el-panel))', 'info-bg': 'color-mix(in oklab, var(--el-info) 11%, var(--el-panel))'}, extra=CASE_PLAYBOOK_LAYOUT_EXTRA), 'tutor-assistant': dict(root=HOME / 'tutor-assistant', pages=['index.html', 'dist/index.html'], default='neutral', alias={'bg': 'bg', 'bg-secondary': 'panel', 'bg-tertiary': 'panel-2', 'text': 'ink', 'text-muted': 'ink-soft', 'text-h': 'ink', 'heading': 'ink', 'accent': 'accent', 'accent-bg': 'accent-soft', 'accent-border': 'accent', 'border': 'line', 'success': 'ok', 'code-bg': 'panel-2', 'shadow': 'shadow-2'}), 'survey-bot': dict(root=HOME / 'survey-bot', pages=['public/*.html'], default='neutral', alias={'bg': 'bg', 'bg-secondary': 'panel', 'bg-tertiary': 'panel-2', 'text': 'ink', 'text-muted': 'ink-soft', 'primary': 'accent', 'primary-dark': 'accent-hover', 'border': 'line', 'success': 'ok', 'danger': 'fail', 'warning': 'warn', 'info': 'info', 'radius': 'r-md'}), 'tactica': dict(root=HOME / 'Documents/tactica', pages=['index.html', 'dist/index.html'], default='neutral', alias={'bg': 'bg', 'fg': 'ink'}), 'RESEARCH-PSYCH': dict(root=HOME / 'Desktop/Research/RESEARCH-PSYCH/site', pages=['*.html', 'dossiers/*.html'], default='polaroid', alias={'bg': 'bg', 'ink': 'ink', 'gold': 'accent'}), 'codex-twitch-cohost': dict(root=HOME / 'codex-twitch-cohost', pages=['index.html', 'public/*.html'], default='neutral', alias={'bg': 'bg', 'text': 'ink', 'accent': 'accent'}), 'tactics-rpg-threejs': dict(root=HOME / 'Documents/tactics-rpg-threejs', pages=['index.html', 'dist/index.html'], default='neutral', alias={'bg': 'bg', 'fg': 'ink'}), 'legal-system': dict(root=HOME / 'Desktop/Legal', pages=['index.html', 'PRODUCTION-MAP-2026-09-28.html', '02-WRECK-CASE/BINDER/*.html', 'GEICO-BAD-FAITH-LAWSUIT/BINDER/*.html', 'PRO-SE-PACKAGE/*.html', '02-WRECK-CASE/M02-SOURCE-AUDIT-AND-CORRECTIONS-REGISTER-2026-09-28.html'], default='umami', alias={'bg': 'bg', 'soft': 'panel', 'ink': 'ink', 'dim': 'mute', 'line': 'line', 'accent': 'accent'}, extra=LEGAL_SYSTEM_EXTRA), 'verified-platforms': dict(root=HOME / 'Desktop/verified-platforms', pages=['*.html'], default='neutral', alias={})}
def alias_block(alias, theme, extra=''):
    if not alias and (not extra):
        return ''
    def value(v):
        return f'var(--el-{v})' if re.fullmatch('[a-z0-9-]+', v) else v
    rows = '\n'.join((f'  --{k}: {value(v)};' for k, v in sorted(alias.items())))
    head = f"/* This site's own variable names, pointed at the theme's tokens. */\n[data-theme]{{\n{rows}\n}}\n" if alias else ''
    return f'<style id="site-kit-alias" data-site-kit="alias">\n' + head + extra + '</style>\n'
RGB_RE = re.compile('#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\\b|rgba?\\(([^)]+)\\)')
def parse_rgb(v):
    v = v.strip()
    m = RGB_RE.fullmatch(v)
    if not m:
        return None
    if m.group(1):
        h = m.group(1)
        if len(h) == 3:
            h = ''.join((c * 2 for c in h))
        return tuple((int(h[i:i + 2], 16) for i in (0, 2, 4)))
    parts = [p.strip() for p in m.group(2).replace('/', ',').split(',')]
    if len(parts) > 3 and float(parts[3]) < 1:
        return None
    try:
        return tuple((int(round(float(p.rstrip('%')))) if '%' not in p else int(round(float(p.rstrip('%')) * 2.55)) for p in parts[:3]))
    except ValueError:
        return None
def theme_colors(theme):
    def block(text, sel):
        m = re.search(re.escape(sel) + '\\s*\\{([^}]*)\\}', text, re.S)
        return m.group(1) if m else ''
    base = block((HERE / 'theme.css').read_text(encoding='utf-8').split('@layer el-themes')[0], ':root,\n[data-theme="neutral"]')
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
    spans = []
    for m in re.finditer('@media[^{]*\\{', css_text):
        depth, i = (1, m.end())
        while i < len(css_text) and depth:
            if css_text[i] == '{':
                depth += 1
            elif css_text[i] == '}':
                depth -= 1
            i += 1
        spans.append((m.start(), i))
    return spans
def special_token(prop, rgb):
    r, g, b = rgb
    p = prop.split('-')[0]
    if r > 246 and g > 246 and (b > 246):
        return {'color': '--el-on-accent', 'fill': '--el-on-accent', 'stroke': '--el-on-accent', 'border': '--el-line', 'background': '--el-panel'}.get(p)
    if r < 12 and g < 12 and (b < 12):
        return {'color': '--el-ink', 'fill': '--el-ink', 'stroke': '--el-ink', 'border': '--el-line', 'background': '--el-bg'}.get(p)
    return None
def stray_overrides(css_text, theme, limit=60, skip_props=()):
    palette = theme_colors(theme)
    if not palette:
        return ('', [])
    inside = media_spans(css_text)
    rules, report = ([], [])
    for m in re.finditer('([^{}@]+)\\{([^{}]*)\\}', css_text):
        if any((s <= m.start() < e for s, e in inside)):
            continue
        selector, body = (m.group(1).strip(), m.group(2))
        decls = []
        for decl in body.split(';'):
            prop, _, value = decl.partition(':')
            rgb = parse_rgb(value)
            if not prop.strip() or not rgb:
                continue
            if prop.strip() in skip_props:
                continue
            prop = prop.strip()
            best, dist = (None, 1000000000.0)
            role = special_token(prop, rgb)
            if role:
                best, dist = (role, 0)
            for token, trgb in palette.items() if best is None else ():
                d = sum(((a - b) ** 2 for a, b in zip(rgb, trgb))) ** 0.5
                if d < dist:
                    best, dist = (token, d)
            if best and dist <= limit:
                decls.append(f'{prop}: var({best})')
                report.append((selector, prop, value.strip(), best, round(dist)))
        if decls:
            rules.append(f'{selector}{{' + ';'.join(decls) + '}')
    return ('\n'.join(rules), report)
def strip_kit(html):
    html = re.sub(re.escape(OPEN) + '.*?' + re.escape(CLOSE) + '\\s*', '', html, flags=re.S)
    html = re.sub('<style[^>]*id="site-kit-[^"]*"[^>]*>.*?</style>\\s*', '', html, flags=re.S)
    html = re.sub('<script[^>]*id="site-kit-js"[^>]*>.*?</script>\\s*', '', html, flags=re.S)
    html = re.sub('\\s*' + re.escape(MARK), '', html)
    html = re.sub('<html lang="([^"]*)" data-theme="[^"]*"', '<html lang="\\1"', html)
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
    if re.search('<html[^>]*data-theme=', html):
        return 'SKIPPED — page already has its own data-theme'
    head_open = '<head>'
    if head_open not in html:
        head_open = re.search('<head[^>]*>', html).group(0)
    head_css = f'<style id="site-kit-theme" data-site-kit="theme">\n{theme_css}\n</style>\n'
    js = f'<script id="site-kit-js" data-site-kit="js">{kit_js}</script>\n'
    if theme != 'polaroid':
        js = js.replace("const DEFAULT = 'polaroid';", f"const DEFAULT = '{theme}';", 1)
    new = html.replace(head_open, head_open + '\n' + head_css, 1)
    new = new.replace('</head>', alias_block(alias, theme, extra_css) + '</head>', 1)
    new = new.replace('</body>', MARK + '\n' + js + '</body>', 1)
    m = re.search('<html\\b[^>]*>', new)
    tag = m.group(0)
    new = new.replace(tag, tag[:-1] + f' data-theme="{theme}">', 1)
    path.write_text(new, encoding='utf-8')
    return 'applied'
def site_css(site, pages):
    texts = {}
    for p in pages:
        html = p.read_text(encoding='utf-8')
        for m in re.finditer('<link[^>]+rel=["\\\']stylesheet["\\\'][^>]*>', html):
            href = re.search('href=["\\\']([^"\\\']+)["\\\']', m.group(0))
            if not href or href.group(1).startswith(('http', '//', 'data:')):
                continue
            f = (p.parent / href.group(1)).resolve()
            if f.is_file() and f not in texts:
                texts[f] = f.read_text(encoding='utf-8', errors='replace')
        for m in re.finditer('<style[^>]*>(.*?)</style>', html, re.S):
            if 'data-site-kit' in m.group(0):
                continue
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
    skip = ('node_modules', '/.git/', '/target/', '/docs/threejs/')
    out = []
    for p in found:
        if any((k in str(p) for k in skip)):
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
    names = list(SITES) if a.all else [a.site] if a.site else []
    if a.list or not names:
        for n, s in SITES.items():
            print(f"{n:24s} {len(pages_for(s)):4d} page(s)  default={s['default']}  {str(s['root']).replace(str(HOME), '~')}")
        return 0
    for n in names:
        if n not in SITES:
            sys.exit(f'unknown site {n!r} — see --list')
        s = SITES[n]
        theme_css = (HERE / 'theme.css').read_text(encoding='utf-8')
        kit_js = (HERE / 'site-kit.js').read_text(encoding='utf-8')
        pages = pages_for(s)
        strays_css, stray_report = ('', [])
        for src, text in site_css(s, pages).items():
            css, rep = stray_overrides(text, s['default'], limit=s.get('stray_limit', 60), skip_props={f'--{k}' for k in s['alias']} | {f'--el-{v}' for v in s['alias'].values()})
            if css:
                strays_css += '\n/* Colours this site hard-coded outside its palette, matched to the nearest theme token. */\n' + css + '\n'
            stray_report += [(str(src).replace(str(HOME), '~'),) + r for r in rep]
        tally = {}
        for p in pages:
            r = apply_to_file(p, theme_css, kit_js, s['default'], s['alias'], a.revert, strays_css + s.get('extra', ''))
            tally[r] = tally.get(r, 0) + 1
        if not a.revert:
            shutil.copytree(HERE / 'fonts', s['root'] / 'fonts', dirs_exist_ok=True)
        print(f'{n}: ' + ', '.join((f'{v} {k}' for k, v in sorted(tally.items()))))
        if stray_report:
            worst = max((r[5] for r in stray_report))
            print(f'  strays mapped: {len(stray_report)} hard-coded colour(s), worst match distance {worst}/60')
            for i, (src, sel, prop, val, tok, dist) in enumerate(stray_report):
                if i == 12:
                    print(f'    … and {len(stray_report) - 12} more')
                    break
                print(f'    {val:>9} -> {tok:<16} {prop:<11} {sel[:44]}')
            unmapped = [x for x in re.finditer('(#[0-9A-Fa-f]{6})', '')]
        else:
            print('  strays mapped: none')
    return 0
if __name__ == '__main__':
    sys.exit(main())
