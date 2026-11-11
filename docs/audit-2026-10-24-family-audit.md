# GreyTeam — Deep Tool Audit (2026-10-24)

Scope: `kali_bank.py` (cortexagent) + the aida backend toolchain
(`~/aida/backend`, read via its Cython `.c` sources; `.so` binaries not
disassembled). Three parallel audit lanes: tool surface, supply chain,
execution reach. Basis for the full rewrite spec below.

## Verdict

**No telemetry, no backdoors, no persistence, no obfuscated payloads, no
hardcoded secrets.** The only third-party egress in the entire tree is
user-configured notification delivery (Telegram/Slack/SMTP, keys read from DB
config — nothing embedded). Deps are pinned, mainstream, no analytics packages,
no post-install hooks. The danger is **policy**, not trickery: raw-aida's
exec/HTTP surfaces are too permissive for a hardened offline agent tool.

## Findings (to fix or drop in the rewrite)

| # | Finding | Severity | Ref |
|---|---------|----------|-----|
| 1 | `execution_mode` FAIL-OPEN: settings-fetch error → fallback `"open"`; defaults `open` in container deploys; arbitrary commands unattended | 🔴 HIGH | `mcp_handlers.c:29746, ~30220`; `api/pending_commands.c ~20120` |
| 2 | `python_exec` = unrestricted Python in pentest container | 🔴 HIGH | `api/commands.c:1816` |
| 3 | `http_request`: zero SSRF controls (no allowlist, no link-local/metadata block, DNS-rebind unchecked, `verify_ssl` caller-controlled) | 🔴 HIGH | `container_service.c:16542, 27314` |
| 4 | Credentials **plaintext** in Postgres (token/password/cookie Text/JSONB) + substitution happens before logging → secrets likely in command history logs; MCP prints creds into LLM context | 🔴 HIGH | `models/credential.py:24-28` |
| 5 | `--localhost` host agent runs `bash -c` on the HOST (HMAC-token-gated Unix socket) | 🟡 MED | `host_agent.py:165-260` |
| 6 | Filter-mode approval = evadable 10-keyword substring (`echo rm` passes) | 🟡 MED | `pending_commands.c:20101` |
| 7 | Socket-proxy `EXEC:1` allows exec into ANY running host container (prefix filter `aida-,exegol-` is app-side only) | 🟡 MED | `docker-compose.yml:118-147` |
| 8 | Non-admin users can PUT `/system/settings/{key}` → loosen `mcp_http_network_policy` to `any` | 🟡 MED | `api/system.c`; `main.py:622` |
| 9 | Secrets/API keys passed in URL query params (`?api_key=`, JWT in WS query) → land in access logs | 🟡 MED | `auth.py:355`; `websocket.c` |
| 10 | `scan` templates f-string-interpolated unquoted into shell (moot vs bash, but pattern must die) | 🟢 LOW | `mcp_handlers.c:38933+` |
| 11 | `open_folder` prefix-comparison bug (`/workspace_evil` passes prefix `/workspace`); zip-slip possible in-container | 🟢 LOW | `api/system.c:1923`; `source_code.c:12545` |
| 12 | Rate limiter honors spoofable `X-Forwarded-For` (auth IP checks do not) | 🟢 LOW | `rate_limit.c:2735-2747` |
| 13 | Default DB creds `aida/aida` ship in example config (live `.env` is non-default, 0600; JWT refuses to run without generated key — good) | 🟢 LOW | `config.py:21-23` |
| 14 | `.so` tree not independently fresh-verifiable (one 2026-10-21 timestamp; venv 3.13 vs Docker 3.11 mismatch → shipped container never loaded them) | 🟢 LOW | build hygiene |

`kali_bank.py`: **CLEAN** — read-only JSON lookup, no subprocess/network/exec.
Note: pin the bank path in code (drop `KALI_BANK_FILE` env override) and
audit the bank JSON itself (external content feeding agent context).

## GreyTeam rewrite spec (hardened standard)

1. **Fail-closed everywhere.** No mode named "open"; default deny; settings
   fetch failure → deny, never allow. Admin-only settings writes.
2. **Sandboxed python_exec** — deny-by-default stdlib-module allowlist, no
   arbitrary code in "open" mode, resource + time caps.
3. **http_request with SSRF hardening** — URL/IP allowlist, block
   127.0.0.0/8, 169.254.0.0/16, RFC1918 unless explicit scope, DNS-pinned
   hosts, no raw `verify_ssl=false` escape.
4. **Credentials encrypted at rest** (fernet with a generated key file),
   `{{PLACEHOLDER}}` substitution AFTER logging the redacted form; never echo
   secret values into tool output or LLM context.
5. **No host mode.** Docker-only, via socket-proxy tightened beyond EXEC
   (exec allowed only inside the dedicated GreyTeam container — name-filtered
   at the proxy, not just app-side).
6. **kali_bank** stays pure-lookup; bank path pinned; bank JSON re-audited
   once as data.
7. **One source tree, one pipeline.** All modules authored clean-py (no
   compiled-binary mystery like aida's), converted through
   `~/cortexagent/scripts/convert_mcp_to_so.py` (fetch → minify+decomment →
   telemetry/external strip → Cython → sha256 hash-pin in
   `state/MANIFEST.json` → registered DISABLED → enable after hash verify).
8. **Log hygiene:** no query-string secrets (header-only auth on MCP),
   redaction middleware verified, response bodies excluded from access logs.
9. **Tool surface (target):** assessment/card/recon CRUD, ASVS grid,
   credentials (encrypted), execute (allowlisted, fail-closed), python_exec
   (sandboxed), http_request (SSRF-hardened), scan (argv-tokenized builders),
   ssl/subdomain/tech wrappers, kali_bank lookup. GreyTeam = the rewrite of
   execute/scan/http into DFIR-reach too (file acquisition, image hashing).