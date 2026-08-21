# Reframing Engine Implementation Plan (Process B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained reframing engine that frames any prompt as ongoing work (session + memory + project context), live at `~/reframing-engine/`.

**Architecture:** A standalone project at `~/reframing-engine/` with a single canonical module `reframing_engine.py` that runs a 4-stage pipeline — CLEAN (slimtoken `reframe_prompt`), CLASSIFY (slimtoken `classify_domain`), GATHER CONTEXT (caller-supplied adapters implementing Protocols in `adapters.py`), FRAME (compose the "not a one-shot" prompt + `build_system`). Context sources are pluggable adapters; the engine never imports cortexagent/cortexllm. The cortexagent repo imports the engine **one-way**.

**Tech Stack:** Python 3.10+ stdlib, `slimtoken.prompt_reframe` (deterministic base), pytest. No new models, no LLM calls in the base path.

## Global Constraints (from the spec, verbatim)

- **Self-contained (HARD).** The reframing engine works by itself — no hard imports of cortexagent, cortexllm, or any agent runtime. stdlib + slimtoken only. Context sources are caller-supplied adapters.
- **No new models.** LLM reconstruction (if any) reuses the resident big model or overseer — zero new VRAM. (Not used in Process B; base path has no LLM.)
- **Reuse slimtoken** as the deterministic base — no duplicated reframing logic.
- **Localhost-only bindings** (127.0.0.1, never 0.0.0.0) for any server.
- **No PII leaks.** Use `Path.home()` / env vars, never hardcoded paths.
- **Process B and Process A (STT fix) are SEPARATE. DO NOT MERGE.** This plan is Process B only. The STT fix (Process A) gets its own plan.

---

## File Structure

```
~/reframing-engine/            ← NEW git repo (task 1 `git init`)
├── adapters.py                # Context Protocols + deterministic Static sample adapters
├── reframing_engine.py        # Canonical self-contained engine (4-stage pipeline)
├── reframe                    # Executable CLI (stdin or argv → framed output)
├── mcp_server.py              # stdio MCP server exposing reframe/classify/clean
├── demo.py                    # Before/after walkthrough with sample adapters
├── README.md                  # Usage + self-containment contract
├── research/
│   └── stt-fix-research.md    # Process A scope + VRAM constraints (separate workstream)
└── tests/
    ├── conftest.py            # inserts project root on sys.path
    ├── test_adapters.py
    ├── test_engine.py
    └── test_cli.py

cortexagent/                    ← existing repo, one-way import only
└── tests/test_reframing_import.py   # proves cortexagent→engine import works & engine stays clean
```

---

### Task 1: Scaffold project + adapters

**Files:**
- Create: `~/reframing-engine/adapters.py`
- Create: `~/reframing-engine/tests/conftest.py`
- Create: `~/reframing-engine/tests/test_adapters.py`

**Interfaces:**
- Produces: `adapters.py` — `SessionAdapter`, `MemoryAdapter`, `ProjectAdapter` (Protocols) + `StaticSession`, `StaticMemory`, `StaticProject` (sample adapters; `context()` returns `Optional[str]`, `None` when empty).

- [ ] **Step 1: git init + scaffold**

Run:
```bash
mkdir -p ~/reframing-engine/tests ~/reframing-engine/research
cd ~/reframing-engine && git init
printf '__pycache__/\n*.pyc\n' > ~/reframing-engine/.gitignore
```
Expected: repo initialized, folders exist.

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""pytest conftest — make the project root importable from tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: Write the failing adapter test**

`tests/test_adapters.py`:
```python
from adapters import StaticSession, StaticMemory, StaticProject


def test_static_session_empty_is_none():
    assert StaticSession("").context() is None


def test_static_session_with_text_returns_text():
    assert StaticSession("Working on proxy auth.").context() == "Working on proxy auth."


def test_static_memory_empty_is_none():
    assert StaticMemory("").context("fix bug", "code") is None


def test_static_memory_returns_text():
    assert StaticMemory("Fixed token accounting.").context("fix", "code") == "Fixed token accounting."


def test_static_project_empty_is_none():
    assert StaticProject("").context() is None


def test_static_project_returns_text():
    assert StaticProject("cortex-toolproxy, branch master").context() == "cortex-toolproxy, branch master"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_adapters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapters'`

- [ ] **Step 5: Write `adapters.py`**

```python
"""adapters — context-source interfaces for the reframing engine.

The engine (reframing_engine.py) never imports these concrete adapters.
Callers supply adapter objects that implement the Protocols below; the
engine holds no reference to any runtime. Zero adapters is a valid config
(the engine then frames with domain only).
"""
from __future__ import annotations

from typing import Optional, Protocol


class SessionAdapter(Protocol):
    """Current session state — recent turns, active task."""

    def context(self) -> Optional[str]:
        """Return a short context string, or None if nothing to attach."""
        ...


class MemoryAdapter(Protocol):
    """Relevant memory for a given prompt."""

    def context(self, prompt: str, domain: str) -> Optional[str]:
        """Return relevant memory, or None."""
        ...


class ProjectAdapter(Protocol):
    """Project context: CLAUDE.md/README, active branch."""

    def context(self) -> Optional[str]:
        """Return project context, or None."""
        ...


# ── Sample adapters (deterministic; for tests + demo) ───────────────────────
class StaticSession:
    def __init__(self, text: str) -> None:
        self._text = text

    def context(self) -> Optional[str]:
        return self._text or None


class StaticMemory:
    def __init__(self, text: str) -> None:
        self._text = text

    def context(self, prompt: str, domain: str) -> Optional[str]:
        return self._text or None


class StaticProject:
    def __init__(self, text: str) -> None:
        self._text = text

    def context(self) -> Optional[str]:
        return self._text or None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_adapters.py -v`
Expected: PASS — 6 passed

- [ ] **Step 7: Commit**

```bash
cd ~/reframing-engine
git add adapters.py tests/conftest.py tests/test_adapters.py .gitignore
git commit -m "feat: adapters — context-source Protocols + Static samples"
```

---

### Task 2: Engine core — CLEAN → CLASSIFY → GATHER → FRAME

**Files:**
- Create: `~/reframing-engine/reframing_engine.py`
- Create: `~/reframing-engine/tests/test_engine.py`

**Interfaces:**
- Consumes: `adapters.py` Protocols from Task 1; `slimtoken.prompt_reframe` resolved by the engine's own resolver (fallback to `~/slimtoken/src/slimtoken/prompt_reframe.py`).
- Produces:
  - `reframing_engine.reframe(prompt, *, session=None, memory=None, project=None, role="generalist", style="terse") -> ReframeResult`
  - `ReframeResult` dataclass: `framed`, `system`, `domain`, `sources`, `cleaned`.

- [ ] **Step 1: Write the failing engine test**

`tests/test_engine.py`:
```python
from adapters import StaticSession, StaticMemory, StaticProject
from reframing_engine import reframe


def test_no_adapters_frames_domain_only():
    r = reframe("can you basically just help me fix the bug in the auth flow please")
    assert r.domain == "code"
    assert "the bug in the auth flow" in r.cleaned
    assert r.framed == r.cleaned          # no context blocks → prompt unchanged
    assert r.sources == []
    assert "Role: generalist" in r.system


def test_all_three_adapters_attach_context():
    r = reframe(
        "fix the bug in the auth flow",
        session=StaticSession("Working on the proxy auth."),
        memory=StaticMemory("We fixed token accounting on 2026-08-19."),
        project=StaticProject("cortex-toolproxy, branch master"),
    )
    assert "Ongoing work: Working on the proxy auth." in r.framed
    assert "Known from memory: We fixed token accounting on 2026-08-19." in r.framed
    assert "Project: cortex-toolproxy, branch master" in r.framed
    assert f"User request: {r.cleaned}" in r.framed
    assert r.sources == ["session", "memory", "project"]


def test_empty_adapter_context_is_omitted():
    r = reframe("fix the bug", session=StaticSession(""))
    assert r.sources == []
    assert "Ongoing work" not in r.framed
    assert r.framed == r.cleaned


def test_result_has_all_fields():
    r = reframe("hello")
    assert r.cleaned and r.system and r.domain == "general"
    assert r.sources == []
    assert r.framed == r.cleaned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reframing_engine'`

- [ ] **Step 3: Write `reframing_engine.py`**

```python
"""reframing_engine — frame any prompt as ongoing work (self-contained).

Pipeline (4 stages):
  1. CLEAN      → slimtoken reframe_prompt (strip filler, dedupe)
  2. CLASSIFY   → slimtoken classify_domain (business/code/osint/…)
  3. GATHER     → caller-supplied adapters (session / memory / project)
  4. FRAME      → compose the "not a one-shot" prompt + build_system

Self-contained (HARD): stdlib + slimtoken.prompt_reframe only. No imports
of cortexagent, cortexllm, or any agent runtime. Context sources arrive as
caller-supplied adapter objects (see adapters.py); zero adapters is valid.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_LOCAL_REF = Path(__file__).resolve().parent.parent / "slimtoken" / "src" \
    / "slimtoken" / "prompt_reframe.py"


def _resolve_reframe():
    """Import slimtoken.prompt_reframe, preferring the canonical local repo."""
    try:
        from slimtoken import prompt_reframe as pr
        pr.frame_prompt
        return pr
    except (ImportError, AttributeError):
        if not _LOCAL_REF.is_file():
            raise RuntimeError(
                "no reframing base: slimtoken.prompt_reframe is missing")
        spec = importlib.util.spec_from_file_location(
            "slim_reframe_local", _LOCAL_REF)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


_pr = _resolve_reframe()


@dataclass
class ReframeResult:
    framed: str          # the composed "not a one-shot" prompt
    system: str          # build_system(domain, role, style)
    domain: str          # classify_domain result
    sources: List[str]   # adapter names that attached context
    cleaned: str         # the cleaned prompt (pre-framing)


def reframe(
    prompt: str,
    *,
    session: Optional[object] = None,
    memory: Optional[object] = None,
    project: Optional[object] = None,
    role: str = "generalist",
    style: str = "terse",
) -> ReframeResult:
    """Frame a prompt as ongoing work.

    ``session`` / ``memory`` / ``project`` are caller-supplied adapters
    conforming to the Protocols in ``adapters.py``. Each is optional; pass
    None (or omit) to disable. With none supplied, the prompt is framed
    with domain framing only.
    """
    cleaned = (_pr.reframe_prompt(prompt) or prompt).strip()
    domain = _pr.classify_domain(cleaned)
    system = _pr.build_system(domain, role=role, style=style)

    blocks: List[str] = []
    sources: List[str] = []

    if session is not None:
        ctx = session.context()
        if ctx:
            blocks.append(f"Ongoing work: {ctx}")
            sources.append("session")

    if memory is not None:
        ctx = memory.context(cleaned, domain)
        if ctx:
            blocks.append(f"Known from memory: {ctx}")
            sources.append("memory")

    if project is not None:
        ctx = project.context()
        if ctx:
            blocks.append(f"Project: {ctx}")
            sources.append("project")

    if blocks:
        framed = "\n".join(blocks) + f"\n\nUser request: {cleaned}"
    else:
        framed = cleaned

    return ReframeResult(
        framed=framed, system=system, domain=domain,
        sources=sources, cleaned=cleaned,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_engine.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
cd ~/reframing-engine
git add reframing_engine.py tests/test_engine.py
git commit -m "feat: engine — CLEAN→CLASSIFY→GATHER→FRAME pipeline, self-contained"
```

---

### Task 3: CLI (`reframe`)

**Files:**
- Create: `~/reframing-engine/reframe` (executable)
- Create: `~/reframing-engine/tests/test_cli.py`

**Interfaces:**
- Consumes: `reframing_engine.reframe`, `adapters.StaticSession/StaticMemory/StaticProject`.
- Produces: `reframe` command — reads prompt from argv or stdin; optional `--no-context`, `--json`, `--role`, `--style`; exit 0 on success, 2 on empty input. Auto-detected context (session tail / memory tail / cwd project+branch) is optional and never fails when files are missing.

- [ ] **Step 1: Write the failing CLI test**

`tests/test_cli.py`:
```python
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "reframe"


def run_cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin, capture_output=True, text=True, cwd=str(ROOT),
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )


def test_cli_prints_framed_prompt():
    proc = run_cli("--no-context", "fix the bug in the auth flow")
    assert proc.returncode == 0
    assert "auth flow" in proc.stdout
    assert "Role:" in proc.stdout


def test_cli_accepts_stdin():
    proc = run_cli("--no-context", stdin="fix the bug please")
    assert proc.returncode == 0
    assert "bug" in proc.stdout


def test_cli_json_output():
    import json
    proc = run_cli("--no-context", "--json", "hello")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "domain" in data and "framed" in data and "system" in data
    assert data["domain"] == "general"


def test_cli_no_prompt_returns_2():
    proc = run_cli("--no-context")
    assert proc.returncode == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — the `reframe` file does not exist.

- [ ] **Step 3: Write the `reframe` CLI**

```python
#!/usr/bin/env python3
"""reframe — CLI for the reframing engine.

Usage:
  reframe "your prompt"
  echo "your prompt" | reframe
  reframe --no-context "domain-only framing"
  reframe --json "your prompt"
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import StaticSession, StaticMemory, StaticProject
from reframing_engine import reframe


def _auto_session() -> str:
    """Tail of the SessionBridge JSONL (last 3 non-empty messages)."""
    p = Path.home() / ".cortexagent" / "state" / "webui_session.jsonl"
    if not p.is_file():
        return ""
    lines = p.read_text(errors="replace").splitlines()[-5:]
    items = []
    for ln in lines:
        try:
            ev = json.loads(ln)
            content = (ev.get("content") or "").strip()
            if content:
                items.append(content[:160])
        except Exception:
            continue
    return "\n".join(items[-3:])


def _auto_memory() -> str:
    """Tail of cortexllm hot+cold memory (last 3 entries)."""
    base = Path.home() / ".config" / "cortexllm" / "memory"
    out = []
    for tier in ("hot", "cold"):
        p = base / tier / "cortexagent.jsonl"
        if not p.is_file():
            continue
        for ln in p.read_text(errors="replace").splitlines()[-3:]:
            try:
                ev = json.loads(ln)
                content = (ev.get("content") or ev.get("text") or "").strip()
                if content:
                    out.append(content[:160])
            except Exception:
                continue
    return "\n".join(out[-3:])


def _auto_project() -> str:
    """cwd name + git branch; never raises."""
    import subprocess
    label = Path.cwd().name
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except Exception:
        branch = ""
    return f"{label}, branch {branch}" if branch else label


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Frame a prompt as ongoing work.")
    ap.add_argument("--no-context", action="store_true",
                    help="skip auto-detected context (domain-only framing)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--role", default="generalist")
    ap.add_argument("--style", default="terse")
    ap.add_argument("prompt", nargs="*", help="prompt text; stdin if empty")
    args = ap.parse_args(argv)

    text = " ".join(args.prompt).strip()
    if not text:
        text = sys.stdin.read().strip()
    if not text:
        print("reframe: no prompt given (argument or stdin)", file=sys.stderr)
        return 2

    session = memory = project = None
    if not args.no_context:
        session = StaticSession(_auto_session())
        memory = StaticMemory(_auto_memory())
        project = StaticProject(_auto_project())

    r = reframe(text, session=session, memory=memory, project=project,
                role=args.role, style=args.style)

    if args.json:
        print(json.dumps(asdict(r), indent=2))
        return 0

    print(r.framed)
    print()
    print(r.system)
    if not r.sources:
        print(f"[domain: {r.domain} | no context attached]")
    else:
        print(f"[context: {', '.join(r.sources)} | domain: {r.domain}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make executable + run tests**

```
chmod +x ~/reframing-engine/reframe
cd ~/reframing-engine && python3 -m pytest tests/test_cli.py -v
```
Expected: PASS — 4 passed

- [ ] **Step 5: Manual smoke**

```
cd ~/reframing-engine && echo "fix the bug in the auth flow" | ./reframe --no-context
```
Expected: framed output + a `Role:` line printed.

- [ ] **Step 6: Commit**

```bash
cd ~/reframing-engine
git add reframe tests/test_cli.py
git commit -m "feat: reframe CLI — argv/stdin input, auto-context, --json"
```

---

### Task 4: MCP server

**Files:**
- Create: `~/reframing-engine/mcp_server.py`
- Create: `~/reframing-engine/tests/test_mcp.py`

**Interfaces:**
- Consumes: `reframing_engine.reframe`, `reframing_engine`'s `_pr.classify_domain` / `_pr.reframe_prompt` (via `reframing_engine` module).
- Produces: stdio MCP JSON-RPC 2.0 server, tools: `reframe.frame` (prompt + optional session/memory/project strings), `reframe.classify`, `reframe.clean`. Responds to `initialize`, `tools/list`, `tools/call`, `notifications/initialized`.

- [ ] **Step 1: Write the failing MCP test**

`tests/test_mcp.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp_server.py"


def call(method, **params):
    """Send one JSON-RPC line to the server and return the parsed reply."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    proc = subprocess.run(
        [sys.executable, str(SERVER)], input=payload,
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    return proc, json.loads(proc.stdout.strip())


def test_initialize():
    proc, reply = call("initialize")
    assert proc.returncode == 0
    assert reply["result"]["serverInfo"]["name"] == "reframing-engine-mcp"


def test_tools_list_has_three_tools():
    proc, reply = call("tools/list")
    names = [t["name"] for t in reply["result"]["tools"]]
    assert "reframe.frame" in names
    assert "reframe.classify" in names
    assert "reframe.clean" in names


def test_frame_tool_with_context():
    payload = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "reframe.frame", "arguments": {
            "prompt": "fix the bug in the auth flow",
            "session": "Working on proxy auth.",
            "memory": "We fixed token accounting.",
            "project": "cortex-toolproxy",
        }},
    }
    proc = subprocess.run([sys.executable, str(SERVER)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(ROOT), timeout=30)
    reply = json.loads(proc.stdout.strip())
    assert proc.returncode == 0
    data = json.loads(reply["result"]["content"][0]["text"])["data"]
    assert data["domain"] == "code"
    assert "Ongoing work: Working on proxy auth." in data["framed"]
    assert data["sources"] == ["session", "memory", "project"]


def test_classify_tool():
    payload = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "reframe.classify",
                   "arguments": {"prompt": "quarterly revenue forecast vs plan"}},
    }
    proc = subprocess.run(
        [sys.executable, str(SERVER)], input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(ROOT), timeout=30)
    reply = json.loads(proc.stdout.strip())
    data = json.loads(reply["result"]["content"][0]["text"])["data"]
    assert data["domain"] == "business"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_mcp.py -v`
Expected: FAIL — `mcp_server.py` does not exist.

- [ ] **Step 3: Write `mcp_server.py`**

```python
"""mcp_server — stdio MCP server exposing the reframing engine.

JSON-RPC 2.0 over stdio (wire-format mirrors slimtoken's
prompt_reframe_server). Thin adapter over reframing_engine: no LLM roundtrip.

Tools (reframe.*):
  reframe.frame     — full pipeline; optional session/memory/project strings
  reframe.classify  — domain classification only
  reframe.clean     — deterministic cleanup only

Usage:
  python3 mcp_server.py            # stdio
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import StaticSession, StaticMemory, StaticProject
from reframing_engine import reframe, _pr

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "reframing-engine-mcp"


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _result(req_id: Any, content: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "result": {"content": content, "isError": False}}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def _schema_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": "reframe.frame",
            "description": ("Full reframing pipeline: clean + classify + "
                            "frame as ongoing work. Optional context strings "
                            "attach session/memory/project context."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "session": {"type": "string",
                                "description": "Optional session context."},
                    "memory": {"type": "string",
                               "description": "Optional memory context."},
                    "project": {"type": "string",
                                "description": "Optional project context."},
                    "role": {"type": "string", "default": "generalist"},
                    "style": {"type": "string", "default": "terse"},
                },
                "required": ["prompt"],
            },
        },
        {
            "name": "reframe.classify",
            "description": "Classify a prompt into a domain "
                           "{business, code, osint, cybersecurity, professional, general}.",
            "inputSchema": {"type": "object",
                            "properties": {"prompt": {"type": "string"}},
                            "required": ["prompt"]},
        },
        {
            "name": "reframe.clean",
            "description": "Deterministic cleanup only (no context framing).",
            "inputSchema": {"type": "object",
                            "properties": {"prompt": {"type": "string"}},
                            "required": ["prompt"]},
        },
    ]


def _content(obj: Any) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}]


def _call_frame(args: Dict[str, Any]) -> Dict[str, Any]:
    session = StaticSession(args.get("session") or "")
    memory = StaticMemory(args.get("memory") or "")
    project = StaticProject(args.get("project") or "")
    r = reframe(
        args.get("prompt", ""),
        session=session, memory=memory, project=project,
        role=args.get("role", "generalist"), style=args.get("style", "terse"),
    )
    return {"domain": r.domain, "framed": r.framed, "system": r.system,
            "cleaned": r.cleaned, "sources": r.sources}


def _call_classify(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"domain": _pr.classify_domain(args.get("prompt", ""))}


def _call_clean(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"cleaned": _pr.reframe_prompt(args.get("prompt", ""))}


_HANDLERS = {
    "reframe.frame": _call_frame,
    "reframe.classify": _call_classify,
    "reframe.clean": _call_clean,
}


def main() -> int:
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME},
                "capabilities": {"tools": {"listChanged": False}},
            }})
            continue

        if method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "tools": _schema_tools()}})
            continue

        if method == "tools/call":
            params = msg.get("params", {}) or {}
            name = params.get("name", "")
            args = params.get("arguments", {}) or {}
            handler = _HANDLERS.get(name)
            if handler is None:
                _send(_error(req_id, -32601, f"unknown tool: {name}"))
                continue
            try:
                result = handler(args)
            except Exception as e:
                _send(_result(req_id, _content({
                    "ok": False, "error": f"{type(e).__name__}: {e}"})))
                continue
            _send(_result(req_id, _content({"ok": True, "data": result})))
            continue

        if method == "notifications/initialized":
            continue

        if req_id is not None:
            _send(_error(req_id, -32601, f"{SERVER_NAME}: unknown method {method!r}"))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/reframing-engine && python3 -m pytest tests/test_mcp.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
cd ~/reframing-engine
git add mcp_server.py tests/test_mcp.py
git commit -m "feat: MCP server — reframe.frame / classify / clean over stdio"
```

---

### Task 5: demo.py + README

**Files:**
- Create: `~/reframing-engine/demo.py`
- Create: `~/reframing-engine/README.md`

**Interfaces:**
- Consumes: `reframing_engine.reframe`, `adapters.Static*`.
- Produces: runnable `demo.py` (before/after on a real prompt) + README documenting usage and the self-containment contract.

- [ ] **Step 1: Write `demo.py`**

```python
#!/usr/bin/env python3
"""demo — run the reframing engine on a real prompt, show before/after."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import StaticSession, StaticMemory, StaticProject
from reframing_engine import reframe

PROMPT = (
    "Can you basically just help me with the quarterly forecast. "
    "The team needs to decide whether to lock the plan or reforecast. "
    "I need you to look at the variance in Q2 as well please."
)


def main() -> int:
    print("BEFORE (raw prompt):")
    print(f"  {PROMPT}\n")

    r = reframe(
        PROMPT,
        session=StaticSession("Preparing Q3 board review."),
        memory=StaticMemory("Q2 variance was 8% over plan; Atlas Corp usage down 31%."),
        project=StaticProject("finance-analytics, branch q3-forecast"),
    )

    print("AFTER (framed for the LLM):")
    print(r.framed)
    print()
    print("SYSTEM PROMPT:")
    print(r.system)
    print()
    print(f"DOMAIN: {r.domain}  |  CONTEXT SOURCES: {', '.join(r.sources)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run demo + verify output**

Run: `cd ~/reframing-engine && python3 demo.py`
Expected: prints raw prompt, framed prompt containing `Ongoing work:` / `Known from memory:` / `Project:` and `User request:`, plus a `SYSTEM PROMPT` and `DOMAIN: business`.

- [ ] **Step 3: Write `README.md`**

```markdown
# reframing-engine

Frame any prompt as **ongoing work** so the LLM treats it as part of a
session — not a one-shot query. Self-contained: stdlib + slimtoken only.
No imports of cortexagent / cortexllm / any agent runtime.

## Pipeline

1. CLEAN    — slimtoken reframe_prompt (strip filler, dedupe, normalize)
2. CLASSIFY — slimtoken classify_domain (business/code/osint/…)
3. GATHER   — caller-supplied context adapters (session / memory / project)
4. FRAME    — compose the "not a one-shot" prompt + build_system

## Usage

```bash
./reframe "fix the bug in the auth flow"       # argv
echo "fix the bug" | ./reframe                 # stdin
./reframe --no-context "domain-only framing"   # skip auto-context
./reframe --json "hello"                       # machine-readable
python3 demo.py                                # before/after walkthrough
python3 mcp_server.py                          # stdio MCP server
```

## Python API

```python
from reframing_engine import reframe
from adapters import StaticSession

r = reframe("fix the bug",
            session=StaticSession("working on proxy auth"),
            memory=None, project=None)
print(r.framed)   # framed prompt
print(r.system)   # composed system prompt
print(r.domain)   # classify_domain result
print(r.sources)  # ["session"]
```

## Self-containment contract (HARD)

- The engine imports stdlib + `slimtoken.prompt_reframe` only.
- Context adapters are caller-supplied objects; the engine defines the
  Protocols in `adapters.py` and never imports runtimes.
- Zero adapters is a valid configuration (domain framing only).
- cortexagent imports this engine one-way — never the reverse.

## Tests

```bash
python3 -m pytest tests/ -v
```
```

- [ ] **Step 4: Commit**

```bash
cd ~/reframing-engine
git add demo.py README.md
git commit -m "docs: demo + README — usage and self-containment contract"
```

---

### Task 6: Research notes (Process A scope — separate workstream)

**Files:**
- Create: `~/reframing-engine/research/stt-fix-research.md`

**Note:** Process A (STT fix) is a SEPARATE workstream and gets its own plan.
This task only records its scope + hard constraints so the folder is complete.

- [ ] **Step 1: Write `research/stt-fix-research.md`**

```markdown
# Process A — STT Fix (SEPARATE workstream)

**Do NOT merge with Process B (reframing engine).** This is a different
project. This file only records the scope + hard constraints.

## Problem
- STT produces garbled output (word-level mishears: "toor"→"tool",
  "reef"→"reframing engine").
- Hallucinations: "Thank you for watching!~" when no one is watching.

## Hard constraints (user directive)
- STT must **stay in VRAM** (GPU), never silently fall back to CPU.
- **Never evict the overseer** (LFM2.5-1.2B, ~0.95 GB on :8082).
- **Never evict the big model** (Qwen3.6-35B, ~13.7 GB on :8080).
- Work within whatever VRAM is free (~500 MiB steady-state).

## Scope
- Fix the current faster-whisper setup (model choice, beam, temperature
  fallback, VAD tuning, vocabulary biasing) within the VRAM envelope.
- Fix the "thank you for watching" hallucination that slips past the
  current denylist.
- Deliverable: research notes + concrete config/code fixes to the STT
  pipeline (`lib/stt.py`, `lib/stt_daemon.py` in cortexagent).

## Status
- [ ] Research on current faster-whisper setup
- [ ] "thank you for watching" hallucination fix
```

- [ ] **Step 2: Commit**

```bash
cd ~/reframing-engine
git add research/stt-fix-research.md
git commit -m "docs: research scope for Process A (STT fix) — separate workstream"
```

---

### Task 7: cortexagent one-way import + smoke

**Files:**
- Create: `cortexagent/tests/test_reframing_import.py`

**Interfaces:**
- Consumes: `~/reframing-engine/reframing_engine.py` (resolved by path, like
  `lib/prompt_framing.py` resolves slimtoken).
- Produces: proof that cortexagent can import the engine one-way, and that
  the engine source stays clean (no cortex/cortexllm imports).

- [ ] **Step 1: Write the failing import test**

`cortexagent/tests/test_reframing_import.py`:
```python
"""One-way integration: cortexagent may import the reframing engine; the
engine must never import cortexagent / cortexllm / any runtime."""
import importlib.util
import subprocess
from pathlib import Path

ENGINE = Path.home() / "reframing-engine" / "reframing_engine.py"


def _load_engine():
    if not ENGINE.is_file():
        import pytest
        pytest.skip("~/reframing-engine/reframing_engine.py not present")
    spec = importlib.util.spec_from_file_location("reframing_engine", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cortexagent_can_import_engine():
    mod = _load_engine()
    r = mod.reframe("fix the bug in the auth flow")
    assert r.domain == "code"
    assert "the bug in the auth flow" in r.cleaned
    assert r.sources == []


def test_engine_source_has_no_runtime_imports():
    """Self-containment contract: no hard imports on cortex/cortexllm."""
    src = ENGINE.read_text()
    forbidden = (
        "import cortex", "from cortex",
        "import cortexllm", "from cortexllm",
        "import session_bridge", "import memory_thin",
    )
    assert not any(f in src for f in forbidden), \
        "engine must not import agent runtimes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/cortexagent && python3 -m pytest tests/test_reframing_import.py -v`
Expected: FAIL — `No module named 'reframing_engine'` (engine not resolvable yet) **or** skip if engine file is missing. After Task 2 the engine exists, so the test should run for real.

- [ ] **Step 3: Run the full engine suite (confirm engine works standalone)**

Run: `cd ~/reframing-engine && python3 -m pytest tests/ -v`
Expected: PASS — all engine tests green.

- [ ] **Step 4: Re-run cortex import test**

Run: `cd ~/cortexagent && python3 -m pytest tests/test_reframing_import.py -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Commit**

```bash
cd ~/cortexagent
git add tests/test_reframing_import.py
git commit -m "test: cortexagent imports reframing engine one-way (self-containment contract)"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Spec §4 `reframe()` API → Task 2
- ✅ Spec §3 adapters (SessionAdapter/MemoryAdapter/ProjectAdapter) → Task 1
- ✅ Spec §5 CLI → Task 3
- ✅ Spec §5 MCP server → Task 4
- ✅ Spec §5 demo → Task 5
- ✅ Spec §5 research/ (Process A reference) → Task 6
- ✅ Spec §5 one-way cortexagent import → Task 7
- ✅ Spec §7 self-contained (HARD) → Task 2 code + Task 7 self-containment test
- ✅ Spec §8 DoD: engine standalone (stdlib+slim only) → Tasks 2 + 7; adapters independently disableable → Task 2 tests; cortex imports one-way → Task 7

**2. Placeholder scan:** No TBD/TODO; every code step has concrete code.

**3. Type consistency:** `ReframeResult` fields (framed/system/domain/sources/cleaned) match across Task 2 (definition), Task 3 CLI (`asdict(r)`), Task 4 MCP (`r.domain`/`r.framed`/`r.system`/`r.cleaned`/`r.sources`), Task 6 (`r.cleaned`, `r.domain`, `r.sources`). Adapter Protocols `context()`/`context(prompt, domain)` match across Tasks 1-2 and `Static*` classes.

**Process A (STT fix) is a separate plan** — do NOT merge into this one.
