# cortexagent Extraction Manifest

The complete copy map for the cortexagent build. Every source path is read-only against
its origin tree. Everything not listed here — and especially everything on the never-copy
list below — is never read or copied into cortexagent.

Model: ~/qwen3.8-27b/Qwen3.8-27B-UD-Q3_K_XL.gguf (CPU-only) with
~/qwen3.8-27b/mmproj-Qwen3.8-27B-f16.gguf (CPU/RAM). Port 11811. All settings
are compiled constants.

## Copy map

| cortexagent module | Source files (read-only) | Transform |
|---|---|---|
| core/loop.py | cortexagent lib/react_loop.py | port, trim post-processing chain |
| core/llm.py | cortexagent lib/overseer.py — only _query_llm, _query_llm_with_tools, _parse_tool_calls, HTTP plumbing | re-point 127.0.0.1:11436 to cortexagent port; strip all cloud lanes |
| core/registry.py | cortexagent lib/tool_registry.py — only register_tool, list_tools, get_schema, execute_tool, _run_command, _schema, check_trust | drop all specialty tools and MCP tool-def loop |
| core/state.py | cortexagent lib/pre_flight_gate.py::classify_intent | port the single function |
| core/subagent.py | cortexagent lib/overseer.py::_spawn_subagent | port; retarget to same local model, no cloud lane |
| tools/files.py | none | authored fresh: read, write, edit, list |
| tools/search.py | none | authored fresh: glob + grep |
| tools/web.py | cortexagent lib/adapters/base.py + lib/adapters/searxng_adapter.py (SearXNG lanes) + greyresearcher patchright_scraper.py, searxng_integrated.py, searx_fallback.py | combined backend: greysearch search lane, greyresearcher pipeline |
| tools/distill.py | greyresearcher page_clean.py, relevance.py, guide_scrub.py | direct port |
| tools/web_optional/*.py | greyresearcher greyresearcher_publisher.py, greyresearcher_site_builder.py, pdf_export.py, photos.py, pipeline_sites.py, site_render.py, site_guardrails.py | direct port, OPTIONAL (outside acceptance gates) |
| tools/browser.py | cortexagent lib/browser_control.py, lib/browser_tools.py | port; shared single Chromium instance with web tool |
| tools/browser_console.py | cortexagent lib/browser_console.py | port |
| tools/kali_bank.py | cortexagent lib/kali_bank.py | direct port |
| tools/docs.py | cortexagent lib/document_adapter.py, lib/pdf_knowledge.py, lib/fast_extract.py | port as parse_document |
| tools/charts.py | cortexagent lib/charts.py | direct port |
| services/memory.py | cortexagent lib/memory_daemon.py, lib/memory_thin.py | port; session name cortexagent; storage under cortexagent/state/ |
| services/scheduler.py | cortexagent lib/scheduler/store.py, lib/scheduler/recovery.py, lib/scheduler/ui.py | port |
| model/server.py | none | authored fresh: the engine launcher, compiled constants |
| model/system-prompt.txt | none | authored fresh: minified system prompt, editable plain text |
| ui/app.py | none (cortexagent lib/statusline.py, lib/status_ticker.py read for rail pattern only) | authored fresh: Textual TUI, 3-box rail, splash per spec |
| ui/splash art | none | glyph tables for GREYAGENT banner + devil art (see plan Task 5) |
| vendor/slimtoken | ~/slimtoken | copied whole, code mode, renamed strings only |
| vendor/patchright | installed patchright package + its Chromium | copied in-tree, no runtime pip |

## Never copied — hard exclusions

- The whole cortex/ TypeScript tree (495MB).
- All MCP proxies and servers: mcp_client.py, lazy_mcp_proxy.py, converted_mcp_tools.py,
  patchright_chrome_mcp.py, both greyresearcher MCP wrappers (converted to direct call-ins).
- The greysearch stack: greysearch_headless.py, all lib/scraper/greysearch_*.py (superseded
  by greyresearcher), lib/scraper/course_*, guide_distill, intern_model.
- Telemetry and observability: token_tracker.py, observability.py.
- All diagnostics and service plumbing: doctor.py, chain_diagnostic.py, errorlog.py,
  hardening_status.py, session_coordinator.py, event_feed.py, heartbeat_service.py,
  daemon.py, searxng_engine_test, scraper_health.
- download.py, download_verified.py (web_fetch covers it).
- All LLM-provider surfaces: add_llm_provider, query_llm tool, cloud lanes, any
  provider-domain endpoint.
- cve_intel.py (user has a separate tool). siem_bridge.py, soar_playbooks.py (user has a
  separate tool).
- skills.py, alert_popup.py, popup_themes.py, tkinter_strip/.
- Output-shaping chain: beautify.py, humanize.py, humanizer.py, post_processor.py,
  output_frame.py (dropped; system prompt handles output discipline).
- actions/ (send_email, send_text, open_pdf, open_url, fetch, run, earnings_tick,
  system_status).
- rag_query and ingest_domain — deferred, excluded from launch (come back later together
  with the research-library combination and coding_practices migration).
- rag/rag_query, ingest_domain surfaces in tool_registry.
- overseer/dashboard (web), .SAFETY_QUICK_REF, all .backup/.bak files, all __pycache__,
  prebuilt .so caches, research/, addons/, extensions/, logs/, scans/, dist/, egg-info,
  install scripts (install.sh, relaunch-check, ps1 scripts), node_modules.
- No AGENTS.md, no CLAUDE.md, no harness/config markdown enters cortexagent.

## Containment rule

Every runtime write stays inside ~/cortex-agent/. Source modules writing to
home-dir paths (e.g. ~/.cortexagent/memory) are remapped to cortexagent-relative paths
during the rename pass and verified at every gate.

## Naming rule

cortexagent -> cortexagent, cortex -> grey, CORTEXAGENT_ -> CORTEXENGINE_ across identifiers,
strings, paths, env vars, config keys. Word-boundary matching; legitimate collisions are
resolved manually via transform exceptions. Word "cortex", "cortexagent", plus provider
names (openai, anthropic, amazon, microsoft, apple, gemini) must appear nowhere in the
final tree (docs/manifest.md and tools/audit.py excepted as the audit's own definition
points).