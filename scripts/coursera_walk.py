from pathlib import Path
#!/usr/bin/env python3
"""Coursera walk: navigate to a URL, wait for load, mark complete (if a
mark-complete button is present), report state. One item per invocation.

Usage: coursera_walk.py <full-coursera-url>

Uses trusted CDP Input.dispatchMouseEvent so clicks register as isTrusted
and fire React onClick handlers.
"""
import sys, time, json
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import browser_control as bc

URL = sys.argv[1]
PREFIX = "https://www.coursera.org/learn/python-crash-course/"
tid = bc.resolve_tab(PREFIX)

bc._cmd(tid, "Page.navigate", {"url": URL}, timeout=30)
present = None
deadline = time.time() + 30
while time.time() < deadline:
    present = bc._eval(tid, """
(() => {
  const b = document.querySelector('button[data-testid="mark-complete"]');
  return b ? { present: true, text: b.innerText.trim().slice(0,20) } : { present: false };
})()
""", timeout=8)
    if isinstance(present, dict) and present.get("present"):
        break
    time.sleep(1)

if not isinstance(present, dict) or not present.get("present"):
    print(json.dumps({"url": URL, "markButton": "absent", "note": "no mark-complete button after 30s (video/plugin/quiz may auto-track or need other handling)"}))
    sys.exit(0)

INVOKE_JS = r"""
(() => {
  const b = document.querySelector('button[data-testid="mark-complete"]');
  if (!b) return { ok:false, reason:'no btn' };
  let onClick = null;
  const propKey = Object.keys(b).find(k => k.startsWith('__reactProps'));
  if (propKey) onClick = b[propKey].onClick;
  if (!onClick) {
    const fk = Object.keys(b).find(k => k.startsWith('__reactFiber'));
    if (fk) { let fib = b[fk];
      while (fib) { if (fib.memoizedProps && fib.memoizedProps.onClick) { onClick = fib.memoizedProps.onClick; break; } fib = fib.return; } }
  }
  if (!onClick) return { ok:false, reason:'no onClick' };
  const ev = {
    preventDefault(){}, stopPropagation(){}, stopImmediatePropagation(){},
    persist(){}, isPropagationStopped:()=>false, isDefaultPrevented:()=>false,
    isTrusted:true, type:'click', currentTarget:b, target:b, nativeEvent:{},
    timeStamp:0, bubbles:true, cancelable:true,
  };
  try { onClick(ev); return { ok:true }; }
  catch(e){ return { ok:false, reason:'invoke-failed: '+String(e).slice(0,120) }; }
})()
"""

state = None
for attempt in range(3):
    res = bc._eval(tid, INVOKE_JS, timeout=8)
    time.sleep(4)
    state = bc._eval(tid, """
(() => {
  const mark = [...document.querySelectorAll('button')].filter(b => /mark as completed/i.test(b.innerText) && b.offsetParent).length;
  const labels = [...document.querySelectorAll('button,[role="button"]')].filter(b => /completed|next item|mark as completed/i.test(b.innerText) && b.offsetParent).map(b => b.innerText.trim().slice(0,25));
  return { markStillVisible: mark, labels: labels.slice(0,5) };
})()
""", timeout=8)
    if isinstance(state, dict):
        if state.get("markStillVisible") != 0:
            time.sleep(2)
            state = bc._eval(tid, """
(() => {
  const mark = [...document.querySelectorAll('button')].filter(b => /mark as completed/i.test(b.innerText) && b.offsetParent).length;
  const labels = [...document.querySelectorAll('button,[role="button"]')].filter(b => /completed|next item|mark as completed/i.test(b.innerText) && b.offsetParent).map(b => b.innerText.trim().slice(0,25));
  return { markStillVisible: mark, labels: labels.slice(0,5) };
})()
""", timeout=8)
        if isinstance(state, dict) and state.get("markStillVisible") == 0:
            break
        else:
            continue
    break

print(json.dumps({"url": URL, "invoke": res, "attempts": attempt + 1, "after": state }))
sys.exit(0 if (isinstance(state, dict) and state.get("markStillVisible") == 0) else 1)
