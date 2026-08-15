#!/usr/bin/env python3
"""post_processor.py — Post-processing pipeline for LLM output.

Strips code fences, thinking preambles, and normalizes glyphs.
This is a *post-processor* job, not an LLM-prompt job (because the LLM
is unreliable about following it).

Usage:
  from lib.post_processor import process_output
  result = process_output(llm_response, show_code=False, show_thinking=False)
  
  # Or via CLI
  echo "raw llm response" | python3 lib/post_processor.py
"""
import re
import sys
from typing import Optional


class PostProcessor:
    """Post-process LLM output to strip fences, preambles, and normalize glyphs.
    
    Args:
        show_code: If True, preserve code blocks (default: False)
        show_thinking: If True, preserve thinking preambles (default: False)
    """
    
    def __init__(self, show_code: bool = False, show_thinking: bool = False):
        self.show_code = show_code
        self.show_thinking = show_thinking
    
    def process(self, text: str) -> str:
        """Run the full post-processing pipeline.
        
        Args:
            text: Raw LLM output
        
        Returns: Processed text
        """
        # Stage 1: Detect and collapse code fences
        if not self.show_code:
            text = self._collapse_code_fences(text)
        else:
            text = self._keep_code_fences(text)
        
        # Stage 2: Strip thinking preambles
        if not self.show_thinking:
            text = self._strip_thinking_preamble(text)
        
        # Stage 3: Normalize glyphs
        text = self._normalize_glyphs(text)
        
        # Stage 4: Strip markdown headers (keep text, remove #)
        text = self._strip_headers(text)
        
        # Stage 5: Normalize bullet lists
        text = self._normalize_bullets(text)
        
        # Stage 6: Strip horizontal rules
        text = self._strip_horizontal_rules(text)
        
        # Stage 7: Strip italic/bold markdown
        text = self._strip_markdown_formatting(text)
        
        # Stage 8: Strip extra whitespace
        text = self._normalize_whitespace(text)
        
        return text
    
    def _collapse_code_fences(self, text: str) -> str:
        """Replace code fences with inline description."""
        # Match fenced code blocks: ```lang ... ```
        pattern = r'```(\w+)?\s*\n(.*?)```'
        def replacer(match):
            lang = match.group(1) or "code"
            code = match.group(2)
            # Count lines
            lines = code.count('\n') + 1
            # Truncate if too long
            preview = code[:100].replace('\n', ' ')
            if len(code) > 100:
                preview += "..."
            return f'[code:{lang} ({lines} lines) — say "show code" to reveal]'
        return re.sub(pattern, replacer, text, flags=re.DOTALL)
    
    def _keep_code_fences(self, text: str) -> str:
        """Keep code fences but normalize them."""
        # Just normalize whitespace around fences
        return re.sub(r'\s*```\s*', '\n```\n', text)
    
    def _strip_thinking_preamble(self, text: str) -> str:
        """Strip thinking/reasoning preambles."""
        # Common patterns for thinking preambles
        patterns = [
            r'^(?:Let me(?:\s+)?(?:think(?:ing)?\s+)?|First(?:\s+)?(?:,|\.)?|To begin(?:\s+)?(?:,|\.)?|I\s+need\s+to(?:\s+)?(?:\s+)?|Sure(?:\s+)?(?:,|\.)?|Here\s+(?:is|are)(?:\s+)?(?:\s+)?).*?\n',
            r'^▎\s*thinking:\s.*?\n',  # Your existing R3 marker
            r'^```(?:thinking|reasoning)\n.*?```',
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
        return text
    
    def _normalize_glyphs(self, text: str) -> str:
        """Normalize glyphs for visual consistency."""
        # Convert bullet lists to ▎ bullets
        text = re.sub(r'^\s*[-*]\s+', '▎ ', text, flags=re.MULTILINE)
        
        # Replace horizontal rules with colored separator
        text = re.sub(r'^---+$', '───', text, flags=re.MULTILINE)
        text = re.sub(r'^===+$', '━━━', text, flags=re.MULTILINE)
        
        return text
    
    def _strip_headers(self, text: str) -> str:
        """Strip markdown headers, keep text."""
        def replace_header(match):
            level = len(match.group(1))
            text = match.group(2)
            # Convert to colored separator
            if level == 1:
                return f"\n━━━ {text} ━━━\n"
            elif level == 2:
                return f"\n─── {text} ───\n"
            else:
                return text
        return re.sub(r'^(#{1,6})\s+(.+)$', replace_header, text, flags=re.MULTILINE)
    
    def _normalize_bullets(self, text: str) -> str:
        """Normalize bullet lists."""
        # Already handled by _normalize_glyphs
        return text
    
    def _strip_horizontal_rules(self, text: str) -> str:
        """Replace horizontal rules with separators."""
        # Already handled by _normalize_glyphs
        return text
    
    def _strip_markdown_formatting(self, text: str) -> str:
        """Strip italic/bold markdown formatting."""
        # Remove **bold** and *italic* markers (terminal can't render them)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        
        return text
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace."""
        # Collapse multiple newlines to single
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text


def process_output(text: str, show_code: bool = False,
                   show_thinking: bool = False) -> str:
    """Process LLM output with the post-processing pipeline.
    
    Args:
        text: Raw LLM output
        show_code: If True, preserve code blocks (default: False)
        show_thinking: If True, preserve thinking preambles (default: False)
    
    Returns: Processed text
    """
    processor = PostProcessor(show_code=show_code, show_thinking=show_thinking)
    return processor.process(text)


def main():
    """Demo: process sample text."""
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
