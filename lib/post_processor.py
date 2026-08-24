#!/usr/bin/env python3

import re
import sys
from typing import Optional


class PostProcessor:


    def __init__(self, show_code: bool = False, show_thinking: bool = False):
        self.show_code = show_code
        self.show_thinking = show_thinking

    def process(self, text: str) -> str:


        if not self.show_code:
            text = self._collapse_code_fences(text)
        else:
            text = self._keep_code_fences(text)


        if not self.show_thinking:
            text = self._strip_thinking_preamble(text)


        text = self._normalize_glyphs(text)


        text = self._strip_headers(text)


        text = self._normalize_bullets(text)


        text = self._strip_horizontal_rules(text)


        text = self._strip_markdown_formatting(text)


        text = self._normalize_whitespace(text)

        return text

    def _collapse_code_fences(self, text: str) -> str:


        pattern = r'```(\w+)?\s*\n(.*?)```'
        def replacer(match):
            lang = match.group(1) or "code"
            code = match.group(2)

            lines = code.count('\n') + 1

            preview = code[:100].replace('\n', ' ')
            if len(code) > 100:
                preview += "..."
            return f'[code:{lang} ({lines} lines) — say "show code" to reveal]'
        return re.sub(pattern, replacer, text, flags=re.DOTALL)

    def _keep_code_fences(self, text: str) -> str:


        return re.sub(r'\s*```\s*', '\n```\n', text)

    def _strip_thinking_preamble(self, text: str) -> str:


        patterns = [
            r'^(?:Let me(?:\s+)?(?:think(?:ing)?\s+)?|First(?:\s+)?(?:,|\.)?|To begin(?:\s+)?(?:,|\.)?|I\s+need\s+to(?:\s+)?(?:\s+)?|Sure(?:\s+)?(?:,|\.)?|Here\s+(?:is|are)(?:\s+)?(?:\s+)?).*?\n',
            r'^▎\s*thinking:\s.*?\n',
            r'^```(?:thinking|reasoning)\n.*?```',
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
        return text

    def _normalize_glyphs(self, text: str) -> str:


        text = re.sub(r'^\s*[-*]\s+', '▎ ', text, flags=re.MULTILINE)


        text = re.sub(r'^---+$', '───', text, flags=re.MULTILINE)
        text = re.sub(r'^===+$', '━━━', text, flags=re.MULTILINE)

        return text

    def _strip_headers(self, text: str) -> str:

        def replace_header(match):
            level = len(match.group(1))
            text = match.group(2)

            if level == 1:
                return f"\n━━━ {text} ━━━\n"
            elif level == 2:
                return f"\n─── {text} ───\n"
            else:
                return text
        return re.sub(r'^(#{1,6})\s+(.+)$', replace_header, text, flags=re.MULTILINE)

    def _normalize_bullets(self, text: str) -> str:


        return text

    def _strip_horizontal_rules(self, text: str) -> str:


        return text

    def _strip_markdown_formatting(self, text: str) -> str:


        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)

        return text

    def _normalize_whitespace(self, text: str) -> str:


        text = re.sub(r'\n{3,}', '\n\n', text)

        text = text.strip()

        return text


def process_output(text: str, show_code: bool = False,
                   show_thinking: bool = False) -> str:

    processor = PostProcessor(show_code=show_code, show_thinking=show_thinking)
    return processor.process(text)


def main():

    sample = """
Let me think about this...

Here is the answer:

```python
def hello():
    print("Hello, World!")
```

Some bullet points:
- First point
- Second point
- Third point

---

# Main Header

## Sub Header

This is **bold** and *italic* text.

"""
    print("=== Original ===")
    print(sample)
    print("\n=== Processed (no code, no thinking) ===")
    print(process_output(sample, show_code=False, show_thinking=False))
    print("\n=== Processed (show code, no thinking) ===")
    print(process_output(sample, show_code=True, show_thinking=False))
    print("\n=== Processed (show both) ===")
    print(process_output(sample, show_code=True, show_thinking=True))


if __name__ == "__main__":
    main()
