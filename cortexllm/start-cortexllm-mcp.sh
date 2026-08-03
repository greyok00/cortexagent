#!/bin/bash
# CortexLLM MCP Server Wrapper
# Sets PYTHONPATH so the MCP server imports the clean memory engine.
# Single memory source for CortexAgent.

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$HOME/cortexllm/repo"

exec python3 "$HOME/cortexllm/repo/cortexllm_mcp_server.py" "$@"