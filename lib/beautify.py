#!/usr/bin/env python3

import os
import re
import sys
from typing import List, Optional, Tuple, Dict
from html import escape as html_escape


try:
    from lib.charts import sparkline, multi_sparkline, waffle, gauge, flowchart
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False


try:
    from lib.semantic_palette import Palette
    PALETTE = Palette()
    PALETTE_AVAILABLE = True
except ImportError:
    PALETTE_AVAILABLE = False
    PALETTE = None



def _is_ascii_mode() -> bool:

    if os.environ.get("CORTEXAGENT_ASCII_FALLBACK", "0") == "1":
        return True
    lang = os.environ.get("LANG", "")
    return "C" == lang or "POSIX" == lang


def _color_reset() -> str:

    if _is_ascii_mode():
        return ""
    return "\033[0m"


def _color_for(role: str) -> str:

    if _is_ascii_mode() or not PALETTE_AVAILABLE:
        return ""
    color = getattr(PALETTE, role, "")
    return color if color else ""


def _is_table_line(line: str) -> bool:
    return line.count("|") >= 2 and "---" not in line


def _normalize_table(block: List[str]) -> str:

    rows = []
    for line in block:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return "\n".join(block)
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]

    sep_idx = None
    for i, r in enumerate(rows):
        if r and all(re.fullmatch(r":?-{2,}:?", c) for c in r):
            sep_idx = i
            break

    data_rows = [r for i, r in enumerate(rows) if i != sep_idx]
    widths = [max(len(r[i]) for r in data_rows) for i in range(ncols)]
    sep = "| " + " | ".join("-" * widths[j] for j in range(ncols)) + " |"

    header_color = _color_for("accent")
    reset = _color_reset()

    out = []
    for i, r in enumerate(rows):
        if i == sep_idx:
            out.append(sep)
        elif i == 0 and header_color:
            cells = [c.ljust(widths[j]) for j, c in enumerate(r)]
            out.append(f"{header_color}| {' | '.join(cells)} |{reset}")
        else:
            cells = [c.ljust(widths[j]) for j, c in enumerate(r)]
            out.append("| " + " | ".join(cells) + " |")
    if sep_idx is None:
        out = [out[0], sep] + out[1:]
    return "\n".join(out)



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

    matches = [_BAR_RE.match(l) for l in lines]
    items = [(m.group(1).strip(), float(m.group(2))) for m in matches]
    mx = max(v for _, v in items)
    scale = 20.0 / mx
    bar_color = _color_for("accent")
    reset = _color_reset()
    out = []
    for label, val in items:
        bar = "█" * max(1, int(val * scale))
        colored = f"{bar_color}{bar}{reset}" if bar_color else bar
        out.append(f"{label:<24} {colored} {val:g}")
    return "\n".join(out)


def _line_chart(lines: List[str]) -> str:

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

    matches = [_BAR_RE.match(l) for l in lines]
    if len(matches) < 2:
        return _bar_chart(lines)
    items = [(m.group(1).strip(), float(m.group(2))) for m in matches]
    total = sum(v for _, v in items)
    if total == 0:
        return _bar_chart(lines)


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



def _detect_hierarchy(lines: List[str]) -> bool:

    if len(lines) < 2:
        return False
    tree_pattern = re.compile(r"^(├──|└──|│\s|└|├|└|┤|├) " + r".*")
    return all(tree_pattern.match(l) or not l.strip() for l in lines)


def _render_tree(lines: List[str]) -> str:

    return "\n".join(lines)







def _is_numeric_series(lines: List[str]) -> bool:

    if len(lines) < 2:
        return False
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    return all(_KV_RE.match(l) for l in lines)


def _chart_palette() -> Optional[Dict[str, str]]:

    if _is_ascii_mode():
        return None
    try:
        pal = {role: getattr(PALETTE, role, "") for role in
               ("accent", "success", "warn", "danger", "info", "muted")}
        pal["reset"] = _color_reset()
        return pal if any(pal.values()) else None
    except Exception:
        return None


def _numeric_series_to_sparkline(lines: List[str]) -> str:

    if not CHARTS_AVAILABLE:
        return "\n".join(lines)

    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    data = {}
    for line in lines:
        m = _KV_RE.match(line)
        if m:
            data[m.group(1).strip()] = [float(m.group(2))]

    if len(data) == 1:

        name, vals = list(data.items())[0]
        spark = sparkline(vals, width=30)
        return f"{name}: {spark} {vals[-1] if vals else 0}"
    elif len(data) <= 6:

        return multi_sparkline(data, width=30, palette=_chart_palette())
    return "\n".join(lines)


def _is_waffle_candidate(lines: List[str]) -> bool:

    if len(lines) < 2:
        return False
    _KV_RE = re.compile(r'^([A-Za-z0-9_ .\-]+):\s*([0-9]+(?:\.[0-9]+)?)\s*$')
    total = 0
    for line in lines:
        m = _KV_RE.match(line)
        if m:
            total += float(m.group(2))

    return total > 0 and 0.5 <= (total - 100) ** 2 / 10000 <= 1.0


def _to_waffle(lines: List[str]) -> str:

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

    return len(lines) == 1 and _KV_RE.match(lines[0])


def _to_gauge(lines: List[str]) -> str:

    if not CHARTS_AVAILABLE:
        return "\n".join(lines)

    m = _KV_RE.match(lines[0])
    if m:
        name = m.group(1).strip()
        value = float(m.group(2))
        return f"{name}: {gauge(value, 0, 100)}"
    return "\n".join(lines)



_FLOW_RE = re.compile(r"^\s*([^→\->]+?)\s*(?:→|->)\s*(.+?)\s*$")


def _detect_flowchart(lines: List[str]) -> bool:

    if not CHARTS_AVAILABLE or len(lines) < 2:
        return False
    edges = 0
    for l in lines:
        if _FLOW_RE.match(l):
            edges += 1
    return edges >= 2


def _to_flowchart(lines: List[str]) -> str:

    if not CHARTS_AVAILABLE:
        return "\n".join(lines)
    nodes: List[str] = []
    edges: List[Tuple[str, str]] = []
    for l in lines:
        m = _FLOW_RE.match(l)
        if not m:
            continue
        src, tgt = m.group(1).strip(), m.group(2).strip()
        for n in (src, tgt):
            if n and n not in nodes:
                nodes.append(n)
        edges.append((src, tgt))
    if not nodes:
        return "\n".join(lines)
    return flowchart(nodes, edges)



def beautify(text: str) -> str:

    if not text or not text.strip():
        return text
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]

        if _is_table_line(line):
            block = []
            while i < len(lines) and _is_table_line(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_normalize_table(block))
            changed = True
            continue

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



        if _KV_RE.match(line):
            block = []
            while i < len(lines) and _KV_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            if len(block) >= 2:
                if _is_bar_block(block):

                    if CHARTS_AVAILABLE:
                        if _is_waffle_candidate(block):
                            out.append(_to_waffle(block))
                            changed = True
                        else:
                            out.append(_numeric_series_to_sparkline(block))
                            changed = True
                    else:

                        try:
                            out.append(_line_chart(block))
                        except Exception:
                            out.append(_bar_chart(block))
                        changed = True
                else:
                    out.append(_kv_to_table(block))
                    changed = True
            elif len(block) == 1 and _is_gauge_candidate(block):

                if CHARTS_AVAILABLE:
                    out.append(_to_gauge(block))
                    changed = True
                else:
                    out.append(block[0])
            else:
                out.append(block[0])
            continue

        if _detect_flowchart([line] + lines[i+1:i+6] if i+1 < len(lines) else []):
            block = [line]
            i += 1
            while i < len(lines) and _FLOW_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_to_flowchart(block))
            changed = True
            continue

        if _detect_hierarchy([line] + lines[i+1:i+6] if i+1 < len(lines) else []):
            block = [line]
            i += 1


            while i < len(lines) and _detect_hierarchy([line, lines[i]]):
                block.append(lines[i])
                i += 1
            out.append(_render_tree(block))
            changed = True
            continue
        out.append(line)
        i += 1
    result = "\n".join(out)
    return result if changed else text


def beautify_html(text: str) -> str:

    text = beautify(text)

    return f"""<div class="beautified">
<pre>{html_escape(text)}</pre>
</div>"""



def main():

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
