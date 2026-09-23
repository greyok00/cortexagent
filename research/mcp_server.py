#!/usr/bin/env python3
"""research — MCP stdio server. Real research mode for cortexagent.

Tools: research_search, research_scrape, research_deep, research_sites.
Local-first: SearXNG on 127.0.0.1, scraper keys from a chmod-600 env file,
keys never appear in tool results (see keys.py redact()).
Register: python3 ~/cortexagent/research/mcp_server.py  (stdio, ~/.mcp.json)
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import keys as research_keys  # noqa: E402
import pipeline  # noqa: E402

TOOLS = [
    {"name": "research_search", "description":
     "Search via local SearXNG (JSON API). Use INSTEAD of generic web_search "
     "when you need real sources: returns deduped results tagged with domain "
     "and tier (primary = cite-first). Params: query (required), category "
     "(general|law|osint|dfir|programming|business), max_results, "
     "time_range (day|week|month|year), language.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "category": {"type": "string"},
         "max_results": {"type": "integer"},
         "time_range": {"type": "string"}, "language": {"type": "string"}},
         "required": ["query"]}},
    {"name": "research_scrape", "description":
     "Fetch one URL and return its readable text (markdown-ish), with "
     "domain/tier metadata and fetch date. Firecrawl fallback (local key) "
     "for JS-heavy pages. Use after research_search, prefer primary-tier domains.",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string"}, "max_chars": {"type": "integer"}},
         "required": ["url"]}},
    {"name": "research_deep", "description":
     "Full research pipeline for one question: multiple searches across "
     "categories (auto-selected), diverse-domain selection, page fetching, "
     "fact extraction WITH per-fact source URLs, and an unverified list for "
     "claims no source supports. Returns a cited brief.",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string"},
         "categories": {"type": "array", "items": {"type": "string"}},
         "max_pages": {"type": "integer"}},
         "required": ["question"]}},
    {"name": "research_sites", "description":
     "The curated reputable-site registry: which domains to trust per "
     "category (tier primary/secondary + notes). Consult BEFORE searching "
     "so queries target primary sources.",
     "inputSchema": {"type": "object", "properties": {
         "category": {"type": "string"}}}},
]


def _redacted(obj):
    return json.loads(research_keys.redact(json.dumps(obj, default=str)))


def dispatch(name, args):
    if name == "research_search":
        return _redacted(pipeline.search(
            args["query"], category=args.get("category", "general"),
            max_results=int(args.get("max_results", 12)),
            time_range=args.get("time_range", ""),
            language=args.get("language", "")))
    if name == "research_scrape":
        return _redacted(pipeline.scrape(
            args["url"], max_chars=int(args.get("max_chars", 20000))))
    if name == "research_deep":
        return _redacted(pipeline.deep(
            args["question"], categories=args.get("categories"),
            max_pages=int(args.get("max_pages", 8))))
    if name == "research_sites":
        cat = args.get("category", "")
        cats = pipeline.SITES["categories"]
        data = {c: e for c, e in cats.items() if not cat or c == cat}
        if cat and cat not in cats:
            return {"ok": False, "error": f"unknown category {cat}",
                    "available": list(cats)}
        return {"ok": True, "categories": data,
                "excluded": pipeline.SITES.get("excluded", [])}
    raise ValueError(f"unknown tool {name}")


def reply(rid, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        m["error"] = error
    else:
        m["result"] = result
    sys.stdout.write(json.dumps(m) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("method") == "initialize":
            reply(req["id"], {"protocolVersion": "2024-11-05", "capabilities":
                              {"tools": {}}, "serverInfo":
                              {"name": "research", "version": "1.0.0"}})
        elif req.get("method") == "notifications/initialized":
            pass
        elif req.get("method") == "tools/list":
            reply(req["id"], {"tools": TOOLS})
        elif req.get("method") == "tools/call":
            try:
                r = dispatch(req["params"]["name"],
                             req["params"].get("arguments", {}))
                reply(req["id"], {"content": [{"type": "text",
                                               "text": json.dumps(r)}]})
            except Exception as e:
                reply(req["id"], error={"code": -32000,
                                        "message": research_keys.redact(f"{e}")})
                traceback.print_exc(file=sys.stderr)
        elif "id" in req:
            reply(req["id"], error={"code": -32601,
                                    "message": "method not found"})


if __name__ == "__main__":
    main()