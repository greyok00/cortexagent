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

if [ -f "${HOME}/security-hardening/alert-send.py" ]; then
  echo "    alert lane detected: actions/send_email.py + actions/send_text.py are armed"
else
  echo "    (optional) alert lane not installed: actions/send_email.py and"
  echo "        actions/send_text.py need ~/security-hardening/alert-send.py +"
  echo "        alert-config.json; without them both exit with a declared FAIL"
fi

if python3 -c "import slimtoken" 2>/dev/null; then
  echo "    slimtoken detected: context-compression MCP will be rendered enabled"
else
  echo "    (optional) slimtoken package not installed — the slimtoken MCP entry"
  echo "        is skipped; install the slimtoken package to enable compression"
fi

if [ -n "${CORTEXAGENT_NO_SUITE:-}" ] && [ "${CORTEXAGENT_NO_SUITE:-}" != "0" ]; then
  echo "    agent suite wiring skipped (CORTEXAGENT_NO_SUITE is set)"
else
  if python3 -c "import slimtoken" 2>/dev/null; then
    echo "    slimtoken already present — leaving untouched"
  else
    python3 -m pip install git+https://github.com/greyok00/slimtoken.git \
      2>/dev/null || echo "    (optional) slimtoken install failed — suite wiring non-fatal"
  fi
  GREYSEARCH_TARGET="${CORTEXAGENT_GREYSEARCH_MCP:-$HOME/greysearch}"
  if [ -d "${GREYSEARCH_TARGET}" ]; then
    echo "    greysearch checkout already present — leaving untouched"
  else
    git clone https://github.com/greyok00/greysearch.git "${GREYSEARCH_TARGET}" \
      || echo "    (optional) greysearch clone failed — suite wiring non-fatal"
  fi
fi

python3 - "${REPO_ROOT}/config" "${CONFIG_DIR}" "${MEMORY_CMD}" "${HOME}" "${REPO_ROOT}" <<'PY'
import json, os, sys, shutil
config_dir, isolated_dir, memory_cmd, home, repo_root = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]


mcp_tpl = os.path.join(config_dir, "mcp.json.template")
mcp_out = os.path.join(isolated_dir, "mcp.json")
if os.path.exists(mcp_tpl):
    tpl = json.load(open(mcp_tpl))
    greysearch_root = os.environ.get(
        "CORTEXAGENT_GREYSEARCH_MCP", os.path.join("~", "greysearch"))
    tpl["mcpServers"]["cortexagent"]["command"] = memory_cmd
    raw = json.dumps(tpl, indent=2)
    raw = raw.replace("{{REPO_ROOT}}", repo_root)
    raw = raw.replace("{{GREYSEARCH_MCP_ROOT}}", os.path.expanduser(greysearch_root).rstrip("/"))
    open(mcp_out, "w").write(raw + "\n")
    print(f"    wrote {mcp_out}")


sett_tpl = os.path.join(config_dir, "settings.json.template")
sett_out = os.path.join(isolated_dir, "settings.json")
if os.path.exists(sett_tpl):
    raw = open(sett_tpl).read()
    raw = raw.replace("{{HOME}}", home)
    raw = raw.replace("{{CONFIG_DIR}}", isolated_dir)
    open(sett_out, "w").write(raw)
    print(f"    wrote {sett_out}")
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
    if systemctl --user enable cortexagent >/dev/null 2>&1; then
      echo "    enabled cortexagent.service (starts on login)"
    fi
    if [ -f "$HOME/.cortexagent/daemon.pid" ]; then
      "${py}" "${REPO_ROOT}/lib/daemon.py" stop >/dev/null 2>&1 || true
    fi
    if systemctl --user restart cortexagent >/dev/null 2>&1; then
      echo "    started cortexagent.service now (always-on, local model unloads when idle)"
    fi
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
      echo "    (set CORTEXAGENT_AUTOSTART=1 to also autostart the daemon that owns the local model)"
    fi
  else
    echo "    systemd not available — overseer can still run manually: python3 lib/overseer.py start"
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
  local chrome_bin="${CORTEXAGENT_CHROME_BIN:-/usr/bin/chromium}"
  local cdp_port="${CORTEXAGENT_CDP_PORT:-9223}"
  
  
  local user_data_dir="${CORTEXAGENT_CHROME_USER_DATA_DIR:-${HOME}/.config/chromium}"
  local dsp="${CORTEXAGENT_DISPLAY:-${DISPLAY:-:0}}"
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
      -e "s|{{DISPLAY}}|${dsp}|g" \
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
  Linux) install_systemd; install_overseer_systemd; install_stealth_chrome_systemd ;;
  *) echo "    $(uname -s): systemd install skipped — run 'cortexagent daemon start' manually" ;;
esac

leak="$(grep -rn "/home/$(whoami)" "${REPO_ROOT}" --include='*.sh' --include='*.py' --include='*.json' --include='*.md' 2>/dev/null | grep -v 'config/mcp.json' | grep -v 'config/settings.json' | grep -v 'memory/' | grep -v '.git/' | grep -v '/tests/' || true)"
if [ -n "$leak" ]; then
  echo "WARN: hardcoded home path found in package (review):" >&2
  echo "$leak" >&2
fi

_py_count=$(find "${REPO_ROOT}/lib" -maxdepth 1 -name '*.py' | wc -l)
echo "  → ${_py_count} .py source files in lib/"

echo ""
echo "Done. Make sure ${BIN_DIR} is on your PATH."
echo "Run:    cortexagent                       # start an interactive session"
echo "        cortexagent -p \"fix this bug\"     # one-shot"
echo "Env knobs: CORTEXAGENT_MODEL, CORTEXAGENT_PORT, CORTEXAGENT_CTX, CORTEXAGENT_NGL"
echo "           CORTEXAGENT_IDLE_UNLOAD_SEC (default 600)"
echo "Logs:    \$HOME/.cortexagent/logs/"
echo ""
echo "Self-contained layout:"
echo "  • config dir:  ${CONFIG_DIR} (settings.json, mcp.json)"
echo "  • memory dir:  ${MEMORY_DIR}"
echo "  • local model: launcher-spawned on 127.0.0.1:11599 (no daemon/proxy service)"
