# knowledge-ingestor MCP — tool reference for the model (2026-11-08, funnel build)

## When to use what (decision order)
1. `kb_search(db=<db>, query=...)` FIRST, every unfamiliar-toolchain task.
   - firm/soft bands in results: firm = cite directly; soft = verify or get.
2. Empty or all-soft + task still needs knowledge → **`kb_learn_topic`**
   (FIRE-AND-FORGET like greysearch: returns run_id + state=running at once;
   an isolated one-shot worker runs the greysearch deep run → robots gate →
   trafilatura/selectolax extraction → quality gate → ingest + guide sections).
   Then watch **`kb_learn_status`** (one status call: running/done/failed, records
   added, admitted/rejected and why). Do NOT re-fire a db that has a running
   learn; do NOT re-call with tweaked args while its run is active — that is
   the retry loop this lifecycle exists to kill. A run takes ~5-10 min.
   `background=false` keeps the legacy blocking lane. Never leave a learn run
   past its wall clock: kbserver reaps + the worker self-kills and both write
   a failed digest. SERP drifting to junk? Re-fire with `pinned_sources`.
3. Exact official pages known → **`kb_ingest_urls`** (surgical backfill; also
   the way to CREATE a new db: ingest first, then kb_learn_topic on it).
4. Local text you trust (solved incident, owner rules) → **`kb_ingest_text`**
   (verbatim, provenance-recorded, no gate).
5. After mass edits/seeded ingest → `kb_rebuild` to re-embed the whole db.

## Databases
- `reference` (1,800+ records) — docs, aapt2, gradle, python PEPs, security
- `pentest` (12,000+ records) — offensive security corpus
- `heuristics` — owner-verified rules (aapt2/gradle HARD RULES live here)
- `linux-hardening` — sysctl/SSH/auditd/CIS baselines (Arch + guides)
- `firewalls` — nftables/iptables/firewalld rule craft
- `malware-defense` — ClamAV/LMD/rkhunter/rootkit defense
- `endpoint-security` — EDR/XDR, Defender-for-Endpoint, host detection
- `python-security` — secure coding, bandit, secrets, pip secure installs
- `case-docs`, `ports`, `gamebuild` — scoped case files
- Create new via kb_ingest_urls (first ingest initializes the db dir).

Learn-run lifecycle mirrors greysearch exactly:
`kb_learn_topic` (fire once) → `kb_learn_status` (digest list) → `kb_search`
(to USE what was learned). Runs live in `learn-runs/<run_id>/` (request,
worker log, digest.json).

## Quality gate (auto-learn only; ingest_text bypasses by design)
+3 official doc domains (developer.android.com, docs.gradle.org, …)
+2 /docs /reference /guide /api paths · +1+ density by word count
+4 canonical stackoverflow question w/ long content (exempted forum rule)
-2 forums/news/coupons/download paths · -3 reddit/medium/dev.to/quora
-2 thin (<60w) · -3 junk-signature pages (subscribe/buy-now walls)
Admit threshold: score ≥ 3. Every rejection is reported with its reason.

## Provenance
Every record carries: source url, site or guide origin, gate verdict string.
`kb_get` with ids → full text; `kb_jobs` → ingest history.
