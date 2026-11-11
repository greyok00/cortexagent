---
name: knowledge-rag
description: Use when answering from offline knowledge, saving a solved incident, or when a knowledge-base search comes up empty - covers the baked-in knowledge lane tools
---

# Knowledge RAG

## Overview

**Core principle:** the knowledge base is offline recall. Search it FIRST, before web research, whenever the question might already be covered. Empty results mean escalate — never guess.

## The Tools

**mcp_knowledge_kb_search** — always first. Returns records with id, url, and a confidence band:

- **firm** — may cite as-is.
- **soft** — verify before relying on it; soft results can be token-adjacent misses.
- **empty** — not covered. Escalate to `kb_learn_topic` or live research. Never fabricate the missing answer.

**mcp_knowledge_kb_learn_topic** — fires a greysearch deep run in a background worker and ingests quality-gated pages plus a Master Guide into the db. Fire it ONCE, then watch **kb_learn_status** like with any background run.

**mcp_knowledge_kb_ingest_text** — records solved incidents and curated material verbatim, with provenance (source, url). No auto-gate: this is the owner-curated lane. When a debugging session ends with a real root cause and fix, this is where it goes. Companion record tool: `kb_get` for full text of known record ids.

## Reference

Full tool reference for the knowledge lane: `mcp/kbserver/MCP_TOOLS.md` in the repo (decision order, database list, quality gate, provenance rules).

## Hygiene

- Ingest in sections or as whole docs with real provenance — a db is only as trustworthy as what it recorded.
- Use `kb_jobs` to audit ingest history before trusting a thin db, and `kb_rebuild` after mass edits.
