"""lib.minify — pure-stdlib LLM request minification pipeline.

The single extraction seam for the standalone plugin (Phase D):
``minify_request(body, cfg)`` is a PURE function taking a plain dict + a
``MinifyConfig``. It imports nothing from ``lib.config`` / ``lib.control`` /
socket code. Build ``MinifyConfig`` from env vars at the call site.

Public API:
    from lib.minify.pipeline import minify_request, MinifyConfig, MinifyStats
"""
from lib.minify.pipeline import (  # noqa: F401
    MinifyConfig,
    MinifyStats,
    minify_request,
    minify_chunked_first_event,
)