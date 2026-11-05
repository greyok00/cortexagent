from pathlib import Path
#!/usr/bin/env python3
"""Dump the Coursera course navigation links (readings/videos/quizzes) in DOM order."""
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import browser_control as bc

tid = bc.resolve_tab('coursera.org/learn/python-crash-course')
js = """
(() => {
  const out = [];
  for (const a of document.querySelectorAll('a')) {
    const href = a.getAttribute('href') || '';
    if (/learn\\/python-crash-course\\/(supplement|lecture|quiz|assignment|peer|discussions|notebook|lab)/.test(href)) {
      const t = (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 70);
      if (t && !out.find(o => o.h === href)) out.push({ h: href, t });
    }
  }
  return out;
})()
"""
res = bc._eval(tid, js, timeout=10)
if not res:
    print("no links found / eval failed", flush=True)
    sys.exit(1)
for o in res:
    print(o["h"][:95], "|", o["t"], flush=True)
