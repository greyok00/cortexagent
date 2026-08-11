#!/bin/bash
# CortexLLM MCP Server Wrapper
# Sets PYTHONPATH so the MCP server imports the clean memory engine.
# Single memory source for CortexAgent.
#
# Resolution order (2026-08-11, post-v0.4.0):
#   1. ~/cortexllm/repo/cortexllm/mcp_server.py  — canonical new package
#   2. ~/cortexllm/repo/legacy/cortexllm_mcp_server.py — pre-v0.4.0 fallback
#   3. ~/cortexagent/memory/mcp_server.py  — last-resort in-tree

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$HOME/cortexllm/repo/cortexllm:$HOME/cortexllm/repo/legacy:$HOME/cortexllm/repo"

if [ -f "$HOME/cortexllm/repo/cortexllm/mcp_server.py" ]; then
    exec python3 "$HOME/cortexllm/repo/cortexllm/mcp_server.py" "$@"
elif [ -f "$HOME/cortexllm/repo/legacy/cortexllm_mcp_server.py" ]; then
    exec python3 "$HOME/cortexllm/repo/legacy/cortexllm_mcp_server.py" "$@"
elif [ -f "$HOME/cortexagent/memory/mcp_server.py" ]; then
    exec python3 "$HOME/cortexagent/memory/mcp_server.py" "$@"
else
    echo "no cortexllm MCP server found" >&2
    exit 1
fi