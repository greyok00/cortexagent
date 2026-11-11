#!/usr/bin/env python3
"""One-time chrome scrub: drop existing records whose text is boilerplate
(nav rails, headline lists), then reembed the touched dbs. Idempotent: uses
the same chrome_score gate as the live pipeline."""
import json, sys, os, time
sys.path.insert(0, "~/knowledge-ingestor")
import kbcore
import kbserver_patch as kp

def scrub_db(db):
    path = kbcore.db_dir(db)
    rows = kbcore.pack_rows(path)
    keep, drop = [], []
    for r in rows:
        x = r.get("x") or ""
        # preserve uploaded/official PDFs regardless — they went through a
        # different (owner-curated) path and rarely carry site chrome
        if (r.get("u") or "").startswith("upload:"):
            keep.append(r); continue
        if kp.chrome_score(x) >= 0.25:
            drop.append(r)
        else:
            keep.append(r)
    if not drop:
        return db, 0, 0
    # rewrite pack atomically
    tmp = f"{path}/pack.jsonl.scrub"
    with open(tmp, "w") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, f"{path}/pack.jsonl")
    return db, len(keep), len(drop)

def main():
    only = sys.argv[1:] or sorted(d.name for d in __import__("pathlib").Path("dbs").iterdir()
                                  if d.is_dir() and d.name != "uploads-tmp")
    print(f"{'db':22} {'kept':>6} {'dropped':>8}")
    t00 = time.time()
    for db in only:
        try:
            name, kept, dropped = scrub_db(db)
            print(f"{name:22} {kept:6} {dropped:8}")
        except Exception as e:
            print(f"{db:22} ERR {str(e)[:60]}")
    print(f"scrub wall: {time.time()-t00:.1f}s")

if __name__ == "__main__":
    main()
