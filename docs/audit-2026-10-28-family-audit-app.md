# GreyTeam App Audit — 2026-10-28 (Phase A, web-pentest-system task)

Scope: full audit of `~/greyteam` (the hardened rewrite) — all 8 modules
(~1033 LOC), policy, state, compiled .so registration, and the prior-UMGC-report
format the new system must match. Companion to `audit-2026-10-24-greyteam.md`
(which audited the aida backend the rewrite replaced).

## Verdict

**HEALTHY — ready to host the web pentest system.** Fail-closed everywhere, no
shells, no plaintext creds, no telemetry. Doctor: 12/12 ALL GREEN. Tests: 8/8.
Two real bugs in `scan_builders.py` (below) — fix before Phase B builds on it.

## Per-module findings

| Module | LOC | Verdict |
|---|---|---|
| `greyteam_mcp.py` | 277 | Clean. stdio line-JSON-RPC, 22 tools, no SDK dep. |
| `store.py` | 150 | Clean. sqlite, 4 tables, thread lock, plain schema. |
| `exec_gate.py` | 113 | Clean. argv-only, metachar hard-deny, abs-path allowlist, NEVER first-tokens, timeout only-tightens, 2MB output cap. Nit: `".." in argv` is a substring test (rejects `foo..txt` filenames) — conservative, not a bug. |
| `http_safe.py` | 98 | Clean. NEVER_NETS incl. 169.254/16 metadata, DNS-pinned at check time, explicit allow + lab_nets, tls_insecure policy-only. |
| `py_sandbox.py` | 93 | Clean. AST import allowlist, rlimits, `-I` isolation, socket-stub sitecustomize. Nit: `open(` string-scan false-positives on comments — conservative. |
| `scan_builders.py` | 96 | **2 bugs** (below). |
| `creds_store.py` | 91 | Clean. fernet, 600 perms, placeholder substitution, redaction verified by doctor. |
| `kali_bank.py` | 115 | Clean. Read-only JSON lookup; 888 tools, 60 grammar slots. |

### scan_builders bugs — FIXED 2026-10-29 (Phase B step 6)
1. **nmap_quick/nmap_vuln default port spec was invalid.** `f"-p{ports or 'top'}"`
   emitted `-ptop`; nmap 7.95 rejects bare `-pT` and the word `top`. Fixed to
   `-pT:1-65535` (top 1000 ports) — verified with a live nmap run (rc=0).
2. **dirb builder dropped the wordlist.** `wlp = _wordlist(wordlist)` was resolved
   then never used — argv was `[dirb, target]`, so the `wordlist` param was dead.
   Fixed to `[dirb, target, wlp]` (dirb usage is `dirb <url> [wordlist]` — URL
   first, verified by running dirb with both arg orders).

Both fixed in `greyteam/scan_builders.py` AND synced to `convert-src/`, recompiled
via `convert_mcp_to_so.py`, hash-pinned, registry deduped to one enabled entry.
Compiled `.so` functionally verified: produces `-pT:1-65535` and passes the dirb
wordlist. Note: the post-fix `.so` sha256 is byte-identical to the pre-fix pin —
the shipped binary already reflected the fixed logic; the source `.py` had drifted
to `'top'`, so this was a latent source regression (would have broken on next
rebuild), not a live runtime fault.

## State (A.2)

- `data/greyteam.db`: 4 assessments (live-audit, matrix-final, matrix-live, T1 —
  all probe/lab data), 20 cards, 15 recon, 18 ASVS rows. No production data at risk.
- `credentials.enc.json` 652B (600) + `.greyteam-creds.key` 44B (600).
- `kali-bank.json` 850KB, `asvs-seed.json` 18 reqs.
- doctor.py: 12/12 ALL GREEN (dirs, policy 14/17, wordlists, asvs, binaries,
  kali-bank, store CRUD, creds roundtrip, sandbox no-egress, gates fail-closed,
  mcp 22/22 tools).
- pytest: 8/8 passed.

## Compiled .so (A.3)

- `cortexagent/mcp/greyteam.cpython-313-x86_64-linux-gnu.so` + 8 module .so — all
  present, MANIFEST.json sha256 pins match on-disk files.
- `mcp/src/greyteam/` = convert-pipeline minified+decommented copy (expected per
  spec item 7: fetch → minify → strip → Cython → hash-pin → register).
- `mcp_registry.json`: greyteam registered and ENABLED (live in this session).

## Environment inventory (matters for Phase B)

- **Present:** nmap, nikto, gobuster, ffuf, dirb, dig, whatweb, openssl, sqlmap,
  file, xxd, sha256sum, md5sum, strings.
- **Missing:** nuclei, wp-scan, subfinder, amass, bandwhich.
  → Phase B pipeline must be built around what's here (nmap/nikto/gobuster/ffuf/
  sqlmap/whatweb); nuclei/wp-scan are optional installs or fetch-on-demand.
- **PDF:** weasyprint, pandoc, chromium all present; `pdf_export.so` already in mcp.

## Report format to match (A.4, from UMGC CTCH 645 Project 4 final)

NIST SP 800-115-style structure the new report generator must reproduce:
Executive Summary → Rules of Engagement → Introduction → Penetration Testing →
Vulnerability Testing → Post-Testing Actions → Methodologies → Phase 1
Reconnaissance & Enumeration → Phase 2 Scanning & Analysis → Phase 3 Exploitation
→ Phase 4 Post-Exploitation → Appendices (evidence).

## Carry into Phase B

1. Fix the two scan_builders bugs first (one-line fixes).
2. Pipeline = orchestrator over existing MCP tools (assessment/card/recon/scan/
   execute) + new `webpentest` module + report generator (HTML → chromium/weasyprint PDF).
3. WordPress = template layer on the same pipeline (Phase C).

---
## Phase B/C/D completion (2026-10-29)
- **webpentest pipeline** (greyteam/webpentest.py): orchestrator over exec_gate +
  http_safe; CVSS v3.1 self-contained scorer (validated 0/2592 vs cvsslib).
- **WordPress add-on** (template layer, not separate system): 8 endpoint probes +
  9 WP_RULES via http_safe; do_wp wired into run() + MCP.
- **Report generator**: HTML + PDF (chromium --print-to-pdf), NIST SP 800-115 /
  UMGC CTCH 645 P4 structure.
- **MCP tools**: webpentest_run + report_generate (24 total), .so hash-pinned
  (4f67a362), 3-way disk=registry=manifest, enabled.
- **ROOT-resolution fix**: adaptive `_resolve_root()` (nearest ancestor with
  policy.json) in exec_gate/http_safe/store/webpentest — the compiled .so now
  resolves to mcp/ correctly.
- **E2E verified**: 127.0.0.1:8899 WP fixture → 5 scanners, 13 findings
  (1 CRIT 9.8 + 3 HIGH 7.3 + 9 MED 5.3), PDF 162KB/8pg valid, pytest 8/8.

## Phase E — CVE enrichment + untested branches (2026-10-29)

Two gaps closed on top of the working pipeline:

### 1. WP plugin CVE enrichment (honest scoring, real NVD IDs)
- **Before**: `WP-PLUGIN-OUTDATED` was a generic 9.8 (C:H/I:H/A:H) for any known plugin version — aggressive, not citable.
- **After**: a local CVE DB (`data/wp-cve-db.json`, 7 plugins / 9 NVD-verified CVEs) is loaded lazily (fail-open). When a plugin's version is below a CVE's `affected_lt` bound, a per-CVE finding fires with the CVE's **real** CVSS vector + score:
  - `WP-PLUGIN-CVE-{CVE-ID}` e.g. `WP-PLUGIN-CVE-CVE-2020-35489` (10.0, contact-form-7 <5.3.2), `CVE-2020-13126` (9.9), `CVE-2020-7109` (9.8).
  - Plugins with no in-range CVE (wordfence 7.8.0 vs CVE-2022-3144 lt=7.6.0) fall through to the honest `WP-PLUGIN-OUTDATED` 5.3 "version disclosed, no known CVE in local DB".
- DB is a JSON file at `ROOT/data/wp-cve-db.json` (installed in both source + mcp data dirs), not an embedded dict — the `.so` reads it from the deployment root, so updates don't require a recompile.

### 2. All scanner branches exercised (ssl, ffuf, sqlmap, nmap_vuln)
- **ssl bug found + fixed**: the `openssl s_client -batch` flag is invalid on OpenSSL 3.x (`s_client` doesn't accept `-batch` — it's an s_server/general option), so the branch errored "Unknown option: -batch". Fix: drop `-batch` and close stdin via `exec_gate.run(stdin_text="")` so s_client can't wait for interactive input on a self-signed cert. Verified: rc=0, cert captured, no hang.
- **ffuf**: added `-X GET` (was missing; ffuf defaults to GET but being explicit avoids the "no request method" edge).
- **sqlmap**: new builder `--batch -q` (non-interactive, quiet); wired `do_sqlmap` through `run()` + the MCP schema (default False).
- **E2E result** (all 9 scanners): 18 findings — 3 CRITICAL CVE findings (10.0/9.9/9.8) + 3 HIGH + 12 MEDIUM. Report: HTML 66KB + PDF 198KB/8 pages, all NIST SP 800-115 sections, CVE findings render with real scores.

### Verification
- pytest 8/8. CVSS scorer 0/2592 vs cvsslib. 3-way hash pinned (registry = disk = MANIFEST, all sibling `.so` match).
- Rebuild note: `convert greyteam` rebuilds the **whole module set** (greyteam + scan_builders + webpentest + exec_gate + http_safe + store + ...). The `greyteam.so` hash is stable across SSL edits because the fix lives in the sibling `scan_builders.so`/`webpentest.so` — the MANIFEST tracks each sibling hash, all confirmed disk==manifest.
