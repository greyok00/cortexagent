#!/bin/bash
# install.sh — set up CortexAgent for the current user.
#
# - templates config/mcp.json and config/settings.json with $HOME paths
# - syncs our minified CLAUDE.md into the isolated config dir
# - creates the standalone memory dir (~/cortexagent/memory)
# - marks scripts executable
# - symlinks bin/cortexagent into ~/.local/bin
#
# No hardcoded home paths; everything is $HOME-relative. Re-runnable.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${CORTEXAGENT_CONFIG_DIR:-$HOME/.cortexagent-config}"
MEMORY_DIR="${CORTEXAGENT_MEMORY_DIR:-$HOME/.cortexagent/memory}"

echo "==> CortexAgent install — ${REPO_ROOT}"
echo "    config dir: ${CONFIG_DIR}"
echo "    memory dir: ${MEMORY_DIR}"

MEMORY_CMD="python3 ${REPO_ROOT}/memory/mcp_server.py"

# ── Make scripts executable ─────────────────────────────────────────────────
chmod +x "${REPO_ROOT}/bin/cortexagent" \
        "${REPO_ROOT}/hooks/"*.sh \
        "${REPO_ROOT}/memory/"*.py \
        "${REPO_ROOT}/lib/"*.py \
        "${REPO_ROOT}/lib/"*.sh 2>/dev/null || true
echo "    scripts made executable"

# ── Render templates → live config files ────────────────────────────────────
python3 - "${REPO_ROOT}/config" "${CONFIG_DIR}" "${MEMORY_CMD}" "${HOME}" "${REPO_ROOT}" <<'PY'
import json, os, sys, shutil
config_dir, isolated_dir, memory_cmd, home, repo_root = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]

# 1. mcp.json (templated by install into isolated config dir)
mcp_tpl = os.path.join(config_dir, "mcp.json.template")
mcp_out = os.path.join(isolated_dir, "mcp.json")
if os.path.exists(mcp_tpl):
    tpl = json.load(open(mcp_tpl))
    tpl["mcpServers"]["cortexagent"]["command"] = memory_cmd
    raw = json.dumps(tpl, indent=2)
    raw = raw.replace("{{REPO_ROOT}}", repo_root)
    open(mcp_out, "w").write(raw + "\n")
    print(f"    wrote {mcp_out}")

# 2. settings.json (templated by install — $HOME and config dir)
sett_tpl = os.path.join(config_dir, "settings.json.template")
sett_out = os.path.join(isolated_dir, "settings.json")
if os.path.exists(sett_tpl):
    raw = open(sett_tpl).read()
    raw = raw.replace("{{HOME}}", home)
    raw = raw.replace("{{CONFIG_DIR}}", isolated_dir)
    open(sett_out, "w").write(raw)
    print(f"    wrote {sett_out}")

# 3. CLAUDE.md → isolated config dir (so ours loads, not the global one)
src_md = os.path.join(config_dir, "CLAUDE.md")
dst_md = os.path.join(isolated_dir, "CLAUDE.md")
if os.path.exists(src_md):
    os.makedirs(isolated_dir, exist_ok=True)
    shutil.copy2(src_md, dst_md)
    print(f"    copied {src_md} → {dst_md}")
PY

# ── Standalone memory dir ─────────────────────────────────────────────────────
mkdir -p "${MEMORY_DIR}/hot" "${MEMORY_DIR}/warm" "${MEMORY_DIR}/cold"
# Seed USER.md if missing (preserve user edits on re-run)
if [ ! -f "${MEMORY_DIR}/USER.md" ] && [ -f "${REPO_ROOT}/memory/USER.md" ]; then
  cp "${REPO_ROOT}/memory/USER.md" "${MEMORY_DIR}/USER.md"
fi
# Seed cold/cortexagent.md if missing
if [ ! -f "${MEMORY_DIR}/cold/cortexagent.md" ] && [ -f "${REPO_ROOT}/memory/cold/cortexagent.md" ]; then
  cp "${REPO_ROOT}/memory/cold/cortexagent.md" "${MEMORY_DIR}/cold/cortexagent.md"
fi
echo "    memory dir: ${MEMORY_DIR}"

# ── Per-profile directories (for lib/profiles.py, lib/loop_guard.py, webui) ──
PROFILES_DIR="${CORTEXAGENT_PROFILES_DIR:-$HOME/.cortexagent/profiles}"
mkdir -p "${PROFILES_DIR}/default"/{state,memory,workspace,sandboxes,logs}
echo "    profiles dir: ${PROFILES_DIR}/default/{state,memory,workspace,sandboxes,logs}"

# ── Webui log dir ───────────────────────────────────────────────────────────
mkdir -p "${HOME}/.cortexagent/logs"

# ── Copy extension for sideloading ───────────────────────────────────────────
EXTENSION_DIR="${HOME}/.local/share/cortexagent/extension"
mkdir -p "${EXTENSION_DIR}"
cp -r "${REPO_ROOT}/extension/"* "${EXTENSION_DIR}/"
echo "    extension: ${EXTENSION_DIR}"
echo "    To sideload in Chromium/Brave:"
echo "      1. Go to chrome://extensions"
echo "      2. Enable Developer mode"
echo "      3. Click 'Load unpacked'"
echo "      4. Select ${EXTENSION_DIR}"

# ── Symlink the binary ──────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
target="${BIN_DIR}/cortexagent"
if [ -e "$target" ] && [ ! -L "$target" ]; then
  echo "    backing up existing ${target} -> ${target}.bak"
  mv "$target" "${target}.bak"
fi
ln -sfn "${REPO_ROOT}/bin/cortexagent" "$target"
echo "    linked ${target} -> ${REPO_ROOT}/bin/cortexagent"

# ── PII self-check ──────────────────────────────────────────────────────────
leak="$(grep -rn "/home/$(whoami)" "${REPO_ROOT}" --include='*.sh' --include='*.py' --include='*.json' --include='*.md' 2>/dev/null | grep -v 'config/mcp.json' | grep -v 'config/settings.json' | grep -v 'config/CLAUDE.md' | grep -v 'memory/' | grep -v '.git/' | grep -v 'tauri/src-tauri/target/' || true)"
if [ -n "$leak" ]; then
  echo "WARN: hardcoded home path found in package (review):" >&2
  echo "$leak" >&2
fi

# ── Next steps ──────────────────────────────────────────────────────────────
echo ""
echo "Done. Make sure ${BIN_DIR} is on your PATH."
echo "Run:    cortexagent                       # start an interactive session"
echo "        cortexagent -p \"fix this bug\"     # one-shot"
echo "Env knobs: CORTEXAGENT_MODEL, CORTEXAGENT_PORT, CORTEXAGENT_CTX, CORTEXAGENT_NGL"
echo "Logs:    \$HOME/.cortexagent-server.log"
echo ""
echo "Self-contained layout:"
echo "  • config dir:  ${CONFIG_DIR} (CLAUDE.md, settings.json, mcp.json)"
echo "  • memory dir:  ${MEMORY_DIR}"
echo "  • excludes:    \$HOME/.claude/CLAUDE.md (via claudeMdExcludes)"
