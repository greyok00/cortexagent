# Scheduler Display Fix & Code/Thinking Hidden by Default

## Problem
The scheduler was showing broken entries like `🕐 unnamed-corrupte (manual )` with raw cron expressions and no proper formatting.

## Root Cause
1. **Missing trigger fields**: Task stored in `tasks.json` lacked `trigger` and `schedule_value` fields
2. **Empty schedule value**: Task had no schedule value, causing "Manual" display
3. **Thinking blocks visible**: Default setting showed thinking blocks

## Fixes Applied

### 1. Backend: Fix Malformed Task Data
- **File**: `~/.cortexagent/scheduler/tasks.json`
- **Change**: Added missing `trigger: "manual"` and `schedule_value: ""` fields
- **Result**: Task now properly identified as manual/one-shot task

### 2. WebUI: Enhanced schedLabel() Function
- **File**: `assets/webui_template.html`
- **Changes**:
  - Handle empty/missing trigger fields gracefully
  - Show "One-shot" for manual tasks without schedule value
  - Show "Pending" for tasks without schedule value
  - Proper emoji icons for all trigger types:
    - 🔄 cron
    - 🌅 daily
    - 📅 weekly
    - 📌 date
    - ⏱ interval
    - 👤 manual
    - 🕐 unknown (fallback)

### 3. WebUI: Code Toggle Functionality
- **File**: `assets/webui_template.html`
- **Changes**:
  - Added `toggleCodeBlock()` function
  - Added [👁] toggle button to task descriptions
  - Click to show/hide code blocks in task details

### 4. TUI: Hide Thinking Blocks by Default
- **File**: `cortex/packages/coding-agent/src/core/settings-manager.ts`
- **Change**: Changed `getHideThinkingBlock()` default from `false` to `true`
- **Result**: Thinking blocks now hidden by default (can be toggled via `/thinking` command)

### 5. TUI: Enhanced Footer with Beautification
- **File**: `cortex/packages/coding-agent/src/modes/interactive/components/footer.ts`
- **Changes**:
  - Import and use beautification utilities
  - Show token counts with Unicode block visualization
  - Show cache hit rate with colored badges
  - Show context window with progress bars
  - Add status badges for thinking levels

## Result
- Scheduler tasks now display with proper emoji icons and human-readable labels
- Code and thinking blocks hidden by default (reduces visual clutter)
- Footer shows enriched statistics with Unicode block visualization
- Tasks with missing data handled gracefully

## Testing
Run these commands to verify:
```bash
# Check scheduler data
python3 -c "import json; print(json.dumps(json.load(open('~/.cortexagent/scheduler/tasks.json')), indent=2))"

# Test scheduler bridge
python3 scripts/schedule_bridge.py list

# Smoke test scheduler
python3 lib/scheduler/ui.py smoke
```

## Future Improvements
- Add more emoji icons for different task types
- Implement color-coded status indicators
- Add animated spinner for running tasks
- Support for Mermaid diagrams in task descriptions
