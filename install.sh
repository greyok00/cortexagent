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

mkdir -p "${CONFIG_DIR}" "${BIN_DIR}"

MEMORY_CMD="python3 ${REPO_ROOT}/memory/mcp_server.py"

# ── Make scripts executable ─────────────────────────────────────────────────
chmod +x "${REPO_ROOT}/bin/cortexagent" \
        "${REPO_ROOT}/hooks/"*.sh \
        "${REPO_ROOT}/memory/"*.py \
        "${REPO_ROOT}/lib/"*.py \
        "${REPO_ROOT}/lib/"*.sh 2>/dev/null || true
echo "    scripts made executable"

# ── Diffusion deps (image/video via in-process diffusers) ────────────────────
# Optional: only installs when CORTEXAGENT_INSTALL_DIFFUSION_DEPS=1 (heavy: torch
# + diffusers + CUDA). Otherwise just prints what's needed so a user can install
# manually. These are NOT auto-installed because a CPU-only/CI box doesn't want
# a multi-GB CUDA torch pull. gen_image (SD1.5/SDXL) needs diffusers+torch+accelerate;
# gen_video (LTX-Video) additionally needs sentencepiece (T5 tokenizer) +
# imageio-ffmpeg (mp4 export).
_diff_deps="diffusers transformers accelerate sentencepiece imageio imageio-ffmpeg opencv-python"
if [ "${CORTEXAGENT_INSTALL_DIFFUSION_DEPS:-0}" = "1" ]; then
  echo "    installing diffusion deps (torch + ${_diff_deps})…"
  python3 -m pip install --break-system-packages --user torch "${_diff_deps}" 2>&1 | tail -2 || \
    echo "    WARN: diffusion deps install failed — see README" >&2
else
  echo "    diffusion deps (not auto-installed): torch ${_diff_deps}"
  echo "      install with: CORTEXAGENT_INSTALL_DIFFUSION_DEPS=1 ${REPO_ROOT}/install.sh"
  echo "      (needed for: cortexagent gen-image / gen-video)"
fi

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

# ── Symlink the entry point → engine/cli.py (unified Python dispatcher) ──────
# `cortexagent` (no args) → cli.py `run` → execs bin/cortexagent (the session
# launcher). Subcommands (`models`, `daemon`, `status`, `install`) are the
# control plane over the daemon's socket. This is the Nuitka-compilable entry.
mkdir -p "$BIN_DIR"
target="${BIN_DIR}/cortexagent"
if [ -e "$target" ] && [ ! -L "$target" ]; then
  echo "    backing up existing ${target} -> ${target}.bak"
  mv "$target" "${target}.bak"
fi
chmod +x "${REPO_ROOT}/engine/cli.py"
ln -sfn "${REPO_ROOT}/engine/cli.py" "$target"
echo "    linked ${target} -> ${REPO_ROOT}/engine/cli.py"

# ── systemd user service (Linux only; OS-aware) ──────────────────────────────
# Installs a user unit that runs the persistent daemon (models + proxy). The
# daemon idle-unloads the big model to free VRAM; the CLI is a thin client.
# Enabled to start on login. Set CORTEXAGENT_AUTOSTART=1 to also start it now.
install_systemd() {
  local unit_tpl="${REPO_ROOT}/config/templates/cortexagent.service"
  local unit_dir="$HOME/.config/systemd/user"
  local unit_out="${unit_dir}/cortexagent.service"
  local py
  py="$(command -v python3 || echo /usr/bin/python3)"
  mkdir -p "${unit_dir}"
  if [ ! -f "${unit_tpl}" ]; then
    echo "    systemd: unit template missing — skipping (non-fatal)" >&2
    return 0
  fi
  # Back up a hand-written / pre-existing unit before overwriting.
  if [ -f "${unit_out}" ] && [ ! -f "${unit_out}.bak" ]; then
    cp -a "${unit_out}" "${unit_out}.bak"
    echo "    backed up existing unit → ${unit_out}.bak"
  fi
  sed -e "s|{{PYTHON}}|${py}|g" -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      "${unit_tpl}" > "${unit_out}"
  echo "    wrote ${unit_out}"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent >/dev/null 2>&1 && echo "    enabled cortexagent.service (starts on login)"
    # The daemon is the DEFAULT backend now (DAEMON_MODE in bin/cortexagent
    # engages whenever this is up) — start it unconditionally, not gated on
    # CORTEXAGENT_AUTOSTART. Stop any manual/orphan daemon holding the
    # control socket / pidfile first so the restart doesn't conflict.
    if [ -f "$HOME/.cortexagent/daemon.pid" ]; then
      "${py}" "${REPO_ROOT}/lib/daemon.py" stop >/dev/null 2>&1 || true
    fi
    systemctl --user restart cortexagent >/dev/null 2>&1 && echo "    started cortexagent.service now (always-on, big idle-unloads)"
  else
    echo "    systemd not available — daemon can still run manually: cortexagent daemon start"
  fi
}

# ── systemd user service: OVERSEER (always-on scheduler + tiny keepalive) ────
# Installs a user unit that runs the overseer daemon — keepalives the 0.5b
# tiny llama-server (:8082) and runs the cron scheduler + task queue + memory
# health, independent of the cortexagent CLI (so scheduled tasks fire even
# when no session is open). Enabled + started now: it is meant to be always on.
install_overseer_systemd() {
  local unit_tpl="${REPO_ROOT}/config/templates/cortexagent-overseer.service"
  local unit_dir="$HOME/.config/systemd/user"
  local unit_out="${unit_dir}/cortexagent-overseer.service"
  local py
  py="$(command -v python3 || echo /usr/bin/python3)"
  mkdir -p "${unit_dir}"
  if [ ! -f "${unit_tpl}" ]; then
    echo "    systemd: overseer unit template missing — skipping (non-fatal)" >&2
    return 0
  fi
  # Back up a hand-written / pre-existing unit before overwriting.
  if [ -f "${unit_out}" ] && [ ! -f "${unit_out}.bak" ]; then
    cp -a "${unit_out}" "${unit_out}.bak"
    echo "    backed up existing unit → ${unit_out}.bak"
  fi
  sed -e "s|{{PYTHON}}|${py}|g" -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      "${unit_tpl}" > "${unit_out}"
  echo "    wrote ${unit_out}"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent-overseer >/dev/null 2>&1 && echo "    enabled cortexagent-overseer.service (starts on login)"
    # Stop any manual/orphan overseer holding the pidfile first (Type=forking
    # would otherwise see "already running" and go inactive).
    if [ -f "$HOME/.cortexagent/overseer.pid" ]; then
      "${py}" "${REPO_ROOT}/lib/overseer.py" stop >/dev/null 2>&1 || true
    fi
    systemctl --user restart cortexagent-overseer >/dev/null 2>&1 && echo "    started cortexagent-overseer.service now (always-on)"
    if [ "${CORTEXAGENT_AUTOSTART:-0}" != "1" ]; then
      echo "    (set CORTEXAGENT_AUTOSTART=1 to also autostart the big-model daemon)"
    fi
  else
    echo "    systemd not available — overseer can still run manually: python3 lib/overseer.py start"
  fi
}

case "$(uname -s)" in
  Linux) install_systemd; install_overseer_systemd ;;
  *) echo "    $(uname -s): systemd install skipped — run 'cortexagent daemon start' manually" ;;
esac

# ── Patch the claude binary (hide "Welcome"/"Tips"/"What's new" banner) ─────────
# Nulls the onboarding strings in the installed `claude` binary so the only
# banner the user sees is CortexAgent's (lib/banner.py). Non-fatal: on a fresh
# box `claude` may not be installed yet, and patching is opt-out. Backs up the
# original to claude.exe.bak first (restore with: python3 lib/patch_binary.py --restore).
if [ "${CORTEXAGENT_PATCH_BINARY:-1}" = "1" ] && [ -f "${REPO_ROOT}/lib/patch_binary.py" ]; then
  if python3 "${REPO_ROOT}/lib/patch_binary.py" --check >/dev/null 2>&1; then
    python3 "${REPO_ROOT}/lib/patch_binary.py" >/dev/null 2>&1 \
      && echo "    claude binary patched (banner/tips hidden) — backup at claude.exe.bak" \
      || echo "    claude binary patch: skipped (not found or not installed yet)"
  else
    echo "    claude binary patch: skipped (claude not installed yet — re-run install after installing claude)"
  fi
fi

# ── PII self-check ──────────────────────────────────────────────────────────
leak="$(grep -rn "/home/$(whoami)" "${REPO_ROOT}" --include='*.sh' --include='*.py' --include='*.json' --include='*.md' 2>/dev/null | grep -v 'config/mcp.json' | grep -v 'config/settings.json' | grep -v 'config/CLAUDE.md' | grep -v 'memory/' | grep -v '.git/' | grep -v 'tauri/src-tauri/target/' | grep -v '/.claude/' | grep -v '/tests/' || true)"
if [ -n "$leak" ]; then
  echo "WARN: hardcoded home path found in package (review):" >&2
  echo "$leak" >&2
fi

# ── Next steps ──────────────────────────────────────────────────────────────
echo ""
echo "Done. Make sure ${BIN_DIR} is on your PATH."
echo "Run:    cortexagent                       # start an interactive session"
echo "        cortexagent -p \"fix this bug\"     # one-shot"
echo "        cortexagent daemon start         # start the persistent backend"
echo "        cortexagent models status        # big/tiny/proxy state"
echo "        cortexagent models unload big    # free ~13 GB VRAM now"
echo "Env knobs: CORTEXAGENT_MODEL, CORTEXAGENT_PORT, CORTEXAGENT_CTX, CORTEXAGENT_NGL"
echo "           CORTEXAGENT_IDLE_UNLOAD_SEC (default 600)"
echo "Logs:    \$HOME/.cortexagent/logs/daemon.log"
echo ""
echo "Self-contained layout:"
echo "  • config dir:  ${CONFIG_DIR} (CLAUDE.md, settings.json, mcp.json)"
echo "  • memory dir:  ${MEMORY_DIR}"
echo "  • daemon:      systemd user service cortexagent.service (models + proxy)"
echo "  • excludes:    \$HOME/.claude/CLAUDE.md (via claudeMdExcludes)"
