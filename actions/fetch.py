#!/usr/bin/env python3
import argparse, hashlib, json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse

CHUNK = 1 << 22
UA = "cortexagent-fetch/1.0"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.1f}{u}"
        n /= 1000
    return f"{n:.1f}TB"

def sha256_of(path, buf=CHUNK):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def hf_sha256(url):
    try:
        m = re.match(r"https://huggingface\.co/([\w.\-]+)/([\w.\-]+)/resolve/(\w+)/(.+)", url)
        if not m:
            return None
        org, repo, rev, fn = m.groups()
        api = (f"https://huggingface.co/api/models/{org}/{repo}/tree/{rev}"
               f"?recursive=true")
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        for entry in json.loads(urllib.request.urlopen(req, timeout=30).read()):
            if entry.get("path") == fn and entry.get("lfs"):
                return entry["lfs"].get("oid")
    except Exception:
        pass
    return None

def size_of(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length", 0))
    except Exception:
        return 0

def aria2_fetch(url, tmp, dest_dir):
    if shutil.which("aria2c"):
        cmd = ["aria2c", "-x", "16", "-s", "16", "-k", "4M", "-c", "--quiet=true",
               "--summary-interval=30", "-d", dest_dir, "-o", os.path.basename(tmp),
               url, "--user-agent", UA]
        r = subprocess.run(cmd)
        return r.returncode == 0
    return None

def python_fetch(url, tmp):
    total = size_of(url)
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if total and have >= total:
        return True
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"
        mode = "ab"
    else:
        mode = "wb"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, mode) as f:
        while True:
            b = r.read(CHUNK)
            if not b:
                break
            f.write(b)
            have += len(b)
    if total and os.path.getsize(tmp) != total:
        log(f"size mismatch: got {os.path.getsize(tmp)}, want {total}")
        return False
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dest", default=".")
    ap.add_argument("--sha256", default=None)
    ap.add_argument("--md5", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        print("OK: fetch self-test (argument parsing, no network)")
        return 0
    if not args.url:
        print("FAIL: fetch needs a URL. usage: run.py fetch <url> [--dest DIR]")
        return 1

    os.makedirs(args.dest, exist_ok=True)
    name = args.out or os.path.basename(urllib.parse.urlparse(args.url).path) or "download.bin"
    final = os.path.join(args.dest, name)
    tmp = final + ".part"

    expected = args.sha256 or hf_sha256(args.url)

    if os.path.exists(final):
        digest = sha256_of(final)
        if expected and digest == expected:
            log(f"OK: {name} already present and verified ({human(os.path.getsize(final))})")
            return 0
        if not expected:
            log(f"WARN: {name} exists but no checksum known; leaving it")
            return 0
        log(f"{name} exists but hash mismatch — redownloading")

    t0 = time.time()
    if aria2_fetch(args.url, tmp, args.dest):
        log(f"downloaded {name} in {time.time()-t0:.0f}s via aria2c")
    else:
        log("aria2c unavailable or failed — python resume stream")
        if not python_fetch(args.url, tmp):
            log(f"FAIL: {name} — download incomplete")
            return 1

    digest = sha256_of(tmp)
    if expected:
        if digest != expected:
            log(f"FAIL: {name} sha256 mismatch — corrupt. Deleting and aborting.")
            os.remove(tmp)
            return 1
        log(f"sha256 verified: {digest[:16]}…")
    if args.md5:
        m = hashlib.md5(open(tmp, "rb").read()).hexdigest()
        if m != args.md5:
            log(f"FAIL: md5 mismatch ({m} != {args.md5})")
            os.remove(tmp)
            return 1

    with open(final + ".sha256", "w") as f:
        f.write(digest + f"  {name}\n")
    os.replace(tmp, final)
    log(f"OK: {name} → {final} ({human(os.path.getsize(final))})")
    return 0

if __name__ == "__main__":
    import re
    sys.exit(main())
