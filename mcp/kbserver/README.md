# kbserver

Offline RAG and ingestion MCP server: a permanent, local document library that
an agent can search, fill, and cite from. It is the counterpart to the bundled
web-research tool: the
pair forms a self-filling knowledge loop.

The server speaks the Model Context Protocol over stdio, so any MCP client can
attach it with a single command.

## What each tool does

| Tool | Purpose |
|---|---|
| `kb_search` | Semantic + keyword search over one library. Results carry a confidence band: `firm` = cite directly, `soft` = verify first. An empty result means *not covered*, never guess. |
| `kb_get` | Full text of specific record ids. |
| `kb_ingest_text` | Verbatim ingest of local text or markdown you trust (solved incident notes, command references, master guides) with provenance recorded. No quality gate by design. |
| `kb_ingest_urls`, `kb_ingest_pdf` | Fetch web pages (politely, spaced apart) or extract text from local PDFs, chunk, embed, and append. |
| `kb_learn_topic` | The auto-learn loop: runs a deep web-research pass on a topic, applies the quality gate to every page, then ingests the admitted pages section by section plus the synthesized Master Guide. Use when `kb_search` returns nothing useful. |
| `kb_jobs` | Ingest history for a library: states, parked items with reasons, duplicates. |
| `kb_rebuild` | Re-embed a whole library after bulk edits. |
| `kb_status`, `kb_delete` | List libraries with index stats; delete one (requires `confirm=1`). |

Embeddings run on CPU through a local MiniLM ONNX model; `kb_ingest_text`,
`kb_ingest_urls`, and keyword search all work without it, and ingest jobs that
need embeddings park until the model is present.

## The auto-learn loop

When `kb_search` cannot answer, `kb_learn_topic` closes the gap:

1. the web-research tool runs a deep research pass (search lanes, headless page render,
   synthesis into a cited Master Guide).
2. Every fetched page passes a deterministic quality gate before ingest:
   official documentation domains and doc-shaped paths score up, content
   density scores up, forum/news/shopping/download pages, thin pages, and
   subscription walls score down. Pages below the admit threshold are
   rejected and every rejection is reported with its reason, so nothing
   silently disappears and nothing invented enters the library.
3. `robots.txt` is checked before extraction.
4. Ingested records carry full provenance: source URL, origin, and the gate
   verdict string.

After a run, call `kb_search` again: the knowledge is now permanently local
and answerable offline.

## Wiring it up

The CortexAgent install script and `config/mcp.json.template` wire
`kbserver.py` in automatically (opt out with `CORTEXAGENT_KBSERVER=0`). For
any other MCP client, add a stdio server entry pointing at this file:

```json
{
  "mcpServers": {
    "kbserver": {
      "command": "python3 /path/to/kbserver/kbserver.py"
    }
  }
}
```

When a greysearch checkout is available at `~/greysearch` (or wherever
`CORTEXAGENT_GREYSEARCH_MCP` points), `kb_learn_topic` imports its research
engine in-process. Without the checkout the server still answers from whatever
the library already holds, and a topic-learning request returns an honest
error naming the missing path.

## Layout

| File | Contents |
|---|---|
| `kbserver.py` | The MCP server: tool registry, JSON-RPC stdio loop, dispatch. |
| `kbcore.py` | Storage: chunking, hashes, duplicate detection, embed + search. |
| `jobs.py` | Background ingest jobs, model state, parked-item journal. |
| `extractors.py` | Web page fetching, robots.txt politeness, text/code extraction. |
| `kbserver_patch.py` | The auto-learn bridge: quality gate, `kb_ingest_text`, `kb_learn_topic`. |
| `MCP_TOOLS.md` | Condensed tool-selection guide for the model reading it at runtime. |
