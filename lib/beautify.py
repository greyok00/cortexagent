#!/usr/bin/env python3
"""lib/beautify.py — beautification pass for overseer output.

Post-processes the overseer's final answer into scannable tables and charts:
  - normalizes markdown tables (aligns columns, adds a separator row)
  - converts CSV/TSV blocks to markdown tables
  - converts ``key: value`` blocks to two-column tables
  - renders simple numeric series as ASCII bar charts

Pure functions — no server, no side effects. Detection is conservative: only
clear patterns are transformed; prose is left untouched.

Usage:
  python3 lib/beautify.py smoke          # self-test
  python3 lib/beautify.py "text"         # beautify a string
"""
from __future__ import annotations

import re
import sys
from typing import List, Optional


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
    out = []
    for i, r in enumerate(rows):
        if i == sep_idx:
            out.append(sep)
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


# ── numeric series → ASCII bar chart ────────────────────────────────────────
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
    out = []
    for label, val in items:
        bar = "█" * max(1, int(val * scale))
        out.append(f"{label:<24} {bar} {val:g}")
    return "\n".join(out)


# ── main entry ──────────────────────────────────────────────────────────────
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
        # key: value block → bar chart if numeric, else table.
        # Conservative: only 2+ consecutive KV lines convert — a single
        # "key: value" line is ambiguous prose ("Next steps: block the IPs.").
        if _KV_RE.match(line):
            block = []
            while i < len(lines) and _KV_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            if len(block) >= 2:
                if _is_bar_block(block):
                    out.append(_bar_chart(block))
                else:
                    out.append(_kv_to_table(block))
                changed = True
            else:
                out.append(block[0])
            continue
        out.append(line)
        i += 1
    result = "\n".join(out)
    return result if changed else text


def beautify_html(text: str) -> str:
    """HTML variant for the webui: wraps tables in <table> and charts in <pre>."""
    import html as _html
    md = beautify(text)
    # convert markdown tables to HTML tables
    lines = md.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        if _is_table_line(lines[i]):
            block = []
            while i < len(lines) and _is_table_line(lines[i]):
                block.append(lines[i])
                i += 1
            rows = [[c.strip() for c in l.strip().strip("|").split("|")]
                    for l in block if "---" not in l]
            if rows:
                out.append("<table>")
                for ri, r in enumerate(rows):
                    tag = "th" if ri == 0 else "td"
                    out.append("<tr>" + "".join(
                        f"<{tag}>{_html.escape(c)}</{tag}>" for c in r) + "</tr>")
                out.append("</table>")
            continue
        out.append(_html.escape(lines[i]))
        i += 1
    return "\n".join(out)


# ── self-test ───────────────────────────────────────────────────────────────
def _smoke() -> int:
    fails = 0

    def check(name: str, got: str, want: str) -> None:
        nonlocal fails
        if got != want:
            print(f"❌ {name}:\n--- got ---\n{got}\n--- want ---\n{want}")
            fails += 1

    # markdown table normalization (adds separator)
    got = beautify("| a | b |\n| 1 | 2 |")
    check("md table", got, "| a | b |\n| - | - |\n| 1 | 2 |")
    # CSV → table
    got = beautify("name,score\nalice,10\nbob,20")
    check("csv table", got, "| name  | score |\n| ----- | ----- |\n| alice | 10    |\n| bob   | 20    |")
    # key: value → table
    got = beautify("host: 10.0.0.5\nport: 8080")
    check("kv table", got, "| host | 10.0.0.5 |\n| ---- | -------- |\n| port | 8080     |")
    # numeric series → bar chart
    got = beautify("requests: 100\nerrors: 25")
    check("bar chart", got, "requests                 ████████████████████ 100\nerrors                   █████ 25")
    # prose untouched
    got = beautify("The investigation is complete. No issues found.")
    check("prose", got, "The investigation is complete. No issues found.")
    # empty
    got = beautify("")
    check("empty", got, "")

    print("beautify: OK" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    if len(sys.argv) > 1:
        print(beautify(" ".join(sys.argv[1:])))
    else:
        print("usage: beautify.py smoke | <text>", file=sys.stderr)
        sys.exit(2)
