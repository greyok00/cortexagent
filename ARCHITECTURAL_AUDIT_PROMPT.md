# CortexAgent Architecture Audit & Optimization Brief

## Mission
Perform a comprehensive architectural analysis of CortexAgent, an AI agent system that routes LLM requests through a proxy, tracks metrics, and provides a CLI/dashboard interface. The goal is to identify security vulnerabilities, stability risks, performance bottlenecks, and opportunities for optimization.

## System Overview

### Components
1. **Grammar Proxy** (Port 8081) — HTTP proxy that:
   - Strips Anthropic `grammar` field from requests (llama-server incompatible)
   - Minifies request bodies via slimtoken (dedup, distill, system, messages)
   - Tracks token usage (prompt/total/avg rates)
   - Exposes `/metrics` endpoint for real-time monitoring

2. **Big Model** (Port 8080) — llama-server serving Qwen3.6-35B-A3B model

3. **Tiny Model** (Port 8082) — llama-server serving LFM2.5-1.2B model (overseer)

4. **Overseer** — Python daemon that:
   - Maintains a task queue (command/llm/agent types)
   - Runs ReAct/Socratic loops via tiny model
   - Dispatches scheduled tasks (cron-based)
   - Manages memory health (hot/warm/cold compartments)
   - Tracks minify stats

5. **React Loop** — Orchestrates tool-calling via tiny model
   - Classifies intent (react/socratic/direct)
   - Manages conversation memory
   - Applies beautification pass to output

6. **WebUI** — HTTP dashboard (Port 8090)
   - Shows system status, queue, schedule, minify stats
   - Serves three.js 3D visualization

7. **System Tray** — GUI tray icon (pystray + appindicator)
   - Overseer lifecycle management
   - Dashboard popout window
   - Minify stats display

8. **Beautify** — Output formatting module
   - Tables, CSV, bar charts, line charts
   - Key-value to table conversion

9. **Token Tracker** — Aggregates token usage from proxy + tiny model

10. **Prompt Framing** — Analyzes user prompts for domain classification
    - Adds domain-specific system prompts
    - Optimizes prompt clarity/conciseness

### Data Flow
```
User Input → Overseer → React Loop → Tiny Model (:8082) → Output → Beautify → Display
User Input → WebUI → Proxy (:8081) → Big Model (:8080) → Response → Proxy minify → UI
```

## Architecture Diagram

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│    CLI      │    │   WebUI     │    │  System Tray│
│  (TUI)      │    │  (Dashboard)│    │  (GUI)      │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │
                    ┌─────▼─────┐
                    │  Proxy    │  (Port 8081)
                    │  (8081)   │
                    │           │
                    └─────┬─────┘
                          │
                    ┌─────▼─────┐
                    │  Big      │  (Port 8080)
                    │  Model    │
                    │  (35B)    │
                    └───────────┘
                    
┌─────────────┐    ┌─────────────┐
│  Overseer   │    │  React Loop │
│  (Daemon)   │    │  (Orchestrator)
└──────┬──────┘    └─────┬───────┘
       │                  │
       └──────────────────┘
                          │
                    ┌─────▼─────┐
                    │  Tiny     │  (Port 8082)
                    │  Model    │
                    │  (1.2B)   │
                    └───────────┘
```

## Security Audit Checklist

### 1. HTTP Proxy Security
- [ ] **Input Validation**: Is user input validated before reaching llama-server?
- [ ] **Request Size Limits**: Are there limits on request body size?
- [ ] **Path Traversal**: Can the proxy be tricked into serving files?
- [ ] **Rate Limiting**: Is there any rate limiting on requests?
- [ ] **Authentication**: Is authentication implemented on `/metrics`?
- [ ] **CORS**: Is CORS configured for the WebUI?
- [ ] **CSRF**: Is CSRF protection in place for WebUI forms?
- [ ] **XSS**: Is output sanitized before rendering in WebUI?

### 2. Model Security
- [ ] **Prompt Injection**: How are user prompts sanitized?
- [ ] **Tool Call Validation**: Are tool calls validated before execution?
- [ ] **Memory Compartmentalization**: Is the hot/warm/cold memory model secure?
- [ ] **Session Isolation**: Are sessions isolated between users?
- [ ] **Data Leakage**: Could sensitive data leak through logs or metrics?

### 3. System Security
- [ ] **Privilege Separation**: Does the proxy/overseer run with minimal privileges?
- [ ] **File Permissions**: Are state files (`~/.cortexagent/`) properly protected?
- [ ] **Environment Variables**: Are sensitive env vars (tokens, keys) masked?
- [ ] **Logging**: Is sensitive data scrubbed from logs?
- [ ] **Third-Party Dependencies**: Are slimtoken, other packages audited?

## Stability Audit Checklist

### 1. Concurrency
- [ ] **Thread Safety**: Are all shared data structures protected with locks?
- [ ] **Race Conditions**: Can multiple requests corrupt state?
- [ ] **Deadlocks**: Are there any lock ordering violations?
- [ ] **Resource Leaks**: Are sockets, file descriptors, memory properly freed?
- [ ] **Connection Pooling**: Is the HTTP client connection pool managed?

### 2. Error Handling
- [ ] **Exception Propagation**: Are exceptions caught at boundaries?
- [ ] **Retry Logic**: Is there exponential backoff for failures?
- [ ] **Circuit Breakers**: Are failing services detected and bypassed?
- [ ] **Timeouts**: Are all network calls bounded by timeouts?
- [ ] **Graceful Degradation**: Does the system fail gracefully under load?

### 3. Memory Management
- [ ] **Hot/Warm/Cold Model**: Is the memory compartmentalization working correctly?
- [ ] **Garbage Collection**: Are there memory leaks in long-running processes?
- [ ] **Token Counting**: Is token counting accurate and bounded?
- [ ] **Context Window**: Is the context window managed to avoid overflow?
- [ ] **Disk Space**: Are log files and state files bounded in size?

## Performance Audit Checklist

### 1. Proxy Performance
- [ ] **Minification**: Is slimtoken actually reducing token counts? (Currently 0% savings)
- [ ] **Grammar Stripping**: Is grammar field stripping optimized?
- [ ] **Connection Reuse**: Are HTTP connections pooled and reused?
- [ ] **Caching**: Is there caching for repeated requests?
- [ ] **Parallelism**: Can multiple requests be processed concurrently?

### 2. Model Performance
- [ ] **Model Selection**: Is the tiny model (1.2B) optimal for overseer tasks?
- [ ] **Prompt Optimization**: Is the prompt framing pass reducing token counts?
- [ ] **Tool Call Overhead**: Is the ReAct loop efficient in tool calls?
- [ ] **Response Formatting**: Is beautification fast enough for real-time use?
- [ ] **Model Loading**: Is model warm-starting implemented?

### 3. System Performance
- [ ] **Queue Processing**: Is the task queue processed efficiently?
- [ ] **State Persistence**: Is JSON state file I/O optimized?
- [ ] **Metrics Collection**: Is `/metrics` endpoint efficient?
- [ ] **Dashboard Polling**: Is the WebUI polling efficient?
- [ ] **Cron Scheduling**: Is the scheduler lightweight?

## Optimization Recommendations

### High Priority
1. **Fix Minification**: slimtoken is designed for large requests with repeated content. The overseer's tiny model path uses small requests, so nothing gets minified. Add a lightweight minification pass in the tiny model path.

2. **Add Caching**: Cache common responses to reduce model calls.

3. **Connection Pooling**: Implement HTTP connection pooling for the proxy.

4. **Memory Leaks**: Audit memory usage in long-running processes.

### Medium Priority
5. **Parallel Processing**: Process independent tasks in parallel.

6. **Batch Requests**: Batch small requests to reduce overhead.

7. **Response Streaming**: Stream responses for better UX.

8. **Model Quantization**: Consider quantized models for faster inference.

### Low Priority
9. **Load Balancing**: Distribute requests across multiple models.

10. **Auto-scaling**: Scale models based on demand.

11. **Monitoring**: Add Prometheus metrics for better observability.

12. **CI/CD**: Implement automated testing and deployment.

## Implementation Priority

1. **Security**: Fix all security vulnerabilities first
2. **Stability**: Ensure the system is stable under load
3. **Performance**: Optimize for speed and efficiency
4. **Features**: Add new features once core is solid

## Questions for Research

1. What are the most common security vulnerabilities in HTTP proxy systems?
2. How can we improve slimtoken's effectiveness for small requests?
3. What are best practices for memory management in Python daemons?
4. How can we implement effective caching for LLM requests?
5. What are the trade-offs between different model sizes for overseer tasks?
6. How can we improve the ReAct loop's efficiency in tool calls?
7. What are best practices for real-time dashboard updates?
8. How can we implement graceful degradation under load?
9. What are the security implications of running a proxy that forwards requests?
10. How can we ensure token counting accuracy across the entire chain?

## Success Criteria

1. **Security**: No critical vulnerabilities found
2. **Stability**: 99.9% uptime under load
3. **Performance**: <1s response time for 95% of requests
4. **Efficiency**: 20% reduction in token usage through optimization
5. **Scalability**: Handle 10x current load without degradation
