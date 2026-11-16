#!/usr/bin/env python3
import json, os, re, hashlib, html, threading, time
from html.parser import HTMLParser
import numpy as np

HOME = os.path.expanduser("~")
MODEL = f"{HOME}/apps/models/hf/Xenova/all-MiniLM-L6-v2"
DIMS, SEQ = 384, 512
QSEQ, FLOOR, FIRM, K = 128, 0.25, 0.45, 60
DB_LOCK = threading.RLock()


class Encoder:
    sess = tok = None

    def __init__(self):
        if os.environ.get("KB_DISABLE_MODEL"):
            raise RuntimeError("model disabled by KB_DISABLE_MODEL")
        import onnxruntime as ort
        from tokenizers import Tokenizer
        so = ort.SessionOptions()
        self.sess = ort.InferenceSession(f"{MODEL}/onnx/model_quantized.onnx", so, providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(f"{MODEL}/tokenizer.json")
        self.inames = [i.name for i in self.sess.get_inputs()]

    def pad(self, n):
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]", length=n)
        self.tok.enable_truncation(max_length=n)

    def encode(self, texts, n=SEQ):
        self.pad(n)
        rows = self.tok.encode_batch(texts) if len(texts) > 1 else [self.tok.encode(texts[0])]
        ids = np.array([e.ids for e in rows], dtype=np.int64)
        att = np.array([e.attention_mask for e in rows], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": att}
        if "token_type_ids" in self.inames:
            feed["token_type_ids"] = np.zeros_like(ids)
        h = self.sess.run(None, feed)[0]
        m = att[:, :, None].astype(np.float32)
        avg = (h * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        return (avg / (np.linalg.norm(avg, axis=1, keepdims=True) + 1e-12)).astype(np.float32)


SKIP_TAGS = {"script", "style", "svg", "nav", "header", "footer", "noscript",
             "img", "button", "template", "aside", "form", "iframe"}

class Grab(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in ("p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "td", "pre"):
            self.flush()
        if tag in ("h1", "h2", "h3", "h4"):
            self.buf.append("\n## " if tag in ("h1", "h2") else "\n### ")
        elif tag == "br":
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "td", "pre"):
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def flush(self):
        t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if t:
            self.blocks.append(t)
        self.buf = []


def html_text(raw):
    g = Grab()
    g.feed(raw)
    g.close()
    out = "\n\n".join(g.blocks)
    out = re.sub(r"\n?\d+(,\d+)? (words?|min[s]?|views?)[^\n]*(read)?", "", out)
    out = re.sub(r"\nSource [^\n]*(↗|http)", "", out)
    out = html.unescape(out)
    return out.strip()


def _pages_pymupdf(path):
    import pymupdf
    doc = pymupdf.open(path)
    pages = []
    for pg in doc:
        d = pg.get_text("dict")
        lines = []
        for b in d.get("blocks") or []:
            for l in b.get("lines") or []:
                txt = "".join(s.get("text", "") for s in l.get("spans") or [])
                sz = max((s.get("size", 0) for s in l.get("spans") or []), default=0)
                bold = any(bool(s.get("flags", 0) & 2) for s in l.get("spans") or [])
                if txt.strip():
                    lines.append((re.sub(r"\s+", " ", txt).strip(), round(sz, 1), bold))
        if lines:
            pages.append(lines)
    doc.close()
    return pages


def _pages_pypdf(path):
    import pypdf
    r = pypdf.PdfReader(path)
    pages = []
    for pg in r.pages:
        lines = [(re.sub(r"\s+", " ", l).strip(), 0.0, False) for l in (pg.extract_text() or "").splitlines() if l.strip()]
        if lines:
            pages.append(lines)
    return pages


def pdf_text_logged(path):
    """Extraction behavior tree: pymupdf first (validated non-empty), then
    pypdf. The branch taken is returned so the journal can record it."""
    branch = ""
    pages = []
    try:
        pages = _pages_pymupdf(path)
        branch = "pymupdf"
    except Exception:
        pages = []
    if not pages:
        pages = _pages_pypdf(path)
        branch = "pypdf"
    from collections import Counter
    sizes = Counter()
    for pp in pages:
        for _, sz, _ in pp:
            sizes[round(sz, 0)] += 1
    mode = sizes.most_common(1)[0][0] if sizes else 0.0

    def is_head(txt, sz, bold):
        letters = [c for c in txt if c.isalpha()]
        caps = len(letters) >= 3 and all(c.isupper() for c in letters) and len(txt) < 92 and not txt.rstrip().endswith((".", ":", ",", ";"))
        return (mode and sz >= mode * 1.18 and len(txt) < 110) or (bold and mode and sz >= mode * 1.04 and len(txt) < 110) or caps

    counts = {}
    for pp in pages:
        for edge in pp[:2] + pp[-2:]:
            t = edge[0].lower()
            if t and len(t) > 3:
                counts[t] = counts.get(t, 0) + 1
    boiler = {t for t, c in counts.items() if c > max(2, len(pages) * 0.4)}
    out, body = [], []
    for pp in pages:
        for txt, sz, bold in pp:
            if txt.lower() in boiler:
                continue
            if is_head(txt, sz, bold):
                if body:
                    out.append(" ".join(body)); body = []
                out.append(f"## {txt}")
            else:
                body.append(txt)
        if body:
            out.append(" ".join(body)); body = []
        out.append("")
    return re.sub(r"- (?=\w)", "", "\n\n".join(out)).strip(), branch


def pdf_text(path):
    return pdf_text_logged(path)[0]


def chunk(text, size=2400):
    blocks = [re.sub(r"[ \t]+", " ", b).strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    secs, head, cur = [], "", []
    for b in blocks:
        if b.startswith("## ") or b.startswith("# "):
            if head or cur:
                secs.append((head, cur))
            head, cur = re.sub(r"^#+\s*", "", b).strip(), []
        else:
            cur.append(b)
    if head or cur:
        secs.append((head, cur))
    out = []
    for head, paras in secs:
        flow = []
        for p in paras:
            if len(p) > size:
                flow += [x for x in re.split(r"(?<=[.!?]) (?=[A-Z0-9])", p) if x]
            else:
                flow.append(p)
        pre = (head + "\n") if head else ""
        budget = max(200, size - len(pre))
        buf = ""
        for p in flow:
            if buf and len(buf) + len(p) + 2 > budget:
                out.append((pre + buf).strip())
                buf = ""
            buf = (buf + "\n\n" + p) if buf else p
        if buf:
            out.append((pre + buf).strip())
    out = [c for c in out if len(c) > 40]
    if not out and text.strip():
        # never-empty rule: a validated text must yield records (a doc that is
        # one heading-block of markdown currently produces none through secs).
        flow = [x for x in re.split(r"(?<=[.!?]) (?=[A-Z0-9])", re.sub(r"\s+", " ", text).strip()) if x]
        buf = ""
        for p_ in flow:
            if buf and len(buf) + len(p_) + 2 > size:
                out.append(buf.strip())
                buf = ""
            buf = (buf + " " + p_) if buf else p_
        if buf:
            out.append(buf.strip())
        out = [c for c in out if len(c) > 40]
    return out


DBS = f"{HOME}/knowledge-ingestor/dbs"

def db_dir(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
        raise ValueError("bad db name")
    return os.path.join(DBS, name)

def dbs():
    if not os.path.isdir(DBS):
        return []
    out = []
    for d in sorted(os.listdir(DBS)):
        p = os.path.join(DBS, d)
        if os.path.isfile(f"{p}/pack.jsonl"):
            n = sum(1 for _ in open(f"{p}/pack.jsonl", encoding="utf-8"))
            out.append({"name": d, "records": n})
    return out

def init_db(path, note=""):
    os.makedirs(f"{path}/learned", exist_ok=True)
    os.makedirs(f"{path}/uploads", exist_ok=True)
    if not os.path.exists(f"{path}/pack.jsonl"):
        open(f"{path}/pack.jsonl", "w").close()
        manifest({"name": os.path.basename(path), "note": note}, path, 0)

def manifest(m, path, n):
    mm = dict(m)
    mm.update({"records": n, "format": "knowledge-ingestor-v1", "built": time.strftime("%F %T")})
    json.dump(mm, open(f"{path}/manifest.json", "w"), indent=2)

EMB_BATCH = 64


def _norm_key(t, x):
    norm = re.sub(r"\s+", " ", f"{t}\n{x}".lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:20]


def records_from(text, base):
    """Chunk into records. One chunk = one record; the source's title/url ride
    on every record; multi-chunk sources get ' - part N' suffixes."""
    parts = chunk(text)
    out = []
    total = len(parts)
    for n, c in enumerate(parts):
        r = dict(base)
        r["t"] = base["t"] if total == 1 else f"{base['t']} - part {n + 1}"
        r["d"] = (c[:150] + "...") if len(c) > 150 else c
        r["x"] = c
        r["k"] = _norm_key(r["t"], c)
        out.append(r)
    return out


def pack_rows(path):
    """Tolerant reader: parse until a torn line, then stop trusting the tail.
    Readers never crash on the crash-window's half-written line."""
    fp = f"{path}/pack.jsonl"
    if not os.path.exists(fp):
        return []
    out = []
    with open(fp, encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if not l:
                continue
            try:
                out.append(json.loads(l))
            except Exception:
                break
    return out


def _vecs_rows(path):
    """Tolerant vector reader: truncates an incomplete trailing row instead of
    raising. Returns (V or None, byte_size)."""
    fp = f"{path}/learned/vectors.bin"
    if not os.path.exists(fp):
        return None, 0
    size = os.path.getsize(fp)
    rows = size // (DIMS * 4)
    if rows == 0:
        return None, size
    with open(fp, "rb") as f:
        V = np.frombuffer(f.read(rows * DIMS * 4), dtype=np.float32).reshape(-1, DIMS)
    return V, size


def _write_vectors(path, V, all_rows):
    """Atomic full rewrite of vectors.bin + ids.jsonl. ids always has one line
    per pack record; rows beyond V carry n=0 (the pending-embed state)."""
    d = f"{path}/learned"
    os.makedirs(d, exist_ok=True)
    ids = []
    for j, r in enumerate(all_rows):
        n = round(float(np.linalg.norm(V[j])), 4) if j < len(V) else 0.0
        ids.append({"i": r["i"], "t": r["t"][:90], "n": n})
    vt, it = f"{d}/vectors.bin.tmp", f"{d}/ids.jsonl.tmp"
    with open(vt, "wb") as f:
        f.write(V.astype(np.float32).tobytes())
    with open(it, "w", encoding="utf-8") as f:
        for d2 in ids:
            f.write(json.dumps(d2, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(vt, f"{d}/vectors.bin")
    os.replace(it, f"{d}/ids.jsonl")


def add_records(path, records, enc, src="web"):
    """Dedup + append. Encoding happens BEFORE the first write so a crash can
    never leave pack rows that a working encoder failed to embed. Returns the
    added ids; duplicates (same content hash or same source url/path) are
    counted by the caller from len(records) - len(added)."""
    with DB_LOCK:
        rows = pack_rows(path)
        ex_ids, keys, urls, mx = set(), set(), set(), 0
        for r in rows:
            i = r.get("i", "")
            ex_ids.add(i)
            if i.startswith("e"):
                try:
                    mx = max(mx, int(i[1:]))
                except ValueError:
                    pass
            keys.add(r.get("k") or _norm_key(r.get("t", ""), r.get("x", "")))
            u = r.get("u") or r.get("p") or ""
            if u:
                urls.add(u)
        fresh, added = [], []
        for rec in records:
            k = rec.get("k") or _norm_key(rec.get("t", ""), rec.get("x", ""))
            rec["k"] = k
            u = rec.get("u") or rec.get("p") or ""
            if k in keys or (u and u in urls):
                continue
            i = rec.get("i")
            while not i or i in ex_ids:
                mx += 1
                i = f"e{mx:04d}"
            ex_ids.add(i)
            rec["i"] = i
            if "src" not in rec:
                rec["src"] = src
            keys.add(k)
            fresh.append(rec)
            added.append(i)
        if not fresh:
            return []
        if enc is not None:
            ve = _embed_batched(enc, [f"{r['t']}\n{r['x']}" for r in fresh])
        for rec in fresh:
            with open(f"{path}/pack.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        final = rows + fresh
        if enc is not None:
            V, _sz = _vecs_rows(path)
            V = ve if V is None else np.vstack([V, ve])
            _write_vectors(path, V, final)
        manifest(json.load(open(f"{path}/manifest.json")) if os.path.exists(f"{path}/manifest.json") else {"name": os.path.basename(path)}, path, len(final))
        return added


def _embed_batched(enc, texts, n=EMB_BATCH):
    if not texts:
        return np.zeros((0, DIMS), dtype=np.float32)
    out = []
    for a in range(0, len(texts), n):
        out.append(enc.encode(texts[a:a + n], SEQ))
    return np.vstack(out) if len(out) > 1 else out[0]


def embed_catchup(path, enc):
    """Embed every record without a vector, batched, atomic. Resumable: the
    invariant is vectors are a prefix of pack order."""
    with DB_LOCK:
        rows = pack_rows(path)
        V, _sz = _vecs_rows(path)
        have = 0 if V is None else V.shape[0]
        if have >= len(rows):
            return 0
        todo = rows[have:]
        ve = _embed_batched(enc, [f"{r['t']}\n{r['x']}" for r in todo])
        V = ve if V is None else np.vstack([V, ve])
        _write_vectors(path, V, rows)
        return len(todo)


def audit_db(path):
    """Storage truth: counts + verdict (ok / pending_embed / needs_rebuild)."""
    rows = pack_rows(path)
    V, size = _vecs_rows(path)
    vec_rows = 0 if V is None else V.shape[0]
    ids_rows = 0
    ifp = f"{path}/learned/ids.jsonl"
    if os.path.exists(ifp):
        with open(ifp, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    try:
                        json.loads(l)
                        ids_rows += 1
                    except Exception:
                        break
    torn = size % (DIMS * 4) != 0
    pair_never_written = vec_rows == 0 and ids_rows == 0 and size == 0
    if torn or vec_rows > len(rows) or (ids_rows != len(rows) and not pair_never_written):
        verdict = "needs_rebuild"
    elif vec_rows < len(rows):
        verdict = "pending_embed"
    else:
        verdict = "ok"
    return {"verdict": verdict, "pack_rows": len(rows), "vec_rows": vec_rows,
            "ids_rows": ids_rows, "pending_embed": max(0, len(rows) - vec_rows),
            "torn_tail": torn}


def rebuild(path, enc):
    """Full atomic re-embed. Model-free callers never invoke this; jobs.py
    marks the db needs_rebuild and repair happens when the model returns."""
    with DB_LOCK:
        rows = pack_rows(path)
        V = _embed_batched(enc, [f"{r['t']}\n{r['x']}" for r in rows])
        _write_vectors(path, V, rows)
        manifest(json.load(open(f"{path}/manifest.json")) if os.path.exists(f"{path}/manifest.json") else {"name": os.path.basename(path)}, path, len(rows))
        return len(rows)


def content_route(ctype, data):
    """Lane dispatch rule over (content-type, sniffed bytes): the ports-db
    misroute class. Returns (lane, handled, why)."""
    ct = (ctype or "").lower()
    head = data[:600]
    if ct.startswith("application/pdf") or head.startswith(b"%PDF"):
        return "pdf", True, f"ctype={ct or 'none'} + magic"
    if "html" in ct or b"<html" in head.lower() or b"<!doctype html" in head.lower():
        return "html", True, f"ctype={ct or 'none'} + html sniff"
    textish = ct.startswith("text/") or any(x in ct for x in
              ("json", "xml", "markdown", "csv", "yaml", "javascript", "x-sh", "plaintext"))
    if textish:
        return "text", True, f"ctype={ct}"
    probe = head.decode("utf-8", "ignore")
    printable = sum(1 for c in probe if c.isprintable() or c in "\n\r\t") / max(1, len(probe))
    if b"\x00" not in head and len(probe) >= 8 and printable >= 0.8:
        return "text", True, f"ctype={ct or 'none'} + printable={printable:.2f}"
    return "unknown", False, f"unroutable ctype={ct or 'none'}"


def search(path, query, k=5, enc=None):
    with DB_LOCK:
        rows = pack_rows(path)
        terms = [t.lower() for t in query.split() if len(t) > 2]
        lex = {}
        for r in rows:
            loc = r.get("p") or r.get("u", "")
            bt = (r["t"].lower() + " " + r.get("d", "").lower() + " " + loc.lower())
            bx = r["x"].lower()
            st = sum(1 for t in terms if t in bt)
            sx = sum(1 for t in terms if t in bx)
            if st or sx >= 2:
                lex[r["i"]] = st * 4 + sx + sx / max(3, len(bx) // 400)
        cos = {}
        if enc is not None:
            V, _sz = _vecs_rows(path)
            if V is not None and V.shape[0]:
                qv = enc.encode([query], QSEQ)[0]
                c = V @ qv
                order = np.argsort(-c)[: 50]
                for rank, j in enumerate(order):
                    if j < len(rows) and float(c[j]) >= FLOOR:
                        cos[rows[j]["i"]] = (float(c[j]), rank)
        srrf = {}
        for i, (cval, rank) in cos.items():
            srrf[i] = 1 / (K + rank + 1)
        lorder = sorted(lex.items(), key=lambda w: -w[1])
        for rank, (i, _) in enumerate(lorder):
            srrf[i] = srrf.get(i, 0.0) + 1 / (K + rank + 1)
        fin = sorted(srrf.items(), key=lambda w: -w[1])[:k]
        if not fin:
            return []
        byid = {r["i"]: r for r in rows if r["i"] in dict(fin)}
        res = []
        for i, _ in fin:
            r = byid[i]
            c = cos[i][0] if i in cos else 0.0
            band = "firm" if c >= FIRM else ("soft" if c >= FLOOR else "lex-only")
            res.append({"i": r["i"], "t": r["t"], "d": r.get("d", ""), "src": r.get("src", "library"),
                        "u": r.get("p") or r.get("u", ""), "cos": round(c, 3), "band": band,
                        "lex": round(lex.get(i, 0.0), 2), "x": r["x"]})
        return res

def fetch(url, timeout=25):
    import urllib.request, urllib.error, gzip, io
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) knowledge-ingestor/0.1", "Accept": "text/html,*/*", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            ctype = resp.headers.get("Content-Type", "")
            return True, data, ctype, resp.status
    except urllib.error.HTTPError as e:
        return False, str(e).encode(), e.headers.get("Content-Type", "") if e.headers else "", e.code
    except Exception as e:
        return False, str(e).encode(), "", 0


def status_set(path, d):
    json.dump({**d, "ts": time.strftime("%F %T")}, open(f"{path}/status.json", "w"))


def status_get(path):
    try:
        return json.load(open(f"{path}/status.json"))
    except Exception:
        return {"state": "idle"}