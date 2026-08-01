#!/bin/bash
# state.sh — small state helpers for cortexagent hooks.
# State lives under $XDG_CACHE_HOME/cortexagent (or ~/.cache/cortexagent).
# Sourced by hooks; not executed directly.

_cortexagent_state_dir() {
  local base="${XDG_CACHE_HOME:-$HOME/.cache}"
  echo "${base}/cortexagent"
}

cc_state_init() {
  mkdir -p "$(_cortexagent_state_dir)"
}

cc_save_last_prompt() {
  local prompt="$1"
  cc_state_init
  # Keep the most recent prompt only (for replay-on-compact).
  printf '%s' "$prompt" > "$(_cortexagent_state_dir)/last-prompt"
}

cc_read_last_prompt() {
  local f="$(_cortexagent_state_dir)/last-prompt"
  [ -f "$f" ] && cat "$f" || true
}