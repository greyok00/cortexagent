#!/usr/bin/env python3
"""lib/config.py — single source of truth for all CortexAgent paths + settings.

Why this exists
---------------
Before this module, paths were hardcoded across the codebase:
  - memory/db.py:26-27        → ~/.config/cortexllm/cortexllm.db
  - hooks/*.sh                 → ~/.cortexllm/memory.sock, ~/.cortexllm/scripts/save-context.py
  - bin/cortexagent            → ~/llama.cpp/build, ~/models, ~/cortexllm/repo/...
  - lib/overseer.py            → ~/.cortexagent
That worked for the original single-machine setup but broke portability and
made the personal-vs-distributable difference impossible to express.

This module centralizes every path/setting behind one resolver with a clear
precedence:

    1. environment variable   (highest — always wins)
    2. ~/.cortexagent/cortexagent.conf   (user config file, INI format)
    3. sensible default        (lowest — matches the original hardcoded values)

CRITICAL: the defaults are intentionally the *original* hardcoded values, so an
existing install (e.g. the developer's) keeps behaving identically with NO config
file and NO env vars. New users / AppImage installs get the same standard paths
in their own $HOME (fresh, empty DBs created on first run). The personal-vs-
distributable delta is expressed purely through env vars / the conf file — never
through different code.

Usage (Python):
    from lib.config import CFG
    CFG.db_path, CFG.cortexllm_dir, CFG.backend, ...

Usage (bash hooks — no shell sourcing needed):
    python3 "$REPO_ROOT/lib/config.py" get db_path
    python3 "$REPO_ROOT/lib/config.py" get cortexllm_socket
    python3 "$REPO_ROOT/lib/config.py" shell        # emit `export` lines
"""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Config file location ────────────────────────────────────────────────────
# The conf file is OPTIONAL. Defaults below match the original hardcoded values,
# so an existing install needs no conf file to keep working identically.
CONF_FILE = Path(os.environ.get(
    "CORTEXAGENT_CONF",
    str(Path.home() / ".cortexagent" / "cortexagent.conf"),
))


def _load_conf() -> configparser.ConfigParser:
    """Load the optional user conf file (INI). Missing file → empty config."""
    cp = configparser.ConfigParser()
    # interpolate=False so {{HOME}}-style placeholders in values aren't mangled
    cp = configparser.ConfigParser(interpolation=None)
    if CONF_FILE.exists():
        try:
            cp.read(CONF_FILE)
        except Exception:
            pass  # malformed conf → fall back to defaults silently
    return cp


_CONF = _load_conf()


def _env(name: str, conf_section: str, conf_key: str,
         default: Optional[str] = None) -> Optional[str]:
    """Resolve a value: env var → conf [section] key → default."""
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


# ── Locked model settings (Phase C) ──────────────────────────────────────────
# These pinned values OVERRIDE env vars + the conf for the big-model llama-server
# args, so a stray CORTEXAGENT_CTX / conf edit / launcher default can't silently
# OOM the 16 GB card again (that was the original hang). The lock is the single
# chokepoint: every Python caller reads CFG.big_ctx etc. The bash launcher
# honors it by sourcing `python3 lib/config.py shell-locked`.
#
# Bypass: CORTEXAGENT_UNLOCK=1 (all keys) or CORTEXAGENT_UNLOCK_<KEY>=1 for one
# key (e.g. CORTEXAGENT_UNLOCK_BIG_CTX=1) — the testing/tuning escape hatch.
# When unlocked, env > conf > default precedence is restored for that key.
LOCKED_KEYS = {
    "big_ctx": 131072,
    "big_ub": 1024,
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
    """Record (once) if env or conf would have produced a different value."""
    envval = os.environ.get(env_name)
    conf_val = None
    try:
        if _CONF.has_option(conf_section, conf_key):
            conf_val = _CONF.get(conf_section, conf_key)
    except Exception:
        pass
    if (envval is not None and str(envval) != str(pinned)) or (
            conf_val is not None and str(conf_val) != str(pinned)):
        _LOCK_LOG.append(
            f"LOCK: {name} env={envval!r} conf={conf_val!r} -> pinned={pinned}")


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
    """Where does the CortexLLM code live?

    Preference:
      1. CORTEXLLM_DIR env / conf        (explicit)
      2. ~/cortexllm/repo                 (global default install)
      3. <repo>/cortexllm                 (vendored copy — new users / AppImage)
    """
    explicit = _env("CORTEXLLM_DIR", "cortexllm", "dir")
    if explicit:
        return str(Path(explicit).expanduser())
    existing = Path.home() / "cortexllm" / "repo"
    if existing.is_dir():
        return str(existing)
    return str(REPO_ROOT / "cortexllm")


class Config:
    """Resolved configuration. Instantiate once (CFG below)."""

    def __init__(self) -> None:
        home = Path.home()

        # ── Core directories ────────────────────────────────────────────────
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

        # ── Memory DB ──────────────────────────────────────────────────────
        # The agent DB and the CortexLLM DB are the SAME file by design
        # (CortexLLM is fully integrated — agent memory IS shared memory).
        # Default = the standard CortexLLM location. Existing install: unchanged.
        # New user: fresh empty DB created here on first run.
        self.db_path = Path(_env(
            "CORTEXAGENT_DB_PATH", "memory", "db_path",
            str(home / ".config" / "cortexllm" / "cortexllm.db")))
        self.cortexllm_db_path = Path(_env(
            "CORTEXLLM_DB_PATH", "memory", "cortexllm_db_path",
            str(self.db_path)))  # defaults to the same file
        self.cortexllm_memory_dir = Path(_env(
            "CORTEXLLM_MEMORY_DIR", "memory", "cortexllm_memory_dir",
            str(home / ".config" / "cortexllm" / "memory")))

        # ── CortexLLM code + daemon runtime ───────────────────────────────
        self.cortexllm_dir = Path(_detect_cortexllm_dir())
        self.cortexllm_mcp_server = self.cortexllm_dir / "cortexllm_mcp_server.py"
        self.cortexllm_socket = Path(_env(
            "CORTEXLLM_SOCKET", "cortexllm", "socket",
            str(home / ".cortexllm" / "memory.sock")))
        self.cortexllm_save_script = Path(_env(
            "CORTEXLLM_SAVE_SCRIPT", "cortexllm", "save_script",
            str(home / ".cortexllm" / "scripts" / "save-context.py")))
        self.cortexllm_hot_file = self.cortexllm_memory_dir / "hot" / "cortexagent.jsonl"

        # ── Model backend ──────────────────────────────────────────────────
        # llamacpp = both models on llama-server (fastest, default).
        # (ollama removed — kept as a string only for future opt-in.)
        self.backend = _env(
            "CORTEXAGENT_BACKEND", "backend", "kind", "llamacpp") or "llamacpp"
        self.llama_dir = Path(_env(
            "CORTEXAGENT_LLAMA_DIR", "backend", "llama_dir",
            str(home / "llama.cpp" / "build")))
        self.models_dir = Path(_env(
            "CORTEXAGENT_MODELS_DIR", "backend", "models_dir",
            str(home / "models")))
        # Big model — empty by default; users MUST configure their own (env
        # CORTEXAGENT_MODEL or ini [backend] big_model). The shipped defaults
        # would otherwise pin new users to a 13 GB IQ3_S that won't fit their
        # GPU. Set this to your own model file path to override.
        self.big_model = _env(
            "CORTEXAGENT_MODEL", "backend", "big_model", "")
        self.big_model_port = _env_int(
            "CORTEXAGENT_PORT", "backend", "big_model_port", 8080)
        self.tiny_model_port = _env_int(
            "CORTEXAGENT_TINY_PORT", "backend", "tiny_model_port", 8082)
        self.tiny_model = _env(
            "CORTEXAGENT_TINY_MODEL", "backend", "tiny_model",
            str(self.models_dir / "lfm2.5-1.2b" / "LFM2.5-1.2B-Instruct-Q4_K_M.gguf"))

        # Vision: REMOVED in v3.x. The big model is multimodal (Qwen3-VL family
        # fine-tunes / Qwen3.6 35B), so a separate vision server (formerly
        # qwen3vl-8b on :8083) is no longer needed. Big handles vision natively
        # and orchestrates image/video gen via diffusers in-process. To re-add
        # a separate vision model, subclass and override big_model with a
        # vision-capable path.

        # ── Big model llama-server args (daemon-managed; mirror the launcher) ─
        # These mirror the env vars bin/cortexagent already reads, so an existing
        # shell profile keeps working. The daemon uses them to own the big model.
        # Context window. 262144 (256k) OOMs a 16 GB card at ub>=2048:
        # --kv-unified makes the compute-buffer reservation scale with ubatch,
        # and at 256k the compute buffer alone is ~1.7 GB on top of the 14.3 GB
        # IQ3_S weights. 131072 (128k) is the tuned value: the hybrid model's KV
        # cache is tiny (~5 KB/token → ~0.6 GB at 128k), so at ub=1024 weights +
        # KV + buffer ≈ 14.1 GB, and with the lean tiny resident ≈ 14.7 GB —
        # a ~1.6 GB margin on 16 GB, with the full 128k window for long sessions.
        # (Measured: 35B = 13.7 GB at 128k/ub512; ub=1024 adds ~0.43 GB buffer.)
        # LOCKED in LOCKED_KEYS below; override only via CORTEXAGENT_UNLOCK=1.
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
        # Prompt-eval batching. ubatch (-ub) is the physical batch and the
        # lever for the compute/graph buffer under --kv-unified: 512 reserves
        # ~0.43 GB, 1024 ~0.86 GB, 2048 ~1.7 GB. 1024 doubles prompt-eval
        # parallelism vs 512 (the 30-tool system prompt evals in half the
        # chunks → faster prompt eval) while staying inside the 16 GB budget
        # (35B process ≈ 14.1 GB at 128k/ub1024 + tiny 0.6 GB ≈ 14.7 GB, ~1.6 GB
        # margin). Token-generation speed is unaffected (governed by -b).
        # LOCKED in LOCKED_KEYS below; override only via CORTEXAGENT_UNLOCK=1.
        self.big_b = _env_int(
            "CORTEXAGENT_B", "backend", "big_b", 2048)
        self.big_ub = _env_locked_int(
            "big_ub", "CORTEXAGENT_UB", "backend", "big_ub", 1024)
        self.big_kv_offload = _env_locked_int(
            "big_kv_offload", "CORTEXAGENT_KV_OFFLOAD", "backend", "big_kv_offload", 1)
        self.big_alias = _env(
            "CORTEXAGENT_ALIAS", "backend", "big_alias", "cortexagent")
        self.big_log = Path(_env(
            "CORTEXAGENT_LOG", "backend", "big_log",
            str(home / ".cortexagent-server.log")))

        # ── big_vram_min_gb (informational; no fallback swap happens) ─────
        # Historical: a smaller fallback model was swapped in when free VRAM
        # was below this threshold. Removed 2026-08-11 — the only model the
        # daemon now serves on :8080 is the big one (with the tiny llama
        # on :8082 powering the overseer). If the big 35B can't load (e.g.
        # the GGUF is missing), the daemon logs the failure and leaves :8080
        # down rather than swapping in a substitute.
        self.big_vram_min_gb = _env_int(
            "CORTEXAGENT_BIG_VRAM_MIN", "backend", "big_vram_min_gb", 14)

        # ── Daemon / idle VRAM management ──────────────────────────────────
        # Big model stays loaded at all times (user pref: "keep it loaded").
        # Set to 0 to disable idle-unload entirely. Any positive value is the
        # grace period in seconds before the daemon unloads big after the last
        # session ends. 0 = never unload (recommended; saves the swap latency
        # the user perceived as bad UX).
        self.idle_unload_sec = _env_int(
            "CORTEXAGENT_IDLE_UNLOAD_SEC", "daemon", "idle_unload_sec", 0)
        # A session that claims the big model but has produced NO request for
        # this long is stale (wrapper died without session-end — SIGPIPE,
        # SIGKILL, orphaned bash). Released so idle-unload can free VRAM.
        # Generous default: longer than any realistic human think gap.
        self.stale_session_sec = _env_int(
            "CORTEXAGENT_STALE_SESSION_SEC", "daemon", "stale_session_sec", 1800)
        self.control_socket = self.state_dir / "control.sock"

        # ── Display / UX ───────────────────────────────────────────────────
        # inline_scroll=0 → Claude Code locked-screen TUI (non-scroll, the
        # "Swooping…" in-place feel). =1 → inline scroll (legacy).
        self.inline_scroll = _env_bool(
            "CORTEXAGENT_INLINE_SCROLL", "display", "inline_scroll", False)

        # ── Optional integrations ──────────────────────────────────────────
        self.browser_enabled = _env_bool(
            "CORTEXAGENT_BRAVE_ENABLED", "integrations", "browser_enabled", True)
        self.firecrawl_enabled = _env_bool(
            "CORTEXAGENT_FIRECRAWL_ENABLED", "integrations", "firecrawl_enabled", True)

        # ── Branding (configurable; default neutral for distribution) ───────
        self.brand = _env("CORTEXAGENT_BRAND", "branding", "name", "CortexAgent")
        self.author = _env("CORTEXAGENT_AUTHOR", "branding", "author", "GreyOK00")

    # ── Helpers ────────────────────────────────────────────────────────────
    def ensure_dirs(self) -> None:
        """Create runtime dirs. Safe to call repeatedly."""
        for d in (self.state_dir, self.logs_dir, self.profiles_dir / "default",
                  self.db_path.parent, self.cortexllm_memory_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def as_dict(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items()}

    def shell_exports(self) -> str:
        """Emit `export KEY=value` lines for bash sourcing."""
        lines = []
        for k, v in self.as_dict().items():
            lines.append(f"export CORTEXAGENT_CFG_{k.upper()}={repr(str(v))}")
        return "\n".join(lines)

    def locked_keys(self) -> dict:
        """Return {key: (pinned, active, unlocked?)} for status display."""
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

# Emit lock divergences once at import (one line per key env/conf tried to
# change). Normally empty → silent. Suppressed if CORTEXAGENT_LOCK_QUIET=1.
if _LOCK_LOG and os.environ.get("CORTEXAGENT_LOCK_QUIET", "").lower() not in (
        "1", "true", "yes", "on"):
    for line in _LOCK_LOG:
        print(f"[config] {line}", file=sys.stderr)


# ── CLI for bash hooks ──────────────────────────────────────────────────────
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
        # Emit `export CORTEXAGENT_*` for the locked keys only, so the bash
        # launcher can source the pinned values regardless of the user's env.
        # Honors CORTEXAGENT_UNLOCK: when a key is unlocked, emit the env/conf
        # value (fall through to normal resolution) instead of the pin.
        env_map = {
            "big_ctx": ("CORTEXAGENT_CTX", 131072),
            "big_ub": ("CORTEXAGENT_UB", 1024),
            "big_ngl": ("CORTEXAGENT_NGL", 999),
            "big_fa": ("CORTEXAGENT_FA", "on"),
            "big_ctk": ("CORTEXAGENT_CTK", "q4_0"),
            "big_ctv": ("CORTEXAGENT_CTV", "q4_0"),
            "big_kv_offload": ("CORTEXAGENT_KV_OFFLOAD", 1),
            "big_np": ("CORTEXAGENT_NP", 1),
        }
        for key, (env_name, pinned) in env_map.items():
            if _unlock_for(key):
                # unlocked: emit whatever the normal resolver produced
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