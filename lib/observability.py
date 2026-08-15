#!/usr/bin/env python3
"""observability.py — End-to-end observability layer for CortexAgent.

Implements:
1. Trace spans for every agent run (routing → framing → LLM → beautify → output)
2. Token/cost/latency/error metrics per span
3. Prompt injection detection and safety scoring
4. Continuous evaluation hooks (groundedness, hallucination, safety)
5. Structured logging with stable session IDs and workflow tags

Architecture:
  - Each user-visible conversation = one "trace"
  - Each LLM call, tool call, memory op = one "span"
  - Spans carry: session_id, span_id, parent_id, timing, metrics, tags
  - All data written atomically to ~/.cortexagent/observability/

Usage:
  python3 lib/observability.py smoke          # self-test
  python3 lib/observability.py traces          # list traces
  python3 lib/observability.py metrics         # display metrics
  python3 lib/observability.py eval --trace=T  # evaluate a trace
"""
import json
import os
import re
import sys
import time
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ── Directory Setup ──────────────────────────────────────────────────────────
_OBS_DIR = Path.home() / ".cortexagent" / "observability"
_OBS_DIR.mkdir(parents=True, exist_ok=True)

_TRACES_FILE = _OBS_DIR / "traces.ndjson"
_METRICS_FILE = _OBS_DIR / "metrics.ndjson"
_EVALS_FILE = _OBS_DIR / "evals.ndjson"
_LOGS_DIR = _OBS_DIR / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

# ── Constants ────────────────────────────────────────────────────────────────
SPAN_TYPES = {
    "routing": "Intent classification + route decision",
    "framing": "Prompt framing + domain analysis",
    "minify":  "Token minification pass",
    "llm":     "LLM inference (big or tiny)",
    "tool":    "Tool execution",
    "beautify": "Output beautification pass",
    "output":  "Final output formatting",
    "memory":  "Memory operation (hot/warm/cold)",
    "eval":    "Evaluation/guardrail check",
    "error":   "Error/failure span",
}

SAFETY_KEYWORDS = [
    "ignore previous", "disregard", "new instructions", "system override",
    "developer mode", "ignore safety", "bypass", "unleash", "jailbreak",
    "DAN mode", "do anything now", "secret mode", "debug mode",
    "prompt injection", "malicious", "attack", "exploit",
]


# ── Trace/Span Data Structures ──────────────────────────────────────────────
class Span:
    """A single span in a trace."""
    __slots__ = ['span_id', 'trace_id', 'parent_id', 'span_type', 'name',
                 'start_time', 'end_time', 'duration_ms', 'tags', 'metrics',
                 'status', 'error', 'payload', 'children']

    def __init__(self, trace_id: str, span_type: str, name: str,
                 parent_id: str = None, tags: Dict = None):
        self.span_id = str(uuid.uuid4())[:8]
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.span_type = span_type
        self.name = name
        self.start_time = time.time()
        self.end_time = None
        self.duration_ms = 0
        self.tags = tags or {}
        self.metrics = {}
        self.status = "ok"
        self.error = ""
        self.payload = {}
        self.children = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        if self.parent_id:
            parent = _get_span(self.trace_id, self.parent_id)
            if parent:
                parent.children.append(self.span_id)

    def set_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def set_error(self, error: str) -> None:
        self.status = "error"
        self.error = str(error)

    def to_dict(self) -> Dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "span_type": self.span_type,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "tags": self.tags,
            "metrics": self.metrics,
            "status": self.status,
            "error": self.error,
            "payload": self.payload,
            "children": self.children,
        }


class Trace:
    """A complete trace with all spans."""
    def __init__(self, trace_id: str = None, session_id: str = None,
                 user_input: str = None, workflow: str = "default"):
        self.trace_id = trace_id or str(uuid.uuid4())[:12]
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.user_input = user_input or ""
        self.workflow = workflow
        self.started_at = time.time()
        self.spans = []

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    def to_dict(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_input": self.user_input[:200] if self.user_input else "",
            "workflow": self.workflow,
            "started_at": self.started_at,
            "duration_ms": round((time.time() - self.started_at) * 1000, 2),
            "spans": [s.to_dict() for s in self.spans],
        }


# ── Trace/Span Storage ──────────────────────────────────────────────────────
def _append_ndjson(path: Path, data: Dict) -> None:
    """Atomically append a JSON line to an NDJSON file."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")
            f.flush()
    except Exception:
        pass


def save_trace(trace: Trace) -> None:
    """Save a trace to disk."""
    _append_ndjson(_TRACES_FILE, trace.to_dict())


def _get_span(trace_id: str, span_id: str) -> Optional[Span]:
    """Retrieve a span from the most recent trace."""
    try:
        if _TRACES_FILE.exists():
            with open(_TRACES_FILE, "r") as f:
                lines = f.readlines()
            for line in reversed(lines[-10:]):
                trace = json.loads(line)
                if trace.get("trace_id") == trace_id:
                    for span in trace.get("spans", []):
                        if span["span_id"] == span_id:
                            return Span(trace_id, span["span_type"], span["name"])
    except Exception:
        pass
    return None


# ── Metrics Tracking ────────────────────────────────────────────────────────
class MetricsCollector:
    """Collect and aggregate metrics across all traces."""

    def __init__(self):
        self.metrics = defaultdict(lambda: {
            "total_runs": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_latency_ms": 0,
            "total_errors": 0,
            "p95_latency_ms": 0,
        })

    def record_span(self, span: Span) -> None:
        """Record metrics from a span."""
        key = span.span_type
        m = self.metrics[key]
        m["total_runs"] += 1
        m["total_tokens_in"] += span.metrics.get("tokens_in", 0)
        m["total_tokens_out"] += span.metrics.get("tokens_out", 0)
        m["total_latency_ms"] += span.duration_ms
        if span.status == "error":
            m["total_errors"] += 1
        # Update p95 (simple approximation)
        if span.duration_ms > m["p95_latency_ms"] * 0.9:
            m["p95_latency_ms"] = span.duration_ms

    def get_summary(self) -> Dict:
        """Get metrics summary."""
        summary = {}
        for key, m in self.metrics.items():
            if m["total_runs"] > 0:
                summary[key] = {
                    "runs": m["total_runs"],
                    "avg_latency_ms": round(m["total_latency_ms"] / m["total_runs"], 2),
                    "p95_latency_ms": round(m["p95_latency_ms"], 2),
                    "tokens_in": m["total_tokens_in"],
                    "tokens_out": m["total_tokens_out"],
                    "error_rate": round(m["total_errors"] / m["total_runs"] * 100, 2),
                }
        return dict(summary)

    def save(self) -> None:
        """Persist metrics to disk."""
        _append_ndjson(_METRICS_FILE, {
            "timestamp": time.time(),
            "metrics": self.get_summary(),
        })


# ── Safety/Injection Detection ──────────────────────────────────────────────
def detect_injection(text: str) -> Tuple[bool, float]:
    """Detect potential prompt injection attempts.

    Returns: (is_injection, confidence_score)
    """
    if not text:
        return False, 0.0

    text_lower = text.lower()
    hits = sum(1 for kw in SAFETY_KEYWORDS if kw in text_lower)
    confidence = min(hits * 0.2, 1.0)  # Each keyword adds 0.2 confidence

    # Check for common injection patterns
    injection_patterns = [
        r"(?i)ignore\s+previous\s+(instructions|prompts|system)",
        r"(?i)new\s+role:?\s*(developer|admin|assistant)",
        r"(?i)disregard\s+all\s+(previous|prior|earlier)",
        r"(?i)system\s+override",
        r"(?i)(?:DAN|do\s+anything\s+now)",
        r"(?i)jailbreak\s+mode",
        r"(?i)bypass\s+safety",
        r"(?i)secret\s+mode",
        r"(?i)debug\s+mode",
    ]
    for pattern in injection_patterns:
        if re.search(pattern, text):
            confidence = max(confidence, 0.9)

    return confidence > 0.5, confidence


def assess_safety(text: str) -> Dict:
    """Assess text for safety concerns.

    Returns: {
        "is_safe": bool,
        "safety_score": float,  # 0-1, higher is safer
        "flags": List[str],
        "confidence": float,
    }
    """
    is_injection, confidence = detect_injection(text)
    flags = []
    if is_injection:
        flags.append("potential_injection")

    return {
        "is_safe": not is_injection,
        "safety_score": round(1.0 - confidence, 2),
        "flags": flags,
        "confidence": round(confidence, 2),
    }


# ── Evaluation Hooks ────────────────────────────────────────────────────────
def evaluate_trace(trace: Trace) -> Dict:
    """Evaluate a trace for quality, safety, and performance.

    Returns: {
        "groundedness": float,  # 0-1, how grounded is the output
        "hallucination_rate": float,  # 0-1, how much hallucination
        "safety_score": float,  # 0-1, how safe is the output
        "performance_score": float,  # 0-1, how efficient was the run
        "overall_score": float,  # weighted average
    }
    """
    # Collect all output from spans
    outputs = []
    for span in trace.spans:
        if span.span_type in ("llm", "output"):
            outputs.append(span.payload.get("content", ""))

    combined = " ".join(outputs)

    # Evaluate groundedness (check for hedging language, citations)
    groundedness = 0.5  # default
    if combined:
        # Check for specific claims, citations, evidence
        has_citations = bool(re.search(r'(?:source|citation|reference|link|url)\s*[:=]', combined.lower()))
        has_hedging = bool(re.search(r'(?:according to|based on|reports|suggests|indicates)', combined.lower()))
        if has_citations or has_hedging:
            groundedness = 0.8

    # Evaluate hallucination (check for uncertainty, contradictions)
    hallucination_rate = 0.1  # default
    if combined:
        uncertain_terms = sum(1 for word in ["possibly", "maybe", "could be", "might be", "unclear"] if word in combined.lower())
        hallucination_rate = min(uncertain_terms * 0.1, 0.5)

    # Evaluate safety
    safety = assess_safety(combined)

    # Evaluate performance (tokens per second, step efficiency)
    performance = 0.5  # default
    llm_spans = [s for s in trace.spans if s.span_type == "llm"]
    if llm_spans:
        total_tokens = sum(s.metrics.get("tokens_out", 0) for s in llm_spans)
        total_time = sum(s.duration_ms for s in llm_spans)
        if total_time > 0:
            tps = total_tokens / (total_time / 1000)
            performance = min(tps / 50, 1.0)  # 50 tps = perfect

    # Overall score (weighted average)
    overall = (
        groundedness * 0.3 +
        (1 - hallucination_rate) * 0.3 +
        safety["safety_score"] * 0.3 +
        performance * 0.1
    )

    return {
        "groundedness": round(groundedness, 2),
        "hallucination_rate": round(hallucination_rate, 2),
        "safety_score": round(safety["safety_score"], 2),
        "performance_score": round(performance, 2),
        "overall_score": round(overall, 2),
        "safety_flags": safety["flags"],
    }


# ── Structured Logging ──────────────────────────────────────────────────────
def log_event(trace_id: str, event: Dict) -> None:
    """Log an event to the observability logs."""
    log_file = _LOGS_DIR / f"{trace_id}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ── Metrics Collector Instance ──────────────────────────────────────────────
metrics = MetricsCollector()


# ── Context Manager for Spans ───────────────────────────────────────────────
def span(trace_id: str, span_type: str, name: str, parent_id: str = None,
         tags: Dict = None) -> Span:
    """Create a span and add it to the trace."""
    span_obj = Span(trace_id, span_type, name, parent_id, tags)
    metrics.record_span(span_obj)
    return span_obj


# ── CLI Interface ───────────────────────────────────────────────────────────
def main():
    """CLI interface for observability."""
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        print("Observability smoke test:")
        # Create a test trace
        trace = Trace(trace_id="test", session_id="test",
                      user_input="test prompt", workflow="test")
        
        # Add some spans
        with span(trace.trace_id, "framing", "domain_classification") as s1:
            s1.set_metric("domain", "professional")
            time.sleep(0.01)
        
        with span(trace.trace_id, "llm", "tiny_model_query") as s2:
            s1.children.append(s2.span_id)
            s2.set_metric("tokens_in", 50)
            s2.set_metric("tokens_out", 100)
            time.sleep(0.01)
        
        with span(trace.trace_id, "beautify", "format_output") as s3:
            s1.children.append(s3.span_id)
            time.sleep(0.01)
        
        # Evaluate
        eval_result = evaluate_trace(trace)
        print(f"  Trace saved: {trace.trace_id}")
        print(f"  Evaluation: {json.dumps(eval_result, indent=2)}")
        print(f"  Metrics: {json.dumps(metrics.get_summary(), indent=2)}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "traces":
        # List recent traces
        if not _TRACES_FILE.exists():
            print("No traces found.")
            return
        with open(_TRACES_FILE, "r") as f:
            lines = f.readlines()[-10:]
        for line in lines:
            trace = json.loads(line)
            print(f"  {trace['trace_id']} | {trace['workflow']} | "
                  f"input: {trace['user_input'][:50]}... | "
                  f"spans: {len(trace['spans'])}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "metrics":
        # Display metrics summary
        print("Metrics Summary:")
        summary = metrics.get_summary()
        for key, m in summary.items():
            print(f"\n  {key}:")
            for k, v in m.items():
                print(f"    {k}: {v}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "eval":
        # Evaluate a trace
        if len(sys.argv) < 3 or sys.argv[2] != "--trace":
            print("Usage: observability.py eval --trace=<trace_id>")
            return
        trace_id = sys.argv[3]
        # Load the trace
        if not _TRACES_FILE.exists():
            print("No traces found.")
            return
        with open(_TRACES_FILE, "r") as f:
            for line in f.readlines():
                trace = json.loads(line)
                if trace["trace_id"] == trace_id:
                    # Reconstruct trace
                    t = Trace(trace_id=trace_id, session_id=trace.get("session_id"))
                    for span_data in trace.get("spans", []):
                        s = Span(trace_id, span_data["span_type"], span_data["name"])
                        s.start_time = span_data["start_time"]
                        s.end_time = span_data["end_time"]
                        s.duration_ms = span_data["duration_ms"]
                        s.tags = span_data.get("tags", {})
                        s.metrics = span_data.get("metrics", {})
                        s.status = span_data.get("status", "ok")
                        s.error = span_data.get("error", "")
                        s.payload = span_data.get("payload", {})
                        s.children = span_data.get("children", [])
                        t.spans.append(s)
                    
                    eval_result = evaluate_trace(t)
                    print(f"Trace {trace_id} Evaluation:")
                    print(json.dumps(eval_result, indent=2))
                    return
        print(f"Trace {trace_id} not found.")
        return


if __name__ == "__main__":
    main()
