#!/bin/bash
# CortexLLM MCP Server Wrapper
# Sets PYTHONPATH so the MCP server imports the clean memory engine.
# Single memory source for CortexAgent.

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$HOME/cortexllm/repo/legacy:$HOME/cortexllm/repo"

if [ -f "$HOME/cortexllm/repo/cortexllm_mcp_server.py" ]; then
    exec python3 "$HOME/cortexllm/repo/cortexllm_mcp_server.py" "$@"
elif [ -f "$HOME/cortexllm/repo/legacy/cortexllm_mcp_server.py" ]; then
    exec python3 "$HOME/cortexllm/repo/legacy/cortexllm_mcp_server.py" "$@"
elif [ -f "$HOME/cortexagent/memory/mcp_server.py" ]; then
    exec python3 "$HOME/cortexagent/memory/mcp_server.py" "$@"
else
    echo "no cortexllm MCP server found" >&2
    exit 1
fi