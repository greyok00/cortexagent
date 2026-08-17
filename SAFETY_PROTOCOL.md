# Safety Protocol — Never Break Things Again

## Core Principle
**No changes to critical files without a snapshot first. No restarts by the agent.**

## Critical Files (Auto-Backed)
These files are snapshotted before ANY modification:
1. `bin/cortexagent` — Main CLI binary
2. `cortex/packages/tui/src/keys.ts` — Keyboard bindings source
3. `cortex/packages/tui/dist/keys.js` — Keyboard bindings compiled
4. `cortex/packages/coding-agent/dist/cli.js` — Coding agent CLI
5. `cortex/packages/coding-agent/dist/main.js` — Coding agent core
6. `lib/overseer.py` — Core orchestration
7. `lib/daemon.py` — Daemon process
8. `lib/observability.py` — Observability layer
9. `config/settings.json` — Configuration
10. `~/.cortex/agent/keybindings.json` — TUI keybindings
11. `~/.cortex/agent/extensions/modes.ts` — TUI mode cycle
12. `cortexllm/cortexllm_mcp_server.py` — MCP server

## Safety Procedure for ALL Changes

### Before ANY file edit:
1. Run `./bin/snapshot.sh save` — creates full snapshot
2. Check for running processes that might lock files:
   ```bash
   pgrep -f cortexagent
   lsof bin/cortexagent 2>/dev/null || true
   ```

### During editing:
3. Use atomic writes where possible:
   ```bash
   # Write to temp, then mv (atomic on same fs)
   cp file file.bak.$(date +%s)    # backup
   # edit file.tmp
   mv file.tmp file                 # atomic swap
   ```

### After editing:
4. Verify the file is syntactically valid:
   ```bash
   # For Python:
   python3 -m py_compile <file>
   # For JS/TS:
   node -c <file>
   # For binary:
   file <file>
   ```
5. Run `./bin/snapshot.sh verify` — confirms snapshot is updated
6. Report what changed + what needs testing
7. **NEVER restart any processes. Let the user do that.**

## Rollback Procedure
```bash
./bin/snapshot.sh restore   # Restores all files from last snapshot
./bin/snapshot.sh verify    # Confirms restore succeeded
```

## When Modifying Build Outputs (dist/)
Always rebuild from source:
```bash
# If changing dist/ files, also verify the source was updated
# This prevents drift between src and dist
```

## Emergency Escape Hatch
If something goes wrong:
```bash
./bin/safe-modify.sh <description> --restore <file>   # Restore single file
./bin/snapshot.sh restore                              # Restore everything
./bin/cortexagent --claude                                                             # Claude fallback
```
