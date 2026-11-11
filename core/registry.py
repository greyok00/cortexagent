from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from typing import Any, Callable, Dict, List, Optional

TOOLS: Dict[str, Dict[str, Any]] = {}

_CMD_TIMEOUT = 3600
_CMD_MAX_OUT = 32000

# GA-11 (2026-11-03): the core shell lane WAS arbitrary `bash shell=True` with
# a 3600 s ceiling and zero rules — the one path where model decisions reached
# the OS directly. Now a rule gate, the same shape as the greypentest exec
# gate: a first-token read-only allowlist, a NEVER-token net, structural
# metachar refusal, redirect targets bound to /dev/null or /tmp/, a git
# second-token rule, and a timeout clamp. Writes belong to the registered
# file tools; anything the gate refuses names the reason so the model can
# reroute instead of retrying forever.
_SAFE_BINS = frozenset((
    "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "date", "du",
    "df", "free", "ps", "wc", "stat", "echo", "file", "which", "env", "printenv",
    "uname", "whoami", "id", "uptime", "hostname", "arch", "nproc", "sort",
    "uniq", "cut", "tr", "comm", "sha256sum", "md5sum", "base64", "xargs",
    "diff", "git", "ss", "ip", "lsof", "nvidia-smi", "taskset", "sleep",
    # 2026-11-06 owner: download/unpack/inspect tier for work like the
    # smoothcsv decompile; python3 is an interpreter (explicit trust-level
    # expansion, not read-only) — the two lanes keep one policy.
    "curl", "wget", "unzip", "tar", "mkdir",
    "python3", "strings", "nm", "objdump", "readelf",
    # 2026-11-06 owner: agent stalled on "cp not in the allow list" during
    # the APK session. Narrow-path file ops (the redirect policy above
    # already confines > to /tmp and /dev/null); rm stays excluded — file
    # tools own deletion. Mirrors exec-gate.ts exactly (one policy, two lanes).
    "cp", "mv", "touch", "dirname", "basename", "realpath", "readlink",
    "awk", "sed", "tee",
))
# git is allowlisted but only for non-mutating subcommands
_GIT_SAFE_SUB = frozenset((
    "status", "diff", "log", "show", "blame", "branch", "rev-parse", "ls-files",
))
# word-boundary net under the allowlist — used only for long distinctive
# binaries, so free-text args like `grep go notes.txt` are not blocked
# (short names rm/mv/cp/sh/go are covered by the allowlist itself).
_NEVER_RE = re.compile(
    r"(?<![\w/@.-])(?:" + "|".join((
        "mkfs", "dd", "killall", "systemctl", "service",
        "pkexec", "eval", "source", "tmux", "setsid",
        "apt-get", "aptitude", "flatpak", "snap",
        "bash", "zsh", "fish", "dash",
    )) + r")(?![\w/-])")
# structural metachars that mean command composition or shell substitution:
# backticks (bare or $( form), $var/$((, process substitution, semicolons
# anywhere, &&, >& — plus <(...) which the token check cannot see
_SUBST_RE = re.compile(r"[`$]\(|[`]|[$][A-Za-z_{]|[<]\(|[>]\(|&&|[&][>]|>[\s]*&")


def _check_cmd(command: str, timeout: int) -> tuple[str, int]:
    """Rule gate for the core shell lane. Returns (None|refusal, clamped_timeout)."""
    timeout = max(1, min(int(timeout), _CMD_TIMEOUT))
    cmd = command.strip()
    if not cmd or "\n" in cmd or "\r" in cmd:
        return "refused: the core shell lane runs one single-line command per call — no multiline scripts", timeout
    if _SUBST_RE.search(cmd):
        return ("refused: shell substitution/composition is not allowed on the "
                "core shell lane (backticks, $(...), <(...), &&, ;, >&)", timeout)
    if _NEVER_RE.search(cmd):
        return ("refused: mutating, interpreter, shell or service-manager "
                "binary in the core shell lane — writes go through the "
                "registered file tools", timeout)
    # redirect targets: only /dev/null and anything under /tmp/; input
    # redirection and heredocs denied outright (paths can be passed as args)
    toks = cmd.split()
    for i, t in enumerate(toks):
        if t.startswith("<"):
            # glued forms like <<'EOF' or <<EOF or <file are still input
            # redirection — the exact-match check alone let them through
            return ("refused: input redirection is not allowed on the core "
                    "shell lane — pass the file path as an argument", timeout)
        if t in (">", ">>", "2>", "2>>", "&>"):
            target = toks[i + 1] if i + 1 < len(toks) else ""
            if target != "/dev/null" and not target.startswith("/tmp/"):
                return ("refused: redirect target must be /dev/null or under "
                        "/tmp/ (file writes go through file tools or /tmp/)", timeout)
    if ";" in cmd:
        return "refused: semicolons are not allowed on the core shell lane — one command per call", timeout
    # every pipeline segment's first token must be on the allowlist
    for seg in cmd.split("|"):
        seg = seg.strip()
        if not seg:
            return "refused: empty pipeline segment", timeout
        try:
            parts = shlex.split(seg)
        except ValueError:
            return "refused: unbalanced quoting in command", timeout
        first = parts[0]
        if first not in _SAFE_BINS:
            return ("refused: %r is not on the core shell allowlist (%s) — "
                    "ask the operator for anything outside it"
                    % (first, ", ".join(sorted(_SAFE_BINS))), timeout)
        if first == "git" and len(parts) > 1 and not parts[1].startswith("-"):
            sub = parts[1]
            if sub not in _GIT_SAFE_SUB:
                return ("refused: git %s is not on the read-only subcommand "
                        "allowlist (%s)" % (sub, ", ".join(sorted(_GIT_SAFE_SUB))), timeout)
    return None, timeout


def _schema(description: str, properties: Dict[str, Any],
            required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties,
        "required": required or []}}


def register_tool(name: str, schema: Dict[str, Any], handler: Callable,
                  category: str = "tool", **_extra) -> None:
    TOOLS[name] = {"schema": schema, "handler": handler, "category": category}


def list_tools(limit: Optional[int] = None, stub: bool = False) -> List[Dict[str, Any]]:
    names = list(TOOLS)
    if limit:
        names = names[:limit]
    out = []
    for n in names:
        s = TOOLS[n]["schema"]
        if stub:
            out.append({"name": n, "description": s.get("description", "")})
        else:
            out.append({"name": n, **s})
    return out


def get_schema(name: str) -> Optional[Dict[str, Any]]:
    t = TOOLS.get(name)
    return dict(t["schema"]) if t else None


def check_trust(result: Dict[str, Any]) -> str:
    blob = str(result.get("output", "")) + str(result.get("error", ""))
    for marker in ("ignore previous", "disregard all", "reveal your",
                   "send your prompt", "exfiltrate"):
        if marker in blob.lower():
            return "suspicious"
    return "ok"


def _resolve(name: str, args: Dict[str, Any]):
    if name in TOOLS:
        return name, args
    action = str(args.get("action") or "").strip()
    if action and (name + "_" + action) in TOOLS:
        rest = {k: v for k, v in args.items() if k != "action"}
        return name + "_" + action, rest
    return None, None


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tname, targs = _resolve(name, args or {})
    if not tname:
        return {"ok": False, "output": "",
                "error": "unknown tool: " + name}
    schema = TOOLS[tname]["schema"]
    missing = [k for k in (schema.get("parameters", {}) or {}).get("required", [])
               if k not in (targs or {})]
    if missing:
        params = sorted((schema.get("parameters", {}) or {}).get("properties", {}).keys())
        return {"ok": False, "output": "",
                "error": "missing argument(s): %s — parameter names for %s are: %s" % (
                    ", ".join(missing), name, ", ".join(params) or "(none)")}
    try:
        result = TOOLS[tname]["handler"](**(targs or {}))
        if not isinstance(result, dict):
            result = {"ok": True, "output": str(result), "error": ""}
        result["trust"] = check_trust(result)
        return result
    except Exception as e:
        return {"ok": False, "output": "", "error": "%s: %s" % (name, e)}


def _run_command(command: str, timeout: int = 3600) -> Dict[str, Any]:
    # GA-11: rule gate first — the refusal names the violated rule so the
    # model can reroute (file tools for writes, web tools for network).
    refusal, timeout = _check_cmd(command, timeout)
    if refusal:
        return {"ok": False, "output": "", "error": refusal}
    try:
        # GA-25 (2026-11-03): own process group + kill PGID on timeout — the
        # old proc.kill() killed only the bash parent and left the whole
        # child tree orphaned on a hung command.
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, executable="/bin/bash", start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except _Timeout:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait(timeout=5)
            return {"ok": False, "output": "",
                    "error": "command timed out after %ds" % timeout}
        return {"ok": proc.returncode == 0, "output": (stdout or "")[-_CMD_MAX_OUT:],
                "error": (stderr or "")[-4000:], "code": proc.returncode}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


def _executor_tool(name: str, args: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(execute_tool, name, args)
        try:
            return fut.result(timeout=timeout)
        except _Timeout:
            return {"ok": False, "output": "",
                    "error": "tool %s timed out after %ds" % (name, timeout)}
    finally:
        ex.shutdown(wait=False)


def register_base(name: str, schema: Dict[str, Any], handler: Callable) -> None:
    register_tool(name, schema, handler)
