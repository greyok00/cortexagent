#!/usr/bin/env python3

import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
from collections import defaultdict

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


_OBS_DIR = Path.home() / ".cortexagent" / "observability"
_OBS_DIR.mkdir(parents=True, exist_ok=True)

_TRACES_FILE = _OBS_DIR / "traces.ndjson"
_METRICS_FILE = _OBS_DIR / "metrics.ndjson"
_LOGS_DIR = _OBS_DIR / "logs"
_LOGS_DIR.mkdir(exist_ok=True)



SAFETY_KEYWORDS = [
    "ignore previous", "disregard", "new instructions", "system override",
    "developer mode", "ignore safety", "bypass", "unleash", "jailbreak",
    "DAN mode", "do anything now", "secret mode", "debug mode",
    "prompt injection", "malicious", "attack", "exploit",
]







_TRACES: Dict[str, "Trace"] = {}
_TRACES_MAX = 200


def _get_trace(trace_id: str, session_id: str = None) -> "Trace":

    trace = _TRACES.get(trace_id)
    if trace is None:
        trace = Trace(trace_id=trace_id, session_id=session_id or str(trace_id))
        _TRACES[trace_id] = trace
        if len(_TRACES) > _TRACES_MAX:
            oldest = next(iter(_TRACES))
            _TRACES.pop(oldest, None)
    return trace



class Span:

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


        _get_trace(trace_id).add_span(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)

        metrics.record_span(self)
        if self.parent_id:
            parent = _get_span(self.trace_id, self.parent_id)
            if parent:
                parent.children.append(self.span_id)

    def set_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value


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



def _append_ndjson(path: Path, data: Dict) -> None:

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")
            f.flush()
    except Exception:
        pass


def save_trace(trace: Trace) -> None:

    reg = _TRACES.get(trace.trace_id)
    if reg is None:
        _append_ndjson(_TRACES_FILE, trace.to_dict())
        return
    if not reg.user_input and trace.user_input:
        reg.user_input = trace.user_input
    if trace.workflow and trace.workflow != "default":
        reg.workflow = trace.workflow
    if trace.session_id and trace.session_id != reg.session_id:
        reg.session_id = trace.session_id
    _append_ndjson(_TRACES_FILE, reg.to_dict())


def _get_span(trace_id: str, span_id: str) -> Optional[Span]:

    trace = _TRACES.get(trace_id)
    if trace:
        for s in trace.spans:
            if s.span_id == span_id:
                return s
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



class MetricsCollector:


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

        key = span.span_type
        m = self.metrics[key]
        m["total_runs"] += 1
        m["total_tokens_in"] += span.metrics.get("tokens_in", 0)
        m["total_tokens_out"] += span.metrics.get("tokens_out", 0)
        m["total_latency_ms"] += span.duration_ms
        if span.status == "error":
            m["total_errors"] += 1

        if span.duration_ms > m["p95_latency_ms"] * 0.9:
            m["p95_latency_ms"] = span.duration_ms

    def get_summary(self) -> Dict:

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

        _append_ndjson(_METRICS_FILE, {
            "timestamp": time.time(),
            "metrics": self.get_summary(),
        })



def detect_injection(text: str) -> Tuple[bool, float]:

    if not text:
        return False, 0.0

    text_lower = text.lower()
    hits = sum(1 for kw in SAFETY_KEYWORDS if kw in text_lower)
    confidence = min(hits * 0.2, 1.0)


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



def evaluate_trace(trace: Trace) -> Dict:


    outputs = []
    for span in trace.spans:
        if span.span_type in ("llm", "output"):
            outputs.append(span.payload.get("content", ""))

    combined = " ".join(outputs)


    groundedness = 0.5
    if combined:

        has_citations = bool(re.search(r'(?:source|citation|reference|link|url)\s*[:=]', combined.lower()))
        has_hedging = bool(re.search(r'(?:according to|based on|reports|suggests|indicates)', combined.lower()))
        if has_citations or has_hedging:
            groundedness = 0.8


    hallucination_rate = 0.1
    if combined:
        uncertain_terms = sum(1 for word in ["possibly", "maybe", "could be", "might be", "unclear"] if word in combined.lower())
        hallucination_rate = min(uncertain_terms * 0.1, 0.5)


    safety = assess_safety(combined)


    performance = 0.5
    llm_spans = [s for s in trace.spans if s.span_type == "llm"]
    if llm_spans:
        total_tokens = sum(s.metrics.get("tokens_out", 0) for s in llm_spans)
        total_time = sum(s.duration_ms for s in llm_spans)
        if total_time > 0:
            tps = total_tokens / (total_time / 1000)
            performance = min(tps / 50, 1.0)


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






metrics = MetricsCollector()



def span(trace_id: str, span_type: str, name: str, parent_id: str = None,
         tags: Dict = None) -> Span:

    return Span(trace_id, span_type, name, parent_id, tags)



def main():

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        print("Observability smoke test:")

        trace = Trace(trace_id="test", session_id="test",
                      user_input="test prompt", workflow="test")


        with span(trace.trace_id, "framing", "domain_classification") as s1:
            s1.set_metric("domain", "professional")
            time.sleep(0.01)

        with span(trace.trace_id, "llm", "llm_query") as s2:
            s1.children.append(s2.span_id)
            s2.set_metric("tokens_in", 50)
            s2.set_metric("tokens_out", 100)
            time.sleep(0.01)

        with span(trace.trace_id, "beautify", "format_output") as s3:
            s1.children.append(s3.span_id)
            time.sleep(0.01)


        eval_result = evaluate_trace(trace)
        print(f"  Trace saved: {trace.trace_id}")
        print(f"  Evaluation: {json.dumps(eval_result, indent=2)}")
        print(f"  Metrics: {json.dumps(metrics.get_summary(), indent=2)}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "traces":

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

        print("Metrics Summary:")
        summary = metrics.get_summary()
        for key, m in summary.items():
            print(f"\n  {key}:")
            for k, v in m.items():
                print(f"    {k}: {v}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "eval":

        if len(sys.argv) < 3 or sys.argv[2] != "--trace":
            print("Usage: observability.py eval --trace=<trace_id>")
            return
        trace_id = sys.argv[3]

        if not _TRACES_FILE.exists():
            print("No traces found.")
            return
        with open(_TRACES_FILE, "r") as f:
            for line in f.readlines():
                trace = json.loads(line)
                if trace["trace_id"] == trace_id:

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
