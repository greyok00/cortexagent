#!/usr/bin/env python3

from typing import List, Dict, Optional, Tuple, Union


VERTICAL_BLOCKS = "▁▂▃▄▅▆▇█"
HORIZONTAL_BLOCKS = "▏▎▍▌▋▊▉█"
HEATMAP_DENSITY = " ░▒▓█"




SERIES_ROLES = ["accent", "success", "warn", "danger", "info", "muted"]
SERIES_GLYPHS = ["█", "▓", "▒", "░", "▌", "▐"]


def _series_style(palette: Optional[Dict[str, str]], index: int) -> Tuple[str, str, str]:

    if not palette:
        return "", "", "█"
    role = SERIES_ROLES[index % len(SERIES_ROLES)]
    color = palette.get(role, "")
    reset = palette.get("reset", "")
    glyph = SERIES_GLYPHS[index % len(SERIES_GLYPHS)]
    return color, reset, glyph


def _map_to_block(value: float, min_val: float, max_val: float,
                  block_set: str = VERTICAL_BLOCKS) -> str:

    if max_val == min_val:
        return block_set[0]
    ratio = (value - min_val) / (max_val - min_val)
    idx = min(int(ratio * len(block_set)), len(block_set) - 1)
    return block_set[idx]


def sparkline(data: List[Union[int, float]], width: Optional[int] = None,
              block_set: str = VERTICAL_BLOCKS) -> str:

    if not data:
        return ""

    min_val = min(data)
    max_val = max(data)

    if width is None:
        width = len(data)


    if len(data) > width:
        step = len(data) / width
        sampled = []
        for i in range(width):
            idx = int(i * step)
            sampled.append(data[idx])
        data = sampled


    blocks = [_map_to_block(v, min_val, max_val, block_set) for v in data]

    return "".join(blocks)


def multi_sparkline(data: Dict[str, List[Union[int, float]]],
                    width: int = 30, max_series: int = 6,
                    palette: Optional[Dict[str, str]] = None) -> str:

    if not data:
        return ""


    items = list(data.items())[:max_series]

    lines = []
    for idx, (name, series) in enumerate(items):
        color, reset, _ = _series_style(palette, idx)
        spark = sparkline(series, width)

        max_name_len = 15
        if len(name) > max_name_len:
            name = name[:max_name_len - 1] + "…"
        if color:
            spark = f"{color}{spark}{reset}"
        lines.append(f"{name:<{max_name_len}} {spark}")

    return "\n".join(lines)


def waffle(data: List[Union[int, float]],
           labels: Optional[List[str]] = None,
           grid_size: int = 10,
           fill_char: str = "█",
           empty_char: str = "░") -> str:

    if not data:
        return ""

    total = sum(data)
    if total == 0:
        return ""


    percentages = [v / total * 100 for v in data]


    total_cells = grid_size * grid_size
    cells = [int(p / 100 * total_cells) for p in percentages]

    cell_sum = sum(cells)
    if cell_sum < total_cells:
        cells[0] += total_cells - cell_sum


    grid = [empty_char] * total_cells
    idx = 0
    for i, n in enumerate(cells):
        for _ in range(n):
            if idx < total_cells:
                grid[idx] = fill_char if labels and i < len(labels) else fill_char
                idx += 1


    lines = []
    for row in range(grid_size):
        row_start = row * grid_size
        row_end = row_start + grid_size
        row_cells = "".join(grid[row_start:row_end])


        if labels and row == 0:
            for i, n in enumerate(cells):
                if i < len(labels):
                    label = labels[i]
                    if n > 0:
                        lines.append(f"{label:<10} {row_cells}")
                        break
        else:
            lines.append(row_cells)


    if labels:
        lines.append("")
        for i, label in enumerate(labels[:len(cells)]):
            pct = percentages[i] if i < len(percentages) else 0
            lines.append(f"  {fill_char} {label}: {pct:.1f}%")

    return "\n".join(lines)


def bar_chart(data: Dict[str, Union[int, float]],
              width: int = 40,
              label_width: int = 15,
              show_value: bool = True,
              palette: Optional[Dict[str, str]] = None) -> str:

    if not data:
        return ""

    max_val = max(data.values())
    if max_val == 0:
        return ""

    lines = []
    for idx, (name, value) in enumerate(data.items()):
        color, reset, glyph = _series_style(palette, idx)

        if len(name) > label_width:
            name = name[:label_width - 1] + "…"


        bar_len = int(value / max_val * width) if max_val > 0 else 0


        bar = ""
        for i in range(bar_len):
            if color:
                bar += glyph
            else:
                ratio = i / max(1, bar_len - 1) if bar_len > 1 else 1
                block = _map_to_block(ratio * 100, 0, 100, HORIZONTAL_BLOCKS)
                bar += block


        bar += empty_char * (width - len(bar))


        value_str = f" {value:g}" if show_value else ""
        if color:
            bar = f"{color}{bar}{reset}"
        lines.append(f"{name:<{label_width}} {bar} {value_str}")

    return "\n".join(lines)


def heatmap(data: List[List[Union[int, float]]],
            row_labels: Optional[List[str]] = None,
            col_labels: Optional[List[str]] = None,
            density: str = HEATMAP_DENSITY) -> str:

    if not data or not data[0]:
        return ""



    flat = [v for row in data for v in row]
    min_val = min(flat)
    max_val = max(flat)


    lines = []
    for i, row in enumerate(data):
        row_str = ""
        for j, val in enumerate(row):
            block = _map_to_block(val, min_val, max_val, density)
            row_str += block


        label = row_labels[i] if row_labels and i < len(row_labels) else ""
        if label:
            lines.append(f"{label:<10} {row_str}")
        else:
            lines.append(f"{'':<10} {row_str}")


    if col_labels:
        label_row = "          " + "".join(f"{l:<1}" for l in col_labels)
        lines.append(label_row)

    return "\n".join(lines)


def calendar_heatmap(rows: Dict[str, List[Union[int, float]]],
                     width: int = 24,
                     density: str = HEATMAP_DENSITY) -> str:

    if not rows:
        return ""


    lines = []
    for label, series in rows.items():
        recent = series[-width:] if len(series) > width else series
        if not recent:
            continue
        mn, mx = min(recent), max(recent)
        cells = "".join(_map_to_block(v, mn, mx, density) for v in recent)
        pad = " " * (width - len(cells))
        lines.append(f"{label:<10} {pad}{cells}")

    return "\n".join(lines)


def flowchart(nodes: List[str], edges: List[Tuple[str, str]]) -> str:

    if not nodes:
        return ""


    children: Dict[str, List[str]] = {n: [] for n in nodes}
    indeg: Dict[str, int] = {n: 0 for n in nodes}
    for src, tgt in edges:
        if src in children and tgt in children:
            children[src].append(tgt)
            indeg[tgt] += 1


    order: List[str] = []
    stack = [n for n in nodes if indeg[n] == 0]
    while stack:
        n = stack.pop()
        order.append(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                stack.append(c)

    layer: Dict[str, int] = {n: 0 for n in nodes}
    for n in order:
        for c in children[n]:
            layer[c] = max(layer[c], layer[n] + 1)

    max_layer = max(layer.values()) if layer else 0
    by_layer: List[List[str]] = [[] for _ in range(max_layer + 1)]
    for n in nodes:
        by_layer[layer[n]].append(n)


    def _box(label: str) -> List[str]:
        w = max(3, len(label) + 2)
        top = "┌" + "─" * w + "┐"
        mid = "│ " + label + " " * (w - len(label) - 1) + "│"
        bot = "└" + "─" * w + "┘"
        return [top, mid, bot]

    rendered: List[List[str]] = []
    for layer_nodes in by_layer:
        boxes = [_box(n) for n in layer_nodes]

        rows = []
        for r in range(3):
            rows.append("  ".join(b[r] for b in boxes))
        rendered.append(rows)


    out: List[str] = []
    for li, rows in enumerate(rendered):
        out.extend(rows)
        if li < len(rendered) - 1:

            width = max(len(r) for r in rows)
            out.append(" " * (width // 2) + "│")
            out.append(" " * (width // 2) + "▼")

    return "\n".join(out)


def gauge(value: float, min_val: float = 0, max_val: float = 100,
          width: int = 20) -> str:

    if max_val == min_val:
        return f"0% {'░' * width}"

    pct = (value - min_val) / (max_val - min_val)
    pct = max(0, min(1, pct))

    filled = int(pct * width)
    empty = width - filled

    bar = "█" * filled + "░" * empty
    pct_str = f"{pct * 100:.1f}%"

    return f"{pct_str:>6} {bar}"


def gantt(tasks: List[Dict], start: str = "00:00",
          end: str = "23:59", width: int = 50) -> str:

    if not tasks:
        return ""


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


        pos_start = int((task_start - start_min) / total_min * width) if total_min > 0 else 0
        pos_end = int((task_end - start_min) / total_min * width) if total_min > 0 else width


        if len(name) > 10:
            name = name[:10] + "…"


        row = f"{name:<10} " + " " * pos_start + "█" * max(1, pos_end - pos_start)
        lines.append(row)

    return "\n".join(lines)


def tree(data: Dict[str, Union[str, Dict]], prefix: str = "",
         is_last: bool = True) -> str:

    if not data:
        return ""

    lines = []
    items = list(data.items())
    for i, (node, child) in enumerate(items):
        is_last_child = i == len(items) - 1


        connector = "└── " if is_last_child else "├── "
        lines.append(f"{prefix}{connector}{node}")


        if isinstance(child, dict):
            new_prefix = prefix + ("    " if is_last_child else "│   ")
            lines.append(tree(child, new_prefix, is_last_child))

    return "\n".join(lines)


def box_plot(data: List[Union[int, float]]) -> str:

    if not data:
        return ""

    sorted_data = sorted(data)
    n = len(sorted_data)

    min_val = sorted_data[0]
    max_val = sorted_data[-1]
    q1 = sorted_data[n // 4]
    median = sorted_data[n // 2]
    q3 = sorted_data[3 * n // 4]


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


def funnel(data: List[Union[int, float]], labels: Optional[List[str]] = None,
           palette: Optional[Dict[str, str]] = None) -> str:

    if not data:
        return ""

    max_val = max(data)
    if max_val == 0:
        return ""

    lines = []
    for i, (val, label) in enumerate(zip(data, labels or [])):
        color, reset, glyph = _series_style(palette, i)
        width = int(val / max_val * 40)
        bar = glyph * max(1, width)


        if i > 0:
            bar = " " * (i * 2) + bar

        name = label if labels and i < len(labels) else f"Stage {i + 1}"
        if color:
            bar = f"{color}{bar}{reset}"
        lines.append(f"{name:<10} {bar} {val}")

    return "\n".join(lines)


def sankey(nodes: List[str], flows: List[Tuple[str, str, float]],
           width: int = 30) -> str:

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

    if not data:
        return ""

    min_val = min(data)
    max_val = max(data)

    if width is None:
        width = min(len(data), 40)


    if len(data) > width:
        step = len(data) / width
        sampled = []
        for i in range(width):
            idx = int(i * step)
            sampled.append(data[idx])
        data = sampled


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



empty_char = "░"



def main():

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
