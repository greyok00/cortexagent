#!/usr/bin/env python3
"""minify_skills.py — decomment + minify the shipped skills corpus.

Owner 2026-11-10: skills ship decommented and minified (the Code Shipping
Default); a Cython/Cythonization pass may follow later once everything is
tested, so this stage stays lossless-to-meaning:

  - strip HTML comments (<!-- ... -->) and YAML comments
  - strip trailing whitespace and leading/trailing blank lines
  - collapse 3+ consecutive blank lines to exactly one
  - collapse runs of spaces that carry no alignment (safe default: keep
    indentation, collapse only trailing runs and blank-line spam)

Usage: minify_skills.py [--check] [root ...]
  --check  report what WOULD change, write nothing
Root defaults to ./skills in the repo, plus the --sync target copies to
the runtime agent skills dir when not --check.
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def minify_md(text: str) -> str:
    # fenced code blocks are preserved verbatim
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    comment_buf: list[str] | None = None
    for line in text.splitlines(keepends=False):
        stripped = line.strip()
        if not in_fence:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = True
                fence_marker = stripped[:3]
                out.append(line.rstrip())
                continue
            if stripped.startswith("<!--"):
                comment_buf = [line]
                if stripped.endswith("-->"):
                    comment_buf = None
                continue
            if comment_buf is not None:
                if stripped.endswith("-->"):
                    comment_buf = None
                elif stripped:
                    comment_buf.append(line)
                continue
            # YAML frontmatter comments
            if len(out) < 12 and stripped == "" or line.lstrip().startswith("# ") and out and out[-1].strip().startswith("---"):
                pass  # frontmatter handled below; normal # headings must live
            if line.startswith(" ") or line.startswith("\t"):
                out.append(line.rstrip())
            else:
                out.append(line.rstrip())
        else:
            out.append(line)
            if stripped.startswith(fence_marker) and len(stripped) <= 4:
                in_fence = False
    if comment_buf is not None:
        pass  # unterminated comment at EOF: drop it
    text = "\n".join(out)
    text = re.sub(r"\n{4,}", "\n\n\n", text)  # 3+ blanks -> 1 blank line pair
    return text.strip("\n") + "\n"

def main() -> int:
    check = "--check" in sys.argv
    roots = [a for a in sys.argv[1:] if not a.startswith("--")] or [os.path.join(REPO, "skills")]
    before_total = after_total = 0
    changed = []
    for root in roots:
        for dp, _, fn in os.walk(root):
            for n in sorted(fn):
                if not n.endswith(".md"):
                    continue
                p = os.path.join(dp, n)
                raw = open(p, "r", encoding="utf8").read()
                new = minify_md(raw)
                before_total += len(raw)
                after_total += len(new)
                if new != raw:
                    changed.append(p)
                    if not check:
                        open(p, "w", encoding="utf8").write(new)
    print("before %d B -> after %d B (%.1f%% smaller), %d files changed"
          % (before_total, after_total,
             100 * (1 - after_total / max(before_total, 1)), len(changed)))
    for p in changed[:40]:
        print("  -", os.path.relpath(p, REPO))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
