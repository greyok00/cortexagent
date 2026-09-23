#!/usr/bin/env python3

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

CONF_FILE = Path(os.environ.get(
    "CORTEXAGENT_CONF",
    str(Path.home() / ".cortexagent" / "cortexagent.conf"),
))

def _load_conf() -> configparser.ConfigParser:

    cp = configparser.ConfigParser(interpolation=None)
    if CONF_FILE.exists():
        try:
            cp.read(CONF_FILE)
        except Exception:
            pass
    return cp

_CONF = _load_conf()

def _env(name: str, conf_section: str, conf_key: str,
         default: Optional[str] = None) -> Optional[str]:

    val = os.environ.get(name)
    if val:
        return val
    if _CONF.has_option(conf_section, conf_key):
        return _CONF.get(conf_section, conf_key)
    return default

def _env_bool(name: str, conf_section: str, conf_key: str,
              default: bool) -> bool:
    val = _env(name, conf_section, conf_key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

def _env_int(name: str, conf_section: str, conf_key: str,
             default: int) -> int:
    val = _env(name, conf_section, conf_key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default

def _env_float(name: str, conf_section: str, conf_key: str,
               default: Optional[float] = None) -> Optional[float]:

    val = _env(name, conf_section, conf_key, None)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

LOCKED_KEYS = {
    "ctx_tokens": 131072,
    "model_ngl": 999,
    "model_fa": "on",
    "model_ctk": "q4_0",
    "model_ctv": "q4_0",
    "kv_offload": 1,
    "model_np": 1,
}
_LOCK_LOG: list = []

def _unlock_for(key: str) -> bool:
    if os.environ.get("CORTEXAGENT_UNLOCK", "").lower() in ("1", "true", "yes", "on"):
        return True
    return os.environ.get(f"CORTEXAGENT_UNLOCK_{key.upper()}", "").lower() in (
        "1", "true", "yes", "on")

def _locked_divergence(name: str, env_name: str, conf_section: str,
                       conf_key: str, pinned) -> None:
    return

def _env_locked_int(name: str, env_name: str, conf_section: str,
                    conf_key: str, default: int) -> int:
    if name in LOCKED_KEYS and not _unlock_for(name):
        pinned = LOCKED_KEYS[name]
        _locked_divergence(name, env_name, conf_section, conf_key, pinned)
        return int(pinned)
    return _env_int(env_name, conf_section, conf_key, default)

def _env_locked(name: str, env_name: str, conf_section: str,
                conf_key: str, default: Optional[str] = None) -> Optional[str]:
    if name in LOCKED_KEYS and not _unlock_for(name):
        pinned = LOCKED_KEYS[name]
        _locked_divergence(name, env_name, conf_section, conf_key, pinned)
        return str(pinned)
    return _env(env_name, conf_section, conf_key, default)

def _detect_cortexllm_dir() -> str:

    explicit = _env("CORTEXLLM_DIR", "cortexllm", "dir")
    if explicit:
        return str(Path(explicit).expanduser())
    existing = Path.home() / "cortexllm" / "repo"
    if existing.is_dir():
        return str(existing)
    return str(REPO_ROOT / "cortexllm")

class Config:

    def __init__(self) -> None:
        home = Path.home()

        self.repo_root = REPO_ROOT
        self.state_dir = Path(_env(
            "CORTEXAGENT_STATE_DIR", "paths", "state_dir",
            str(home / ".cortexagent")))
        self.config_dir = Path(_env(
            "CORTEXAGENT_CONFIG_DIR", "paths", "config_dir",
            str(home / ".cortexagent-config")))
        self.profiles_dir = Path(_env(
            "CORTEXAGENT_PROFILES_DIR", "paths", "profiles_dir",
            str(home / ".cortexagent" / "profiles")))
        self.logs_dir = self.state_dir / "logs"

        self.db_path = Path(_env(
            "CORTEXAGENT_DB_PATH", "memory", "db_path",
            str(home / ".config" / "cortexllm" / "cortexllm.db")))

        self.cortexllm_dir = Path(_detect_cortexllm_dir())
        self.cortexllm_socket = Path(_env(
            "CORTEXLLM_SOCKET", "cortexllm", "socket",
            str(home / ".cortexllm" / "memory.sock")))
        self.cortexllm_save_script = Path(_env(
            "CORTEXLLM_SAVE_SCRIPT", "cortexllm", "save_script",
            str(home / ".cortexllm" / "scripts" / "save-context.py")))

        self.llama_dir = Path(_env(
            "CORTEXAGENT_LLAMA_DIR", "backend", "llama_dir",
            str(home / "llama.cpp" / "build")))
        self.models_dir = Path(_env(
            "CORTEXAGENT_MODELS_DIR", "backend", "models_dir",
            str(home / "models")))

        self.model_path = _env(
            "CORTEXAGENT_MODEL", "backend", "model_path", "")

        self.local_port = _env_int(
            "CORTEXAGENT_LOCAL_PORT", "backend", "local_port", 11599)
        self.model_cloud = _env(
            "CORTEXAGENT_CLOUD_MODEL", "provider", "ollama_model",
            "glm-5.3-flash:cloud")

        self.cortex_router_mode = _env(
            "CORTEXAGENT_ROUTER_MODE", "cortex", "router_mode", "auto")
        self.cortex_host = _env(
            "CORTEXAGENT_HOST", "cortex", "host", "127.0.0.1")
        self.cortex_toolproxy = _env_bool(
            "CORTEXAGENT_TOOLPROXY", "cortex", "toolproxy", False)
        self.cortex_brand = _env(
            "CORTEXAGENT_BRAND", "branding", "name", "Cortex")
        self.cortex_author = _env(
            "CORTEXAGENT_AUTHOR", "branding", "author", "")

        self.ctx_tokens = _env_locked_int(
            "ctx_tokens", "CORTEXAGENT_CTX", "backend", "ctx_tokens", 131072)
        self.model_ngl = _env_locked_int(
            "model_ngl", "CORTEXAGENT_NGL", "backend", "model_ngl", 999)
        self.model_fa = _env_locked(
            "model_fa", "CORTEXAGENT_FA", "backend", "model_fa", "on")
        self.model_ctk = _env_locked(
            "model_ctk", "CORTEXAGENT_CTK", "backend", "model_ctk", "q4_0")
        self.model_ctv = _env_locked(
            "model_ctv", "CORTEXAGENT_CTV", "backend", "model_ctv", "q4_0")
        self.model_np = _env_locked_int(
            "model_np", "CORTEXAGENT_NP", "backend", "model_np", 1)

        self.model_temp = _env(
            "CORTEXAGENT_TEMP", "backend", "model_temp", "1.0")
        self.model_top_p = _env(
            "CORTEXAGENT_TOP_P", "backend", "model_top_p", "0.95")
        self.model_top_k = _env_int(
            "CORTEXAGENT_TOP_K", "backend", "model_top_k", 20)
        self.model_min_p = _env(
            "CORTEXAGENT_MIN_P", "backend", "model_min_p", "0.0")

        self.batch_size = _env_int(
            "CORTEXAGENT_B", "backend", "batch_size", 2048)
        self.model_ub = _env_int(
            "CORTEXAGENT_UB", "backend", "model_ub", 1024)
        self.kv_offload = _env_locked_int(
            "kv_offload", "CORTEXAGENT_KV_OFFLOAD", "backend", "kv_offload", 1)
        self.model_alias = _env(
            "CORTEXAGENT_ALIAS", "backend", "model_alias", "cortexagent")
        self.model_log = Path(_env(
            "CORTEXAGENT_LOG", "backend", "model_log",
            str(home / ".cortexagent-server.log")))

        self.vram_min_gb = _env_int(
            "CORTEXAGENT_BIG_VRAM_MIN", "backend", "vram_min_gb", 14)

        self.auto_load = _env_int(
            "CORTEXAGENT_AUTO_LOAD", "daemon", "auto_load", 0) == 1

        self.stale_session_sec = _env_int(
            "CORTEXAGENT_STALE_SESSION_SEC", "daemon", "stale_session_sec", 1800)
        self.control_socket = self.state_dir / "control.sock"

        self.inline_scroll = _env_bool(
            "CORTEXAGENT_INLINE_SCROLL", "display", "inline_scroll", False)

        self.browser_enabled = _env_bool(
            "CORTEXAGENT_BRAVE_ENABLED", "integrations", "browser_enabled", True)
        self.firecrawl_enabled = _env_bool(
            "CORTEXAGENT_FIRECRAWL_ENABLED", "integrations", "firecrawl_enabled", True)

        self.brand = _env("CORTEXAGENT_BRAND", "branding", "name", "CortexAgent")
        self.author = _env("CORTEXAGENT_AUTHOR", "branding", "author", "")

        self.vram_buffer_mb = _env_int(
            "CORTEXAGENT_VRAM_BUFFER_MB", "vram", "buffer_mb", 512)

        self.latency_alert_p95_ms = _env_float(
            "CORTEXAGENT_LATENCY_ALERT_P95_MS", "metrics", "latency_alert_p95_ms", 5000.0)

    def ensure_dirs(self) -> None:

        for d in (self.state_dir, self.logs_dir, self.profiles_dir / "default",
                  self.db_path.parent):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def as_dict(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items()}

    def shell_exports(self) -> str:

        lines = []
        for k, v in self.as_dict().items():
            lines.append(f"export CORTEXAGENT_CFG_{k.upper()}={repr(str(v))}")
        return "\n".join(lines)

    def locked_keys(self) -> dict:

        out = {}
        for k, pinned in LOCKED_KEYS.items():
            active = getattr(self, k, None)
            out[k] = {
                "pinned": pinned,
                "active": active,
                "unlocked": _unlock_for(k),
                "matches": str(active) == str(pinned),
            }
        return out

CFG = Config()

def _cli() -> int:
    if len(sys.argv) < 2:
        print("usage: config.py get <key> | shell | list | shell-locked | lock-status",
              file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "get" and len(sys.argv) >= 3:
        key = sys.argv[2]
        val = getattr(CFG, key, None)
        if val is None:
            print(f"unknown key: {key}", file=sys.stderr)
            return 1
        print(str(val))
        return 0
    if cmd == "shell":
        print(CFG.shell_exports())
        return 0
    if cmd == "list":
        for k, v in CFG.as_dict().items():
            print(f"{k}={v}")
        return 0
    if cmd == "shell-locked":

        env_map = {
            "ctx_tokens": ("CORTEXAGENT_CTX", 131072),
            "model_ngl": ("CORTEXAGENT_NGL", 999),
            "model_fa": ("CORTEXAGENT_FA", "on"),
            "model_ctk": ("CORTEXAGENT_CTK", "q8_0"),
            "model_ctv": ("CORTEXAGENT_CTV", "q8_0"),
            "kv_offload": ("CORTEXAGENT_KV_OFFLOAD", 1),
            "model_np": ("CORTEXAGENT_NP", 1),
        }
        for key, (env_name, pinned) in env_map.items():
            if _unlock_for(key):

                val = getattr(CFG, key, pinned)
            else:
                val = LOCKED_KEYS[key]
            print(f"export {env_name}={val}")
        return 0
    if cmd == "local":
        print(f"export CORTEXAGENT_MODEL='{CFG.model_path or ''}'")
        return 0
    if cmd == "lock-status":
        for k, info in CFG.locked_keys().items():
            flag = "UNLOCKED" if info["unlocked"] else ("locked" if info["matches"] else "DRIFT!")
            print(f"{k}: pinned={info['pinned']} active={info['active']} [{flag}]")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2

if __name__ == "__main__":
    sys.exit(_cli())
