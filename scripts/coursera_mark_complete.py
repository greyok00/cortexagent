from pathlib import Path
#!/usr/bin/env python3
"""Coursera mark-complete via trusted CDP Input.dispatchMouseEvent.

Raw CDP Input.dispatchMouseEvent produces isTrusted=true events that DO
fire React onClick.

Usage: coursera_mark_complete.py [url-prefix]
"""
import sys, time, json
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import browser_control as bc

URL_PREFIX = sys.argv[1] if len(sys.argv) > 1 else "coursera.org/learn/python-crash-course/supplement/RijhS"

tid = bc.resolve_tab(URL_PREFIX)
print(f"target: {tid[:12]}  prefix: {URL_PREFIX[:40]}", flush=True)

def click_button():
    r = bc._eval(tid, """
      (() => {
        const b = document.querySelector('button[data-testid="mark-complete"]');
        if (!b) return { ok:false, reason:'no button' };
        b.scrollIntoView({ block:'center', behavior:'instant' });
        const r = b.getBoundingClientRect();
        return { ok:true, x: r.x + r.width/2, y: r.y + r.height/2 };
      })()
    """, timeout=8)
    if not isinstance(r, dict) or not r.get("ok"):
        return r
    x, y = round(r["x"]), round(r["y"])
    bc._cmd(tid, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, timeout=6)
    time.sleep(0.12)
    bc._cmd(tid, "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}, timeout=6)
    time.sleep(0.08)
    bc._cmd(tid, "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}, timeout=6)
    return {"ok": True, "x": x, "y": y}

res = click_button()
print("click:", json.dumps(res), flush=True)
time.sleep(4)
state = bc._eval(tid, """
  (() => {
    const mark = [...document.querySelectorAll('button')].filter(b => /mark as completed/i.test(b.innerText) && b.offsetParent).length;
    const labels = [...document.querySelectorAll('button,[role="button"]')].filter(b => /completed|next item|mark as completed/i.test(b.innerText) && b.offsetParent).map(b => b.innerText.trim().slice(0,25));
    return { markStillVisible: mark, labels: labels.slice(0,5) };
  })()
""", timeout=8)
print("after:", json.dumps(state), flush=True)
sys.exit(0 if (isinstance(state, dict) and state.get("markStillVisible") == 0) else 1)
