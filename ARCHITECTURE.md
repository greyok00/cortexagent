# CortexAgent Architecture

A local, air-gapped coding agent runtime with two llama-server models, a slimtoken chokepoint proxy, an always-on overseer daemon, and three UIs (CLI, 3D WebUI, tray), with all traffic on 127.0.0.1 and no cloud fallbacks.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER                                     │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐                   │
│  │   TUI     │  │  WebUI    │  │  Tray     │                   │
│  │  (Textual)│  │  (3D)     │  │  (GTK)    │                   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘                   │
│        │              │              │                          │
│        └──────────────┼──────────────┘                          │
│                       │                                         │
│               ┌───────▼───────┐                                 │
│               │  SessionBridge│  ← Shared file bridge (JSONL)    │
│               │  (JSONL log)  │  ← Atomic appends + cursors    │
│               └───────┬───────┘                                 │
│                       │                                         │
│               ┌───────▼───────┐                                 │
│               │   CONTROL     │                                 │
│               │   SOCKET      │                                 │
│               └───────┬───────┘                                 │
└───────────────────────┼─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      DAEMON (lib/daemon.py)                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Big Model: Qwen3.6-35B on :8080                        │   │
│  │  - Multimodal (vision, tools)                             │   │
│  │  - Session management                                     │   │
│  │  - Idle-unload (VRAM management)                          │   │
│  │  - VRAM monitoring                                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Proxy: Grammar Proxy on :8081                           │   │
│  │  - Strips Anthropic grammar fields                        │   │
│  │  - Slimtoken minification (5 stages)                      │   │
│  │  - Cold memory attachment                                   │   │
│  │  - Token tracking + /metrics endpoint                       │   │
│  │  - Dashboard step counting                                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  SessionBridge: Shared file bridge                       │   │
│  │  - Atomic JSONL appends + flock                           │   │
│  │  - Per-origin cursors                                     │   │
│  │  - SSE streaming to UIs                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                   OVERSEER (lib/overseer.py)                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Tiny Model: LFM2.5-1.2B on :8082                        │   │
│  │  - ReAct/Socratic orchestration                            │   │
│  │  - Tool registry (12 core + MCP + browser)                  │   │
│  │  - Stub mode (35 tokens vs 180 full)                       │   │
│  │  - Injection guardrails                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Queue Manager                                           │   │
│  │  - Task types: command, llm, subagent, media, ingest     │   │
│  │  - Sequential dispatch + lock                            │   │
│  │  - Cleanup (old tasks, >1 hour)                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Schedule Manager                                          │   │
│  │  - Cron, daily, weekly, date-based schedules              │   │
│  │  - Enable/disable control                                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Memory Management                                       │   │
│  │  - Hot: uncapped append of every prompt/response           │   │
│  │  - Cold: JSON + SQLite for fast queries                   │   │
│  │  - Hot→Cold distill on every tick                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Observability (lib/observability.py)                     │   │
│  │  - Trace spans for every agent run                        │   │
│  │  - Token/cost/latency/error metrics                       │   │
│  │  - Prompt injection detection                             │   │
│  │  - Evaluation hooks (groundedness, hallucination, safety) │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Load Test Kit (lib/load_test.py)                         │   │
│  │  - Concurrent proxy requests                              │   │
│  │  - Overseer queue dispatches                              │   │
│  │  - Memory pressure tests                                  │   │
│  │  - Disk I/O stress                                        │   │
│  │  - End-to-end stress tests                                │   │
│  │  - Error injection (model down, timeout)                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Full Test Suite (lib/run_full_test.py)                   │   │
│  │  - Component health check                                 │   │
│  │  - Chain diagnostic                                       │   │
│  │  - Load test suite                                        │   │
│  │  - Error injection tests                                  │   │
│  │  - Comprehensive report generation                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Request Chain

The request chain flows through several passes before reaching the model:

```
User Input
    │
    ▼
┌─────────────────────────────────────────────┐
│  1. MEMORY APPEND                           │
│     - SessionBridge writes to JSONL log      │
│     - Atomic append + flock                  │
│     - Per-origin cursor tracking             │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  2. INTENT CLASSIFICATION                   │
│     - pre_flight_gate.py                     │
│     - Classifies: command, llm, info, etc.   │
│     - Detects: ambiguous, safety, memory     │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  3. ROUTING                                 │
│     - CLI/WebUI → Grammar Proxy (big model)  │
│     - Overseer → Tiny Model (direct)         │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  4. PROMPT FRAMING (overseer path)          │
│     - prompt_framing.py                      │
│     - Domain classification                  │
│     - Prompt optimization                    │
│     - System prompt injection                │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  5. MINIFICATION (proxy path)               │
│     - slimtoken pipeline (5 stages)          │
│     - stages: system, dedup, messages,       │
│       tools, distill                         │
│     - Token budget: 131072                   │
│     - Chunked minify + response minify       │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  6. MODEL INFERENCE                         │
│     - Big: Qwen3.6-35B on :8080             │
│     - Tiny: LFM2.5-1.2B on :8082            │
│     - Streaming responses                    │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  7. BEAUTIFICATION                          │
│     - beautify.py                            │
│     - Tables, CSV, key:value → markdown      │
│     - ASCII bar/line/pie charts             │
│     - Tree/hierarchy diagrams                │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  8. OUTPUT FORMATTING                       │
│     - output_frame.py                        │
│     - Domain-specific structure              │
│     - Executive summary, findings,          │
│       recommendations, action items          │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  9. SESSION LOG                             │
│     - SessionBridge writes to JSONL log     │
│     - Atomic append + flock                 │
│     - SSE streaming to UIs                  │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  10. UI RENDERING                           │
│      - TUI: Textual chat with typed blocks   │
│      - WebUI: 3D dashboard + chat            │
│      - Tray: Popout dashboard + tray icon    │
└─────────────────────────────────────────────┘
```

## Core Components

### 1. Grammar Proxy (`lib/grammar_proxy.py`)

**Purpose**: Strips Anthropic grammar fields from requests, runs minification, tracks tokens.

**Features**:
- Grammar field stripping (Anthropic → llama-server compatibility)
- 5-stage slimtoken minification pipeline
- Cold memory attachment
- Token tracking + `/metrics` endpoint
- Dashboard step counting
- Streaming response forwarding

**Minification Stages**:
1. `system`: Minify system prompt
2. `dedup`: Deduplicate repeated tool output
3. `messages`: Budget backstop for messages
4. `tools`: Minify tool schemas
5. `distill`: Distill old turns into summaries

**Token Tracking**:
- Records `tokens_in`, `tokens_out`, `tokens_saved` per request
- Maintains `ratio_pct` savings rate
- Persists to `~/.cortexagent/minify_stats.json`
- Exposed via `/metrics` endpoint

### 2. Overseer (`lib/overseer.py`)

**Purpose**: Orchestrates the tiny model, manages queues, schedules, and memory.

**Features**:
- Tiny model: LFM2.5-1.2B on `:8082`
- ReAct/Socratic orchestration via `react_loop.py`
- Task queue: command, llm, subagent, media, ingest
- Schedule manager: cron, daily, weekly, date-based
- Memory management: hot → cold
- Token tracking: proxy + tiny model paths merged
- Output beautification + formatting passes

**Queue Types**:
- `command`: Execute shell commands
- `llm`: ReAct/Socratic loop with tiny model
- `subagent`: Spawn Claude Code subagent (full tool access)
- `image`: Generate images via diffusion
- `video`: Generate videos via diffusion
- `media`: Auto-detect image/video/text
- `ingest`: Domain-specific knowledge ingestion

### 3. React Loop (`lib/react_loop.py`)

**Purpose**: Drives the tiny model through Thought → Action → Observation loops.

**Modes**:
- `react`: Straight tool-calling loop for well-defined tasks
- `socratic`: Surface assumptions + falsification questions
- `direct`: Single tiny query, no tools (conversation)

**Features**:
- Domain classification via `prompt_framing.py`
- Prompt optimization before model call
- Injection guardrails on tool outputs
- Stub mode: 35 tokens vs 180 full for tool surface
- Timeout protection for hung tools
- Step publishing to dashboard/tray

### 4. Session Bridge (`lib/session_bridge.py`)

**Purpose**: Shared-file bridge between TUI, webui, and overseer.

**Features**:
- Atomic JSONL appends with `flock`
- Per-origin cursor tracking
- SSE streaming to UIs
- Tail API for chat history

**Concurrency**:
- Writes take exclusive `LOCK_EX`
- Reads snap cursor at file open
- `O_APPEND` ensures atomic writes ≤ 4096B

### 5. TUI (`lib/tui.py`)

**Purpose**: Full-screen chat with Textual 8.x.

**Features**:
- Streaming (chunk-by-chunk) via `claude -p`
- Typed response blocks: text, code, tools, disclosures
- Collapsed code cards with copy/save/search
- Terminal-escape-sanitized output
- Compact status line + footer hints

### 6. WebUI (`lib/webui.py`)

**Purpose**: 3D dashboard with chat interface.

**Features**:
- Real-time metrics: VRAM, tokens, TPS, latency
- Mini-map (3D visualization)
- Chat interface with streaming
- Dashboard cards for all subsystems
- SSE streaming for live updates

### 7. Tray (`lib/tray.py`)

**Purpose**: System tray icon with popout dashboard.

**Features**:
- Manages overseer start/stop
- Quick options: dashboard, CLI, restart
- Popout dashboard: memory, tokens, queue, alerts
- Real-time updates via state files

## Observability Layer

### Trace Spans (`lib/observability.py`)

**Architecture**:
- Each user-visible conversation = one "trace"
- Each LLM call, tool call, memory op = one "span"
- Spans carry: `session_id`, `span_id`, `parent_id`, `timing`, `metrics`, `tags`
- All data written atomically to `~/.cortexagent/observability/`

**Span Types**:
- `routing`: Intent classification + route decision
- `framing`: Prompt framing + domain analysis
- `minify`: Token minification pass
- `llm`: LLM inference (big or tiny)
- `tool`: Tool execution
- `beautify`: Output beautification pass
- `output`: Final output formatting
- `memory`: Memory operation (hot/cold)
- `eval`: Evaluation/guardrail check
- `error`: Error/failure span

**Safety Detection**:
- Keyword matching for injection patterns
- Pattern matching for common injection techniques
- Confidence scoring (0-1)
- Safety flags for downstream handling

**Evaluation Hooks**:
- Groundedness: Check for citations, hedging language
- Hallucination: Check for uncertainty terms
- Safety: Prompt injection detection
- Performance: Tokens per second, step efficiency

### Load Test Kit (`lib/load_test.py`)

**Test Types**:
1. **Proxy Test**: Concurrent requests to grammar proxy
2. **Overseer Test**: Concurrent queue dispatches
3. **Memory Test**: Sustained memory pressure over time
4. **Disk I/O Test**: File write stress (atomic append + rename)
5. **End-to-End Test**: Full request chain simulation
6. **Error Injection**: Model down, network timeout

**Metrics**:
- Success/failure rates
- Throughput (req/s)
- Latency: avg, p95, max
- Error rates by type

### Full Test Suite (`lib/run_full_test.py`)

**Orchestration**:
1. Component health check
2. Chain diagnostic
3. Observability smoke test
4. Load test suite
5. Error injection tests
6. Comprehensive report generation

**Report**:
- JSON report with all test results
- Colored summary in terminal
- Metrics across all subsystems

## Memory Architecture

### Memory Tiers

```
┌─────────────────────────────────────────────┐
│  HOT (Uncapped Append)                      │
│  - Every prompt/response written immediately │
│  - No size limit                            │
│  - Stored in JSONL log                      │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  COLD (Archived)                            │
│  - Old turns distilled into summaries       │
│  - JSON + SQLite for fast queries           │
│  - Domain categorization                    │
│  - Written every idle tick                  │
└─────────────────────────────────────────────┘
```

### Memory Operations

- **Hot → Cold Distill**: Every tick, hot data is distilled to cold facts
- **Compact**: When hot exceeds threshold, old data is compacted
- **Query**: Fast queries via SQLite

## Token Tracking

### Proxy Path (Big Model)

- Tracks `tokens_in`, `tokens_out`, `tokens_saved` per request
- Minification savings: `tokens_saved = tokens_in - tokens_out`
- Savings ratio: `ratio_pct = tokens_saved / tokens_in * 100`
- Persists to `~/.cortexagent/minify_stats.json`
- Exposed via `/metrics` endpoint

### Tiny Model Path (Overseer)

- Tracks `tokens_in`, `tokens_out`, `tokens_saved` per query
- Rough estimate: `tokens = chars / 4`
- Merged with proxy stats for unified view
- Persists to `~/.cortexagent/token_tracker.json`
- Exposed via `overseer status` CLI

### Unified Token Stats

```json
{
  "proxy": {
    "runs": 69,
    "tokens_in": 373,
    "tokens_out": 373,
    "tokens_saved": 0,
    "ratio_pct": 0.0
  },
  "tiny_model": {
    "runs": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "tokens_saved": 0,
    "ratio_pct": 0.0
  },
  "total": {
    "runs": 69,
    "tokens_in": 373,
    "tokens_out": 373,
    "tokens_saved": 0,
    "ratio_pct": 0.0
  }
}
```

## Security Model

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

### Safety Detection

- **Keyword Matching**: 20+ injection keywords
- **Pattern Matching**: Common injection techniques
- **Confidence Scoring**: 0-1 safety score
- **Flags**: `potential_injection`, `unsafe_content`, etc.

## Performance

### Optimization Strategies

1. **Minification**: 5-stage slimtoken pipeline
2. **Stub Mode**: 35 tokens vs 180 full for tool surface
3. **Token Budget**: 131072 token limit
4. **Chunked Minify**: For long contexts
5. **Response Minify**: Stream compression
6. **Memory Tiers**: Hot → Cold

### Metrics

- **Throughput**: req/s (load tests)
- **Latency**: avg, p95, max (ms)
- **Error Rate**: % of failed requests
- **Token Savings**: % reduction via minification
- **VRAM Usage**: Per-process breakdown

## Usage

### Start System

```bash
# Start daemon + proxy + models
python3 lib/daemon.py start

# Start overseer
python3 lib/overseer.py start

# Start WebUI
python3 lib/webui.py start
```

### Run Tests

```bash
# Full test suite
python3 lib/run_full_test.py

# Component health
python3 lib/run_full_test.py health

# Load tests
python3 lib/run_full_test.py load

# Load test kit
python3 lib/load_test.py proxy --count=100 --parallel=10
python3 lib/load_test.py overseer --count=50 --parallel=5
python3 lib/load_test.py e2e --count=100 --parallel=10
python3 lib/load_test.py disk --count=1000 --parallel=20
python3 lib/load_test.py error --injection=model_down
python3 lib/load_test.py all --count=500 --parallel=20
```

### Check Status

```bash
# Overseer status
python3 lib/overseer.py status

# Chain diagnostic
python3 lib/chain_diagnostic.py

# Observability
python3 lib/observability.py traces
python3 lib/observability.py metrics
python3 lib/observability.py eval --trace=<trace_id>
```

## File Structure

```
cortexagent/  (clone root)
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
├── ARCHITECTURE.md           # This file
├── ARCHITECTURAL_AUDIT_PROMPT.md   # Audit brief
└── CHAIN_OVERHAUL_PLAN.md    # Implementation plan
```

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
- `~/.cortexagent/observability/traces.ndjson`: Trace data
- `~/.cortexagent/observability/metrics.ndjson`: Metrics data
- `~/.cortexagent/test_results/`: Load test results
