#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.request
import urllib.error

CHUNK = 1 << 20
MIN_CHUNKED_SIZE = 64 << 20
UA = "cortexagent-downloader/1.0"

def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def _open(url: str, start: int = 0, end: int | None = None,
          timeout: int = 60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        **({"Range": f"bytes={start}-" if end is None
           else f"bytes={start}-{end}"} if start or end is not None else {})})
    return urllib.request.urlopen(req, timeout=timeout)

def _remote_size(url: str) -> tuple[int, bool]:
    try:
        with _open(url) as r:
            size = int(r.headers.get("Content-Length") or 0)
            return size, r.headers.get("Accept-Ranges") == "bytes"
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA},
                                     method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            size = int(r.headers.get("Content-Length") or 0)
            return size, r.headers.get("Accept-Ranges") == "bytes"
    except Exception:
        return 0, False

def _sidecar_hash(url: str) -> str | None:
    cands = [url + ".sha256"]
    if "/" in url:
        base = url.rsplit("/", 1)
        cands.append(base[0] + "/" + base[1].split("?")[0] + ".sha256")
    for c in cands:
        try:
            with _open(c) as r:
                text = r.read(4096).decode("utf-8", "replace")
            m = re.search(r"\b([a-fA-F0-9]{64})\b", text)
            if m:
                return m.group(1).lower()
        except Exception:
            continue
    return None

class _RangeIgnored(Exception):
    pass

def _chunk_worker(url: str, part: pathlib.Path, start: int, end: int,
                  attempts: int = 8) -> str:
    for attempt in range(1, attempts + 1):
        try:
            have = part.stat().st_size if part.exists() else 0
            want = end - start + 1
            if have >= want:
                return "ok"
            with _open(url, start=start + have, end=end) as r:
                if r.status != 206:
                    raise _RangeIgnored()
                with part.open("ab") as out:
                    while True:
                        b = r.read(CHUNK)
                        if not b:
                            break
                        out.write(b)
            if part.stat().st_size >= want:
                return "ok"
            raise IOError(f"short read {part.stat().st_size}/{want}")
        except _RangeIgnored:
            raise
        except Exception as e:
            print(f"  chunk {part.name} attempt {attempt} FAILED: "
                  f"{str(e)[:80]}", flush=True)
            time.sleep(min(60, 3 * attempt))
    return "failed"

def _download_chunked(url: str, dest: pathlib.Path, size: int,
                      workers: int) -> bool:
    bounds = []
    step = size // workers
    for i in range(workers):
        start = i * step
        end = (size - 1) if i == workers - 1 else (start + step - 1)
        bounds.append((start, end))
    parts = [dest.with_suffix(dest.suffix + f".part{i}")
             for i in range(len(bounds))]
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_chunk_worker, url, p, s, e): (p, s, e)
                for p, (s, e) in zip(parts, bounds)}
        ok = all(f.result() == "ok" for f in cf.as_completed(futs))
    if not ok:
        return False
    with dest.open("wb") as out:
        for p in parts:
            with p.open("rb") as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    out.write(b)
            p.unlink()
    return True

def _download_plain(url: str, dest: pathlib.Path,
                    attempts: int = 8) -> bool:
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            have = part.stat().st_size if part.exists() else 0
            with _open(url, start=have) as r:
                if have and r.status != 206:
                    have = 0
                    part.unlink()
                with part.open("ab" if have else "wb") as out:
                    while True:
                        b = r.read(CHUNK)
                        if not b:
                            break
                        out.write(b)
            part.replace(dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 416 and part.exists():
                part.replace(dest)
                return True
            print(f"  attempt {attempt} FAILED {url}: HTTP {e.code}",
                  flush=True)
        except Exception as e:
            print(f"  attempt {attempt} FAILED {url}: {str(e)[:80]}",
                  flush=True)
        time.sleep(min(60, 3 * attempt))
    return False

def fetch(url: str, dest_dir: str | pathlib.Path, expected_sha: str = "",
          workers: int = 6) -> dict:
    dest_dir = pathlib.Path(dest_dir).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._+-]", "_",
                  url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]) or "file"
    dest = dest_dir / name
    if not expected_sha:
        expected_sha = _sidecar_hash(url) or ""
    expected_sha = expected_sha.lower().strip()

    size, ranges_ok = _remote_size(url)
    ok = False
    if size >= MIN_CHUNKED_SIZE and ranges_ok and workers > 1:
        try:
            ok = _download_chunked(url, dest, size, workers)
        except _RangeIgnored:
            for p in dest.parent.glob(dest.name + ".part*"):
                p.unlink()
    if not ok:
        ok = _download_plain(url, dest)
    if not ok or not dest.exists():
        return {"url": url, "file": str(dest), "status": "failed"}

    got = _sha256_file(dest)
    rec = {"url": url, "file": str(dest),
           "size": dest.stat().st_size, "sha256": got}
    if expected_sha and got != expected_sha:
        dest.unlink()
        rec["status"] = "hash_mismatch"
        rec["expected"] = expected_sha
        print(f"HASH MISMATCH {name}: {got[:12]} != {expected_sha[:12]} "
              f"— corrupt file deleted", flush=True)
    elif expected_sha:
        rec["status"] = "verified"
        print(f"VERIFIED {name} ({dest.stat().st_size / 1e9:.2f} GB sha ok)",
              flush=True)
    else:
        rec["status"] = "unverified_no_hash"
        print(f"DOWNLOADED {name} (no expected hash found — recorded "
              f"sha256 {got[:12]}…)", flush=True)
    return rec

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="parallel + resumable + hash-verified downloads "
                    "(any http(s) file)")
    ap.add_argument("urls", nargs="+", help="file URLs")
    ap.add_argument("--dest", default=".", help="target directory")
    ap.add_argument("--sha256", default="", help="expected sha256 (applies "
                    "when one URL is given; else auto sidecar)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    results = []
    with cf.ThreadPoolExecutor(max_workers=min(args.workers,
                                               len(args.urls))) as pool:
        futs = [pool.submit(fetch, u, args.dest,
                            args.sha256 if len(args.urls) == 1 else "",
                            args.workers)
                for u in args.urls]
        for f in cf.as_completed(futs):
            results.append(f.result())

    manifest = pathlib.Path(args.dest) / "MANIFEST.json"
    try:
        prior = json.loads(manifest.read_text()) if manifest.exists() else {}
    except Exception:
        prior = {}
    prior.update({r["file"]: r for r in results})
    manifest.write_text(json.dumps(prior, indent=2))

    bad = [r["file"] for r in results if r["status"] not in
           ("verified", "unverified_no_hash")]
    ok = [r for r in results if r["status"] == "verified"]
    unv = [os.path.basename(r["file"]) for r in results
           if r["status"] == "unverified_no_hash"]
    if bad:
        print(f"FAILED/UNVERIFIED REMAIN: {bad}", flush=True)
    elif unv:
        print(f"DONE, {len(unv)} unverified (no hash available): {unv}",
              flush=True)
    else:
        print(f"ALL VERIFIED ({len(ok)})", flush=True)
    return 0 if not bad else 1

if __name__ == "__main__":
    sys.exit(main())
