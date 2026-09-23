#!/bin/bash
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

chmod +x "${REPO_ROOT}/bin/cortexagent" \
        "${REPO_ROOT}/hooks/"*.sh \
        "${REPO_ROOT}/memory/"*.py \
        "${REPO_ROOT}/lib/"*.py \
        "${REPO_ROOT}/lib/"*.sh 2>/dev/null || true
echo "    scripts made executable"

echo "    installing slimtoken (minify + grammar-strip)…"
python3 -m pip install --break-system-packages --user \
  "slimtoken>=0.3.3" "orjson" "xxhash" 2>&1 | tail -2 || \
  echo "    WARN: slimtoken install failed — see README" >&2

echo "    building native modules (Cython)…"
python3 -m pip install --break-system-packages --user cython 2>&1 | tail -1 >/dev/null
python3 "${REPO_ROOT}/tools/build_opt.py" 2>&1 | tail -3

echo "    verifying Cython artifacts…"
if python3 "${REPO_ROOT}/tools/build_opt.py" --check 2>&1 | tee /tmp/_build_opt_check.$$ | grep -q "on .py fallback"; then
  echo "WARN: some modules still on .py fallback — install is functional but NOT optimized." >&2
  echo "      Re-run install.sh after 'pip install --user cython' to retry the build." >&2
fi
rm -f /tmp/_build_opt_check.$$

echo "    minifying source (comments + docstrings)…"
python3 "${REPO_ROOT}/tools/minify_source.py" 2>&1 | tail -3 || \
  echo "    WARN: source minify failed — leaving .py as-is" >&2

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

mkdir -p "${MEMORY_DIR}/hot" "${MEMORY_DIR}/warm" "${MEMORY_DIR}/cold"
if [ ! -f "${MEMORY_DIR}/USER.md" ] && [ -f "${REPO_ROOT}/memory/USER.md" ]; then
  cp "${REPO_ROOT}/memory/USER.md" "${MEMORY_DIR}/USER.md"
fi
if [ ! -f "${MEMORY_DIR}/cold/cortexagent.md" ] && [ -f "${REPO_ROOT}/memory/cold/cortexagent.md" ]; then
  cp "${REPO_ROOT}/memory/cold/cortexagent.md" "${MEMORY_DIR}/cold/cortexagent.md"
fi
echo "    memory dir: ${MEMORY_DIR}"

PROFILES_DIR="${CORTEXAGENT_PROFILES_DIR:-$HOME/.cortexagent/profiles}"
mkdir -p "${PROFILES_DIR}/default"/{state,memory,workspace,sandboxes,logs}
echo "    profiles dir: ${PROFILES_DIR}/default/{state,memory,workspace,sandboxes,logs}"

mkdir -p "${HOME}/.cortexagent/logs"

mkdir -p "$BIN_DIR"
target="${BIN_DIR}/cortexagent"
if [ -e "$target" ] && [ ! -L "$target" ]; then
  echo "    backing up existing ${target} -> ${target}.bak"
  mv "$target" "${target}.bak"
fi
chmod +x "${REPO_ROOT}/engine/cli.py"
ln -sfn "${REPO_ROOT}/engine/cli.py" "$target"
echo "    linked ${target} -> ${REPO_ROOT}/engine/cli.py"

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
  if [ -f "${unit_out}" ] && [ ! -f "${unit_out}.bak" ]; then
    cp -a "${unit_out}" "${unit_out}.bak"
    echo "    backed up existing unit → ${unit_out}.bak"
  fi
  sed -e "s|{{PYTHON}}|${py}|g" -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      "${unit_tpl}" > "${unit_out}"
  echo "    wrote ${unit_out}"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent >/dev/null 2>&1 && echo "    enabled cortexagent.service (starts on login)"
    if [ -f "$HOME/.cortexagent/daemon.pid" ]; then
      "${py}" "${REPO_ROOT}/lib/daemon.py" stop >/dev/null 2>&1 || true
    fi
    systemctl --user restart cortexagent >/dev/null 2>&1 && echo "    started cortexagent.service now (always-on, big idle-unloads)"
  else
    echo "    systemd not available — daemon can still run manually: cortexagent daemon start"
  fi
}

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
  if [ -f "${unit_out}" ] && [ ! -f "${unit_out}.bak" ]; then
    cp -a "${unit_out}" "${unit_out}.bak"
    echo "    backed up existing unit → ${unit_out}.bak"
  fi
  sed -e "s|{{PYTHON}}|${py}|g" -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      "${unit_tpl}" > "${unit_out}"
  echo "    wrote ${unit_out}"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent-overseer >/dev/null 2>&1 && echo "    enabled cortexagent-overseer.service (starts on login)"
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

install_tray_systemd() {
  if [ "$(uname -s)" != "Linux" ]; then return; fi
  if ! command -v systemctl >/dev/null 2>&1; then return; fi
  if [ ! -f "${REPO_ROOT}/lib/tray.py" ]; then return; fi
  unit_tpl="${REPO_ROOT}/config/templates/cortexagent-tray.service"
  unit_out="${HOME}/.config/systemd/user/cortexagent-tray.service"
  if [ ! -f "${unit_tpl}" ]; then
    echo "    tray template missing — skipping (${unit_tpl})" >&2
    return
  fi
  if [ -f "${unit_out}" ] && [ ! -f "${unit_out}.bak" ]; then
    cp -a "${unit_out}" "${unit_out}.bak"
    echo "    backed up existing unit → ${unit_out}.bak"
  fi
  sed -e "s|{{PYTHON}}|${py}|g" -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      "${unit_tpl}" > "${unit_out}"
  echo "    wrote ${unit_out}"
  if systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent-tray.service >/dev/null 2>&1 \
      && echo "    enabled cortexagent-tray.service (wolf-head tray on login)"
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
      systemctl --user start cortexagent-tray.service >/dev/null 2>&1 \
        && echo "    started cortexagent-tray.service (linked to overseer)"
    else
      echo "    no DISPLAY/WAYLAND_DISPLAY — skipping tray start (will autostart on next graphical login)"
    fi
  fi
}

install_stealth_chrome_systemd() {
  if [ "${STEALTH_CHROME_SYSTEMD:-1}" != "1" ]; then return; fi
  if [ "$(uname -s)" != "Linux" ]; then return; fi
  if ! command -v systemctl >/dev/null 2>&1; then return; fi
  local tmpl="${REPO_ROOT}/config/templates/cortexagent-stealth-chrome.service"
  local dst="${HOME}/.config/systemd/user/cortexagent-stealth-chrome.service"
  if [ ! -f "${tmpl}" ]; then
    echo "    stealth-chrome template missing — skipping (${tmpl})" >&2
    return
  fi
  local py
  py="$(command -v python3 || echo /usr/bin/python3)"
  local chrome_bin="${CORTEXAGENT_CHROME_BIN:-/usr/bin/google-chrome}"
  local cdp_port="${CORTEXAGENT_CDP_PORT:-9222}"
  local user_data_dir="${CORTEXAGENT_CHROME_USER_DATA_DIR:-${HOME}/.config/chrome-stealth-profile}"
  mkdir -p "$(dirname "${dst}")"
  if [ -f "${dst}" ] && [ ! -f "${dst}.bak" ]; then
    cp -a "${dst}" "${dst}.bak"
    echo "    backed up existing unit → ${dst}.bak"
  fi
  sed \
      -e "s|{{PYTHON}}|${py}|g" \
      -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
      -e "s|{{CHROME}}|${chrome_bin}|g" \
      -e "s|{{CDP_PORT}}|${cdp_port}|g" \
      -e "s|{{USER_DATA_DIR}}|${user_data_dir}|g" \
      "${tmpl}" > "${dst}"
  echo "    wrote ${dst}"
  if systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable cortexagent-stealth-chrome.service >/dev/null 2>&1 \
      && echo "    enabled cortexagent-stealth-chrome.service (Patchright automation driver, starts on login)"
    if [ "${STEALTH_CHROME_START:-0}" = "1" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
      systemctl --user start cortexagent-stealth-chrome.service >/dev/null 2>&1 \
        && echo "    started cortexagent-stealth-chrome.service now"
    fi
  else
    echo "    systemd not available — start stealth chrome manually: python3 -m lib.stealth.worker start"
  fi
}

case "$(uname -s)" in
  Linux) install_systemd; install_overseer_systemd; install_tray_systemd; install_stealth_chrome_systemd ;;
  *) echo "    $(uname -s): systemd install skipped — run 'cortexagent daemon start' manually" ;;
esac

if [ "${CORTEXAGENT_PATCH_BINARY:-1}" = "1" ] && [ -f "${REPO_ROOT}/lib/patch_binary.py" ]; then
  if python3 "${REPO_ROOT}/lib/patch_binary.py" --check >/dev/null 2>&1; then
    python3 "${REPO_ROOT}/lib/patch_binary.py" >/dev/null 2>&1 \
      && echo "    claude binary patched (banner/tips hidden) — backup at claude.exe.bak" \
      || echo "    claude binary patch: skipped (not found or not installed yet)"
  else
    echo "    claude binary patch: skipped (claude not installed yet — re-run install after installing claude)"
  fi
fi

leak="$(grep -rn "/home/$(whoami)" "${REPO_ROOT}" --include='*.sh' --include='*.py' --include='*.json' --include='*.md' 2>/dev/null | grep -v 'config/mcp.json' | grep -v 'config/settings.json' | grep -v 'config/CLAUDE.md' | grep -v 'memory/' | grep -v '.git/' | grep -v 'tauri/src-tauri/target/' | grep -v '/.claude/' | grep -v '/tests/' || true)"
if [ -n "$leak" ]; then
  echo "WARN: hardcoded home path found in package (review):" >&2
  echo "$leak" >&2
fi

echo ""
echo "Optimization summary:"
_so_listing="$(python3 "${REPO_ROOT}/tools/build_opt.py" --check 2>/dev/null || true)"
echo "  ${_so_listing}"
_total_so_bytes=$(stat -c%s "${REPO_ROOT}"/lib/*.so 2>/dev/null | awk '{s+=$1} END {print s+0}')
if [ "${_total_so_bytes:-0}" -gt 0 ]; then
  _total_so_kb=$((_total_so_bytes / 1024))
  echo "  → ${_total_so_kb} KB of native code (5 hot modules)"
else
  echo "  → no native modules — running pure-Python (functional, slower)"
fi
_py_count=$(find "${REPO_ROOT}/lib" -maxdepth 1 -name '*.py' | wc -l)
echo "  → ${_py_count} .py files in lib/ (minified)"

echo ""
echo "Done. Make sure ${BIN_DIR} is on your PATH."
echo "Run:    cortexagent                       # start an interactive session"
echo "        cortexagent -p \"fix this bug\"     # one-shot"
echo "Env knobs: CORTEXAGENT_MODEL, CORTEXAGENT_PORT, CORTEXAGENT_CTX, CORTEXAGENT_NGL"
echo "           CORTEXAGENT_IDLE_UNLOAD_SEC (default 600)"
echo "Logs:    \$HOME/.cortexagent/logs/"
echo ""
echo "Self-contained layout:"
echo "  • config dir:  ${CONFIG_DIR} (CLAUDE.md, settings.json, mcp.json)"
echo "  • memory dir:  ${MEMORY_DIR}"
echo "  • local model: launcher-spawned on 127.0.0.1:11599 (no daemon/proxy service)"
echo "  • excludes:    \$HOME/.claude/CLAUDE.md (via claudeMdExcludes)"
