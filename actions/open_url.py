#!/usr/bin/env python3
import json, subprocess, sys, time, urllib.request

VALID_SCHEMES = ("http://", "https://")

def open_url(url):
    if not url.startswith(VALID_SCHEMES):
        url = "https://" + url
    import json as _json, urllib.request as _ur, websocket as _ws
    try:
        host = url.split("://")[1].split("/")[0].replace("www.", "")
        tabs = _json.loads(_ur.urlopen("http://127.0.0.1:9224/json", timeout=4).read())
        pages = [t for t in tabs if t.get("type") == "page"]
        RESERVED = ("mail.google.com", "calendar.google.com", "voice.google.com")
        target = next((t for t in pages if host in t.get("url", "")), None)
        if not target:
            spare = [t for t in pages if not any(r in t.get("url", "") for r in RESERVED)
                     and "newtab" not in t.get("url", "")]
            if not spare:
                return False, f"no spare tab for {host} — saved tabs are protected"
            target = spare[-1]
        c = _ws.create_connection(target["webSocketDebuggerUrl"], timeout=8)
        c.send(_json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        c.recv(); c.close()
        return True, f"{url} navigated inside existing tab (no new tabs/windows)"
    except Exception as _e:
        return False, f"no default browser on :9224 ({_e})"
def urllib_request_json():
    req = urllib.request.Request("http://127.0.0.1:9224/json")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: open_url.py <url> [more urls]")
        sys.exit(1)
    for u in sys.argv[1:]:
        ok, msg = open_url(u)
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
