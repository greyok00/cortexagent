#!/usr/bin/env python3
"""run_full_test.py — Full system test orchestration.

Runs the complete test suite:
1. Component health check
2. Chain diagnostic
3. Observability smoke test
4. Load test suite
5. Error injection tests
6. Comprehensive report generation

Usage:
  python3 lib/run_full_test.py          # run everything
  python3 lib/run_full_test.py health   # health check only
  python3 lib/run_full_test.py load     # load tests only
  python3 lib/run_full_test.py report   # generate report only
"""
import json
import os
import sys
import time
import socket
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ── Color Constants ──────────────────────────────────────────────────────────
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


def log(msg: str, color: str = RESET, prefix: str = "") -> None:
    """Print a colored message."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\u001b[33m🚀 \u001b[1mrun_full_test\u001b[0m \u001b[2m[{ts}]\u001b[0m \u001b[{color}m{prefix} {msg}\u001b[0m",
          file=sys.stderr, flush=True)


def run_component_health() -> Dict:
    """Check component health."""
    log("Checking component health...", CYAN)
    results = {
        "components": {},
        "all_healthy": True,
    }
    
    components = {
        "Proxy (minify)": ("127.0.0.1", 8081),
        "Big model (llama-server)": ("127.0.0.1", 8080),
        "Tiny model (llama-server)": ("127.0.0.1", 8082),
    }
    
    for name, addr in components.items():
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect(addr)
            s.close()
            results["components"][name] = {"status": "healthy", "error": None}
            log(f"  ✅ {name} on :{addr[1]}", GREEN)
        except Exception as e:
            results["components"][name] = {"status": "unhealthy", "error": str(e)}
            results["all_healthy"] = False
            log(f"  ❌ {name} on :{addr[1]}: {e}", RED)
    
    return results


def run_chain_diagnostic() -> Dict:
    """Run the chain diagnostic."""
    log("Running chain diagnostic...", CYAN)
    results = {}
    
    # Import and run diagnostic
    try:
        # Import the module (it will execute the diagnostic code on import)
        import lib.chain_diagnostic  # noqa: F401
        results["chain"] = "diagnostic_completed"
    except Exception as e:
        results["chain"] = f"error: {e}"
    
    return results


def run_observability_test() -> Dict:
    """Run the observability smoke test."""
    log("Running observability smoke test...", CYAN)
    results_local = {}
    try:
        from lib.observability import Trace, Span, save_trace, evaluate_trace, metrics
        import time
        
        # Create a test trace
        trace = Trace(trace_id="full_test", session_id="full_test_session",
                      user_input="Full system test", workflow="full_test")
        
        # Add spans
        with Span(trace.trace_id, "routing", "intent_classification") as s1:
            s1.set_metric("intent", "information_retrieval")
            time.sleep(0.001)
        
        with Span(trace.trace_id, "framing", "domain_classification") as s2:
            s2.set_metric("domain", "professional")
            time.sleep(0.001)
        
        with Span(trace.trace_id, "llm", "tiny_model_query") as s3:
            s3.set_metric("tokens_in", 50)
            s3.set_metric("tokens_out", 100)
            time.sleep(0.01)
        
        with Span(trace.trace_id, "beautify", "format_output") as s4:
            time.sleep(0.001)
        
        with Span(trace.trace_id, "output", "final_output") as s5:
            s5.payload["content"] = "Test output for full system test."
            time.sleep(0.001)
        
        # Save trace
        save_trace(trace)
        
        # Evaluate
        eval_result = evaluate_trace(trace)
        
        results_local["observability"] = {
            "trace_id": trace.trace_id,
            "spans_added": 5,
            "evaluation": eval_result,
        }
        
        log(f"  ✅ Trace saved: {trace.trace_id}", GREEN)
        log(f"  ✅ Evaluation score: {eval_result['overall_score']}", GREEN)
        
    except Exception as e:
        results_local["observability"] = f"error: {e}"
        log(f"  ❌ Observability test failed: {e}", RED)
    
    return results_local


def run_load_tests() -> Dict:
    """Run the load test suite."""
    log("Running load tests...", CYAN)
    results_local = {}
    
    try:
        from lib.load_test import run_proxy_test, run_overseer_test, run_e2e_test, run_disk_test
        
        # Run quick load tests (reduced counts for speed)
        results_local["proxy"] = run_proxy_test(10, 5)
        time.sleep(1)  # Cool down between tests
        
        results_local["overseer"] = run_overseer_test(10, 2)
        time.sleep(1)  # Cool down between tests
        
        results_local["e2e"] = run_e2e_test(10, 5)
        time.sleep(1)  # Cool down between tests
        
        results_local["disk_io"] = run_disk_test(100, 10)
        
        log("  ✅ Load tests complete", GREEN)
        
    except Exception as e:
        results_local["load_tests"] = f"error: {e}"
        log(f"  ❌ Load tests failed: {e}", RED)
    
    return results_local


def run_error_tests() -> Dict:
    """Run error injection tests."""
    log("Running error injection tests...", CYAN)
    results_local = {}
    
    try:
        from lib.load_test import run_error_test
        
        results_local["model_down"] = run_error_test("model_down")
        results_local["network_timeout"] = run_error_test("network_timeout")
        
        log("  ✅ Error injection tests complete", GREEN)
        
    except Exception as e:
        results_local["error_tests"] = f"error: {e}"
        log(f"  ❌ Error tests failed: {e}", RED)
    
    return results_local


def generate_report(results: Dict) -> None:
    """Generate a comprehensive test report."""
    log("Generating comprehensive test report...", CYAN)
    
    report = {
        "report_time": datetime.now().isoformat(),
        "components": results.get("components_health", {}),
        "chain_diagnostic": results.get("chain_diagnostic", {}),
        "observability": results.get("observability", {}),
        "load_tests": results.get("load_tests", {}),
        "error_tests": results.get("error_tests", {}),
    }
    
    # Save report
    report_file = Path.home() / ".cortexagent" / "test_results" / f"full_test_{int(time.time())}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    # Print summary
    log(f"\n{'='*70}", CYAN)
    log(f"FULL TEST REPORT", CYAN)
    log(f"{'='*70}", CYAN)
    
    # Component health
    log(f"\n1. COMPONENT HEALTH", GREEN)
    comp_health = results.get("components_health", {}).get("components", {})
    for name, status in comp_health.items():
        if status.get("status") == "healthy":
            log(f"  ✅ {name}: healthy", GREEN)
        else:
            log(f"  ❌ {name}: {status.get('error', 'unhealthy')}", RED)
    
    # Chain diagnostic
    log(f"\n2. CHAIN DIAGNOSTIC", GREEN)
    chain_diag = results.get("chain_diagnostic", {})
    if chain_diag.get("chain") == "diagnostic_completed":
        log(f"  ✅ Chain diagnostic passed", GREEN)
    else:
        log(f"  ❌ Chain diagnostic failed: {chain_diag.get('chain', 'unknown')}", RED)
    
    # Observability
    log(f"\n3. OBSERVABILITY", GREEN)
    obs = results.get("observability", {})
    if obs:
        log(f"  ✅ Trace saved: {obs.get('trace_id', 'unknown')}", GREEN)
        eval_score = obs.get('evaluation', {}).get('overall_score', 0)
        log(f"  ✅ Evaluation score: {eval_score}", GREEN)
    else:
        log(f"  ❌ Observability test failed", RED)
    
    # Load tests
    log(f"\n4. LOAD TESTS", GREEN)
    load_tests = results.get("load_tests", {})
    if load_tests:
        for test_name in ["proxy", "overseer", "e2e", "disk_io"]:
            test_result = load_tests.get(test_name, {})
            if test_result:
                successes = test_result.get("successes", 0)
                failures = test_result.get("failures", 0)
                throughput = test_result.get("throughput", 0)
                latency_p95 = test_result.get("latency_p95_ms", 0)
                
                status_str = f"{successes}/{test_result.get('count', 0)} passed"
                if failures > 0:
                    status_str += f" ({failures} failures)"
                
                log(f"  {test_name:10s} {status_str:30s} "
                    f"{throughput:.1f} req/s  "
                    f"p95: {latency_p95:.1f}ms",
                    GREEN if failures == 0 else RED)
    else:
        log(f"  ❌ Load tests failed", RED)
    
    # Error tests
    log(f"\n5. ERROR INJECTION", GREEN)
    error_tests = results.get("error_tests", {})
    if error_tests:
        for test_name in ["model_down", "network_timeout"]:
            test_result = error_tests.get(test_name, {})
            if test_result:
                successes = test_result.get("successes", 0)
                failures = test_result.get("failures", 0)
                status_str = f"{successes}/{test_result.get('count', 0)} passed"
                if failures > 0:
                    status_str += f" ({failures} failures)"
                log(f"  {test_name:20s} {status_str}", GREEN if failures == 0 else RED)
    else:
        log(f"  ❌ Error tests failed", RED)
    
    # Report location
    log(f"\n{'='*70}", CYAN)
    log(f"Report saved to: {report_file}", CYAN)
    log(f"{'='*70}", CYAN)


def main():
    """Run the full test suite."""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        results = {}
        results["components_health"] = run_component_health()
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "load":
        results = {}
        results["load_tests"] = run_load_tests()
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        # Generate report from existing results
        log("Report generation requires running full test suite first.", RED)
        return
    
    # Run everything
    log("Starting full system test suite...", CYAN)
    start_time = time.time()
    
    results = {}
    
    try:
        results["components_health"] = run_component_health()
        results["chain_diagnostic"] = run_chain_diagnostic()
        results["observability"] = run_observability_test()
        results["load_tests"] = run_load_tests()
        results["error_tests"] = run_error_tests()
    except Exception as e:
        log(f"  ❌ Test suite failed: {e}", RED)
        import traceback
        traceback.print_exc()
    
    # Generate report
    generate_report(results)
    
    # Print duration
    duration = time.time() - start_time
    log(f"\nTotal duration: {duration:.2f}s", CYAN)
    log(f"Test suite complete!", GREEN)


if __name__ == "__main__":
    main()
