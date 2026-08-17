# CortexLLM — Memory Engine

Per-profile memory system for MCP-compatible AI agents. This is the clean core
that CortexAgent installs at `~/cortexllm/repo/` and shares across platforms.

## What's here (the memory engine)

| File | Purpose |
|------|---------|
| `cortexllm_db.py` | SQLite storage layer (hot/cold tiers) |
| `cortexllm_vector.py` | BM25 vector search |
| `cortexllm_graph.py` | Deterministic knowledge graph |
| `cortexllm_ontology.py` | Rule-based ontology / taxonomy |
| `cortexllm_models.py` | Pydantic data models |
| `cortexllm_mcp_server.py` | MCP server (read / write / search / clear) |
| `cortexllm_bridge.py` | Direct DB bridge for in-process agents |
| `memory_manager.py` | 3-tier manager + session resume |
| `cold_distiller.py` | Cold-tier distillation |
| `loop_guard.py` | Failure / loop detection |
| `model_router.py` | Model routing |
| `protect-memory.py` | Hot-memory cap (cron) |
| `migrate_to_sqlite.py` | Migration utility |

## Data lives elsewhere (never in this repo)

| Path | Holds |
|------|-------|
| `~/.config/cortexllm/cortexllm.db` | The shared SQLite DB |
| `~/.cortexllm/` | Runtime: `memory.sock`, daemon, logs |

## Run

```bash
# MCP server over stdio
python3 cortexllm_mcp_server.py

# Via wrapper (sets PYTHONPATH)
./start-cortexllm-mcp.sh
```

## Dependencies

- `mcp` (MCP SDK) and `pydantic` — standard Python packages.
- No platform ties. No coupling to any external agent framework.