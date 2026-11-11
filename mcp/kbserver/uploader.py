#!/usr/bin/env python3
import json, os, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbcore
import jobs

PORT = 8855
ROOT = os.path.dirname(os.path.abspath(__file__))

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Knowledge Ingester</title>
<style>
:root{--bg:#0c0f13;--card:#161b21;--edge:#242c35;--ink:#dbe2ea;--dim:#8b97a5;--acc:#e8c45a;--ok:#5fd394;--warn:#ff9b8a;--blue:#7dd7f0}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui}
.wrap{max-width:1020px;margin:0 auto;padding:22px 20px 60px}
header{display:flex;align-items:center;gap:12px;padding:6px 0 18px}
.mark{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,#e8c45a,#7a5f00);display:grid;place-items:center;font-weight:800;color:#141000;font-size:15px}
h1{font-size:18px;margin:0}
.badge{font-size:11px;color:#141000;background:#9aa5b1;border-radius:20px;padding:3px 10px;margin-left:auto}
h2{font-size:13px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase;margin:26px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(318px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:14px 16px}
.card .name{font-weight:700;color:var(--acc);font-size:15px}
.pill{display:inline-block;font-size:11px;border-radius:20px;padding:2px 10px;margin-left:8px;vertical-align:2px}
.idle{background:#232b34;color:#9aa5b1}.run{background:#17324a;color:var(--blue)}.done{background:#123024;color:var(--ok)}.err{background:#33191a;color:var(--warn)}.pause{background:#332a14;color:#e8c45a}
.bar{height:8px;border-radius:6px;background:#0d1116;margin:10px 0 6px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#e8c45a88,#e8c45a);width:0%;}
.meta{font-size:12px;color:var(--dim)}
.recs{margin-top:10px;border-top:1px solid var(--edge);padding-top:8px;display:none}
.recs div{font-size:12px;color:#aab6c2;padding:3px 0;border-bottom:1px dotted #1f262e;cursor:default}
.recs span{color:var(--blue);font-family:ui-monospace,monospace}
button{background:#2a333e;color:var(--ink);border:0;border-radius:8px;padding:9px 16px;font-size:13px;cursor:pointer}
button.pri{background:var(--acc);color:#161000;font-weight:700}
button:hover{filter:brightness(1.12)}
input[type=text]{width:100%;box-sizing:border-box;background:#0d1116;border:1px solid var(--edge);color:var(--ink);border-radius:8px;padding:9px 11px}
textarea{width:100%;box-sizing:border-box;background:#0d1116;border:1px solid var(--edge);color:var(--ink);border-radius:8px;padding:9px 11px;min-height:74px;font:12px ui-monospace,monospace}
.drop{border:2px dashed #344050;border-radius:12px;padding:22px;text-align:center;color:var(--dim);cursor:pointer;transition:.15s}
.drop.on{border-color:var(--acc);color:var(--acc);background:#e8c45a11}
.drop b{color:var(--ink)}
.files{font-size:12px;color:var(--dim);margin-top:8px;min-height:16px}
.row{display:flex;gap:10px;align-items:flex-start}
.row .col{flex:1}
.road{margin-top:26px;background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:14px 16px;color:var(--dim);font-size:12.5px}
.road code{color:var(--blue)}
.sk{color:var(--warn)}
</style></head><body><div class="wrap">
<header><div class="mark">KI</div><h1>Knowledge Ingester</h1><div class="badge">MiniLM-L6 CPU · offline after ingest</div></header>

<h2>Build a knowledge base</h2>
<div class="card">
<div class="row"><div class="col" style="max-width:280px"><label style="color:var(--dim);font-size:12px">database name</label>
<input id="nb" placeholder="motosniper-rules, umgc-law..."><button class="pri" style="margin:10px 0 0" onclick="create()">create db</button></div></div>
<div id="cret" class="meta" style="margin-top:8px"></div></div>

<div class="card">
<label style="color:var(--dim);font-size:12px">target database</label>
<input id="db" placeholder="db name" list="dblist"><datalist id="dblist"></datalist>
<div style="height:12px"></div>
<div class="drop" id="drop" onclick="document.getElementById('pdf').click()">
<b>drop PDFs here</b> or click to choose — multi-file; extracted with headings, boilerplate stripped, embedded on CPU
<input type="file" id="pdf" multiple accept="application/pdf" style="display:none">
<div class="files" id="files"></div></div>
<label style="color:var(--dim);font-size:12px;margin-top:12px">or paste source URLs (one per line, fetched politely)</label>
<textarea id="urls" placeholder="https://example.org/article"></textarea>
<button class="pri" onclick="ingest()">extract + condense + embed</button>
<div class="meta" id="igstat" style="margin-top:10px"></div></div>

<h2>Knowledge bases</h2>
<div class="grid" id="dbs"><div class="card meta">loading…</div></div>

<div class="road"><b>Query it:</b> any MCP-capable client → <code>python3 ~/knowledge-ingestor/kbserver.py</code>
(kb_search / kb_get / kb_ingest_urls / kb_ingest_pdf) — or offline CLI:
<code>ai-ref-sem -f dbs/&lt;name&gt;/pack.jsonl [terms]</code>. Everything stays under <code>~/knowledge-ingestor/dbs/</code>. Loopback only.</div>
</div><script>
const $ = id => document.getElementById(id);
['dragover','dragenter'].forEach(e => $('drop').addEventListener(e, ev => { ev.preventDefault(); $('drop').classList.add('on'); }));
['dragleave','drop'].forEach(e => $('drop').addEventListener(e, ev => { ev.preventDefault(); $('drop').classList.remove('on'); }));
$('drop').addEventListener('drop', ev => {
  $('pdf').files = ev.dataTransfer.files; showfiles(ev.dataTransfer.files);
});
$('pdf').addEventListener('change', ev => showfiles($('pdf').files));
function showfiles(fl){ $('files').textContent = fl.length ? [...fl].map(f => f.name + ' (' + (f.size/1024|0) + 'kb)').join(' · ') : ''; }
async function jpost(p, body){ const r = await fetch(p, body ? {method:'POST', body} : {method:'POST'}); return r.json(); }
async function create(){
  const fd = new FormData(); fd.append('name', $('nb').value.trim());
  const j = await jpost('/create', fd);
  $('cret').textContent = j.ok ? '✓ db ready: ' + j.name : '✗ ' + j.msg;
  refresh();
}
async function ingest(){
  const db = $('db').value.trim();
  if (!db) { $('igstat').textContent = '✗ pick a db name first'; return; }
  const fd = new FormData(); fd.append('db', db);
  [...$('pdf').files].forEach(f => fd.append('pdf[]', f, f.name));
  fd.append('urls', $('urls').value);
  const j = await jpost('/ingest', fd);
  $('igstat').innerHTML = j.ok
    ? '↻ job started in ' + j.db + ' — ' + j.files + ' file(s) + ' + j.urls + ' url(s)'
    : '✗ ' + j.msg;
  refresh();
}
async function toggle(n){
  const r = await fetch('/records?db=' + encodeURIComponent(n)); const j = await r.json();
  const el = document.getElementById('rec-' + n);
  el.style.display = el.style.display === 'block' ? 'none' : 'block';
  el.innerHTML = j.records.length ? j.records.map(x => '<div><span>' + x.i + '</span> ' + x.t.slice(0,74) + '</div>').join('') : '<div>empty</div>';
}
const max = n => Math.max(...n, 1);
async function refresh(){
  const r = await fetch('/stats'); const j = await r.json();
  document.getElementById('dblist').innerHTML = (j.dbs||[]).map(d => '<option value="' + d.name + '">').join('');
  const mx = max((j.dbs||[]).map(d => d.records));
  $('dbs').innerHTML = (j.dbs||[]).map(d => {
    const p = {idle:'', running:'run', done:'done', error:'err', extracting:'run', embedding:'run',
               validating:'run', queued:'run', embedding_paused:'pause', needs_rebuild:'err', interrupted:'err'}[d.state] || '';
    const skip = d.skipped ? '<div class="sk">parked ' + d.skipped.length + '</div>' : '';
    const dup = d.dups ? '<div class="meta">duplicates skipped: ' + d.dups + '</div>' : '';
    const pend = d.pending_embed ? '<div class="pause" style="display:inline-block;font-size:11px;border-radius:20px;padding:2px 10px;margin-right:6px">' + d.pending_embed + ' pending embed</div>' : '';
    const err = d.error ? '<div class="err">' + d.error + '</div>' : '';
    return '<div class="card"><span class="name">'+d.name+'</span><span class="pill '+p+'">'+(d.state||'idle')+'</span>' +
      '<div class="bar"><i style="width:' + Math.round(100*d.records/mx) + '%\"></i></div>' +
      '<div class="meta">'+d.records+' records'+(d.added!=null?' · last job +'+d.added:'')+'</div>' + pend + err + dup + skip +
      '<button style="margin-top:8px;font-size:12px;padding:5px 12px" onclick="toggle(\''+d.name+'\')">records</button>' +
      '<div class="recs" id="rec-'+d.name+'"></div></div>';
  }).join('') || '<div class="card meta">no databases yet — create one above</div>';
}
setInterval(refresh, 1800); refresh();
</script></body></html>"""

def page():
    return PAGE

def safe_db(n):
    n = (n or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", n):
        raise ValueError("bad name")
    return kbcore.db_dir(n)

def tail_records(path, n=12):
    rows = kbcore.pack_rows(path)
    return [{"i": r["i"], "t": r["t"], "src": r.get("src", "")} for r in rows[-n:][::-1]]

def mpart(body, boundary):
    fields, files = {}, []
    for part in body.split(b"--" + boundary):
        if b"filename=" in part[:600]:
            fnm = re.search(rb'filename="([^"]*)"', part[:600])
            if fnm and fnm.group(1).strip():
                p = part.split(b"\r\n\r\n", 1)
                if len(p) == 2:
                    blob = p[1].rsplit(b"\r\n", 1)[0]
                    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", fnm.group(1).decode())
                    updir = os.path.join(ROOT, "dbs", "uploads-tmp")
                    os.makedirs(updir, exist_ok=True)
                    fp = os.path.join(updir, f"{int(time.time())}_{safe}")
                    open(fp, "wb").write(blob)
                    files.append(fp)
            continue
        fnm = re.search(rb'name="([^"]*)"', part[:600])
        if fnm:
            p = part.split(b"\r\n\r\n", 1)
            if len(p) == 2:
                fields.setdefault(fnm.group(1).decode(), []).append(p[1].rsplit(b"\r\n", 1)[0].decode(errors="replace"))
    return fields, files

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, page().encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/stats"):
            out = []
            for d in kbcore.dbs():
                st = kbcore.status_get(kbcore.db_dir(d["name"]))
                out.append({**d, **{k: st.get(k) for k in
                            ("state", "added", "skipped", "error", "phase", "dups", "pending_embed", "jobid")}})
            self._send(200, json.dumps({"dbs": out}).encode())
        elif self.path.startswith("/records"):
            q = parse_qs(urlparse(self.path).query)
            try:
                self._send(200, json.dumps({"records": tail_records(safe_db(q.get("db", [""])[0]))}).encode())
            except Exception as e:
                self._send(400, json.dumps({"records": [], "err": str(e)}).encode())
        else:
            self._send(404, b'{"error":"no"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        typ = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", typ)
        fields, files = mpart(body, m.group(1).strip('"').encode()) if m else (parse_qs(body.decode(errors="replace")), [])
        if self.path == "/create":
            try:
                path = safe_db(fields.get("name", [""])[0])
                kbcore.init_db(path, note="webui")
                self._send(200, json.dumps({"ok": True, "name": os.path.basename(path)}).encode())
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "msg": str(e)}).encode())
        elif self.path == "/ingest":
            try:
                path = safe_db(fields.get("db", [""])[0])
                kbcore.init_db(path)
                urls = [u.strip() for u in fields.get("urls", [""])[0].splitlines() if u.strip().startswith("http")]
                newloc = []
                for f in files:
                    os.makedirs(f"{path}/uploads", exist_ok=True)
                    tgt = os.path.join(f"{path}/uploads", os.path.basename(f))
                    os.replace(f, tgt)
                    newloc.append(tgt)
                items = [("pdf", t, {"d": "document", "f": "webui"}) for t in newloc] + \
                        [("url", u, {"d": "web", "f": "webui"}) for u in urls]
                if not items:
                    self._send(400, json.dumps({"ok": False, "msg": "nothing to ingest: no pdfs or http urls"}).encode())
                else:
                    jobs.reconcile(path, autostart=False)
                    j = jobs.create_job(path, items, note="webui")
                    if jobs.try_claim(path, j["jobid"]):
                        jobs.start_threaded(path, j)
                    self._send(200, json.dumps({"ok": True, "db": os.path.basename(path),
                                                "files": len(newloc), "urls": len(urls),
                                                "jobid": j["jobid"]}).encode())
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "msg": str(e)}).encode())
        else:
            self._send(404, b'{"error":"no"}')

if __name__ == "__main__":
    os.makedirs(f"{ROOT}/dbs", exist_ok=True)
    resumed = jobs.reconcile_all(kbcore.DBS, autostart=True)
    if resumed:
        print(f"reconcile resumed jobs: {resumed}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"knowledge-ingestor portal ready on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()