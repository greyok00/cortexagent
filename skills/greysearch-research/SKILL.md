---
name: greysearch-research
description: Use when doing live web research, scraping a known page, or filling a knowledge gap with a deep search run - covers the always-on greysearch lane (baked in)
---

# Greysearch Research

## Overview

**Core principle:** greysearch lane tools are always standing by (baked in, cannot be disabled). Fire a deep run once, in the background, and report the run id — never loop retuned retries while it is active.

## The Tools

**mcp_greysearch_mcp_greysearch** — the one research entry point.

- Default flow is a deep run: search lanes, page scraping, and a Master Guide file you read when it finishes.
- Call it ONCE with `background=true` (the default). It returns a run_id immediately. The finished digest (pages, findings, guide path, failed lanes) arrives via **mcp_greysearch_health**. Do not poll in a tight loop and do not re-call greysearch while a run is active.

**Modes you actually choose between:**

- Normal research: pass a `query`. Long questions get decomposed into short keyword searches automatically — never send long-tail queries yourself.
- Known page: pass `url` instead of `query` for one synchronous, fast scrape with the full payload (tables, headings, links, images, code).
- Ranked results only: set `scrape_all=false` when you just need sources ranked, with no scraping or guide.
- Off-topic drift: use `pinned_sources` with exact primary-domain URLs; they are fetched first and rank ahead of search results.

**Budgets:** tiers brief/standard/deep/report map to page and second caps. Explicit `max_results`/`max_seconds` override the tier. Default is 10 pages / 300 seconds.

## Shared Infrastructure

The browser-slot pool is shared infra. A run holds its browser lane for its whole lifetime — other clients wait for a free slot. Fire-and-forget means exactly that: start it, go do other work, come back when you have something useful to do with the results.

## After the Run

- Read the Master Guide file from the digest's guide path before citing anything.
- Thin runs report what failed or was skipped — they never pretend to be complete. Say so downstream.
- For durable, offline recall, ingest what you learned into the knowledge base (see the knowledge-rag skill).
