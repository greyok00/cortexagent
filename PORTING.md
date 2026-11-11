# PORTING.md — fork-side fixes awaiting owner decision to port upstream

Owner law (2026-11-10): sibling trees are never written. Fixes made in the
cortex-agent forks of shared code are recorded here so the owner can port them
upstream in their own session when they choose.

- **2026-11-10 greysearch vendored copy** — no code diverged from the live
  tree (boot-sync keeps it current). Parity checked for the searxng
  conf-fallback path (absent upstream AND here; both fall back identically).
- **2026-11-10 kbserver learn journal** — the vendored kbserver keeps its
  `learn-runs/` journal fork-local (`mcp/kbserver/learn-runs/`), because
  writing into `~/knowledge-ingestor/learn-runs/` would violate the
  no-overwrite law. CONSEQUENCE (known, deliberate): the fork's journal is
  separate from the portal's, so cross-agent double-scrape dedup does not
  exist between portal and cortex-agent learn topics. If cross-agent dedup is
  wanted, the upstream change is to move LEARN_RUNS to the shared
  `~/knowledge-ingestor/` root (owner's call; dbs/ stays shared today).
- **2026-11-10 locked-lane call timeouts** — cortex-agent-side fix (no
  upstream analog: the sibling trees don't have the locked lane). Per-lane
  tools/call ceilings (greysearch/knowledge 10 min, memory 2 min) after the
  owner reported persistent TIMEOUTs — a flat 60 s cap broke legitimate
  multi-minute deep runs.
