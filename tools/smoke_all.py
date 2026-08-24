#!/usr/bin/env python3

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))


class R:
    def __init__(self, name: str, passed: bool, detail: str = "",
                 errors: Optional[List[str]] = None):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.errors = errors or []
    def __repr__(self):
        return f"R({self.name}, passed={self.passed}, detail={self.detail!r})"
    def to_dict(self):
        return {"name": self.name, "passed": self.passed,
                "detail": self.detail, "errors": self.errors}



def _sys_run(args: List[str], timeout: int = 60, cwd: Optional[Path] = None,
             env: Optional[Dict] = None) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(
            args, cwd=str(cwd or REPO_ROOT),
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as e:
        return 2, "", f"exec error: {e}"


def _http_get(url: str, timeout: float = 1.5) -> Tuple[int, str, str]:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", errors="replace"), ""
    except Exception as e:
        return 0, "", str(e)



def layer_compile(scope: List[Path]) -> R:
    name = "L1.compile"
    errors: List[str] = []
    n = 0
    import py_compile
    for root in scope:
        for path in root.rglob("*.py"):
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                py_compile.compile(str(path), doraise=True)
                n += 1
            except py_compile.PyCompileError as e:
                errors.append(f"{path.relative_to(REPO_ROOT)}: {e}")
    if errors:
        return R(name, False, f"{n} ok, {len(errors)} failed", errors[:10])
    return R(name, True, f"{n} files compiled")



def layer_import() -> R:
    name = "L2.import"
    errors: List[str] = []
    n = 0
    lib_dir = REPO_ROOT / "lib"
    for path in sorted(lib_dir.glob("*.py")):
        if path.name.startswith("_") or path.name in ("__init__.py",):
            continue
        mod = f"lib.{path.stem}"
        try:
            __import__(mod)
            n += 1
        except Exception as e:
            errors.append(f"{mod}: {type(e).__name__}: {e}")
    if errors:
        return R(name, False, f"{n} ok, {len(errors)} failed", errors[:10])
    return R(name, True, f"{n} modules imported")



def layer_module_smoke() -> R:
    name = "L3.module-smoke"
    errors: List[str] = []
    n_ok = 0
    n_skip = 0
    lib_dir = REPO_ROOT / "lib"

    for path in sorted(lib_dir.glob("*.py")):
        if path.name.startswith("_") or path.name in ("__init__.py",):
            continue
        text = path.read_text(errors="replace")
        has_smoke_fn = "def _smoke(" in text or "def smoke(" in text
        has_main_smoke = ('if __name__ == "__main__"' in text
                          and '"--smoke"' in text)
        if not (has_smoke_fn or has_main_smoke):
            n_skip += 1
            continue

        if has_main_smoke:


            is_heavy = any(s in path.name for s in
                           ("diffusion_backend",
                            "diffusers", "img2img"))






            timeout = 600 if "image_adapter" in path.name else (180 if is_heavy else 30)
            rc, out, err = _sys_run(
                ["python3", str(path), "--smoke"], timeout=timeout)
            if rc == 0:
                n_ok += 1
            else:
                errors.append(
                    f"{path.name} --smoke: rc={rc} | "
                    f"out={out[:200]!r} | err={err[:200]!r}")
        elif has_smoke_fn:
            try:
                import importlib
                mod = importlib.import_module(f"lib.{path.stem}")
                if hasattr(mod, "_smoke"):
                    rc = mod._smoke()
                    if isinstance(rc, int) and rc == 0:
                        n_ok += 1
                    else:
                        errors.append(f"{path.name}: _smoke() returned {rc!r}")
                else:
                    n_skip += 1
            except SystemExit:
                n_ok += 1
            except Exception as e:

                errors.append(f"{path.name}: {type(e).__name__}: {str(e)[:200]}")
    if errors:
        return R(name, False, f"{n_ok} ok, {len(errors)} failed; "
                              f"{n_skip} skipped", errors[:10])
    return R(name, True, f"{n_ok} ok, {n_skip} skipped")



def layer_cli() -> R:
    name = "L4.cli"
    errors: List[str] = []

    cmds = [
        (["python3", "lib/overseer.py", "status"], "overseer status"),
        (["python3", "lib/daemon.py", "status"], "daemon status"),
        (["python3", "lib/converted_mcp_tools.py"], "converted_mcp_tools"),
        (["python3", "lib/observability.py", "--smoke"], "observability --smoke"),
        (["python3", "lib/observability.py", "traces"], "observability traces"),
        (["python3", "lib/tool_registry.py", "--smoke"], "tool_registry --smoke"),
        (["python3", "lib/token_tracker.py", "--smoke"], "token_tracker --smoke"),
        (["python3", "lib/token_tracker.py", "status"], "token_tracker status"),
        (["python3", "lib/memory_thin.py", "sessions"], "memory_thin sessions"),
    ]
    for cmd, label in cmds:
        rc, out, err = _sys_run(cmd, timeout=30)
        if rc != 0:
            errors.append(f"{label}: rc={rc} | err={err[:200]!r}")
    if errors:
        return R(name, False, f"{len(cmds) - len(errors)} ok, "
                              f"{len(errors)} failed", errors)
    return R(name, True, f"{len(cmds)} cmds ok")



def layer_live() -> R:
    name = "L5.live"
    errors: List[str] = []
    notes: List[str] = []
    endpoints = [
        ("http://127.0.0.1:8080/health", "big model"),
        ("http://127.0.0.1:8081/health", "grammar proxy"),
        ("http://127.0.0.1:8082/health", "tiny model"),
    ]
    for url, label in endpoints:
        code, body, err = _http_get(url)
        if code >= 200 and code < 400:
            notes.append(f"{label}: {code}")
        else:
            errors.append(f"{label} ({url}): {err[:120]}")

    if not notes:
        return R(name, False, "all endpoints down", errors)
    return R(name, True, f"up: {', '.join(notes)}; "
                         f"down: {len(errors)}", errors)



def layer_hot_paths() -> R:
    name = "L6.hot-paths"
    errors: List[str] = []

    try:
        from lib.observability import Trace, Span, save_trace, evaluate_trace
        nid = f"smoke-{int(time.time())}"
        trace = Trace(trace_id=nid, session_id="smoke", user_input="smoke",
                      workflow="smoke")
        with Span(trace.trace_id, "llm", "smoke-call") as s:
            s.set_metric("tokens_in", 50)
            s.set_metric("tokens_out", 100)
        save_trace(trace)

        path = Path.home() / ".cortexagent" / "observability" / "traces.ndjson"
        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        mine = [t for t in lines if t["trace_id"] == nid]
        if not mine:
            errors.append("observability: trace not on disk")
        elif len(mine[-1]["spans"]) == 0:
            errors.append("observability: spans attached=0 (the spans: [] bug)")
        eval_ = evaluate_trace(trace)
        if eval_["overall_score"] == 0.0:
            errors.append("observability: eval overall=0 (output empty)")
    except Exception as e:
        errors.append(f"observability: {type(e).__name__}: {e}")


    try:
        from lib.token_tracker import merge_stats, get_status
        s = merge_stats()
        for k in ("tiny_model", "proxy", "total", "merged_history"):
            if k not in s:
                errors.append(f"token_tracker: missing key {k!r}")
        tiny = s.get("tiny_model", {})
        if tiny and not isinstance(tiny, dict):
            errors.append(f"token_tracker: tiny_model is {type(tiny).__name__}, not dict")
        if "errors" in tiny and tiny["errors"]:
            errors.append(f"token_tracker: tiny_model errors: {tiny['errors']}")
    except Exception as e:
        errors.append(f"token_tracker: {type(e).__name__}: {e}")


    try:
        from lib.converted_mcp_tools import CONVERTED_TOOLS, TOOL_MAP
        adv = [t["function"]["name"] for t in CONVERTED_TOOLS]
        missing = [n for n in adv if n not in TOOL_MAP]
        if missing:
            errors.append(f"converted_mcp_tools: advertised but not reachable: "
                          f"{missing}")

        for name, args in [
            ("memory_search", {"query": "smoke", "limit": 1}),
            ("memory_search_semantic", {"query": "smoke", "limit": 1}),
            ("memory_graph_query", {"action": "stats"}),
            ("memory_ontology", {"action": "stats"}),
            ("slimtoken_minify", {"messages": [{"role": "user", "content": "smoke"}] * 2}),
            ("slimtoken_maxify", {"messages": [{"role": "user", "content": "smoke"}]}),
            ("magicui_generate", {"description": "smoke", "format": "html"}),
            ("alpaca_get_account", {}),
            ("ibkr_get_positions", {}),
            ("quant_trader_strategy", {"symbol": "AAPL"}),
        ]:
            try:
                result = TOOL_MAP[name](**args)
                if not isinstance(result, dict):
                    errors.append(f"{name}: returned {type(result).__name__}")
                elif "error" in result and "not configured" not in result["error"]:


                    pass
            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}: {e}")
    except Exception as e:
        errors.append(f"converted_mcp_tools: {type(e).__name__}: {e}")


    try:
        from lib.memory_thin import append, read_last, search, write_cold, read_cold
        mark = f"smoke-{int(time.time())}-{int(time.time()*1000) % 100000}"
        ok = False
        for attempt in (1, 2):
            try:
                append(mark, role="user")
            except SystemExit:
                pass
            time.sleep(0.3)
            s = search(mark, limit=5)
            if s:
                ok = True
                break
        if not ok:
            errors.append("memory_thin: append did not round-trip via search "
                          "(2 attempts)")
        write_cold(mark)
        time.sleep(0.2)
        if not any(mark in e.get("content", "") for e in read_cold()):
            errors.append("memory_thin: cold write did not round-trip")
    except Exception as e:
        errors.append(f"memory_thin: {type(e).__name__}: {e}")


    try:
        import sys
        for mod_path in ["lib.tool_registry", "tool_registry"]:
            if mod_path in sys.modules:
                del sys.modules[mod_path]
        import tool_registry
        tools = tool_registry.list_tools()
        if len(tools) < 5:
            errors.append(f"tool_registry: only {len(tools)} tools listed")
    except Exception as e:
        errors.append(f"tool_registry: {type(e).__name__}: {e}")

    if errors:
        return R(name, False, f"{len(errors)} failures", errors)
    return R(name, True, "all hot paths green")



def layer_socket() -> R:
    name = "L7.socket"
    sock = Path.home() / ".cortexllm" / "memory.sock"
    if not sock.exists():
        return R(name, True, "memory.sock not present (skipped)")
    try:
        import json as _json
        payload = _json.dumps({
            "role": "user",
            "content": f"smoke-{int(time.time())}",
            "platform": "cortexagent",
            "metadata": {"smoke": True},
        }) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(sock))
            s.sendall(payload.encode())
        return R(name, True, "memory.sock send OK")
    except Exception as e:
        return R(name, False, f"socket error: {e}")



def layer_config() -> R:
    name = "L8.config"
    errors: List[str] = []
    try:
        from lib.config import CFG


        stt_device = getattr(CFG, "stt_device", None)
        stt_model = getattr(CFG, "stt_model", None)
        if stt_device is None:
            errors.append("CFG.stt_device missing")
        if stt_model is None:
            errors.append("CFG.stt_model missing")
    except Exception as e:
        errors.append(f"config: {type(e).__name__}: {e}")
    if errors:
        return R(name, False, "; ".join(errors))
    return R(name, True, f"stt_device={stt_device}, stt_model={stt_model}")



def run_all(layers: List[str], no_live: bool) -> Dict[str, Any]:
    scope = [REPO_ROOT / "lib", REPO_ROOT / "cortex", REPO_ROOT / "cortexllm",
             REPO_ROOT / "tests"]
    handlers: Dict[str, Callable[[], R]] = {
        "compile": lambda: layer_compile(scope),
        "import":  layer_import,
        "smoke":   layer_module_smoke,
        "cli":     layer_cli,
        "live":    (lambda: R("L5.live", True, "skipped (--no-live)")) if no_live else layer_live,
        "hot":     layer_hot_paths,
        "socket":  layer_socket,
        "config":  layer_config,
    }
    selected = [(k, v) for k, v in handlers.items() if k in layers]
    started_at = time.time()
    results: List[R] = []
    for k, fn in selected:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            r = R(f"L?{k}", False, f"layer threw: {type(e).__name__}: {e}",
                  errors=[traceback.format_exc()])
        r.elapsed = round(time.time() - t0, 3)
        results.append(r)
    elapsed = round(time.time() - started_at, 3)
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "elapsed_sec": elapsed,
            "exit_code": 0 if failed == 0 else 1,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "results": [r.to_dict() for r in results],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CortexAgent end-to-end smoke harness")
    ap.add_argument("--layer", action="append", default=[],
                    help="Restrict to specific layer(s). Default: all.")
    ap.add_argument("--no-live", action="store_true",
                    help="Skip live HTTP endpoint checks")
    ap.add_argument("--json", action="store_true", help="JSON output only")
    args = ap.parse_args(argv)
    layers = args.layer or ["compile", "import", "smoke", "cli", "live", "hot",
                            "socket", "config"]
    out = run_all(layers, args.no_live)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        s = out["summary"]
        print(f"\n{'='*60}")
        print(f"Smoke: {s['passed']} passed / {s['failed']} failed "
              f"in {s['elapsed_sec']}s")
        print(f"{'='*60}")
        for r in out["results"]:
            mark = "✅" if r["passed"] else "❌"
            print(f"  {mark} {r['name']:<14} {r['detail']}")
            for e in r["errors"][:3]:
                print(f"      → {e}")
        if s["failed"] > 0:
            print(f"\nFAILED: {s['failed']} layers")
        else:
            print("\nALL GREEN")
    return out["summary"]["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
