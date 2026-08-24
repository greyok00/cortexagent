#!/usr/bin/env python3

import json
import os
import sys
import time
import random
import socket
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


TEST_RESULTS_DIR = Path.home() / ".cortexagent" / "test_results"
TEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def log(msg: str, color: str = RESET) -> None:

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\u001b[33m🧪 \u001b[1mload_test\u001b[0m \u001b[2m[{ts}]\u001b[0m \u001b[{color}m{msg}\u001b[0m",
          file=sys.stderr, flush=True)


def run_test(name: str, func, count: int = 10, parallel: int = 5) -> Dict:

    log(f"Starting test: {name} (count={count}, parallel={parallel})", CYAN)
    start_time = time.time()

    results = {
        "name": name,
        "count": count,
        "parallel": parallel,
        "start_time": datetime.now().isoformat(),
        "results": [],
        "errors": [],
        "latencies": [],
        "successes": 0,
        "failures": 0,
        "errors_total": 0,
    }

    def run_single_test(i: int) -> Dict:
        try:
            start = time.time()
            result = func(i)
            elapsed = time.time() - start
            results["latencies"].append(elapsed * 1000)
            results["results"].append(result)
            if result.get("ok", False):
                results["successes"] += 1
            else:
                results["failures"] += 1
                if result.get("error"):
                    results["errors"].append(result["error"])
            return result
        except Exception as e:
            results["errors_total"] += 1
            results["errors"].append(str(e))
            return {"ok": False, "error": str(e)}


    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = [executor.submit(run_single_test, i) for i in range(count)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                results["errors_total"] += 1
                results["errors"].append(str(e))

    elapsed = time.time() - start_time
    results["end_time"] = datetime.now().isoformat()
    results["duration_seconds"] = round(elapsed, 2)
    results["throughput"] = round(count / elapsed, 2) if elapsed > 0 else 0


    if results["latencies"]:
        results["latency_avg_ms"] = round(sum(results["latencies"]) / len(results["latencies"]), 2)
        results["latency_p95_ms"] = sorted(results["latencies"])[int(len(results["latencies"]) * 0.95)]
        results["latency_max_ms"] = max(results["latencies"])
    else:
        results["latency_avg_ms"] = 0
        results["latency_p95_ms"] = 0
        results["latency_max_ms"] = 0


    test_file = TEST_RESULTS_DIR / f"{name}_{int(time.time())}.json"
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)


    log(f"Test '{name}' complete:", GREEN)
    log(f"  Successes: {results['successes']}/{results['count']}",
        GREEN if results["failures"] == 0 else RED)
    log(f"  Failures: {results['failures']}", RED if results["failures"] > 0 else GREEN)
    log(f"  Errors: {results['errors_total']}", RED if results["errors_total"] > 0 else GREEN)
    log(f"  Throughput: {results['throughput']} req/s", CYAN)
    log(f"  Latency avg: {results['latency_avg_ms']:.1f}ms", CYAN)
    log(f"  Latency p95: {results['latency_p95_ms']:.1f}ms", CYAN)
    log(f"  Latency max: {results['latency_max_ms']:.1f}ms", RED if results["latency_max_ms"] > 5000 else CYAN)

    return results



def test_proxy_request(i: int) -> Dict:

    try:

        url = "http://127.0.0.1:8081/completions"
        data = json.dumps({
            "model": "qwen3-35b",
            "prompt": f"This is test prompt #{i} for load testing.",
            "max_tokens": 100,
            "temperature": 0.7,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            response = json.loads(resp.read())
            return {"ok": True, "response": response.get("choices", [{}])[0].get("text", "")[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_proxy_test(count: int = 100, parallel: int = 10) -> Dict:

    log("Testing proxy (big model path) under load...", CYAN)
    return run_test("proxy", test_proxy_request, count, parallel)



def test_overseer_dispatch(i: int) -> Dict:

    try:
        from lib import overseer


        result = overseer.queue_add(
            task_type="llm",
            prompt=f"Test task #{i}: Calculate 2+2 and explain your reasoning.",
            system="You are a helpful assistant.",
            model="tiny",
            timeout=30,
            domain="professional"
        )

        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "queue_add failed")}


        state = overseer._load_state()
        success = overseer._execute_task(
            {
                "id": f"test-{i}",
                "type": "llm",
                "prompt": f"Test task #{i}: Calculate 2+2 and explain your reasoning.",
                "system": "You are a helpful assistant.",
                "timeout": 30,
            },
            state=state
        )

        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_overseer_test(count: int = 50, parallel: int = 5) -> Dict:

    log("Testing overseer (tiny model path) under load...", CYAN)
    return run_test("overseer", test_overseer_dispatch, count, parallel)



def test_memory_pressure(duration: int = 60) -> Dict:

    log(f"Testing memory pressure for {duration}s...", CYAN)
    start_time = time.time()
    results = {
        "name": "memory",
        "duration": duration,
        "samples": [],
        "errors": [],
    }

    try:
        from lib import memory_db
    except ImportError:
        return {"ok": False, "error": "memory_db module not found"}

    while time.time() - start_time < duration:
        try:
            stats = memory_db.get_memory_stats()
            results["samples"].append({
                "timestamp": time.time(),
                "hot": stats.get("hot", 0),
                "warm": stats.get("warm", 0),
                "cold": stats.get("cold", 0),
            })
            time.sleep(1)
        except Exception as e:
            results["errors"].append(str(e))

    results["ok"] = True
    results["final_samples"] = results["samples"][-10:]
    return results


def run_memory_test(duration: int = 60) -> Dict:

    return run_test("memory", lambda i: test_memory_pressure(duration)["ok"], 1, 1)



def test_disk_io(i: int) -> Dict:

    try:
        test_file = TEST_RESULTS_DIR / f"disk_test_{i}.json"
        data = {
            "index": i,
            "timestamp": time.time(),
            "data": "x" * 1000,
        }


        tmp = test_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(test_file)


        with open(test_file, "r", encoding="utf-8") as f:
            read_data = json.loads(f.read())


        test_file.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_disk_test(count: int = 1000, parallel: int = 20) -> Dict:

    log("Testing disk I/O under pressure...", CYAN)
    return run_test("disk_io", test_disk_io, count, parallel)



def test_e2e_request(i: int) -> Dict:

    try:

        from lib.observability import Trace, Span, save_trace
        trace = Trace(trace_id=f"e2e-{i}", session_id=f"session-{i}",
                      user_input=f"Test e2e request #{i}", workflow="load_test")


        with Span(trace.trace_id, "framing", "domain_classification") as s1:
            s1.set_tag("domain", "professional")
            time.sleep(0.001)


        with Span(trace.trace_id, "llm", "tiny_model_query") as s2:
            s2.set_metric("tokens_in", 50)
            s2.set_metric("tokens_out", 100)
            time.sleep(0.01)


        with Span(trace.trace_id, "beautify", "format_output") as s3:
            time.sleep(0.001)


        with Span(trace.trace_id, "output", "final_output") as s4:
            s4.payload["content"] = f"Test output #{i}: This is the final result."
            time.sleep(0.001)


        save_trace(trace)

        return {"ok": True, "trace_id": trace.trace_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_e2e_test(count: int = 100, parallel: int = 10) -> Dict:

    log("Testing end-to-end chain under load...", CYAN)
    return run_test("e2e", test_e2e_request, count, parallel)



def test_model_down(i: int) -> Dict:

    try:

        sock = socket.socket()
        sock.settimeout(2)
        try:
            sock.connect(("127.0.0.1", 8082))
            sock.close()
            return {"ok": False, "error": "Model is still up (expected failure)"}
        except Exception:
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_network_timeout(i: int) -> Dict:

    try:

        url = "http://127.0.0.1:99999/timeout"
        req = urllib.request.Request(url, timeout=1)
        try:
            with urllib.request.urlopen(req, timeout=1) as resp:
                resp.read()
            return {"ok": False, "error": "Request succeeded (unexpected)"}
        except Exception:
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_error_test(injection: str = "model_down") -> Dict:

    log(f"Testing error injection: {injection}...", CYAN)
    if injection == "model_down":
        return run_test("error_model_down", test_model_down, 5, 1)
    elif injection == "network_timeout":
        return run_test("error_network_timeout", test_network_timeout, 5, 1)
    else:
        return {"ok": False, "error": f"Unknown injection: {injection}"}



def run_all_tests(count: int = 500, parallel: int = 20) -> Dict:

    log("Starting comprehensive load test suite...", CYAN)
    start_time = time.time()

    results = {
        "name": "all_tests",
        "start_time": datetime.now().isoformat(),
        "tests": {},
        "summary": {},
    }


    tests = [
        ("proxy", lambda: run_proxy_test(count // 10, parallel)),
        ("overseer", lambda: run_overseer_test(count // 20, parallel // 2)),
        ("e2e", lambda: run_e2e_test(count // 10, parallel)),
        ("disk_io", lambda: run_disk_test(min(count, 500), parallel)),
    ]

    for test_name, test_func in tests:
        try:
            results["tests"][test_name] = test_func()
        except Exception as e:
            results["tests"][test_name] = {"ok": False, "error": str(e)}

    results["end_time"] = datetime.now().isoformat()
    results["duration_seconds"] = round(time.time() - start_time, 2)


    total = len(results["tests"])
    passed = sum(1 for t in results["tests"].values() if t.get("ok", False))
    results["summary"] = {
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 2) if total > 0 else 0,
    }

    log("Comprehensive load test complete!", GREEN)
    log(f"Passed: {passed}/{total} ({results['summary']['pass_rate']}%)",
        GREEN if results["summary"]["pass_rate"] == 100 else RED)

    return results



def main():

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "proxy":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        run_proxy_test(count, parallel)

    elif len(sys.argv) > 1 and sys.argv[1] == "overseer":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        run_overseer_test(count, parallel)

    elif len(sys.argv) > 1 and sys.argv[1] == "memory":
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        run_memory_test(duration)

    elif len(sys.argv) > 1 and sys.argv[1] == "disk":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
        parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        run_disk_test(count, parallel)

    elif len(sys.argv) > 1 and sys.argv[1] == "e2e":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        run_e2e_test(count, parallel)

    elif len(sys.argv) > 1 and sys.argv[1] == "error":
        injection = sys.argv[2] if len(sys.argv) > 2 else "model_down"
        run_error_test(injection)

    elif len(sys.argv) > 1 and sys.argv[1] == "all":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        run_all_tests(count, parallel)

    elif len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        print("Load test smoke test:")

        result = run_test("smoke", lambda i: {"ok": True}, 5, 2)
        print(f"  Smoke test passed: {result['successes']}/{result['count']}")

    else:
        print("Usage: load_test.py [proxy|overseer|memory|disk|e2e|error|all] [count] [parallel]")
        print(__doc__)


if __name__ == "__main__":
    main()
