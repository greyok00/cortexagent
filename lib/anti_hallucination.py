#!/usr/bin/env python3
"""anti_hallucination — verify paths, CLI flags, services, and user claims before tool use.

Verify paths, CLI flags, services, and user claims before tool use.

  - COMMON_PATHS and SERVICES dicts are loaded from
    ~/.cortexagent/config/verification.json (auto-created with sensible defaults)
  - Generic verify_service_running() instead of hardcoded browser checks
  - verify_command_arguments() checks a multi-arg command (CLI + flags + paths)
    against its help output before running

Stdlib only.

CLI:
  python3 anti_hallucination.py verify --prompt "..." [--files PATH ...] [--claim "..."]
  python3 anti_hallucination.py check-cli "git commit -m 'x'"
  python3 anti_hallucination.py check-service NAME
  python3 anti_hallucination.py check-path PATH [--must-be-readable]
  python3 anti_hallucination.py smoke
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_CONFIG_FILE = Path.home() / ".cortexagent" / "config" / "verification.json"

_DEFAULT_CONFIG: Dict = {
    # Path aliases — short name → absolute path
    "paths": {
        "cortexagent_config": str(Path.home() / ".cortexagent-config"),
        "cortexagent_memory": str(Path.home() / ".cortexagent" / "memory"),
        "claude_projects": str(Path.home() / ".claude" / "projects"),
    },
    # Services: short name → {port, process_pattern}
    "services": {
        "llama_server": {"port": 8080, "process": "llama-server"},
        "cortexagent_memory_mcp": {"port": None, "process": "mcp_server.py"},
    },
}


def _load_config() -> Dict:
    if not _CONFIG_FILE.exists():
        try:
            _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CONFIG, indent=2))
        except Exception:
            pass
        return json.loads(json.dumps(_DEFAULT_CONFIG))  # deep copy
    try:
        cfg = json.loads(_CONFIG_FILE.read_text())
        # Merge missing keys from defaults
        for k, v in _DEFAULT_CONFIG.items():
            cfg.setdefault(k, v if isinstance(v, dict) else v)
        return cfg
    except Exception:
        return json.loads(json.dumps(_DEFAULT_CONFIG))


# ── Result container ───────────────────────────────────────────────────────
class VerificationResult:
    def __init__(self):
        self.passed = True
        self.blocker: Optional[str] = None
        self.verifications: List[Dict] = []
        self.warnings: List[str] = []
        self.recommendations: List[str] = []
        self.web_search_needed = False
        self.web_search_query: Optional[str] = None

    def add_verification(self, name: str, passed: bool, details: str) -> None:
        self.verifications.append({
            "name": name,
            "passed": passed,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })
        if not passed:
            self.passed = False
            if not self.blocker:
                self.blocker = f"{name} verification failed: {details}"

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_recommendation(self, msg: str) -> None:
        self.recommendations.append(msg)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "blocker": self.blocker,
            "verifications": self.verifications,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
            "web_search_needed": self.web_search_needed,
            "web_search_query": self.web_search_query,
        }


# ── CLI command verification ──────────────────────────────────────────────
def verify_cli_command(command: str) -> VerificationResult:
    """Verify a CLI command: command exists, flags appear valid."""
    result = VerificationResult()
    parts = command.split()
    if not parts:
        result.add_verification("CLI", False, "Empty command")
        return result
    base_cmd = parts[0]
    try:
        which_result = subprocess.run(
            ["which", base_cmd], capture_output=True, text=True, timeout=5
        )
        if which_result.returncode != 0:
            result.add_verification("CLI command exists", False,
                                    f"'{base_cmd}' not found in PATH")
            result.add_recommendation(f"Install {base_cmd} or check PATH")
            return result
        result.add_verification("CLI command exists", True,
                                f"Found at: {which_result.stdout.strip()}")
    except Exception as e:
        result.add_verification("CLI command exists", False, f"Error checking: {e}")
        return result

    try:
        help_result = subprocess.run(
            [base_cmd, "--help"], capture_output=True, text=True, timeout=5
        )
        help_text = (help_result.stdout + help_result.stderr).lower()
        for part in parts[1:]:
            if part.startswith("-"):
                flag = part.split("=")[0].lstrip("-")
                if flag and flag not in help_text:
                    result.add_warning(f"Flag '-{flag}' may not exist for {base_cmd}")
                    result.web_search_needed = True
                    result.web_search_query = f"{base_cmd} command line flags reference"
        result.add_verification("CLI flags valid", True, "Flags appear valid")
    except subprocess.TimeoutExpired:
        result.add_warning(f"--help timed out for {base_cmd}")
    except Exception as e:
        result.add_warning(f"Could not verify flags: {e}")
    return result


def verify_command_arguments(command: str, paths: Optional[List[str]] = None) -> VerificationResult:
    """Verify a full command (base + flags + paths). Checks the binary, flags,
    and that any path-like arguments exist."""
    result = verify_cli_command(command)
    parts = command.split()
    if paths:
        for p in paths:
            file_result = verify_file_exists(p)
            result.verifications.extend(file_result.verifications)
            result.warnings.extend(file_result.warnings)
    else:
        # Auto-detect path-like arguments
        for part in parts[1:]:
            if part.startswith("/") or part.startswith("~") or part.startswith("./"):
                fr = verify_file_exists(part, must_be_readable=False)
                if not fr.passed:
                    result.add_warning(f"Argument path may not exist: {part}")
    return result


# ── Service verification ───────────────────────────────────────────────────
def verify_service_running(service_name: str) -> VerificationResult:
    """Verify a service is running (port listening + process present)."""
    result = VerificationResult()
    cfg = _load_config()
    services = cfg.get("services", {})
    if service_name not in services:
        result.add_verification(f"Service {service_name}", False, "Unknown service")
        result.add_recommendation(
            f"Add '{service_name}' to {_CONFIG_FILE} under 'services'"
        )
        return result
    config = services[service_name]

    # Port check (if configured)
    port = config.get("port")
    if port is not None:
        port_ok = False
        # Prefer ss, fall back to netstat, fall back to socket connect
        try:
            ss = subprocess.run(["ss", "-tln"], capture_output=True, text=True, timeout=5)
            port_ok = f":{port} " in ss.stdout or ss.stdout.endswith(f":{port}")
        except Exception:
            pass
        if not port_ok:
            try:
                netstat = subprocess.run(
                    ["netstat", "-tln"], capture_output=True, text=True, timeout=5
                )
                port_ok = f":{port}" in netstat.stdout
            except Exception:
                pass
        if not port_ok:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                port_ok = sock.connect_ex(("127.0.0.1", port)) == 0
                sock.close()
            except Exception:
                pass
        if port_ok:
            result.add_verification(f"Service {service_name} port",
                                    True, f"Port {port} is listening")
        else:
            result.add_verification(f"Service {service_name} port",
                                    False, f"Port {port} not listening")
            result.add_recommendation(f"Start {service_name} service")

    # Process check
    proc_pattern = config.get("process")
    if proc_pattern:
        try:
            pgrep = subprocess.run(
                ["pgrep", "-f", proc_pattern], capture_output=True, timeout=5
            )
            if pgrep.returncode == 0:
                result.add_verification(f"Service {service_name} process",
                                        True, f"PID: {pgrep.stdout.strip()}")
            else:
                result.add_verification(f"Service {service_name} process",
                                        False, f"Process '{proc_pattern}' not found")
        except Exception as e:
            result.add_verification(f"Service {service_name} process",
                                    False, f"Could not check process: {e}")

    # HTTP health check (if url provided)
    health_url = config.get("health_url")
    if health_url:
        try:
            with urllib.request.urlopen(health_url, timeout=3) as resp:
                if resp.status < 400:
                    result.add_verification(f"Service {service_name} health",
                                            True, f"{health_url} returned {resp.status}")
                else:
                    result.add_verification(f"Service {service_name} health",
                                            False, f"{health_url} returned {resp.status}")
        except Exception as e:
            result.add_verification(f"Service {service_name} health",
                                    False, f"Cannot reach {health_url}: {e}")

    return result


# ── File path verification ────────────────────────────────────────────────
def verify_file_exists(path: str, must_be_readable: bool = True) -> VerificationResult:
    """Verify a file path exists and (optionally) is readable."""
    result = VerificationResult()
    expanded = Path(path).expanduser()
    if not expanded.exists():
        result.add_verification(f"File exists: {path}", False,
                                f"Path does not exist: {expanded}")
        result.add_recommendation("Check file path or create the file")
        return result
    result.add_verification(f"File exists: {path}", True, f"Found at: {expanded}")
    if must_be_readable:
        try:
            expanded.read_text()
            result.add_verification(f"File readable: {path}", True, "File is readable")
        except PermissionError:
            result.add_verification(f"File readable: {path}", False, "Permission denied")
        except Exception as e:
            result.add_verification(f"File readable: {path}", False, f"Error: {e}")
    return result


# ── User-claim verification ───────────────────────────────────────────────
def verify_user_claim(claim: str, context: Optional[Dict] = None) -> VerificationResult:
    """Verify a user's claim against actual system state."""
    result = VerificationResult()
    cfg = _load_config()
    services = cfg.get("services", {})
    claim_lower = claim.lower()

    for service_name in services:
        if service_name in claim_lower:
            sr = verify_service_running(service_name)
            result.verifications.extend(sr.verifications)
            result.warnings.extend(sr.warnings)
            if sr.passed and ("broken" in claim_lower or "not working" in claim_lower):
                result.add_warning(
                    "Service is running but user reports issues - may be config problem"
                )
                result.recommendations.append("Check configuration files and logs")

    file_pattern = r'(?:file|config|path)[\s:]+["\']?([~/.\w\-/]+)["\']?'
    matches = re.findall(file_pattern, claim, re.IGNORECASE)
    for path in matches:
        fr = verify_file_exists(path)
        result.verifications.extend(fr.verifications)
        result.warnings.extend(fr.warnings)

    uncertainty_words = ["think", "maybe", "probably", "not sure", "i guess", "seems like"]
    if any(w in claim_lower for w in uncertainty_words):
        result.web_search_needed = True
        result.web_search_query = claim
    return result


# ── Main entry point ──────────────────────────────────────────────────────
def verify_before_code(user_prompt: str,
                       context: Optional[Dict] = None) -> VerificationResult:
    """Run all verifications relevant to a prompt.

    Context dict keys:
      - files_mentioned: list of paths to check
      - claim: a user statement to validate
      - commands: list of CLI commands to verify
      - services: list of service names to check
    """
    result = VerificationResult()
    context = context or {}
    cfg = _load_config()
    services = cfg.get("services", {})
    prompt_lower = user_prompt.lower()

    # 1. Commands
    commands = list(context.get("commands", []))
    # Auto-detect verb-command patterns
    cmd_patterns = [
        r'(?:run|execute|call|invoke)\s+(\w+)',
        r'(\w+)\s+(?:command|script|tool)',
        r'(?:use|try)\s+(\w+)',
    ]
    for pattern in cmd_patterns:
        for cmd in re.findall(pattern, prompt_lower):
            if cmd not in ("the", "a", "an", "this", "that"):
                commands.append(cmd)
    for cmd in commands:
        cr = verify_cli_command(cmd)
        result.verifications.extend(cr.verifications)
        result.warnings.extend(cr.warnings)
        if not cr.passed:
            result.blocker = f"CLI verification failed: {cmd}"
            result.passed = False

    # 2. Services mentioned
    for service_name in services:
        if service_name in prompt_lower:
            sr = verify_service_running(service_name)
            result.verifications.extend(sr.verifications)
            result.warnings.extend(sr.warnings)
            if not sr.passed:
                result.add_recommendation(f"Start {service_name} before proceeding")

    for s in context.get("services", []):
        sr = verify_service_running(s)
        result.verifications.extend(sr.verifications)
        result.warnings.extend(sr.warnings)

    # 3. Files
    for path in context.get("files_mentioned", []):
        fr = verify_file_exists(path)
        result.verifications.extend(fr.verifications)
        result.warnings.extend(fr.warnings)

    # 4. Claim
    if "claim" in context:
        cr = verify_user_claim(context["claim"], context)
        result.verifications.extend(cr.verifications)
        result.warnings.extend(cr.warnings)

    # 5. Web-search recommendation
    if result.web_search_needed:
        result.add_recommendation(f"Web search recommended: {result.web_search_query}")

    if not result.passed:
        suffix = "; Verification failed - address issues before code generation"
        result.blocker = (result.blocker or "Verification failed") + suffix
    return result


def format_report(result: VerificationResult) -> str:
    lines = []
    lines.append("✅ Anti-Hallucination: PASSED" if result.passed
                 else "❌ Anti-Hallucination: BLOCKED")
    if result.blocker:
        lines.append(f"   Blocker: {result.blocker}")
    lines.append("")
    lines.append("Verifications:")
    for v in result.verifications:
        lines.append(f"  {'✓' if v['passed'] else '✗'} {v['name']}: {v['details']}")
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  ⚠ {w}")
    if result.recommendations:
        lines.append("")
        lines.append("Recommendations:")
        for r in result.recommendations:
            lines.append(f"  → {r}")
    if result.web_search_needed:
        lines.append("")
        lines.append(f"🔍 Web search recommended: {result.web_search_query}")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────
def _cli(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    rest = argv[1:]
    if cmd == "verify":
        # gather --prompt, --files, --claim, --command, --service
        kwargs: Dict = {}
        files: List[str] = []
        commands: List[str] = []
        services: List[str] = []
        i = 0
        while i < len(rest):
            if rest[i] == "--prompt" and i + 1 < len(rest):
                kwargs["prompt"] = rest[i + 1]; i += 2
            elif rest[i] == "--files" and i + 1 < len(rest):
                files.append(rest[i + 1]); i += 2
            elif rest[i] == "--claim" and i + 1 < len(rest):
                kwargs["claim"] = rest[i + 1]; i += 2
            elif rest[i] == "--command" and i + 1 < len(rest):
                commands.append(rest[i + 1]); i += 2
            elif rest[i] == "--service" and i + 1 < len(rest):
                services.append(rest[i + 1]); i += 2
            else:
                i += 1
        prompt = kwargs.get("prompt", "")
        ctx: Dict = {}
        if files:
            ctx["files_mentioned"] = files
        if "claim" in kwargs:
            ctx["claim"] = kwargs["claim"]
        if commands:
            ctx["commands"] = commands
        if services:
            ctx["services"] = services
        r = verify_before_code(prompt, ctx)
        print(format_report(r))
        return 0 if r.passed else 1
    if cmd == "check-cli":
        r = verify_cli_command(" ".join(rest))
        print(format_report(r))
        return 0 if r.passed else 1
    if cmd == "check-service":
        r = verify_service_running(rest[0] if rest else "")
        print(format_report(r))
        return 0 if r.passed else 1
    if cmd == "check-path":
        path = rest[0] if rest else ""
        readable = "--must-be-readable" in rest
        r = verify_file_exists(path, must_be_readable=readable)
        print(format_report(r))
        return 0 if r.passed else 1
    if cmd == "smoke":
        return _smoke()
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def _smoke() -> int:
    # verify_cli_command on a known-good command
    r = verify_cli_command("ls --help")
    print(f"  ls --help: passed={r.passed}")

    # verify_cli_command on a missing command
    r = verify_cli_command("definitely-not-a-real-binary-xyz")
    assert not r.passed
    print(f"  fake binary: passed={r.passed}  blocker={r.blocker[:50]}…")

    # verify_file_exists
    r = verify_file_exists("/etc/hostname")
    assert r.passed
    print(f"  /etc/hostname: passed={r.passed}")
    r = verify_file_exists("/this/does/not/exist/anywhere")
    assert not r.passed
    print(f"  nonexistent: passed={r.passed}")

    # verify_service_running on a known service (might not be running in smoke)
    r = verify_service_running("llama_server")
    print(f"  llama_server: passed={r.passed}  verifications={len(r.verifications)}")

    # verify_before_code integration
    r = verify_before_code("Run definitely-not-a-real-binary-xyz", context={
        "files_mentioned": ["/etc/hostname", "/this/does/not/exist"],
    })
    assert not r.passed
    print(f"  integration: passed={r.passed}  blocker={r.blocker[:60]}…")
    print("anti_hallucination: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))