"""cortexllm — CortexLLM storage and processing layer.

This package provides the persistent storage and processing layer for
CortexAgent's memory, graph, vector search, and ontology systems.

Components:
  - cortex_tokenizer: BM25 tokenizer (Cython + Python fallback)
  - cortexllm_db: SQLite memory backend (hot/warm/cold tiers)
  - cortexllm_graph: Graph extraction + BFS traversal
  - cortexllm_vector: BM25 inverted-index search
  - cortexllm_ontology: Ontology operations (categorize, taxonomy, gaps, tags)
  - memory_manager: Unified memory manager (combines all tiers)
  - cold_distiller: Cold storage distillation
  - cortexllm_bridge: Bridge layer to external systems
"""
from __future__ import annotations

# ── Lazy imports for performance ─────────────────────────────────────────────
def __getattr__(name):
    """Lazy-load cortexllm submodules on first access."""
    import importlib
    
    modules = {
        "MemoryManager": "cortexllm_db",
        "GraphStore": "cortexllm_graph",
        "VectorStore": "cortexllm_vector",
        "OntologyEngine": "cortexllm_ontology",
        "Tokenize": "cortex_tokenizer",
    }
    
    if name in modules:
        mod = importlib.import_module(f".{modules[name]}", __name__)
        return getattr(mod, name)
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MemoryManager",
    "GraphStore",
    "VectorStore",
    "OntologyEngine",
    "Tokenize",
]
