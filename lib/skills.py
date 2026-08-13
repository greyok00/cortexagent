#!/usr/bin/env python3
"""lib/skills.py — skills system for the CortexAgent harness.

Skills are reusable capability bundles, modularized the way slimtoken and
cortexllm are. Each skill is a Python module exposing:

    NAME        — unique skill name (kebab-case)
    DESCRIPTION — one-line description shown to the model
    SCHEMA      — {"type": "object", "properties": {...}, "required": [...]}
    run(args)   — callable returning {"ok": bool, "output": str, "error": str}

Skills load from a directory (default ``~/.cortexagent/skills/``) and register
in the tool registry as ``skill_<name>`` so the overseer react loop can call
them like any other tool.

Usage:
  python3 lib/skills.py smoke          # self-test
  python3 lib/skills.py list           # list loaded skills
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.tool_registry import register_tool  # noqa: E402

DEFAULT_SKILLS_DIR = Path(os.environ.get(
    "CORTEXAGENT_SKILLS_DIR", "~/.cortexagent/skills")).expanduser()

# name -> {"description", "schema", "run"}
SKILLS: Dict[str, Dict[str, Any]] = {}


def register_skill(name: str, description: str, schema: Dict[str, Any],
                   run: Callable) -> None:
    """Add a skill at runtime. ``run`` must return {"ok", "output", "error"}."""
    SKILLS[name] = {"description": description, "schema": schema, "run": run}


def _load_module(path: Path) -> Optional[Dict[str, Any]]:
    """Load one skill module file. Returns None on any failure."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"cortexagent_skill_{path.stem}", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        name = getattr(mod, "NAME", path.stem)
        description = getattr(mod, "DESCRIPTION", "")
        schema = getattr(mod, "SCHEMA", {"type": "object", "properties": {}})
        run = getattr(mod, "run", None)
        if not callable(run):
            print(f"skills: {path.name} has no callable run()", file=sys.stderr)
            return None
        return {"name": name, "description": description,
                "schema": schema, "run": run}
    except Exception as e:
        print(f"skills: failed to load {path.name}: {e}", file=sys.stderr)
        return None


def load_skills_dir(path: Optional[Path] = None) -> int:
    """Load skill modules from a directory. Returns count loaded. Idempotent."""
    d = Path(path) if path else DEFAULT_SKILLS_DIR
    if not d.exists():
        return 0
    count = 0
    for f in sorted(d.glob("*.py")):
        if f.name.startswith("_"):
            continue
        skill = _load_module(f)
        if skill and skill["name"] not in SKILLS:
            register_skill(skill["name"], skill["description"],
                           skill["schema"], skill["run"])
            count += 1
    return count


def list_skills() -> List[Dict[str, Any]]:
    """Return the loaded skills as a sorted list of dicts."""
    return [{"name": n, "description": s["description"]}
            for n, s in sorted(SKILLS.items())]


def run_skill(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a skill by name. Returns {"ok", "output", "error"}."""
    skill = SKILLS.get(name)
    if skill is None:
        return {"ok": False, "output": "", "error": f"unknown skill: {name}"}
    try:
        result = skill["run"](**args)
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, "output": str(result), "error": ""}
    except TypeError as e:
        return {"ok": False, "output": "", "error": f"skill {name} bad args: {e}"}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"skill {name} failed: {e}"}


def register_skill_tools() -> int:
    """Register every loaded skill as ``skill_<name>`` in the tool registry."""
    from lib.tool_registry import TOOLS
    count = 0
    for name, s in sorted(SKILLS.items()):
        full = f"skill_{name}"
        if full in TOOLS:
            continue
        schema = s["schema"] or {"type": "object", "properties": {}}
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        register_tool(full, {
            "description": s["description"],
            "parameters": {"type": "object", "properties": props,
                           "required": required}},
            _make_handler(name))
        count += 1
    return count


def _make_handler(name: str):
    def _handler(**kwargs: Any) -> Dict[str, Any]:
        return run_skill(name, kwargs)
    return _handler


def _smoke() -> int:
    n = load_skills_dir()
    print(f"skills dir: {DEFAULT_SKILLS_DIR} — loaded {n}")
    for s in list_skills():
        print(f"  skill_{s['name']}: {s['description'][:60]}")
    print("skills: OK")
    return 0


def _list() -> int:
    load_skills_dir()
    for s in list_skills():
        print(f"skill_{s['name']}: {s['description']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        sys.exit(_list())
    print("usage: skills.py smoke | list", file=sys.stderr)
    sys.exit(2)
