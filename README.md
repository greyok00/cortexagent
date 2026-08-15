# CortexAgent

A local, air-gapped coding agent runtime with two llama-server models, a slimtoken chokepoint proxy, an always-on overseer daemon, and three UIs (CLI, 3D WebUI, tray), with all traffic on 127.0.0.1 and no cloud fallbacks.

## Quick Start

```bash
# Start the system
python3 lib/daemon.py start      # Start big model + proxy
python3 lib/overseer.py start    # Start tiny model + overseer
python3 lib/webui.py start       # Start WebUI (optional)

# Use the CLI
python3 lib/tui.py               # Launch TUI chat

# Check status
python3 lib/overseer.py status   # Overseer status
python3 lib/chain_diagnostic.py  # Full chain diagnostic
```

## Architecture

CortexAgent is designed as a fully instrumented "agent spine" with:
- **Routing** → Intent classification + route decision
- **Framing** → Domain analysis + prompt optimization
- **LLM** → Big model (Qwen3.6-35B) + tiny model (LFM2.5-1.2B)
- **Beautify** → Tables, charts, diagrams
- **Output** → Domain-specific formatting

See `ARCHITECTURE.md` for the full architecture diagram and component details.

## Observability

CortexAgent includes a comprehensive observability layer:

### Trace Spans

Each agent run generates a trace with spans for every operation:
```python
from lib.observability import Trace, Span, save_trace

trace = Trace(user_input="test", workflow="example")
with Span(trace.trace_id, "llm", "tiny_model_query") as span:
    span.set_metric("tokens_in", 50)
    span.set_metric("tokens_out", 100)
save_trace(trace)
```

### Metrics

Token/cost/latency/error metrics are collected per span:
```bash
# View metrics
python3 lib/observability.py metrics
```

### Evaluations

Automated evaluations for groundedness, hallucination, and safety:
```bash
python3 lib/observability.py eval --trace=<trace_id>
```

### Load Test Kit

Test the system under pressure:
```bash
# Quick smoke test
python3 lib/load_test.py --smoke

# Proxy load test (100 requests, 10 parallel)
python3 lib/load_test.py proxy --count=100 --parallel=10

# Overseer load test (50 requests, 5 parallel)
python3 lib/load_test.py overseer --count=50 --parallel=5

# End-to-end load test
python3 lib/load_test.py e2e --count=100 --parallel=10

# Disk I/O stress test
python3 lib/load_test.py disk --count=1000 --parallel=20

# Error injection tests
python3 lib/load_test.py error --injection=model_down
python3 lib/load_test.py error --injection=network_timeout

# Run all tests
python3 lib/load_test.py all --count=500 --parallel=20
```

### Full Test Suite

Comprehensive system test with report generation:
```bash
# Run everything
python3 lib/run_full_test.py

# Health check only
python3 lib/run_full_test.py health

# Load tests only
python3 lib/run_full_test.py load
```

## Components

### Grammar Proxy (`lib/grammar_proxy.py`)

Strips Anthropic grammar fields, runs slimtoken minification, tracks tokens.

**Features**:
- 5-stage minification: system, dedup, messages, tools, distill
- Token budget: 131072
- Chunked minify + response minify
- Token tracking + `/metrics` endpoint

### Overseer (`lib/overseer.py`)

Orchestrates the tiny model, manages queues, schedules, and memory.

**Features**:
- Tiny model: LFM2.5-1.2B on `:8082`
- Task queue: command, llm, subagent, media, ingest
- Schedule manager: cron, daily, weekly, date-based
- Memory management: hot → warm → cold
- Token tracking: proxy + tiny model paths merged

### React Loop (`lib/react_loop.py`)

Drives the tiny model through Thought → Action → Observation loops.

**Modes**:
- `react`: Straight tool-calling loop
- `socratic`: Surface assumptions + falsification questions
- `direct`: Single tiny query, no tools

### Session Bridge (`lib/session_bridge.py`)

Shared-file bridge between TUI, webui, and overseer.

**Features**:
- Atomic JSONL appends with `flock`
- Per-origin cursor tracking
- SSE streaming to UIs

### TUI (`lib/tui.py`)

Full-screen chat with Textual 8.x.

**Features**:
- Streaming (chunk-by-chunk)
- Typed response blocks: text, code, tools, disclosures
- Collapsed code cards with copy/save/search
- Terminal-escape-sanitized output

### WebUI (`lib/webui.py`)

3D dashboard with chat interface.

**Features**:
- Real-time metrics: VRAM, tokens, TPS, latency
- Mini-map (3D visualization)
- Chat interface with streaming
- Dashboard cards for all subsystems

### Tray (`lib/tray.py`)

System tray icon with popout dashboard.

**Features**:
- Manages overseer start/stop
- Quick options: dashboard, CLI, restart
- Popout dashboard: memory, tokens, queue, alerts

## Security

### Defenses

1. **Grammar Proxy**: Strips grammar fields, minifies content
2. **Injection Guardrails**: Explicit warnings on tool outputs
3. **Trust Tagging**: Tool outputs wrapped in "tool_output" markers
4. **Output Filtering**: Sanitized terminal output
5. **Sandboxing**: Command execution with timeouts
6. **Session Isolation**: Per-origin cursors + logging

### Safety Detection

- **Keyword Matching**: 20+ injection keywords
- **Pattern Matching**: Common injection techniques
- **Confidence Scoring**: 0-1 safety score
- **Flags**: `potential_injection`, `unsafe_content`, etc.

## Token Tracking

### Proxy Path (Big Model)

- Tracks `tokens_in`, `tokens_out`, `tokens_saved` per request
- Minification savings: `tokens_saved = tokens_in - tokens_out`
- Savings ratio: `ratio_pct = tokens_saved / tokens_in * 100`

### Tiny Model Path (Overseer)

- Tracks `tokens_in`, `tokens_out`, `tokens_saved` per query
- Merged with proxy stats for unified view

### View Stats

```bash
python3 lib/overseer.py status
python3 lib/chain_diagnostic.py
python3 lib/observability.py metrics
```

## Memory Architecture

### Memory Tiers

```
HOT (Uncapped Append)
  → WARM (Curated Facts)
    → COLD (Archived)
```

### Memory Operations

- **Hot → Warm Sync**: Every tick
- **Cold Distill**: Every idle tick
- **Compact**: When hot exceeds threshold
- **Query**: Fast queries via SQLite

## Configuration

### Environment Variables

- `CORTEXAGENT_STATE_DIR`: State directory (default: `~/.cortexagent`)
- `CORTEXAGENT_MAX_TOOLS`: Max tools for tiny model (default: 16)
- `CORTEXAGENT_TOOL_STUBS`: Enable stub mode (default: 1)
- `CORTEXAGENT_MINIFY`: Enable minification (default: 1)
- `CORTEXAGENT_MINIFY_TOOLS`: Minify tool schemas (default: 1)
- `CORTEXAGENT_AUTHOR`: Author tag for prompts

### State Files

- `~/.cortexagent/overseer_state.json`: Overseer state
- `~/.cortexagent/overseer_queue.json`: Task queue
- `~/.cortexagent/overseer_schedule.json`: Schedule entries
- `~/.cortexagent/token_tracker.json`: Token stats
- `~/.cortexagent/minify_stats.json`: Minify stats
- `~/.cortexagent/observability/`: Observability data
- `~/.cortexagent/test_results/`: Load test results

## File Structure

```
/home/grey/cortexagent/
├── lib/
│   ├── beautify.py           # Output beautification
│   ├── chain_diagnostic.py   # Full chain diagnostic
│   ├── daemon.py             # Big model daemon
│   ├── grammar_proxy.py      # Proxy + minification
│   ├── load_test.py          # Load test kit
│   ├── observability.py      # Trace/metrics/evals
│   ├── output_frame.py       # Output formatting
│   ├── overseer.py           # Overseer daemon
│   ├── pre_flight_gate.py    # Intent classification
│   ├── prompt_framing.py     # Prompt optimization
│   ├── react_loop.py         # ReAct/Socratic engine
│   ├── response_model.py     # TUI response parsing
│   ├── run_full_test.py      # Full test suite
│   ├── session_bridge.py     # Shared file bridge
│   ├── tiny_llm.py           # Tiny model interface
│   ├── token_tracker.py      # Token tracking
│   ├── tool_registry.py      # Tool registry
│   ├── tui.py                # Terminal UI
│   └── webui.py              # Web UI
├── assets/
│   └── cortexagentsquarelogo.png  # Tray icon
├── ARCHITECTURE.md           # Full architecture diagram
├── ARCHITECTURAL_AUDIT_PROMPT.md   # Audit brief
├── CHAIN_OVERHAUL_PLAN.md    # Implementation plan
└── README.md                 # This file
```

## Development

### Testing

```bash
# Run all tests
python3 lib/run_full_test.py

# Run specific tests
python3 lib/run_full_test.py health
python3 lib/run_full_test.py load

# Load test kit
python3 lib/load_test.py --smoke
python3 lib/load_test.py proxy --count=100 --parallel=10
python3 lib/load_test.py overseer --count=50 --parallel=5
python3 lib/load_test.py e2e --count=100 --parallel=10

# Observability
python3 lib/observability.py --smoke
python3 lib/observability.py traces
python3 lib/observability.py metrics
python3 lib/observability.py eval --trace=<trace_id>
```

### Adding New Components

1. Create module in `lib/`
2. Add to chain diagnostic (`lib/chain_diagnostic.py`)
3. Add to load test (`lib/load_test.py`)
4. Add to full test suite (`lib/run_full_test.py`)
5. Document in `ARCHITECTURE.md`

### Adding New Tests

1. Add test function to `lib/load_test.py`
2. Add test runner to `lib/run_full_test.py`
3. Document in README.md

## Performance

### Optimization Strategies

1. **Minification**: 5-stage slimtoken pipeline
2. **Stub Mode**: 35 tokens vs 180 full for tool surface
3. **Token Budget**: 131072 token limit
4. **Chunked Minify**: For long contexts
5. **Response Minify**: Stream compression
6. **Memory Tiers**: Hot → Warm → Cold

### Key Metrics

- **Throughput**: req/s (load tests)
- **Latency**: avg, p95, max (ms)
- **Error Rate**: % of failed requests
- **Token Savings**: % reduction via minification
- **VRAM Usage**: Per-process breakdown

## Security

### Threat Model

- **Single-user, local system**: User is trusted
- **Untrusted content**: Files, emails, web pages, MCP outputs, browser content can contain adversarial instructions
- **Local-only**: All traffic on 127.0.0.1, no cloud fallbacks

### Defenses

1. **Grammar Proxy**: Strips grammar fields, minifies content
2. **Injection Guardrails**: Explicit warnings on tool outputs
3. **Trust Tagging**: Tool outputs wrapped in "tool_output" markers
4. **Output Filtering**: Sanitized terminal output
5. **Sandboxing**: Command execution with timeouts
6. **Session Isolation**: Per-origin cursors + logging

## License

This project is proprietary and confidential.
