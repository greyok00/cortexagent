from __future__ import annotations
import html
import json
import pathlib
import re
from typing import Any, Dict, List, Optional
CSS_PATH = pathlib.Path('~/research-guide/assets/css/site.css')

def _esc(s: str) -> str:
    return html.escape(s or '')

def _link(href: str, text: str) -> str:
    return f'<a href="{_esc(href)}">{_esc(text or href)}</a>'

def build_page(title: str, answer: str, lead: str, sections: List[Dict[str, Any]], sources: Optional[List[Dict[str, str]]]=None, extra_head: str='') -> str:
    css = ''
    if CSS_PATH.exists():
        css = CSS_PATH.read_text(encoding='utf-8')
    body_parts: List[str] = []
    body_parts.append(f'<h1>{_esc(title)}</h1>')
    body_parts.append(f'<p class="ux-answer">{_esc(answer)}</p>')
    body_parts.append(f'<div class="ux-lead"><p>{_esc(lead)}</p></div>')
    for sec in sections:
        if sec.get('heading'):
            body_parts.append(f"<h2>{_esc(sec['heading'])}</h2>")
        for para in sec.get('prose', []):
            if '<a ' in para:
                body_parts.append(f'<p>{para}</p>')
            else:
                body_parts.append(f'<p>{_esc(para)}</p>')
        fig = sec.get('figure')
        if fig:
            fig_html = fig.get('html', '')
            body_parts.append('<figure class="ux-figure">')
            body_parts.append(f"""<p class="ux-figure-lead">{_esc(fig.get('lead', ''))}</p>""")
            body_parts.append(fig_html)
            body_parts.append(f"""<figcaption class="ux-figure-cap">{_esc(fig.get('cap', ''))}</figcaption>""")
            body_parts.append('</figure>')
        if sec.get('steps'):
            body_parts.append('<ol class="ux-steps">')
            for step in sec['steps']:
                if '<a ' in step or '<b>' in step:
                    body_parts.append(f'<li>{step}</li>')
                else:
                    body_parts.append(f'<li>{_esc(step)}</li>')
            body_parts.append('</ol>')
        if sec.get('callout'):
            body_parts.append(f"""<div class="ux-note"><b>{_esc(sec['callout'].get('title', 'Note'))}</b> {_esc(sec['callout'].get('body', ''))}</div>""")
    if sources:
        body_parts.append('<div class="ux-verify"><b>Sources & verification</b><br>')
        for s in sources:
            verified = s.get('verified', True)
            label = _esc(s.get('label') or s.get('url', ''))
            url = _esc(s.get('url', ''))
            flag = '' if verified else ' <span class="ux-unverified">UNVERIFIED — do not rely</span>'
            if url:
                body_parts.append(f'<a href="{url}">{label}</a>{flag}<br>')
            else:
                body_parts.append(f'{label}{flag}<br>')
        body_parts.append('</div>')
    inner = '\n'.join(body_parts)
    return f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{_esc(title)}</title>\n<style>{css}</style>\n{extra_head}\n</head>\n<body style="background:var(--ux-paper,#FDFCF9);color:var(--ux-ink,#1B1A17);margin:0;padding:2rem 1.2rem">\n<div class="ux-prose">\n{inner}\n</div>\n</body>\n</html>\n'

def check_page(html_text: str) -> List[str]:
    fails = []
    if 'class="ux-answer"' not in html_text:
        fails.append('missing one-line answer (ux-answer)')
    if 'class="ux-lead"' not in html_text:
        fails.append("missing why-you'd-care (ux-lead)")
    if 'class="ux-figure"' in html_text:
        if 'class="ux-figure-lead"' not in html_text:
            fails.append('figure without lead sentence (ux-figure-lead)')
        if 'ux-figure-cap' not in html_text:
            fails.append('figure without follow-up caption (ux-figure-cap)')
    if '**' in html_text and '<strong>' not in html_text and ('<b>' not in html_text):
        fails.append('literal ** markers in output (not rendered)')
    if 'class="ux-verify"' not in html_text:
        fails.append('missing verification/sources block (ux-verify)')
    return fails

def build_front_door(title: str, answer: str, lead: str, doors: List[Dict[str, str]], sources: Optional[List[Dict[str, str]]]=None) -> str:
    css = CSS_PATH.read_text(encoding='utf-8') if CSS_PATH.exists() else ''
    doors_html = '<div class="ux-doors">\n'
    for d in doors:
        doors_html += f'''<a class="ux-door" href="{_esc(d['href'])}"><b>{_esc(d['title'])}</b><span>{_esc(d['desc'])}</span></a>\n'''
    doors_html += '</div>'
    verify = ''
    if sources:
        verify = '<div class="ux-verify"><b>Sources</b><br>'
        for s in sources:
            flag = '' if s.get('verified', True) else ' <span class="ux-unverified">UNVERIFIED</span>'
            verify += f'''<a href="{_esc(s.get('url', ''))}">{_esc(s.get('label') or s.get('url', ''))}</a>{flag}<br>'''
        verify += '</div>'
    return f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{_esc(title)}</title>\n<style>{css}</style>\n</head>\n<body style="background:var(--ux-paper,#FDFCF9);color:var(--ux-ink,#1B1A17);margin:0;padding:2rem 1.2rem">\n<div class="ux-prose">\n<h1>{_esc(title)}</h1>\n<p class="ux-answer">{_esc(answer)}</p>\n<div class="ux-lead"><p>{_esc(lead)}</p></div>\n{doors_html}\n{verify}\n</div>\n</body>\n</html>\n'