# CortexAgent Request Chain Overhaul Plan

## Problem Analysis

### Current Chain
1. **User input** → CLI or webui
2. **Overseer** → creates task in queue (type "llm")
3. **React loop** → calls `tiny_llm.query()` or `tiny_llm.query_with_tools()` to tiny model (:8082)
4. **Output** → beautified (basic tables/CSV/bar charts) → displayed

### Issues
1. **Minification NOT working**: slimtoken is designed for large requests with repeated content (long tool results, repeated messages). The overseer's tiny model path uses small requests with no repeated content, so slimtoken does nothing (0 savings across 69 runs).
2. **No prompt framing pass**: User prompts are sent directly to the tiny model without analysis or optimization.
3. **Beautification too basic**: Only tables, CSV, bar charts. Needs charts, graphs, tables, imagery.
4. **No output frame of reference pass**: Final output is not structured for business/OSINT/cybersecurity/professional use.
5. **Token tracking incomplete**: Only tracks proxy (big model) tokens, not tiny model tokens.

## Solution

### 1. Prompt Framing Pass (BEFORE minification)
- Analyze user prompt for domain (business, OSINT, cybersecurity, professional)
- Add appropriate framing/context to the system prompt
- Optimize the prompt for clarity and conciseness
- Shrink redundant parts of the prompt
- This happens BEFORE any minification

### 2. Fix Minification for Tiny Model Path
- The overseer's tiny model path bypasses the proxy entirely (goes directly to :8082)
- Add a lightweight minification pass in the tiny model path
- Track token usage for both tiny and big model paths
- Merge minify stats from both paths

### 3. Overhaul Beautification
- Add more chart types: line charts, pie charts, radar charts
- Add tables: formatted markdown tables, HTML tables
- Add imagery: ASCII art, diagrams, flowcharts
- Add formatting: color coding, bold/italics, sections
- This happens AFTER the LLM generates output

### 4. Output Frame of Reference Pass
- Structure the final output for the domain (business, OSINT, cybersecurity, professional)
- Add summary, key findings, recommendations
- Add context, references, sources
- Add action items, next steps
- This happens AFTER beautification

### 5. Token Tracking for Tiny Model Path
- Track token usage for the tiny model path
- Merge with proxy stats for a complete picture
- Display in overseer status and dashboard

## Implementation Order

1. Create `lib/prompt_framing.py` - analyze and optimize user prompts
2. Create `lib/token_tracker.py` - track token usage for both paths
3. Overhaul `lib/beautify.py` - add charts, graphs, tables, imagery
4. Create `lib/output_frame.py` - structure final output for domain
5. Update `lib/react_loop.py` - wire up the new passes
6. Update `lib/overseer.py` - track token usage, display stats
7. Schedule all tasks and execute them
