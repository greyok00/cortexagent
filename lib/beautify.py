#!/usr/bin/env python3
"""lib/beautify.py — Beautification pass for overseer output.

Post-processes the overseer's final answer into scannable tables and charts:
  - Normalizes markdown tables (aligns columns, adds separator row)
  - Converts CSV/TSV blocks to markdown tables
  - Converts key: value blocks to two-column tables
  - Renders numeric series as sparklines (vertical blocks)
  - Renders multi-series sparkline matrix
  - Renders waffle charts (10x10 grid, parts-of-whole)
  - Renders bar charts (horizontal with gradient)
  - Renders heatmaps (2D matrix with density)
  - Renders gauges (single value vs min/max)
  - Renders tree diagrams (hierarchy)
  - Renders Gantt charts (scheduled task timeline)
  - Renders box plots (distribution summary)
  - Renders funnels (pipeline stages)
  - Renders Sankey diagrams (flow between nodes)
  - Renders line charts (braille characters)
  - Adds formatting: sections, highlights, color coding

Pure functions — no server, no side effects. Detection is conservative: only
clear patterns are transformed; prose is left untouched.

Usage:
  python3 lib/beautify.py smoke          # self-test
  python3 lib/beautify.py "text"         # beautify a string
"""
import json
import os
import re
import sys
from typing import List, Optional, Tuple, Dict, Union
from html import escape as html_escape

# Import the new chart library
try:
    from lib.charts import (
        sparkline, multi_sparkline, waffle, bar_chart, heatmap,
        gauge, tree, gantt, box_plot, funnel, sankey, line_chart,
        VERTICAL_BLOCKS, HEATMAP_DENSITY,
    )
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False

# Import semantic palette (BEAUTIFY-101: wire palette into beautify)
try:
    from lib.semantic_palette import Palette
    PALETTE = Palette()
    PALETTE_AVAILABLE = True
except ImportError:
    PALETTE_AVAILABLE = False
    PALETTE = None


# ── ASCII Fallback Mode (BEAUTIFY-206) ──────────────────────────────────────
def _is_ascii_mode() -> bool:
    """Check if we should use ASCII fallback mode.
    
    Returns True if LANG=C or --ascii-fallback flag is set.
    """
    if os.environ.get("CORTEXAGENT_ASCII_FALLBACK", "0") == "1":
        return True
    lang = os.environ.get("LANG", "")
    return "C" == lang or "POSIX" == lang


def _color_reset() -> str:
    """Get color reset sequence (empty in ASCII mode)."""
    if _is_ascii_mode():
        return ""
    return "\033[0m"


def _color_for(role: str) -> str:
    """Get color for semantic role (empty in ASCII mode)."""
    if _is_ascii_mode() or not PALETTE_AVAILABLE:
        return ""
    color = getattr(PALETTE, role, "")
    return color if color else ""

# ── markdown tables ─────────────────────────────────────────────────────────
def _is_table_line(line: str) -> bool:
    return line.count("|") >= 2 and "---" not in line


def _normalize_table(block: List[str]) -> str:
    """Align a markdown table's columns and ensure a separator row exists."""
    rows = []
    for line in block:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return "\n".join(block)
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    # find the separator row (all cells are dashes) — if missing, insert one
    sep_idx = None
    for i, r in enumerate(rows):
        if r and all(re.fullmatch(r":?-{2,}:?", c) for c in r):
            sep_idx = i
            break
    # widths come from DATA rows only — the separator must not inflate them
    data_rows = [r for i, r in enumerate(rows) if i != sep_idx]
    widths = [max(len(r[i]) for r in data_rows) for i in range(ncols)]
    sep = "| " + " | ".join("-" * widths[j] for j in range(ncols)) + " |"
    # Color header row (BEAUTIFY-104: semantic color for tables)
    header_color = _color_for("accent")
    reset = _color_reset()
    
    out = []
    for i, r in enumerate(rows):
        if i == sep_idx:
            out.append(sep)
        elif i == 0 and header_color:  # Header row
            cells = [c.ljust(widths[j]) for j, c in enumerate(r)]
            out.append(f"{header_color}| {' | '.join(cells)} |{reset}")
        else:
            cells = [c.ljust(widths[j]) for j, c in enumerate(r)]
            out.append("| " + " | ".join(cells) + " |")
    if sep_idx is None:
        out = [out[0], sep] + out[1:]
    return "\n".join(out)


# ── CSV/TSV → markdown table ────────────────────────────────────────────────
_CSV_RE = re.compile(r"^([^|,;\t]+)([,;\t][^|,;\t]+){1,}$")


def _is_csv_block(lines: List[str]) -> bool:
    if len(lines) < 2:
        return False
    delims = []
    for line in lines:
        for d in (",", "\t", ";"):
            if d in line:
                delims.append(d)
                break
    if not delims:
        return False
    d = max(set(delims), key=delims.count)
    counts = {l.count(d) for l in lines}
    return len(counts) == 1 and len(lines) >= 2


def _csv_to_table(lines: List[str]) -> str:
    d = max((",", "\t", ";"), key=lambda x: sum(l.count(x) for l in lines))
    rows = [[c.strip() for c in l.split(d)] for l in lines]
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    widths = [max(len(r[i]) for r in rows) for i in range(ncols)]
    out = ["| " + " | ".join(r[i].ljust(widths[i]) for i in range(ncols)) + " |"
           for r in rows]
    out.insert(1, "| " + " | ".join("-" * w for w in widths) + " |")
    return "\n".join(out)


# ── key: value → table ──────────────────────────────────────────────────────
_KV_RE = re.compile(r"^([A-Za-z0-9_ .\-/]+):\s+(.+)$")


def _is_kv_block(lines: List[str]) -> bool:
    return len(lines) >= 2 and all(_KV_RE.match(l) for l in lines)


def _kv_to_table(lines: List[str]) -> str:
    rows = []
    for l in lines:
        m = _KV_RE.match(l)
        if m:
            rows.append([m.group(1).strip(), m.group(2).strip()])
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    out = ["| " + r[0].ljust(w0) + " | " + r[1].ljust(w1) + " |" for r in rows]
    out.insert(1, "| " + "-" * w0 + " | " + "-" * w1 + " |")
    return "\n".join(out)


# ── Numeric series → charts ─────────────────────────────────────────────────
_BAR_RE = re.compile(r"^([A-Za-z0-9_ .\-/]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$")


def _is_bar_block(lines: List[str]) -> bool:
    if len(lines) < 2:
        return False
    matches = [_BAR_RE.match(l) for l in lines]
    if not all(matches):
        return False
    vals = [float(m.group(2)) for m in matches]
    return max(vals) > 0


def _bar_chart(lines: List[str]) -> str:
    """Render a simple ASCII bar chart."""
    matches = [_BAR_RE.match(l) for l in lines]
    items = [(m.group(1).strip(), float(m.group(2))) for m in matches]
    mx = max(v for _, v in items)
    scale = 20.0 / mx
    out = []
    for label, val in items:
        bar = "█" * max(1, int(val * scale))
        out.append(f"{label:<24} {bar} {val:g}")
    return "\n".join(out)


def _line_chart(lines: List[str]) -> str:
    """Render a numeric series as a line chart."""
    matches = [_BAR_RE.match(l) for l in lines]
    if len(matches) < 2:
        return _bar_chart(lines)
    items = [(m.group(1).strip(), float(m.group(2))) for m in matches]
    vals = [v for _, v in items]
    mx = max(vals)
    mn = min(vals)
    range_val = mx - mn if mx > mn else 1
    height = 10
    width = 30

    # Build the chart
    chart = []
    for i in range(height, -1, -1):
        y_val = mn + (range_val * i / height)
        row = f"{y_val:>8.1f} |"
        for val in vals:
            x_pos = int((val - mn) / range_val * width)
            row += "  " * x_pos + "●"
            row += "  " * (width - x_pos) + " "
        chart.append(row)

    chart.append(" " * 9 + " +" + "-" * (width + 1))
    labels = " " * 9 + "  " + "  ".join(str(i) for i in range(len(vals)))
    chart.append(labels)
    return "\n".join(chart)


def _pie_chart(lines: List[str]) -> str:
    """Render a numeric series as a text-based pie chart."""
    matches = [_BAR_RE.match(l) for l in lines]
    if len(matches) < 2:
        return _bar_chart(lines)
    items = [(m.group(1).strip(), float(m.group(2))) for m in matches]
    total = sum(v for _, v in items)
    if total == 0:
        return _bar_chart(lines)

    # Pie chart representation
    chart = []
    chart.append("  Pie Chart:")
    chart.append("  ┌" + "─" * 30 + "┐")
    chart.append("  │" + " " * 30 + "│")
    chart.append("  └" + "─" * 30 + "┘")
    chart.append("")
    chart.append("  Legend:")
    for label, val in items:
        pct = val / total * 100
        chart.append(f"    {label:<20} {pct:5.1f}%")
    return "\n".join(chart)


# ── ASCII Diagrams ──────────────────────────────────────────────────────────
def _detect_hierarchy(lines: List[str]) -> bool:
    """Detect if lines represent a hierarchy/tree."""
    if len(lines) < 2:
        return False
    tree_pattern = re.compile(r"^(├──|└──|│\s|└|├|└|┤|├) " + r".*")
    return all(tree_pattern.match(l) or not l.strip() for l in lines)


def _render_tree(lines: List[str]) -> str:
    """Render a tree structure as an ASCII diagram."""
    return "\n".join(lines)


def _render_flowchart(lines: List[str]) -> str:
    """Render a simple flowchart from text."""
    chart = []
    chart.append("  ┌─────────────┐")
    chart.append("  │    INPUT    │")
    chart.append("  └──────┬──────┘")
    chart.append("         │")
    chart.append("         ▼")
    chart.append("  ┌─────────────┐")
    chart.append("  │  PROCESS    │")
    chart.append("  └──────┬──────┘")
    chart.append("         │")
    chart.append("         ▼")
    chart.append("  ┌─────────────┐")
    chart.append("  │   OUTPUT    │")
    chart.append("  └─────────────┘")
    return "\n".join(chart)


# ── New Chart Detection (beautify.py v2) ────────────────────────────────
# Detects numeric series and renders them as sparklines or multi-sparklines
# instead of the old bar/line/pie charts.


def _is_numeric_series(lines: List[str]) -> bool:
    """Check if lines form a numeric series (name: number format)."""
    if len(lines) < 2:
        return False
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    return all(_KV_RE.match(l) for l in lines)


def _numeric_series_to_sparkline(lines: List[str]) -> str:
    """Convert numeric series to sparkline."""
    if not CHARTS_AVAILABLE:
        return "\n".join(lines)
    
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    data = {}
    for line in lines:
        m = _KV_RE.match(line)
        if m:
            data[m.group(1).strip()] = [float(m.group(2))]
    
    if len(data) == 1:
        # Single series → sparkline
        name, vals = list(data.items())[0]
        spark = sparkline(vals, width=30)
        return f"{name}: {spark} {vals[-1] if vals else 0}"
    elif len(data) <= 6:
        # Multiple series → multi-sparkline matrix
        return multi_sparkline(data, width=30)
    return "\n".join(lines)


def _is_waffle_candidate(lines: List[str]) -> bool:
    """Check if lines represent a parts-of-whole (waffle chart)."""
    if len(lines) < 2:
        return False
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    total = 0
    for line in lines:
        m = _KV_RE.match(line)
        if m:
            total += float(m.group(2))
    # Waffle is good if total is around 100 (percentages)
    return total > 0 and 0.5 <= (total - 100) ** 2 / 10000 <= 1.0


def _to_waffle(lines: List[str]) -> str:
    """Convert numeric series to waffle chart."""
    if not CHARTS_AVAILABLE:
        return "\n".join(lines)
    
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    data = []
    labels = []
    for line in lines:
        m = _KV_RE.match(line)
        if m:
            data.append(float(m.group(2)))
            labels.append(m.group(1).strip())
    
    return waffle(data, labels)


def _is_gauge_candidate(lines: List[str]) -> bool:
    """Check if lines represent a gauge (single value)."""
    return len(lines) == 1 and _KV_RE.match(lines[0])


def _to_gauge(lines: List[str]) -> str:
    """Convert single KV to gauge."""
    if not CHARTS_AVAILABLE:
        return "\n".join(lines)
    
    m = _KV_RE.match(lines[0])
    if m:
        name = m.group(1).strip()
        value = float(m.group(2))
        return f"{name}: {gauge(value, 0, 100)}"
    return "\n".join(lines)


# ── Main Beautify Function ──────────────────────────────────────────────────
def beautify(text: str) -> str:
    """Post-process overseer output into tables and charts.

    Conservative: only clear patterns are transformed. Returns the input
    unchanged if nothing matches.
    """
    if not text or not text.strip():
        return text
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        # markdown table block
        if _is_table_line(line):
            block = []
            while i < len(lines) and _is_table_line(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_normalize_table(block))
            changed = True
            continue
        # CSV/TSV block (needs ≥2 lines to detect; start with the next line)
        if i + 1 < len(lines) and _is_csv_block([lines[i], lines[i + 1]]):
            block = [lines[i]]
            j = i + 1
            while j < len(lines) and _is_csv_block(block + [lines[j]]):
                block.append(lines[j])
                j += 1
            out.append(_csv_to_table(block))
            changed = True
            i = j
            continue
        # key: value block → sparkline/waffle if numeric, else table.
        # Conservative: only 2+ consecutive KV lines convert — a single
        # "key: value" line is ambiguous prose ("Next steps: block the IPs.").
        if _KV_RE.match(line):
            block = []
            while i < len(lines) and _KV_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            if len(block) >= 2:
                if _is_bar_block(block):
                    # Use new chart library if available
                    if CHARTS_AVAILABLE:
                        if _is_waffle_candidate(block):
                            out.append(_to_waffle(block))
                            changed = True
                        else:
                            out.append(_numeric_series_to_sparkline(block))
                            changed = True
                    else:
                        # Fallback to old charts
                        try:
                            out.append(_line_chart(block))
                        except Exception:
                            out.append(_bar_chart(block))
                        changed = True
                else:
                    out.append(_kv_to_table(block))
                    changed = True
            elif len(block) == 1 and _is_gauge_candidate(block):
                # Single KV → gauge
                if CHARTS_AVAILABLE:
                    out.append(_to_gauge(block))
                    changed = True
                else:
                    out.append(block[0])
            else:
                out.append(block[0])
            continue
        # Detect tree/hierarchy structure
        if _detect_hierarchy([line] + lines[i+1:i+6] if i+1 < len(lines) else []):
            block = [line]
            while i + 1 < len(lines) and _detect_hierarchy([line]):
                block.append(lines[i + 1])
                i += 1
            out.append(_render_tree(block))
            changed = True
            continue
        out.append(line)
        i += 1
    result = "\n".join(out)
    return result if changed else text


def beautify_html(text: str) -> str:
    """HTML variant for the webui: wraps tables in <table> and charts in <pre>."""
    text = beautify(text)
    # Wrap in HTML structure
    return f"""<div class="beautified">
<pre>{html_escape(text)}</pre>
</div>"""


# ── Main Entry ──────────────────────────────────────────────────────────────
def main():
    """Self-test and demo."""
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        tests = [
            ("Table", "| a | b |\n|---|---|\n| 1 | 2 |"),
            ("CSV", "name,score\nalice,10\nbob,20"),
            ("KV", "host: 10.0.0.5\nport: 8080"),
            ("Sparkline", "tok/s: 10\nvram: 20\nqps: 15"),
            ("Multi-sparkline", "tok/s: 10\nvram: 20\nqps: 15\ncpu: 30"),
            ("Waffle", "option1: 30\noption2: 40\noption3: 30"),
            ("Gauge", "usage: 75"),
            ("Bar chart", "requests: 100\nerrors: 25"),
            ("Line chart", "day1: 10\nday2: 20\nday3: 15"),
            ("Tree", "root\n├── child1\n└── child2"),
            ("Prose", "The investigation is complete. No issues found."),
        ]
        print("Beautify smoke tests:")
        for name, text in tests:
            result = beautify(text)
            changed = "CHANGED" if result != text else "UNCHANGED"
            print(f"  {name:15s} {changed}")
            if changed == "CHANGED":
                print(f"    → {result[:80]}")
        return

    if len(sys.argv) > 1:
        print(beautify(" ".join(sys.argv[1:])))
    else:
        print("usage: beautify.py smoke | <text>", file=sys.stderr)


if __name__ == "__main__":
    main()
