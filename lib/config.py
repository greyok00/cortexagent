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
        self.big_model = _env(
            "CORTEXAGENT_MODEL", "backend", "big_model",
            str(self.models_dir / "qwen3.6-35b-iq3s" /
                "Qwen3.6-35B-A3B-UD-IQ3_S.gguf"))
        self.big_model_port = _env_int(
            "CORTEXAGENT_PORT", "backend", "big_model_port", 8080)
        self.tiny_model_port = _env_int(
            "CORTEXAGENT_TINY_PORT", "backend", "tiny_model_port", 8082)
        self.tiny_model = _env(
            "CORTEXAGENT_TINY_MODEL", "backend", "tiny_model",
            str(self.models_dir / "qwen2.5-0.5b" / "qwen2.5-0.5b-q4_0.gguf"))

        # ── Big model llama-server args (daemon-managed; mirror the launcher) ─
        # These mirror the env vars bin/cortexagent already reads, so an existing
        # shell profile keeps working. The daemon uses them to own the big model.
        self.big_ctx = _env_int(
            "CORTEXAGENT_CTX", "backend", "big_ctx", 262144)
        self.big_ngl = _env_int(
            "CORTEXAGENT_NGL", "backend", "big_ngl", 999)
        self.big_fa = _env(
            "CORTEXAGENT_FA", "backend", "big_fa", "on")
        self.big_ctk = _env(
            "CORTEXAGENT_CTK", "backend", "big_ctk", "q4_0")
        self.big_ctv = _env(
            "CORTEXAGENT_CTV", "backend", "big_ctv", "q4_0")
        self.big_np = _env_int(
            "CORTEXAGENT_NP", "backend", "big_np", 1)
        self.big_kv_offload = _env_int(
            "CORTEXAGENT_KV_OFFLOAD", "backend", "big_kv_offload", 1)
        self.big_alias = _env(
            "CORTEXAGENT_ALIAS", "backend", "big_alias", "cortexagent")
        self.big_log = Path(_env(
            "CORTEXAGENT_LOG", "backend", "big_log",
            str(home / ".cortexagent-server.log")))

        # ── Daemon / idle VRAM management ──────────────────────────────────
        self.idle_unload_sec = _env_int(
            "CORTEXAGENT_IDLE_UNLOAD_SEC", "daemon", "idle_unload_sec", 600)
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
        self.author = _env("CORTEXAGENT_AUTHOR", "branding", "author", "CortexAgent")

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


CFG = Config()


# ── CLI for bash hooks ──────────────────────────────────────────────────────
def _cli() -> int:
    if len(sys.argv) < 2:
        print("usage: config.py get <key> | shell | list", file=sys.stderr)
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
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli())