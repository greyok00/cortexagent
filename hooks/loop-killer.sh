#!/usr/bin/env bash
# Disabled: this hook caused the CortexAgent TUI to be SIGKILLed.
#
# This hook fired on every Stop event and checked the transcript for
# 'Connection error' lines. When llama-server is stopped (for example during
# a model swap), a stale loop-killer process could keep firing.
# was hung), the TUI showed connection errors and retried. After 4+ errors
# in the last 40 transcript lines, this hook sent `kill -9` to the TUI
# process ($PPID_AGENT), killing it with SIGKILL.
#
# The TUI would then show: "line 433: <PID> Killed ${AGENT_CLI}"
#
# Connection errors are TRANSIENT — llama-server might be restarting, or
# the network might be flaky. Killing the TUI on transient connection
# errors is wrong. The hook has been disabled.
#
# Fix: removed from settings.json Stop hook. This file is a no-op.
exit 0
