#!/usr/bin/env python3
"""cortexagent TUI — built with Textual 8.x.

Minimal chat interface. No sidebar, no nav. Just input + log.

Usage:
  cortexagent
  python3 lib/tui.py smoke
  python3 lib/tui.py --help
  python3 lib/tui.py --web
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Input, RichLog, Label
from textual.binding import Binding


# ── Colors ─────────────────────────────────────────────────────────────────
BG = "#0D0D0D"
BG2 = "#1A1A1A"
TEXT = "#E8E8E8"
TEXT2 = "#888888"
TEXT3 = "#555555"
ACCENT = "#C4B89B"
BORDER = "rgba(128,128,128,0.12)"
GREEN = "#4A8B5C"

CORTEX_THEME = Theme(
    name="cortexagent",
    primary=ACCENT,
    accent=ACCENT,
    surface=BG2,
    background=BG,
    foreground=TEXT,
    dark=True,
)

CSS = f"""
Screen {{
    background: {BG};
}}
#chat_log {{
    height: 1fr;
    background: {BG};
    border: solid {BORDER};
    margin: 1;
    padding: 0 1;
}}
#chat_input {{
    dock: bottom;
    background: {BG2};
    color: {TEXT};
    border: tall {BORDER};
    margin: 0 1 1 1;
    padding: 1 2;
}}
#chat_input:focus {{
    border: tall {ACCENT};
}}
#chat_input:ansi {{
    background: {BG2};
    color: {TEXT};
}}
#chat_input:ansi:focus {{
    border: tall {ACCENT};
}}
#status_bar {{
    background: {BG2};
    color: {TEXT3};
    height: 1;
    dock: bottom;
    padding: 0 1;
}}
"""


class TokenCounter:
    def __init__(self, window: int = 30):
        self.window = window
        self.samples: list[tuple[float, int]] = []

    def add_sample(self, tokens: int) -> None:
        now = time.time()
        self.samples.append((now, tokens))
        cutoff = now - self.window
        self.samples = [(t, n) for t, n in self.samples if t >= cutoff]

    @property
    def rate(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        total = sum(n for _, n in self.samples)
        elapsed = self.samples[-1][0] - self.samples[0][0]
        return total / elapsed if elapsed > 0 else 0.0

    @property
    def total(self) -> int:
        return sum(n for _, n in self.samples)


class ChatScreen(Screen):
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self):
        super().__init__()
        self.counter = TokenCounter()
        self.history: list[dict] = []

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat_log", highlight=True, markup=True)
        yield Input(id="chat_input", placeholder="Type a message...")
        yield Label(id="status_bar")

    def on_mount(self) -> None:
        self.query_one("#chat_input", Input).focus()
        self._update_footer()
        self.set_interval(1, self._update_footer)
        log = self.query_one("#chat_log", RichLog)
        log.write(f"[bold {ACCENT}]CORTEXAGENT[/] [dim]by GreyOK00[/dim]")
        log.write("[dim]Type a message to start.[/dim]")

    def _log(self, text: str, style: str = "dim") -> None:
        self.query_one("#chat_log", RichLog).write(f"[{style}]{text}[/{style}]")

    def _add_msg(self, role: str, content: str, meta: Optional[dict] = None) -> None:
        log = self.query_one("#chat_log", RichLog)
        if role == "user":
            log.write(f"[bold {ACCENT}]▸[/] {content}")
        elif role == "assistant":
            log.write(f"[bold {GREEN}]✓[/] {content}")
            if meta and meta.get("tokens"):
                log.write(f"[dim]  {meta['tokens']} tok in {meta.get('elapsed', '0s')}[/dim]")
        elif role == "system":
            log.write(f"[dim]{content}[/dim]")
        self.history.append({"role": role, "content": content, "metadata": meta or {}})

    def _update_footer(self) -> None:
        bar = self.query_one("#status_bar", Label)
        rate = self.counter.rate
        total = self.counter.total
        if total > 0:
            bar.update(f"⚡ {rate:.1f} tok/s  |  📊 {total} tokens")
        else:
            bar.update("CORTEXAGENT by GreyOK00")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def _send(self, text: str) -> None:
        if not text.strip():
            return
        text = text.strip()
        self._add_msg("user", text)
        self.query_one("#chat_input", Input).value = ""
        self._process_message(text)

    @work(exclusive=True, thread=True)
    def _process_message(self, text: str) -> None:
        start = time.time()
        agent = os.environ.get("CORTEXAGENT_CLI", "claude")
        context = self._build_context()
        prompt = context + "\n\nUser: " + text

        try:
            proc = subprocess.Popen(
                [agent, "-p", prompt],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            stdout, stderr = proc.communicate(timeout=300)
            elapsed = time.time() - start
            resp = stdout.strip() or f"(no response: {stderr.strip()[:200]})" if stderr else "(no response)"
            self.counter.add_sample(0)
            self.app.call_from_thread(self._add_msg, "assistant", resp, {
                "tokens": 0, "elapsed": f"{elapsed:.1f}s",
            })
            self.history.append({"role": "assistant", "content": resp})
        except FileNotFoundError:
            self.app.call_from_thread(self._add_msg, "system", "Agent binary not found. Check CORTEXAGENT_CLI.")
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(self._add_msg, "system", "Request timed out after 300s.")
        except Exception as e:
            self.app.call_from_thread(self._add_msg, "system", f"Error: {e}")

    def _build_context(self) -> str:
        parts = []
        for msg in self.history[-20:]:
            r = msg["role"]
            c = msg.get("content", "")
            if r == "user":
                parts.append(f"User: {c}")
            elif r == "assistant":
                parts.append(f"Assistant: {c}")
        return "\n".join(parts[-10:])

    def action_clear(self) -> None:
        self.query_one("#chat_log", RichLog).clear()
        self.history.clear()
        self.counter = TokenCounter()
        self._log("Chat cleared.")

    def action_quit(self) -> None:
        self.app.exit()


class CortexAgentApp(App):
    TITLE = "CortexAgent"
    CSS = CSS

    def __init__(self):
        super().__init__()
        self.register_theme(CORTEX_THEME)
        self.theme = "cortexagent"

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())


def _check_terminal() -> bool:
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "").lower()
    if not term or term in ("dumb", "emacs", "vt100"):
        return False
    return True


def _print_help() -> None:
    print(__doc__)
    print()
    print("Environment:")
    print("  CORTEXAGENT_CLI       Agent binary (default: claude)")
    print("  CORTEXAGENT_WEBUI_PORT Web UI port (default: 8090)")
    print("  CORTEXAGENT_WEBUI_BIND Web UI bind (default: 127.0.0.1)")


def _print_web_url() -> None:
    port = os.environ.get("CORTEXAGENT_WEBUI_PORT", "8090")
    bind = os.environ.get("CORTEXAGENT_WEBUI_BIND", "127.0.0.1")
    print(f"http://{bind}:{port}/")


def main():
    flags = set(a for a in sys.argv[1:] if a.startswith("-"))
    if "--help" in flags or "-h" in flags:
        _print_help()
        return
    if "--web" in flags:
        _print_web_url()
        return
    if not _check_terminal():
        port = os.environ.get("CORTEXAGENT_WEBUI_PORT", "8090")
        bind = os.environ.get("CORTEXAGENT_WEBUI_BIND", "127.0.0.1")
        print("CortexAgent TUI requires a real terminal (256-color, TTY).", file=sys.stderr)
        print(f"Web UI available at: http://{bind}:{port}/", file=sys.stderr)
        sys.exit(1)
    app = CortexAgentApp()
    app.run()


def _smoke() -> int:
    tc = TokenCounter()
    tc.add_sample(100)
    tc.add_sample(200)
    assert tc.total == 300
    print(f"  TokenCounter: total={tc.total}")
    assert _check_terminal() == sys.stdout.isatty()
    print(f"  Terminal check: {_check_terminal()}")
    print("tui: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    main()
