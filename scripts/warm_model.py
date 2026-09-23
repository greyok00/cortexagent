import json
import sys
import time
import urllib.request

for _ in range(170):
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:11599/v1/chat/completions",
                data=json.dumps({"model": "cortexagent",
                                 "messages": [{"role": "user", "content": "hi"}],
                                 "max_tokens": 1}).encode(),
                headers={"Content-Type": "application/json"}),
            timeout=5)
        r.read()
        sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit(1)
