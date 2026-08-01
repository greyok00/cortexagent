#!/usr/bin/env python3
"""profiles — per-profile state directory + workspace registry.

Ported (minimal) from OpenClaw's agents.list pattern. Each profile gets its
own state directory under ~/.cortexagent/profiles/<name>/ with subdirs for
memory, workspace, sandboxes, logs.

Used by dispatcher, cold_distiller, heartbeat_service, and the web UI to
isolate per-profile state without colliding.

Stdlib only.

Env knobs:
  CORTEXAGENT_PROFILES_DIR  default ~/.cortexagent/profiles
  CORTEXAGENT_DEFAULT_PROFILE  default "default"

CLI:
  python3 profiles.py list                # list all profiles
  python3 profiles.py show [NAME]         # show paths for a profile (default: default)
  python3 profiles.py create NAME         # create a new profile
  python3 profiles.py delete NAME         # delete a profile (with --force)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULT_PROFILE = "default"


def _profiles_root() -> Path:
    raw = os.environ.get("CORTEXAGENT_PROFILES_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cortexagent" / "profiles"


def default_profile_name() -> str:
    return os.environ.get("CORTEXAGENT_DEFAULT_PROFILE", _DEFAULT_PROFILE)


def ensure_default_profile() -> Path:
    """Create the default profile if it doesn't exist. Returns its root."""
    root = profile_dir(default_profile_name())
    if not root.exists():
        _create_profile_dirs(root)
    return root


def profile_dir(name: str) -> Path:
    """Return the root dir for a profile, without creating it."""
    safe = _safe_name(name)
    return _profiles_root() / safe


def list_profiles() -> List[str]:
    """List all profiles that exist on disk."""
    root = _profiles_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith("."))


def create_profile(name: str) -> Path:
    """Create a profile and its subdirs. Idempotent."""
    root = profile_dir(name)
    _create_profile_dirs(root)
    return root


def delete_profile(name: str, force: bool = False) -> bool:
    """Delete a profile and all its state. Refuses without --force."""
    root = profile_dir(name)
    if not root.exists():
        return False
    if name == default_profile_name() and not force:
        raise ValueError(f"refusing to delete default profile '{name}' without force=True")
    shutil.rmtree(root)
    return True


def get_state_dir(name: str) -> Path:
    """Per-profile state (loop_guard state, heartbeat state, etc.)."""
    return profile_dir(name) / "state"


def get_memory_dir(name: str) -> Path:
    """Per-profile memory scratch. (Real memory lives in ~/.cortexagent/memory/.)"""
    return profile_dir(name) / "memory"


def get_workspace(name: str) -> Path:
    """Per-profile working directory the agent writes into."""
    return profile_dir(name) / "workspace"


def get_sandboxes(name: str) -> Path:
    """Per-profile sandbox root used by the dispatcher."""
    return profile_dir(name) / "sandboxes"


def get_logs(name: str) -> Path:
    """Per-profile log directory."""
    return profile_dir(name) / "logs"


def profile_summary(name: str) -> Dict:
    """Return path + existence for each per-profile subdir."""
    root = profile_dir(name)
    subdirs = {
        "state": get_state_dir(name),
        "memory": get_memory_dir(name),
        "workspace": get_workspace(name),
        "sandboxes": get_sandboxes(name),
        "logs": get_logs(name),
    }
    return {
        "name": name,
        "root": str(root),
        "exists": root.exists(),
        "subdirs": {k: {"path": str(v), "exists": v.exists()} for k, v in subdirs.items()},
    }


def _safe_name(name: str) -> str:
    """Sanitize profile names — only alnum, dash, underscore."""
    if not name or not isinstance(name, str):
        raise ValueError(f"invalid profile name: {name!r}")
    if any(c for c in name if not (c.isalnum() or c in "-_.")):
        raise ValueError(f"profile name must be alnum / - / _ / .: {name!r}")
    return name


def _create_profile_dirs(root: Path) -> None:
    for sub in ("state", "memory", "workspace", "sandboxes", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    # Write a metadata file so we can detect profile version later
    meta = root / "profile.json"
    if not meta.exists():
        meta.write_text(json.dumps({
            "name": root.name,
            "version": 1,
            "created_at": _now_iso(),
        }, indent=2))


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


# ── CLI ─────────────────────────────────────────────────────────────────────
def _cli(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd, *rest = argv
    if cmd == "list":
        names = list_profiles()
        if not names:
            print("(no profiles — run `profiles.py create <name>`)")
        else:
            for n in names:
                marker = " (default)" if n == default_profile_name() else ""
                print(f"{n}{marker}")
        return 0
    if cmd == "show":
        name = rest[0] if rest else default_profile_name()
        import json
        print(json.dumps(profile_summary(name), indent=2))
        return 0
    if cmd == "create":
        if not rest:
            print("usage: profiles.py create NAME", file=sys.stderr)
            return 2
        root = create_profile(rest[0])
        print(f"created {root}")
        return 0
    if cmd == "delete":
        if not rest:
            print("usage: profiles.py delete NAME [--force]", file=sys.stderr)
            return 2
        force = "--force" in rest
        name = rest[0]
        try:
            ok = delete_profile(name, force=force)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"deleted {name}" if ok else f"profile {name} did not exist")
        return 0
    if cmd == "ensure-default":
        root = ensure_default_profile()
        print(f"default profile ready at {root}")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))