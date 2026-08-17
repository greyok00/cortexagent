# TUI Footer Pipeline Redesign

## Overview
Redesigned the TUI footer to display the full prompt pass-through pipeline from typing to output, with real-time status indicators and settings/toggles.

## Architecture References
- **OBSERVABILITY_IMPLEMENTATION.md**: Trace spans, metrics, evaluations
- **OBSERVATION_COMPLETE.md**: Pipeline stages, storage, performance
- **execution_flow.md**: OPERATOR execution flow, pipeline definitions
- **ARCHITECTURE.md**: Full architecture diagram, request chain

## Pipeline Stages
```
User Input → Memory → Intent → Routing → Framing → Model → Beautify → Output → UI
    │         │       │       │       │       │       │        │       │
    ▼         ▼       ▼       ▼       ▼       ▼       ▼        ▼       ▼
   📝         🎯      🔀      📐      🤖      🎨      📤       [done]  [done]
```

## Changes Made

### 1. TUI Footer Component (`footer.ts`)
**File**: `cortex/packages/coding-agent/src/modes/interactive/components/footer.ts`

**Added**:
- `PIPELINE_STAGES` constant: Defines all pipeline stages with icons and labels
- `PIPELINE_COLORS`: Color mapping for pipeline statuses (pending, active, complete, error, skipped)
- `createPipelineIndicator()`: Creates a pipeline status indicator with icon + status
- `getPipelineStatus()`: Extracts pipeline status from session state
- `renderPipelineBar()`: Renders the pipeline status bar with arrows between stages
- `renderSettingsToggles()`: Renders settings/toggles (thinking level, model, auto-compaction, etc.)

**Modified**:
- `render()`: Now renders 3 lines instead of 2:
  - Line 1: Path + session info
  - Line 2: Stats + pipeline status + settings toggles
  - Line 3: Extension statuses (if available)

### 2. Pipeline Status
**Status Values**:
- `pending`: Stage waiting to execute
- `active`: Stage currently executing
- `complete`: Stage finished successfully
- `error`: Stage failed with error
- `skipped`: Stage skipped

**Status Detection**:
```typescript
// If streaming, model is active
if (state.isStreaming) {
  status["model"] = "active";
  status["framing"] = "complete";
  status["routing"] = "complete";
  status["intent"] = "complete";
  status["memory"] = "complete";
}

// If streaming message exists, beautify/output may be active
if (state.streamingMessage) {
  status["model"] = "complete";
  status["beautify"] = "active";
  status["output"] = "active";
}
```

### 3. Settings/Toggles
**Available Toggles**:
- `🧠 [thinking]`: Thinking level badge (off, minimal, low, medium, high, xhigh, max)
- `🏢 [provider]`: Model provider badge (if multiple providers available)
- `🔄 [auto]`: Auto-compaction toggle
- `🧪 [xp]`: Experimental features toggle
- `👁`: Code block toggle (hidden by default)

## Visual Layout

```
~/cortexagent (master) • session-123
↑1.2k █▓▒░ ↓2.3k █▓▒░ R500k█ W100k█ [75%] $0.012 • 📝 complete 🎯 complete 🔀 complete 📐 complete 🤖 active 🎨 pending 📤 pending | 🧠 [high] 🏢 [openai] 🔄 [auto] 🧪 [xp] 👁
```

## Pipeline Visualization

**Active Pipeline**:
```
📝 complete 🎯 complete 🔀 complete 📐 complete 🤖 active 🎨 pending 📤 pending
```

**Completed Pipeline**:
```
📝 complete 🎯 complete 🔀 complete 📐 complete 🤖 complete 🎨 complete 📤 complete
```

**Error State**:
```
📝 complete 🎯 complete 🔀 complete 📐 complete 🤖 error 🎨 skipped 📤 skipped
```

## Code Blocks Hidden by Default
**File**: `cortex/packages/coding-agent/src/core/settings-manager.ts`

Changed default from `false` to `true`:
```typescript
getHideThinkingBlock(): boolean {
    return this.settings.hideThinkingBlock ?? true;  // HIDDEN by default
}
```

## Testing

### Manual Test
```bash
# Run cortex and observe footer
cortexagent
```

### Expected Output
```
~/cortexagent (master) • session-123
↑1.2k █▓▒░ ↓2.3k █▓▒░ R500k█ W100k█ [75%] $0.012 • 📝 complete 🎯 complete 🔀 complete 📐 complete 🤖 active 🎨 pending 📤 pending | 🧠 [high] 🏢 [openai] 🔄 [auto] 🧪 [xp] 👁
```

## Future Improvements

1. **Real-time Metrics**: Add latency, token throughput, error rates to pipeline
2. **Trace Integration**: Show active trace spans in footer
3. **Expandable View**: Click pipeline stage to see detailed metrics
4. **Color Coding**: Use different colors for different pipeline stages
5. **Animation**: Add spinner animation for active stages
6. **Keyboard Shortcuts**: Add shortcuts to toggle pipeline view
7. **History**: Show pipeline history for past runs

## Documentation

### Key Documents
1. **OBSERVABILITY_IMPLEMENTATION.md** - Full observability architecture
2. **OBSERVATION_COMPLETE.md** - Observability implementation complete
3. **execution_flow.md** - OPERATOR execution flow
4. **ARCHITECTURE.md** - Full architecture diagram

### How to Use
1. **For users**: Observe pipeline status in footer during agent runs
2. **For developers**: Extend pipeline stages in `PIPELINE_STAGES`
3. **For implementers**: Add new metrics in `getPipelineStatus()`
4. **For testers**: Verify pipeline status updates during agent runs

## Conclusion

The TUI footer now displays the full prompt pass-through pipeline with real-time status indicators and settings/toggles. Code blocks are hidden by default to reduce visual clutter.

**Next**: Integrate real-time metrics and trace spans for enhanced observability.
