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
    "big_ctx": 131072,
    "big_ngl": 999,
    "big_fa": "on",
    "big_ctk": "q4_0",
    "big_ctv": "q4_0",
    "big_kv_offload": 1,
    "big_np": 1,
}
_LOCK_LOG: list = []


def _unlock_for(key: str) -> bool:
    if os.environ.get("CORTEXAGENT_UNLOCK", "").lower() in ("1", "true", "yes", "on"):
        return True
    return os.environ.get(f"CORTEXAGENT_UNLOCK_{key.upper()}", "").lower() in (
        "1", "true", "yes", "on")


def _locked_divergence(name: str, env_name: str, conf_section: str,
                       conf_key: str, pinned) -> None:
    # Quiet by default — divergence between env/conf and the pinned value is
    # tracked via `lock-status` / `CFG.locked_keys()` only. Printing to stderr
    # at module import time delays CLI startup and is not actionable here.
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




        self.backend = _env(
            "CORTEXAGENT_BACKEND", "backend", "kind", "llamacpp") or "llamacpp"
        self.llama_dir = Path(_env(
            "CORTEXAGENT_LLAMA_DIR", "backend", "llama_dir",
            str(home / "llama.cpp" / "build")))
        self.models_dir = Path(_env(
            "CORTEXAGENT_MODELS_DIR", "backend", "models_dir",
            str(home / "models")))




        self.big_model = _env(
            "CORTEXAGENT_MODEL", "backend", "big_model", "")
        self.big_model_port = _env_int(
            "CORTEXAGENT_PORT", "backend", "big_model_port", 8080)




        self.cortex_router_mode = _env(
            "CORTEXAGENT_ROUTER_MODE", "cortex", "router_mode", "auto")
        self.cortex_host = _env(
            "CORTEXAGENT_HOST", "cortex", "host", "127.0.0.1")
        self.cortex_toolproxy = _env_bool(
            "CORTEXAGENT_TOOLPROXY", "cortex", "toolproxy", False)
        self.cortex_brand = _env(
            "CORTEXAGENT_BRAND", "branding", "name", "Cortex")
        self.cortex_author = _env(
            "CORTEXAGENT_AUTHOR", "branding", "author", "GreyOK00")




















        self.big_ctx = _env_locked_int(
            "big_ctx", "CORTEXAGENT_CTX", "backend", "big_ctx", 131072)
        self.big_ngl = _env_locked_int(
            "big_ngl", "CORTEXAGENT_NGL", "backend", "big_ngl", 999)
        self.big_fa = _env_locked(
            "big_fa", "CORTEXAGENT_FA", "backend", "big_fa", "on")
        self.big_ctk = _env_locked(
            "big_ctk", "CORTEXAGENT_CTK", "backend", "big_ctk", "q4_0")
        self.big_ctv = _env_locked(
            "big_ctv", "CORTEXAGENT_CTV", "backend", "big_ctv", "q4_0")
        self.big_np = _env_locked_int(
            "big_np", "CORTEXAGENT_NP", "backend", "big_np", 1)








        self.big_b = _env_int(
            "CORTEXAGENT_B", "backend", "big_b", 2048)
        self.big_ub = _env_int(
            "CORTEXAGENT_UB", "backend", "big_ub", 1024)
        self.big_kv_offload = _env_locked_int(
            "big_kv_offload", "CORTEXAGENT_KV_OFFLOAD", "backend", "big_kv_offload", 1)
        self.big_alias = _env(
            "CORTEXAGENT_ALIAS", "backend", "big_alias", "cortexagent")
        self.big_log = Path(_env(
            "CORTEXAGENT_LOG", "backend", "big_log",
            str(home / ".cortexagent-server.log")))








        self.big_vram_min_gb = _env_int(
            "CORTEXAGENT_BIG_VRAM_MIN", "backend", "big_vram_min_gb", 14)







        self.idle_unload_sec = _env_int(
            "CORTEXAGENT_IDLE_UNLOAD_SEC", "daemon", "idle_unload_sec", 0)




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
        self.author = _env("CORTEXAGENT_AUTHOR", "branding", "author", "GreyOK00")











        self.stt_model = _env("CORTEXAGENT_STT_MODEL", "stt", "model", "base")
        self.stt_device = _env("CORTEXAGENT_STT_DEVICE", "stt", "device", "cuda")
        self.stt_mic_device = _env(
            "CORTEXAGENT_STT_MIC", "stt", "mic_device", "Logi USB Headset")
        self.stt_hotkey = _env(
            "CORTEXAGENT_STT_HOTKEY", "stt", "hotkey", "<ctrl>+<shift>+space")
        self.stt_speak_to_capture = _env_bool(
            "CORTEXAGENT_STT_SPEAK", "stt", "speak_to_capture", True)
        self.stt_vad_threshold = _env_float(
            "CORTEXAGENT_STT_VAD_THRESHOLD", "stt", "vad_threshold", 0.05)









        self.stt_vad_silence_sec = _env_float(
            "CORTEXAGENT_STT_VAD_SILENCE", "stt", "vad_silence_sec", 1.5)




        self.stt_vad_max_utterance_sec = _env_float(
            "CORTEXAGENT_STT_VAD_MAX_UTTERANCE", "stt", "vad_max_utterance_sec", 10.0)









        self.stt_cleanup = _env_bool(
            "CORTEXAGENT_STT_CLEANUP", "stt", "cleanup", False)
        self.stt_cleanup_target = _env(
            "CORTEXAGENT_STT_CLEANUP_TARGET", "stt", "cleanup_target", "big")



        self.stt_cleanup_max_sentences = _env_int(
            "CORTEXAGENT_STT_CLEANUP_MAX_SENTENCES", "stt",
            "cleanup_max_sentences", 4)








        self.vram_buffer_mb = _env_int(
            "CORTEXAGENT_VRAM_BUFFER_MB", "vram", "buffer_mb", 512)




        self.latency_alert_p95_ms = _env_float(
            "CORTEXAGENT_LATENCY_ALERT_P95_MS", "metrics", "latency_alert_p95_ms", 5000.0)



        self.context_alert_pct = _env_float(
            "CORTEXAGENT_CTX_ALERT_PCT", "metrics", "context_alert_pct", 76.0)
        self.context_critical_pct = _env_float(
            "CORTEXAGENT_CTX_CRITICAL_PCT", "metrics", "context_critical_pct", 90.0)
        self.context_critical_ticks = _env_int(
            "CORTEXAGENT_CTX_CRITICAL_TICKS", "metrics", "context_critical_ticks", 3)


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



# _LOCK_LOG is reserved for future diagnostic use; divergence is currently
# quiet at import time. See `lib/config.py lock-status` for introspection.



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
            "big_ctx": ("CORTEXAGENT_CTX", 131072),
            "big_ngl": ("CORTEXAGENT_NGL", 999),
            "big_fa": ("CORTEXAGENT_FA", "on"),
            "big_ctk": ("CORTEXAGENT_CTK", "q4_0"),
            "big_ctv": ("CORTEXAGENT_CTV", "q4_0"),
            "big_kv_offload": ("CORTEXAGENT_KV_OFFLOAD", 1),
            "big_np": ("CORTEXAGENT_NP", 1),
        }
        for key, (env_name, pinned) in env_map.items():
            if _unlock_for(key):

                val = getattr(CFG, key, pinned)
            else:
                val = LOCKED_KEYS[key]
            print(f"export {env_name}={val}")
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