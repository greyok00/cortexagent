# CortexAgent ↔ slimtoken/cortexllm — Separation & Propagation Rules

> **Living document.** Updated 2026-08-11. The hard rule is: keep generic
> improvements generic; keep CortexAgent-specific code CortexAgent-only. This
> file is the rubric for both directions.

---

## 1. The boundary

CortexAgent **imports** from two upstream packages:

| Upstream | Where CortexAgent touches it | What CortexAgent adds on top |
|---|---|---|
| `slimtoken.pipeline` | `lib/grammar_proxy.py`, `lib/overseer.py` (minify_request, MinifyConfig) | prompt-shape tuning, LOCKED_KEYS-style config gating |
| `cortexllm.*` (db, vector, graph, ontology, mcp_server) | `lib/grammar_proxy.py`, `bin/cortexagent`, `memory/`, `lib/memory_thin.py`, `~/.cortexllm/scripts/memory-daemon.py` | platform="cortexagent", in-tree `memory/mcp_server.py`, integration with SessionBridge |

Everything else in `/home/grey/cortexagent/lib`, `/memory`, `/engine`, `/hooks`,
`/install.sh`, `bin/cortexagent` is **CortexAgent-specific** — it must NOT be
propagated upstream.

### The "decoupled" test

> If I strip `platform="cortexagent"`, the daemon hooks, the SessionBridge, the
> unified chat, and the model-specific config, does the rest still work?

- **YES → propagates.** Examples: a fix to the daemon-socket line reader, a
  smarter NDJSON trim policy, a new cortexllm-vector query, a slimtoken
  minify rule.
- **NO → stays.** Examples: the SessionBridge multi-voice schema, the
  in-tree `memory/mcp_server.py` (the upstream one doesn't know about
  `platform="cortexagent"` and the unified chat), the `lib/daemon.py` 35B
  keepalive policy.

---

## 2. Propagation workflow (CortexAgent → upstream)

When you change a CortexAgent file that the "decoupled" test says is generic:

1. **Identify the upstream target:**
   - `slimtoken` → `~/slimtoken/repo/` (or github `greyok00/slimtoken`)
   - `cortexllm` → `~/cortexllm/repo/` (or github `greyok00/cortexllm`)
2. **Strip CortexAgent assumptions.** Remove any reference to:
   - `platform="cortexagent"` (use `platform="default"` or env-override)
   - `~/.cortexagent/`, `~/.config/cortexllm/memory/cortexagent.*`
   - The daemon, overseer, webui, SessionBridge
   - `LOCKED_KEYS` and `CORTEXAGENT_*` env names
3. **Add safe defaults.** Standalone users don't have an autostart daemon or
   the same hardware. Anything that's a CortexAgent tuning knob (the
   `big_ctx: 131072` value, the `kv-unified` opt-in) should be opt-in in the
   upstream version, with a comment explaining what it does.
4. **Test in the standalone repo first.** Use the upstream's own smoke suite.
   The standalone test harness can't import `lib.*` — write a small reproducer
   that exercises only the changed function.
5. **Cut a patch bump in the upstream repo** (`v0.3.4` style) and bump the
   dependency reference in `bin/cortexagent` or the install script if the
   consumer pins a version.
6. **Update the standalone smoke + integration test.** Don't ship the change
   to CortexAgent until the upstream smoke is green.

**Concrete examples from this session:**
- `v0.3.2` split import path fix (`legacy/` → `repo/`): applied to both
  CortexAgent (`bin/cortexagent`, `cortexllm/start-cortexllm-mcp.sh`) and the
  standalone scripts. Standalone has its own PR/release. Pre-merge here,
  post-merge there.
- `_atomic_append` and `drain-until-EOF`: are already standalone-clean (no
  `platform=` hard-coded), but still pending merge into the new
  `cortexllm/` package — this doc serves as the work-order for that.

---

## 3. Propagation workflow (upstream → CortexAgent)

When you upgrade `slimtoken` or `cortexllm`:

1. **Read the upstream CHANGELOG.** Look for new env knobs, default-config
   changes, new functions in `slimtoken.pipeline` /
   `cortexllm.{db,vector,graph,ontology,mcp_server}`.
2. **Audit the CortexAgent config gating.** Anything that was a
   `CORTEXAGENT_*` env knob wrapping an upstream default should be checked:
   did the upstream default change? Should our override be relaxed?
3. **Run the CortexAgent smoke gate.** `python3 tests/run_smoke.py` — make
   sure 31/31 coverage + ≥33/38 tests still pass. The 5 known failures
   (audit-stale references) should be unchanged.
4. **Run the end-to-end bridge test** (if SessionBridge touched):
   ```bash
   python3 -c '
   from lib.webui import BRIDGE, serve_forever
   import threading, urllib.request, json, time, socket
   s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
   sv=serve_forever(port=port);threading.Thread(target=sv.serve_forever,daemon=True).start()
   BRIDGE._path.write_text("")
   events=[]
   def reader():
     r=urllib.request.urlopen(f"http://127.0.0.1:{port}/webui-events",timeout=8)
     for raw in r:
       line=raw.decode().strip()
       if line.startswith("data:"): events.append(json.loads(line[5:]))
       if len(events)>=3: break
   threading.Thread(target=reader,daemon=True).start(); time.sleep(0.5)
   BRIDGE.write("tui",{"id":"t1","from":"tui","username":"Big Model","type":"response","content":"x"})
   BRIDGE.write("overseer",{"id":"o1","from":"overseer","username":"Overseer","type":"message","content":"y"})
   time.sleep(2); sv.shutdown(); sv.server_close()
   assert "t1" in {e.get("id") for e in events}
   assert "o1" in {e.get("id") for e in events}
   print("bridge OK")
   '
   ```

---

## 4. What's CortexAgent-specific and stays here

| Module / file | Why it stays |
|---|---|
| `lib/session_bridge.py` | Multi-voice chat under different usernames — CortexAgent UX |
| `memory/mcp_server.py` (in-tree copy) | Knows `platform="cortexagent"` and the in-tree DB schema |
| `lib/daemon.py` | 35B keepalive, no fallback swap, idle_unload=0 default — user prefs |
| `lib/overseer.py` | Owns tiny on :8082, schedules warm→cold distillation, daemon watchdog |
| `lib/grammar_proxy.py` | Wraps slimtoken minify with CortexAgent prompt-shape rules + chunked grammar-strip |
| `lib/webui.py` | 3D chat pane + nested overseer dashboard schema |
| `lib/tui.py` | Textual streaming TUI with response_model blocks |
| `lib/tray.py`, `lib/tray_dashboard.py` | System-tray icon + overseer popout |
| `lib/diffusion_backend.py` | In-process diffusers (image + LTX-Video) |
| `lib/response_model.py` | Parse artifacts/sanitize ANSI/collapse — pure parse layer |
| `lib/banner.py` | ANSI in-place boot banner |
| `bin/cortexagent` | bash launcher with daemon-mode + welcome screen |
| `install.sh` | Installs systemd services + user dirs (CortexAgent-specific paths) |
| `config/templates/cortexagent*.service` | Systemd user units (template-style, env-vars, no PII) |
| `hooks/*.sh` | CLI session hooks writing via `memory_thin.py` |
| `engine/` | DAG workflow engine (CortexAgent-specific) |

## 5. What's generic and should be propagated

| Item | Where it lives now | What to propagate |
|---|---|---|
| `_atomic_append` POSIX helper | `lib/memory_thin.py`, `~/.cortexllm/scripts/{memory-daemon,save-context}.py`, `lib/session_bridge.py` | **Pending upstream merge.** Add `cortexllm.atomic_append(...)` to the `cortexllm/` package with a "use when concurrent writers exist" docstring; the `flock+fsync` variant belongs upstream |
| Memory-daemon drain-until-EOF (`handle_client`) | `~/.cortexllm/scripts/memory-daemon.py` | **Pending upstream merge.** The fix (loop `recv(64KB)` until EOF, 8MB cap) is generic — any UNIX-socket server benefits. Port into `cortexllm.daemon.handle_client` and re-export |
| Chunked grammar-strip standalone path (`_forward_chunked_strip_only`) | `lib/grammar_proxy.py` | The chunked-dechunk-rewrite is generic; the cortexagent-specific parts (the LOCKED_KEYS gate) stay here |
| Slimtoken minify rule improvements for prompt-shape X | `lib/grammar_proxy.py`, `lib/overseer.py` | Any new rule that's safe-by-default goes upstream. Qwen3.6 / 35B-specific patterns stay here |
| NDJSON append without caps (2026-08-11 rule) | Both sides | Mirror in `~/.cortexllm/scripts/save-context.py`; upstream default is already uncapped |

---

## 6. Maintenance checklist (run before merging any CortexAgent change)

> A change is "generic-propagatable" if the test in §1 says YES.

- [ ] **Did I touch `lib/grammar_proxy.py` minify rules or chunked handling?**
      If yes → ensure the standalone `slimtoken` repo's pipeline doesn't
      regress. Run `python3 -m pytest ~/slimtoken/repo/tests/`.
- [ ] **Did I touch `lib/memory_thin.py` or `memory/mcp_server.py`?**
      If yes → run the standalone cortexllm smoke (`python3
      ~/cortexllm/repo/tests/test_smoke.py`). If the change is generic, port
      it to `~/cortexllm/repo/cortexllm/` and cut a patch release.
- [ ] **Did I add a new env knob (`CORTEXAGENT_*`)?** If yes → check
      whether the upstream default should be the same. If so, propose the
      change upstream and remove our override once it's shipped.
- [ ] **Did I change the SessionBridge?** Almost always CortexAgent-specific.
      No propagation needed; just update `docs/ARCHITECTURE.md` §5 and the
      unified-session memory entry.
- [ ] **Did I touch a systemd unit template?** CortexAgent-specific (paths,
      env names). No propagation.
- [ ] **Did I add a new cortexllm vector / graph / ontology query?** Generic
      → port to upstream.
- [ ] **Did I bump a slimtoken or cortexllm version pin?** Re-run both smoke
      suites; check the 5 known smoke failures didn't shift.

---

## 7. What "default configs that work for anyone" means in practice

For the slimtoken minify config, the upstream default should:
- Have **no `LOCKED_KEYS`** — those are CortexAgent's policy, not slimtoken's.
- Use **safe-by-default minify rules** — turn off anything aggressive by
  default; let users opt in via env knobs.
- **Not assume a specific model family.** Qwen3.6-specific blocklist patterns
  belong in CortexAgent, not slimtoken.
- **Pair-safe** — slimtoken already guarantees pair-safety by construction;
  CortexAgent relies on this.

For the cortexllm memory engine, the upstream default should:
- Use **`platform="default"`** — never `"cortexagent"`.
- **Not assume a daemon socket exists** — direct NDJSON append as fallback.
- **Not assume hooks/`*.sh` exist** — the daemon is the only optional
  acceleration; everything works without it.
- **Not assume a SessionBridge or unified chat** — those are CortexAgent UX.

---

## 8. When the rule fails (escalation)

If a CortexAgent improvement would only make sense for THIS project, that's
fine — it stays in-tree. The rule isn't "always propagate"; it's "propagate
when the change makes anyone else's project better." If a change depends on:

- The 35B Qwen3.6 model's quirks → CortexAgent-only.
- The `cortexagent` config dir / isolated settings → CortexAgent-only.
- The daemon/overseer control socket protocol → CortexAgent-only.
- `X-CortexAgent-Session` / `X-CortexAgent-Origin` headers → CortexAgent-only.

…then it stays. Document *why* in the commit message so the next reader
knows.

---

## 9. Cross-references

- `docs/ARCHITECTURE.md` §9 — separation table
- `docs/AUDIT-2026-08-11.md` — full audit with concrete CortexAgent↔upstream fixes
- `lib/memory_thin.py` — CLI hook wrapper
- `memory/mcp_server.py` — in-tree MCP server (CortexAgent-specific)
- `~/cortexllm/repo/cortexllm/` — generic upstream (v0.3.2+)
- `~/slimtoken/repo/slimtoken/` — generic upstream