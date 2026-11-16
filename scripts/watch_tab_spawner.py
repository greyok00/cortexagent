#!/usr/bin/env python3
import json, sys, time, urllib.request
import websocket

CDP = "http://127.0.0.1:9223"
LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tab_spawner.log"

def ext_name(opener_id, names):
    if not opener_id:
        return ""
    if opener_id in names:
        return names[opener_id]
    return opener_id[:12]

def _connect():
    ver = json.load(urllib.request.urlopen(CDP + "/json/version", timeout=3))
    ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=3, suppress_origin=True)
    ws.settimeout(4.0)
    ws.send(json.dumps({"id": 1, "method": "Target.setDiscoverTargets", "params": {"discover": True}}))
    return ws

def main():
    existing, names = set(), {}
    armed_at = time.time() + 2.0
    out = open(LOG, "a", buffering=1)
    out.write(f"=== watcher armed at {time.strftime('%H:%M:%S')}; logging new targets ===\n")
    ws = _connect()
    while True:
        try:
            raw = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        except Exception:
            time.sleep(2); ws = _connect(); continue
        if raw.get("method") == "Target.targetCreated":
            ti = raw["params"]["targetInfo"]
            tid = ti["targetId"]
            names[tid] = ti.get("title") or ti.get("url", "")
            if tid in existing:
                continue
            existing.add(tid)
            if time.time() < armed_at:
                continue
            opener = ti.get("openerId", "") or ""
            line = (f"{time.strftime('%H:%M:%S')} NEW type={ti.get('type'):13s} "
                    f"url={ti.get('url','')[:55]!r} opener={ext_name(opener, names)[:40]}\n")
            out.write(line); out.flush()

if __name__ == "__main__":
    main()
