# Claude Code Environment Variables

> Source: https://code.claude.com/docs/en/env-vars.md
> Pulled 2026-08-11

## Setting Environment Variables

**In your shell** (lasts for the terminal session):

```bash
export API_TIMEOUT_MS="1200000"
claude
```

**In settings files** (applies every time `claude` runs):

```json ~/.claude/settings.json
{
  "env": {
    "API_TIMEOUT_MS": "1200000",
    "BASH_DEFAULT_TIMEOUT_MS": "300000"
  }
}
```

## Precedence Rules

1. **Settings file `env` over shell**: Values in `env` block replace shell values at startup
2. **Environment variables over settings keys**: `ANTHROPIC_MODEL` overrides the `model` setting
3. **To override an unsettable variable**: Set it to empty string `"CLAUDE_CODE_USE_VERTEX": ""`
4. **Special boolean rules**: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`,
   `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING`, `CLAUDE_CODE_TMUX_TRUECOLOR`,
   `FALLBACK_FOR_ALL_PRIMARY_MODELS`, `IS_DEMO` only check if set (any non-empty
   value enables).

## Variables Reference

| Variable | Purpose |
| :--- | :--- |
| `ANTHROPIC_API_KEY` | API key sent as `X-Api-Key` header. Overrides subscription in `-p` mode. |
| `ANTHROPIC_AUTH_TOKEN` | Custom value for `Authorization` header |
| `ANTHROPIC_AWS_API_KEY` | Workspace API key for Claude Platform on AWS |
| `ANTHROPIC_AWS_BASE_URL` | Override Claude Platform on AWS endpoint URL |
| `ANTHROPIC_AWS_WORKSPACE_ID` | Required for Claude Platform on AWS |
| `ANTHROPIC_BASE_URL` | Override API endpoint for proxy/gateway routing |
| `ANTHROPIC_BEDROCK_BASE_URL` | Override Amazon Bedrock endpoint URL |
| `ANTHROPIC_BEDROCK_MANTLE_BASE_URL` | Override Amazon Bedrock Mantle endpoint URL |
| `ANTHROPIC_BEDROCK_REGION_PREFIX` | Cross-region inference profile prefix |
| `ANTHROPIC_BEDROCK_SERVICE_TIER` | Amazon Bedrock service tier |
| `ANTHROPIC_BETAS` | Comma-separated list of `anthropic-beta` header values |
| `ANTHROPIC_CUSTOM_HEADERS` | Custom headers to add to requests |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | Custom model ID for `/model` picker |
| `ANTHROPIC_DEFAULT_FABLE_MODEL` | Model ID the `fable` alias resolves to |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Model ID the `haiku` alias resolves to |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Model ID the `opus` alias resolves to |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Model ID the `sonnet` alias resolves to |
| `ANTHROPIC_FOUNDRY_API_KEY` | API key for Microsoft Foundry |
| `ANTHROPIC_FOUNDRY_AUTH_TOKEN` | Bearer token for Microsoft Foundry |
| `ANTHROPIC_FOUNDRY_BASE_URL` | Full base URL for Microsoft Foundry |
| `ANTHROPIC_FOUNDRY_RESOURCE` | Microsoft Foundry resource name |
| `ANTHROPIC_MODEL` | Name of the model setting to use |
| `ANTHROPIC_SMALL_FAST_MODEL` | **[DEPRECATED]** Name of Haiku-class model for background tasks |
| `ANTHROPIC_VERTEX_BASE_URL` | Override Google Cloud's Agent Platform endpoint URL |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project ID |
| `ANTHROPIC_WORKSPACE_ID` | Workspace ID for workload identity federation |
| `API_FORCE_IDLE_TIMEOUT` | Override 5-minute body idle timeout. `0` to disable. |
| `API_TIMEOUT_MS` | Timeout for API requests. **Default: 600000** (10 min). |
| `AWS_BEARER_TOKEN_BEDROCK` | Amazon Bedrock API key |
| `BASH_DEFAULT_TIMEOUT_MS` | Default timeout for bash commands. **Default: 120000** (2 min). |
| `BASH_MAX_OUTPUT_LENGTH` | Max characters of bash output read back. **Default: 30000**. |
| `BASH_MAX_TIMEOUT_MS` | Maximum timeout model can set. **Default: 600000** (10 min). |
| `CLAUDECODE` | Set to `1` in subprocesses Claude Code spawns (detects in-claude env) |
| `CLAUDE_AFK_COUNTDOWN_MS` | Milliseconds before auto-continue countdown |
| `CLAUDE_AFK_TIMEOUT_MS` | Milliseconds idle before unanswered dialog auto-continues |
| `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS` | `1` to disable built-in subagent types |
| `CLAUDE_AGENT_SDK_MCP_NO_PREFIX` | `1` to skip `mcp__<server>__` prefix on SDK MCP tools |
| `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` | Stall timeout for background subagents. **Default: 600000**. |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | Set percentage (1-100) to trigger compaction |
| `CLAUDE_AUTO_BACKGROUND_TASKS` | `1` to force-enable automatic backgrounding |
| `CLAUDE_AX_SCREEN_READER` | `1` for screen-reader friendly output |
| `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR` | Return to original cwd after each Bash command |
| `CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS` | Byte-level streaming idle watchdog timeout |
| `CLAUDE_CLIENT_PRESENCE_FILE` | Path to file indicating screen unlock state |
| `CLAUDE_CODE_ACCESSIBILITY` | `1` to keep native terminal cursor visible |
| `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` | `1` to load memory files from `--add-dir` directories |
| `CLAUDE_CODE_ALT_SCREEN_FULL_REPAINT` | `1` to repaint entire screen on every frame |
| `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT` | `1` to send effort parameter with every request |
| `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` | Interval to refresh credentials |
| `CLAUDE_CODE_ARTIFACT_AUTO_OPEN` | `0` to stop opening browser for new artifacts |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | `0` to omit attribution block from system prompt |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Auto-compact window in tokens (100000-1000000) |
| `CLAUDE_CODE_AUTO_CONNECT_IDE` | Override automatic IDE connection |
| `CLAUDE_CODE_AWS_CHAIN_RESOLVE_TIMEOUT_MS` | Time to wait for AWS credential chain. **Default: 60000**. |
| `CLAUDE_CODE_BRIDGE_SESSION_ID` | Session ID for active Remote Control connection |
| `CLAUDE_CODE_CERT_STORE` | Comma-separated CA certificate sources. **Default: `bundled,system`**. |
| `CLAUDE_CODE_CHILD_SESSION` | `1` in subprocesses spawned via Bash/PowerShell/Monitor |
| `CLAUDE_CODE_CLIENT_CERT` | Path to client certificate for mTLS |
| `CLAUDE_CODE_CLIENT_KEY` | Path to client private key for mTLS |
| `CLAUDE_CODE_CLIENT_KEY_PASSPHRASE` | Passphrase for encrypted client key |
| `CLAUDE_CODE_DEBUG_LOGS_DIR` | Override debug log file path |
| `CLAUDE_CODE_DEBUG_LOG_LEVEL` | Minimum log level (`verbose`, `debug`, `info`, `warn`, `error`) |
| `CLAUDE_CODE_DISABLE_1M_CONTEXT` | `1` to disable 1M context window support |
| `CLAUDE_CODE_SIMPLE` | Set by `--bare`; disables hooks/skills/plugins/MCP/CLAUDE.md |
| `CLAUDE_CODE_SKIP_PROMPT_HISTORY` | Disables session persistence in any mode |
| `CLAUDE_CODE_SAFE_MODE` | Set by `--safe-mode`; disables all customizations |
| `CLAUDE_CODE_FORWARD_SUBAGENT_TEXT` | Forward subagent text/thinking in output stream |
| `CLAUDE_CODE_DEBUG_LOGS_DIR` | Override debug log file path |
| `MCP_TIMEOUT` | MCP server connection timeout (30s default) |
| `CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX` | Prefix for auto-generated Remote Control names |
| `CLAUDE_AX_SCREEN_READER` | Override for screen-reader mode |
| `IS_DEMO` | CortexAgent brand env var (set in bin/cortexagent) |

## Numeric Values

Numeric variables accept scientific notation and digit separators:
- `2e3` → 2000
- `64_000` → 64000

Before v2.1.211, these could silently set smaller values (e.g., `1e6` → 1).
