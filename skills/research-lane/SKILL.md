---
name: research-lane
description: Use when the model needs to know how to route research work in cortex-server - deep web research runs through the baked-in greysearch lane, persistent knowledge through the baked-in knowledge lane; there is no separate research server.
---

# research-lane

 cortex-server has ONE research surface: the **greysearch lane**, baked in as
 an always-spawning capability from repo-vendored, sha256-pinned sources. The
 old "research" MCP entry never worked as a spawned server (it is an argparse
 CLI, not a stdio server) and was retired on 2026-11-10 — do not attempt to
 call a research server; the compiled CLI in `mcp/research.*.so` exists only
 for offline `--help` consultation.

## How to route research

1. **Open-ended / multi-source investigation** → the greysearch tool
   (`mcp_greysearch_mcp_greysearch`). Long questions are decomposed for you;
   deep runs scrape pages and write a Master Guide. Fire it ONCE with
   `background` unset (default) and check `mcp_greysearch_mcp_greysearch_health`
   for the digest. Do NOT re-call greysearch while a run is active — re-calling
   with tweaked arguments while health shows a live run is the retry loop this
   design exists to kill.
2. **Persisted, citable knowledge** → the knowledge lane (`mcp_knowledge_*`):
   see the `knowledge-rag` skill for search/learn/ingest discipline.
3. **A known page** → greysearch with `url` instead of `query` (fast, sync,
   full payload).
4. Both lanes run on the shared local SearXNG (:8888) and a shared browser
   pool — one session owns a lane at a time; long searches are decomposed into
   short keyword queries. See `greysearch-research` for the full playbook.
