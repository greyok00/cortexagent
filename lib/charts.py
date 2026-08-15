#!/usr/bin/env python3
"""charts.py — ASCII/Unicode chart library for CortexAgent CLI.

Pure functions for rendering:
  - Sparkline (1D line chart with vertical blocks)
  - Multi-series sparkline matrix (compare 4-6 metrics)
  - Waffle chart (10×10 grid, parts-of-whole)
  - Bar chart (horizontal with gradient)
  - Heatmap (2D matrix with density)
  - Gauge (single value vs min/max)
  - Tree diagram (hierarchy)
  - Gantt chart (scheduled task timeline)

All charts are terminal-renderable and use Unicode block elements.
Pure functions — no server, no side effects.

Usage:
  from lib.charts import sparkline, waffle, heatmap
  print(sparkline([10, 20, 15, 30, 25]))
  print(waffle([30, 40, 30], labels=["A", "B", "C"]))
  print(heatmap([[1, 2], [3, 4]], labels=["row1", "row2"]))
"""
import sys
from typing import List, Dict, Optional, Tuple, Union
from math import ceil

# ── Vertical blocks (8-step sparkline) ──────────────────────────────────
VERTICAL_BLOCKS = "▁▂▃▄▅▆▇█"
HORIZONTAL_BLOCKS = "▏▎▍▌▋▊▉█"
HEATMAP_DENSITY = " ░▒▓█"


def _map_to_block(value: float, min_val: float, max_val: float,
                  block_set: str = VERTICAL_BLOCKS) -> str:
    """Map a value to a block character in the given set.
    
    Args:
        value: The value to map (assumed to be in [min_val, max_val])
        min_val: Minimum value (maps to first char)
        max_val: Maximum value (maps to last char)
        block_set: The set of block characters to use
    
    Returns: A single block character
    """
    if max_val == min_val:
        return block_set[0]
    ratio = (value - min_val) / (max_val - min_val)
    idx = min(int(ratio * len(block_set)), len(block_set) - 1)
    return block_set[idx]


def sparkline(data: List[Union[int, float]], width: Optional[int] = None,
              block_set: str = VERTICAL_BLOCKS) -> str:
    """Render a sparkline (1D line chart) using vertical blocks.
    
    Args:
        data: List of numeric values
        width: Target width in cells (default: len(data))
        block_set: Set of block characters to use
    
    Returns: Sparkline string
    """
    if not data:
        return ""
    
    min_val = min(data)
    max_val = max(data)
    
    if width is None:
        width = len(data)
    
    # Sample data to fit width
    if len(data) > width:
        step = len(data) / width
        sampled = []
        for i in range(width):
            idx = int(i * step)
            sampled.append(data[idx])
        data = sampled
    
    # Map each value to a block
    blocks = [_map_to_block(v, min_val, max_val, block_set) for v in data]
    
    return "".join(blocks)


def multi_sparkline(data: Dict[str, List[Union[int, float]]],
                    width: int = 30, max_series: int = 6) -> str:
    """Render a multi-series sparkline matrix.
    
    Compares 4-6 metrics at a glance. Each row is one metric.
    
    Args:
        data: Dict mapping metric name -> list of numeric values
        width: Target width in cells
        max_series: Maximum number of series to display
    
    Returns: Matrix string
    """
    if not data:
        return ""
    
    # Limit to max_series
    items = list(data.items())[:max_series]
    
    lines = []
    for name, series in items:
        spark = sparkline(series, width)
        # Truncate name to fit
        max_name_len = 15
        if len(name) > max_name_len:
            name = name[:max_name_len - 1] + "…"
        lines.append(f"{name:<{max_name_len}} {spark}")
    
    return "\n".join(lines)


def waffle(data: List[Union[int, float]],
           labels: Optional[List[str]] = None,
           grid_size: int = 10,
           fill_char: str = "█",
           empty_char: str = "░") -> str:
    """Render a waffle chart (10×10 grid) for parts-of-whole.
    
    Better than pie for terminal rendering — honest, dense, reads in a
    single glance.
    
    Args:
        data: List of numeric values (sums to 100% or normalized)
        labels: Optional list of labels for each segment
        grid_size: Grid dimension (default: 10, so 10×10 = 100 cells)
        fill_char: Character for filled cells
        empty_char: Character for empty cells
    
    Returns: Waffle chart string
    """
    if not data:
        return ""
    
    total = sum(data)
    if total == 0:
        return ""
    
    # Normalize to percentages
    percentages = [v / total * 100 for v in data]
    
    # Calculate cells per segment
    total_cells = grid_size * grid_size
    cells = [int(p / 100 * total_cells) for p in percentages]
    # Adjust for rounding
    cell_sum = sum(cells)
    if cell_sum < total_cells:
        cells[0] += total_cells - cell_sum
    
    # Build grid
    grid = [empty_char] * total_cells
    idx = 0
    for i, n in enumerate(cells):
        for _ in range(n):
            if idx < total_cells:
                grid[idx] = fill_char if labels and i < len(labels) else fill_char
                idx += 1
    
    # Render grid
    lines = []
    for row in range(grid_size):
        row_start = row * grid_size
        row_end = row_start + grid_size
        row_cells = "".join(grid[row_start:row_end])
        
        # Add label for first row of each segment
        if labels and row == 0:
            seg_start = 0
            for i, n in enumerate(cells):
                if i < len(labels):
                    label = labels[i]
                    if n > 0:
                        lines.append(f"{label:<10} {row_cells}")
                        break
        else:
            lines.append(row_cells)
    
    # Add legend
    if labels:
        lines.append("")
        for i, label in enumerate(labels[:len(cells)]):
            pct = percentages[i] if i < len(percentages) else 0
            lines.append(f"  {fill_char} {label}: {pct:.1f}%")
    
    return "\n".join(lines)


def bar_chart(data: Dict[str, Union[int, float]],
              width: int = 40,
              label_width: int = 15,
              show_value: bool = True) -> str:
    """Render a horizontal bar chart with gradient.
    
    Args:
        data: Dict mapping category -> numeric value
        width: Bar width in cells
        label_width: Width for category labels
        show_value: Whether to show the value at the end
    
    Returns: Bar chart string
    """
    if not data:
        return ""
    
    max_val = max(data.values())
    if max_val == 0:
        return ""
    
    lines = []
    for name, value in data.items():
        # Truncate label
        if len(name) > label_width:
            name = name[:label_width - 1] + "…"
        
        # Calculate bar length
        bar_len = int(value / max_val * width) if max_val > 0 else 0
        
        # Build bar with gradient
        bar = ""
        for i in range(bar_len):
            ratio = i / max(1, bar_len - 1) if bar_len > 1 else 1
            block = _map_to_block(ratio * 100, 0, 100, HORIZONTAL_BLOCKS)
            bar += block
        
        # Pad with empty
        bar += empty_char * (width - len(bar))
        
        # Format value
        value_str = f" {value:g}" if show_value else ""
        lines.append(f"{name:<{label_width}} {bar} {value_str}")
    
    return "\n".join(lines)


def heatmap(data: List[List[Union[int, float]]],
            row_labels: Optional[List[str]] = None,
            col_labels: Optional[List[str]] = None,
            density: str = HEATMAP_DENSITY) -> str:
    """Render a heatmap (2D matrix) using density characters.
    
    Args:
        data: 2D list of numeric values
        row_labels: Optional labels for rows
        col_labels: Optional labels for columns
        density: Density characters (light to dark)
    
    Returns: Heatmap string
    """
    if not data or not data[0]:
        return ""
    
    rows = len(data)
    cols = len(data[0])
    
    # Find min/max
    flat = [v for row in data for v in row]
    min_val = min(flat)
    max_val = max(flat)
    
    # Build grid
    lines = []
    for i, row in enumerate(data):
        row_str = ""
        for j, val in enumerate(row):
            block = _map_to_block(val, min_val, max_val, density)
            row_str += block
        
        # Add row label
        label = row_labels[i] if row_labels and i < len(row_labels) else ""
        if label:
            lines.append(f"{label:<10} {row_str}")
        else:
            lines.append(f"{'':<10} {row_str}")
    
    # Add column labels
    if col_labels:
        label_row = "          " + "".join(f"{l:<1}" for l in col_labels)
        lines.append(label_row)
    
    return "\n".join(lines)


def gauge(value: float, min_val: float = 0, max_val: float = 100,
          width: int = 20) -> str:
    """Render a gauge (single value vs min/max).
    
    Args:
        value: Current value
        min_val: Minimum value
        max_val: Maximum value
        width: Gauge width in cells
    
    Returns: Gauge string
    """
    if max_val == min_val:
        return f"0% {'░' * width}"
    
    pct = (value - min_val) / (max_val - min_val)
    pct = max(0, min(1, pct))  # Clamp to [0, 1]
    
    filled = int(pct * width)
    empty = width - filled
    
    bar = "█" * filled + "░" * empty
    pct_str = f"{pct * 100:.1f}%"
    
    return f"{pct_str:>6} {bar}"


def gantt(tasks: List[Dict], start: str = "00:00",
          end: str = "23:59", width: int = 50) -> str:
    """Render a Gantt chart (scheduled task timeline).
    
    Args:
        tasks: List of dicts with 'name', 'start', 'end' keys
        start: Start time string (HH:MM)
        end: End time string (HH:MM)
        width: Timeline width in cells
    
    Returns: Gantt chart string
    """
    if not tasks:
        return ""
    
    # Parse times
    def parse_time(t: str) -> float:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    
    start_min = parse_time(start)
    end_min = parse_time(end)
    total_min = end_min - start_min
    
    lines = []
    for task in tasks:
        name = task.get("name", "Task")
        task_start = parse_time(task["start"])
        task_end = parse_time(task["end"])
        
        # Calculate position
        pos_start = int((task_start - start_min) / total_min * width) if total_min > 0 else 0
        pos_end = int((task_end - start_min) / total_min * width) if total_min > 0 else width
        
        # Truncate name
        if len(name) > 10:
            name = name[:10] + "…"
        
        # Build row
        row = f"{name:<10} " + " " * pos_start + "█" * max(1, pos_end - pos_start)
        lines.append(row)
    
    return "\n".join(lines)


def tree(data: Dict[str, Union[str, Dict]], prefix: str = "",
         is_last: bool = True) -> str:
    """Render a tree diagram (hierarchy).
    
    Args:
        data: Dict mapping node -> value or sub-dict
        prefix: Prefix for recursion
        is_last: Whether this is the last sibling
    
    Returns: Tree string
    """
    if not data:
        return ""
    
    lines = []
    items = list(data.items())
    for i, (node, child) in enumerate(items):
        is_last_child = i == len(items) - 1
        
        # Connector
        connector = "└── " if is_last_child else "├── "
        lines.append(f"{prefix}{connector}{node}")
        
        # Recurse
        if isinstance(child, dict):
            new_prefix = prefix + ("    " if is_last_child else "│   ")
            lines.append(tree(child, new_prefix, is_last_child))
    
    return "\n".join(lines)


def box_plot(data: List[Union[int, float]]) -> str:
    """Render a box plot (min/Q1/median/Q3/max).
    
    Args:
        data: List of numeric values
    
    Returns: Box plot string
    """
    if not data:
        return ""
    
    sorted_data = sorted(data)
    n = len(sorted_data)
    
    min_val = sorted_data[0]
    max_val = sorted_data[-1]
    q1 = sorted_data[n // 4]
    median = sorted_data[n // 2]
    q3 = sorted_data[3 * n // 4]
    
    # Build plot
    plot_width = 40
    plot = (
        f"├{'─' * (plot_width - 2)}┤\n"
        f"│{min_val:<{plot_width - 2}}│\n"
        f"├{'─' * (plot_width - 2)}┤\n"
        f"│{q1:<{plot_width - 2}}│\n"
        f"├{'─' * (plot_width - 2)}┤\n"
        f"│{median:<{plot_width - 2}}│\n"
        f"├{'─' * (plot_width - 2)}┤\n"
        f"│{q3:<{plot_width - 2}}│\n"
        f"├{'─' * (plot_width - 2)}┤\n"
        f"│{max_val:<{plot_width - 2}}│\n"
        f"└{'─' * (plot_width - 2)}┘"
    )
    
    return plot


def funnel(data: List[Union[int, float]], labels: Optional[List[str]] = None) -> str:
    """Render a funnel (pipeline stages).
    
    Args:
        data: List of numeric values (decreasing)
        labels: Optional labels for each stage
    
    Returns: Funnel string
    """
    if not data:
        return ""
    
    max_val = max(data)
    if max_val == 0:
        return ""
    
    lines = []
    n = len(data)
    for i, (val, label) in enumerate(zip(data, labels or [])):
        width = int(val / max_val * 40)
        bar = "█" * max(1, width)
        
        # Taper effect
        if i > 0:
            bar = " " * (i * 2) + bar
        
        name = label if labels and i < len(labels) else f"Stage {i + 1}"
        lines.append(f"{name:<10} {bar} {val}")
    
    return "\n".join(lines)


def sankey(nodes: List[str], flows: List[Tuple[str, str, float]],
           width: int = 30) -> str:
    """Render a Sankey diagram (flow between nodes).
    
    Args:
        nodes: List of node names
        flows: List of (source, target, weight) tuples
        width: Flow width in cells
    
    Returns: Sankey diagram string
    """
    if not flows:
        return ""
    
    lines = []
    lines.append("  Flow Diagram:")
    lines.append("  " + "─" * (width + 10))
    
    for src, tgt, weight in flows:
        flow_width = int(weight / max(f[2] for f in flows) * width) if flows else 0
        flow = "━" * max(1, flow_width)
        lines.append(f"  {src:<10} {flow} {tgt}")
    
    lines.append("  " + "─" * (width + 10))
    return "\n".join(lines)


def line_chart(data: List[Union[int, float]], width: Optional[int] = None) -> str:
    """Render a line chart using braille characters.
    
    Args:
        data: List of numeric values
        width: Target width in cells (default: len(data))
    
    Returns: Line chart string
    """
    if not data:
        return ""
    
    min_val = min(data)
    max_val = max(data)
    
    if width is None:
        width = min(len(data), 40)
    
    # Sample data to fit width
    if len(data) > width:
        step = len(data) / width
        sampled = []
        for i in range(width):
            idx = int(i * step)
            sampled.append(data[idx])
        data = sampled
    
    # Map to braille characters
    braille_chars = "⠁⠃⠇⠏⠟⠿⣿"
    braille = ""
    for v in data:
        if max_val == min_val:
            braille += braille_chars[0]
        else:
            ratio = (v - min_val) / (max_val - min_val)
            idx = min(int(ratio * len(braille_chars)), len(braille_chars) - 1)
            braille += braille_chars[idx]
    
    return braille


# ── Constants ──────────────────────────────────────────────────────────────
empty_char = "░"


# ── Main Entry ──────────────────────────────────────────────────────────────
def main():
    """Demo: print all chart types."""
    print("=== Sparkline ===")
    print(sparkline([10, 20, 15, 30, 25, 35, 30, 40]))
    print()
    
    print("=== Multi-sparkline ===")
    print(multi_sparkline({
        "tok/s": [10, 20, 15, 30, 25, 35, 30, 40],
        "vr": [5, 10, 8, 15, 12, 18, 15, 20],
        "qps": [1, 2, 1, 3, 2, 3, 2, 4],
    }))
    print()
    
    print("=== Waffle ===")
    print(waffle([30, 40, 30], labels=["A", "B", "C"]))
    print()
    
    print("=== Bar Chart ===")
    print(bar_chart({"cpu": 80, "mem": 60, "disk": 40}))
    print()
    
    print("=== Heatmap ===")
    print(heatmap([[1, 2, 3], [4, 5, 6], [7, 8, 9]],
                  row_labels=["R1", "R2", "R3"]))
    print()
    
    print("=== Gauge ===")
    print(gauge(75, 0, 100))
    print()
    
    print("=== Gantt ===")
    print(gantt([
        {"name": "Task A", "start": "09:00", "end": "12:00"},
        {"name": "Task B", "start": "13:00", "end": "17:00"},
    ]))
    print()
    
    print("=== Tree ===")
    print(tree({
        "root": {
            "child1": {},
            "child2": {
                "grandchild1": {},
                "grandchild2": {},
            },
        }
    }))
    print()
    
    print("=== Box Plot ===")
    print(box_plot([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
    print()
    
    print("=== Funnel ===")
    print(funnel([100, 80, 60, 40, 20], labels=["Queued", "Running", "Done", "Failed", "Error"]))
    print()
    
    print("=== Sankey ===")
    print(sankey(
        ["Source", "Process", "Target"],
        [("Source", "Process", 10), ("Process", "Target", 8), ("Source", "Target", 2)],
    ))
    print()
    
    print("=== Line Chart ===")
    print(line_chart([10, 20, 15, 30, 25, 35, 30, 40, 35, 45]))
    print()


if __name__ == "__main__":
    main()
