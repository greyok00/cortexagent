#!/usr/bin/env python3
"""cortexagent TUI — built with Textual 8.x.

Full-screen chat with a compact, typed response model:

  · claude -p runs STREAMING (chunk-by-chunk), not one blocking communicate()
  · assistant output is parsed into typed blocks — text, code artifacts,
    tool status, disclosures — instead of one raw scrolling blob
  · code blocks become collapsed cards; Enter opens a full-screen viewer
    with copy / save / search
  · long responses collapse into "Details (N)" disclosures
  · model/tool output is terminal-escape-sanitized (can never control the TTY)
  · parsing + rendering live in lib/response_model.py (pure, testable)

Keys:
  j/k            scroll chat          c       copy artifact to clipboard
  enter          open/toggle block    s       save artifact to file
  tab            move focus           /       search inside artifact
  ctrl+c         cancel (again: quit) ?       help
  ctrl+l         clear chat           esc     close help / viewer

Usage:
  cortexagent                    interactive TUI
  python3 lib/tui.py smoke       self-test
  python3 lib/tui.py --help
  python3 lib/tui.py --web
  python3 lib/tui.py --plain [prompt]   one-shot, plain-text output (non-TTY)
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib.config import CFG  # author tag is configurable (CORTEXAGENT_AUTHOR)
from lib.response_model import (
    ArtifactBlock,
    DisclosureBlock,
    TextBlock,
    ToolBlock,
    collapse,
    format_visual,
    parse_response,
    render_plain,
    sanitize_terminal,
)
from lib.session_bridge import SessionBridge

# Session bridge: shared file for TUI ↔ webui chat sync
_BRIDGE = SessionBridge()

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.markup import escape
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import Button, Input, Label, Static


# ── Colors ─────────────────────────────────────────────────────────────────
BG = "#0D0D0D"
BG2 = "#1A1A1A"
TEXT = "#E8E8E8"
TEXT2 = "#888888"
TEXT3 = "#555555"
ACCENT = "#C4B89B"
BORDER = "rgba(128,128,128,0.12)"
GREEN = "#4A8B5C"
RED = "#C4554D"

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
#topbar {{
    dock: top;
    height: 1;
    background: {BG2};
    color: {TEXT2};
    padding: 0 1;
}}
#chat {{
    height: 1fr;
    background: {BG};
    border: solid {BORDER};
    margin: 1;
    padding: 0 1;
}}
#chat_input {{
    dock: bottom;
    height: 3;
    background: {BG2};
    color: {TEXT};
    border: tall {BORDER};
    margin: 0 1 0 1;
    padding: 1 2;
}}
#chat_input:focus {{
    border: tall {ACCENT};
}}
#footer_hint {{
    dock: bottom;
    height: 1;
    background: {BG2};
    color: {TEXT3};
    padding: 0 1;
}}
.banner {{
    color: #96DCFF;
    margin: 1 0 1 0;
    text-style: bold;
}}
.user {{
    color: {ACCENT};
    margin: 1 0 0 0;
    text-style: bold;
}}
.stream {{
    color: {TEXT};
    margin: 0 0 1 0;
}}
.txt {{
    color: {TEXT};
    margin: 0 0 1 0;
}}
.artifact {{
    background: {BG2};
    color: {ACCENT};
    margin: 0 0 1 0;
    width: 100%;
}}
.artifact:focus {{
    border: tall {ACCENT};
}}
.disc {{
    background: {BG2};
    color: {TEXT2};
    margin: 0 0 1 0;
    width: 100%;
}}
.disc:focus {{
    border: tall {TEXT2};
}}
.detail {{
    color: {TEXT2};
    margin: 0 0 1 2;
}}
.tool {{
    color: {GREEN};
    margin: 0 0 0 0;
}}

#viewer {{
    width: 92%;
    height: 92%;
    border: tall {ACCENT};
    background: {BG};
    padding: 1 2;
}}
#viewer_title {{
    color: {ACCENT};
    text-style: bold;
    margin-bottom: 1;
}}
#viewer_search {{
    display: none;
    margin-bottom: 1;
    background: {BG2};
    border: tall {BORDER};
    padding: 0 1;
}}
#viewer_search.show {{
    display: block;
}}
#viewer_scroll {{
    height: 1fr;
    background: {BG};
    border: solid {BORDER};
}}
#viewer_scroll .code {{
    color: {TEXT};
    background: {BG2};
    padding: 0 2;
    overflow-x: auto;
}}
#viewer_hint {{
    color: {TEXT3};
    height: 1;
    margin-top: 1;
}}
#help {{
    width: 60%;
    height: 70%;
    border: tall {ACCENT};
    background: {BG};
    padding: 1 2;
}}
#help .k {{
    color: {TEXT};
    margin: 0 0 0 2;
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


# ── Response block widgets ──────────────────────────────────────────────────
class ArtifactCard(Button):
    """Collapsed code-artifact card — Enter opens the full viewer."""

    def __init__(self, artifact, panel: "TurnPanel"):
        label = (f"▸ Code artifact: {escape(artifact.filename)} · "
                 f"{escape(artifact.language)} · {artifact.n_lines} lines")
        super().__init__(label, classes="artifact")
        self.artifact = artifact
        self.panel = panel

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self:
            self.panel.app.open_artifact(self.artifact)


class DisclosureCard(Button):
    """Collapsible disclosure (Details / Code artifacts / Tool activity)."""

    def __init__(self, disclosure: DisclosureBlock):
        super().__init__(f"▸ {escape(disclosure.title)}", classes="disc")
        self.disc = disclosure
        self._detail: Optional[Static] = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self:
            return
        if self._detail is None:
            self._detail = Static(escape(self.disc.detail), classes="detail")
            self.parent.mount(self._detail, after=self)
        else:
            self._detail.remove()
            self._detail = None


class TurnPanel(Vertical):
    """One user→assistant turn: prompt header, streaming text, typed blocks."""

    stream = reactive("")
    state = reactive("idle")

    def __init__(self, user_text: str, **kw):
        super().__init__(**kw)
        self.user_text = user_text
        self._stream_widget: Optional[Static] = None
        self.elapsed = 0.0

    def compose(self) -> ComposeResult:
        yield Static(f"[bold {ACCENT}]▸ {escape(self.user_text)}[/]", classes="user")
        yield Static(classes="stream", id="stream")

    def on_mount(self) -> None:
        self._stream_widget = self.query_one("#stream", Static)
        if self.stream:
            self._stream_widget.update(escape(self.stream))
            self._auto_scroll()

    def watch_stream(self, value: str) -> None:
        if self._stream_widget is not None:
            self._stream_widget.update(escape(value))
            self._auto_scroll()

    def _auto_scroll(self) -> None:
        parent = self.parent
        if isinstance(parent, VerticalScroll):
            parent.scroll_end(animate=False)

    def append(self, chunk: str) -> None:
        self.stream += chunk

    def finish(self, elapsed: float) -> None:
        self.state = "completed"
        self.elapsed = elapsed
        if self._stream_widget is not None:
            self._stream_widget.remove()
            self._stream_widget = None
        blocks = collapse(parse_response(self.stream))
        if not blocks:
            self.mount(Static("[dim](no response)[/]", classes="txt"))
        for b in blocks:
            w = self._make_block(b)
            if w is not None:
                self.mount(w)
        self._auto_scroll()

    def finish_error(self, error: str) -> None:
        self.state = "failed"
        self.elapsed = 0.0
        if self._stream_widget is not None:
            self._stream_widget.remove()
            self._stream_widget = None
        self.mount(Static(f"[bold {RED}]✗ {escape(error)}[/]", classes="txt"))
        self._auto_scroll()

    def finish_cancelled(self) -> None:
        self.state = "cancelled"
        if self._stream_widget is not None:
            self._stream_widget.update(escape(self.stream) + "\n…")
        self._auto_scroll()

    def _make_block(self, b):
        if isinstance(b, TextBlock):
            # Visual pass: markdown tables → box-drawn tables, numeric columns
            # → █ bar charts, ASCII art preserved, headings get a ▎ accent.
            width = max(40, self.app.size.width - 6)
            return Static(escape(format_visual(b.text, width)), classes="txt")
        if isinstance(b, ArtifactBlock):
            return ArtifactCard(b.artifact, self)
        if isinstance(b, DisclosureBlock):
            return DisclosureCard(b)
        if isinstance(b, ToolBlock):
            mark = {"ok": "✓", "running": "●", "failed": "!"}.get(b.status, "•")
            return Static(f"[{GREEN}]{mark}[/] {escape(b.summary)}", classes="tool")
        return None


# ── Modal screens ───────────────────────────────────────────────────────────
class ArtifactViewer(ModalScreen):
    """Full-screen code viewer with copy / save / search."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("c", "copy", "Copy"),
        Binding("s", "save", "Save"),
        Binding("slash", "search", "Search"),
    ]

    def __init__(self, artifact):
        super().__init__()
        self.artifact = artifact
        self._matches: List[int] = []
        self._pos = -1

    def compose(self) -> ComposeResult:
        with Vertical(id="viewer"):
            yield Label(
                f"[bold]{escape(self.artifact.filename)}[/] · "
                f"{escape(self.artifact.language)} · {self.artifact.n_lines} lines",
                id="viewer_title",
            )
            yield Input(id="viewer_search", placeholder="Search…")
            with VerticalScroll(id="viewer_scroll"):
                yield Static(escape(self.artifact.source), classes="code")
            yield Label(
                "[dim]c copy · s save · / search · enter next · esc close[/]",
                id="viewer_hint",
            )

    def on_mount(self) -> None:
        self.query_one("#viewer_scroll", VerticalScroll).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "viewer_search":
            self._update_matches(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "viewer_search":
            if self._matches:
                self._pos = (self._pos + 1) % len(self._matches)
                self._goto(self._matches[self._pos])
            event.input.value = ""

    def _update_matches(self, term: str) -> None:
        term = term.lower()
        lines = self.artifact.source.splitlines()
        self._matches = [i for i, ln in enumerate(lines) if term in ln.lower()]
        self._pos = -1
        hint = self.query_one("#viewer_hint", Label)
        if self._matches:
            hint.update(
                f"[dim]{len(self._matches)} matches · enter next · c copy · "
                f"s save · esc close[/]"
            )
            self._goto(self._matches[0])
        else:
            hint.update("[dim]no matches · c copy · s save · esc close[/]")

    def _goto(self, idx: int) -> None:
        self.query_one("#viewer_scroll", VerticalScroll).scroll_to(
            y=idx, animate=False
        )

    def action_copy(self) -> None:
        text = self.artifact.source
        try:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode(), check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                subprocess.run(["wl-copy"], input=text.encode(), check=True)
            except (FileNotFoundError, subprocess.CalledProcessError):
                self.app.notify("No clipboard tool (xclip / wl-copy) found.")
                return
        self.app.notify("Copied to clipboard.")

    def action_save(self) -> None:
        cwd = Path.cwd()
        base = cwd / self.artifact.filename
        target = base
        stem, suffix = base.stem, base.suffix
        i = 1
        while target.exists():
            target = cwd / f"{stem}-{i}{suffix}"
            i += 1
        try:
            target.write_text(self.artifact.source)
        except OSError as e:
            self.app.notify(f"Save failed: {e}")
            return
        self.app.notify(f"Saved → {target}")

    def action_search(self) -> None:
        inp = self.query_one("#viewer_search", Input)
        inp.add_class("show")
        inp.focus()

    def action_close(self) -> None:
        self.app.pop_screen()


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        rows = [
            ("j / k", "scroll chat"),
            ("↑/↓", "navigate blocks / viewer"),
            ("enter", "open code artifact / toggle disclosure"),
            ("tab", "move focus between blocks"),
            ("c", "copy artifact to clipboard"),
            ("s", "save artifact to file"),
            ("/", "search inside artifact"),
            ("ctrl+c", "cancel running turn (again: quit)"),
            ("ctrl+l", "clear chat"),
            ("?", "this help"),
            ("esc", "close help / viewer"),
        ]
        with Vertical(id="help"):
            yield Static("[bold]CortexAgent TUI keys[/]", classes="txt")
            for key, desc in rows:
                yield Static(f"[{ACCENT}]{key:<10}[/] {desc}", classes="k")

    def action_close(self) -> None:
        self.app.pop_screen()


# ── Main chat screen ────────────────────────────────────────────────────────
class ChatScreen(Screen):
    BINDINGS = [
        Binding("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("j", "scroll_down", "Scroll down"),
        Binding("k", "scroll_up", "Scroll up"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        self.counter = TokenCounter()
        self.history: list[dict] = []
        self.active_panel: Optional[TurnPanel] = None
        self._banner: Optional[Static] = None
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._worker_running = False
        self._session_start = time.time()
        self._turn_start = 0.0
        self._model = (
            os.environ.get("CLAUDE_MODEL_NAME")
            or os.environ.get("CORTEXAGENT_ALIAS")
            or "local"
        )
        # ── Session bridge (TUI ↔ webui sync) ─────────────────────────────
        self._bridge_seq: int = 0  # last seq read from bridge
        self._bridge_thread: Optional[threading.Thread] = None
        self._bridge_stop = threading.Event()

    def compose(self) -> ComposeResult:
        yield Label(id="topbar")
        self._banner = Static(self._banner_text(), classes="banner")
        with VerticalScroll(id="chat"):
            yield self._banner
        yield Input(id="chat_input", placeholder="Type a message…")
        yield Static(
            "[dim]? help · j/k scroll · enter send · ctrl+c cancel · ctrl+l clear[/]",
            id="footer_hint",
        )

    def _banner_text(self) -> str:
        from lib import banner as _banner
        lines = "\n".join(f"[#96DCFF]  {_ln}[/]" for _ln in _banner.LOGO)
        lines += f"\n[dim]  CORTEXAGENT by {CFG.author}[/]"
        if self._model:
            lines += f"\n[dim]  Model: {self._model}[/]"
        lines += "\n[dim]Type a message to start.[/dim]"
        return lines

    def on_mount(self) -> None:
        self.query_one("#chat_input", Input).focus()
        self.set_interval(1, self._tick)
        # Start session bridge polling thread
        self._bridge_thread = threading.Thread(
            target=self._bridge_poll, daemon=True, name="tui-bridge"
        )
        self._bridge_thread.start()

    def _tick(self) -> None:
        bar = self.query_one("#topbar", Label)
        elapsed = time.time() - self._session_start
        p = self.active_panel
        state = p.state if p else "idle"
        parts = [f"CortexAgent · {CFG.author}", self._model, state]
        if p:
            if p.state == "streaming" and self._turn_start:
                parts.append(f"{time.time() - self._turn_start:.0f}s")
            elif p.elapsed:
                parts.append(f"{p.elapsed:.0f}s")
        if self.counter.total:
            parts.append(f"{self.counter.rate:.0f} tok/s")
            parts.append(f"{self.counter.total} tok")
        parts.append(f"session {elapsed:.0f}s")
        bar.update(" · ".join(parts))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def _send(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        chat = self.query_one("#chat", VerticalScroll)
        panel = TurnPanel(text)
        chat.mount(panel)
        self.active_panel = panel
        self._cancelled = False
        self._turn_start = time.time()
        inp = self.query_one("#chat_input", Input)
        inp.value = ""
        inp.focus()
        self.history.append({"role": "user", "content": text, "metadata": {}})
        # Forward to webui via bridge — username is "User" so the chat pane can
        # label this entry under the local user even when both UIs are open.
        self._bridge_write({
            "id": str(uuid.uuid4()),
            "type": "message",
            "username": "User",
            "content": text,
            "ts": datetime.now().isoformat(),
        })
        self._process_message(text, panel)

    @work(exclusive=True, thread=True)
    def _process_message(self, text: str, panel: TurnPanel) -> None:
        start = time.time()
        agent = os.environ.get("CORTEXAGENT_CLI", "claude")
        prompt = self._build_context() + "\n\nUser: " + text
        self._worker_running = True
        cmd = [agent, "-p", prompt]
        mcp = os.environ.get("CORTEXAGENT_MCP_CONFIG")
        if mcp:
            cmd += ["--mcp-config", mcp]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            self.app.call_from_thread(
                panel.finish_error,
                "Agent binary not found. Check CORTEXAGENT_CLI.",
            )
            self._worker_running = False
            return
        self._proc = proc

        q: "queue.Queue[tuple]" = queue.Queue()

        def pump(stream, sid: str) -> None:
            try:
                while True:
                    chunk = stream.read(64)
                    if not chunk:
                        break
                    q.put((sid, chunk))
            except Exception as e:  # pragma: no cover - defensive
                q.put((sid, f"\n[stderr:{e}]"))
            finally:
                q.put(("eof", sid))

        threads = [
            threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True),
        ]
        for t in threads:
            t.start()

        stderr_buf: List[str] = []
        eofs = 0
        while eofs < 2:
            try:
                sid, data = q.get(timeout=0.2)
            except queue.Empty:
                if self._cancelled:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                continue
            if sid == "eof":
                eofs += 1
            elif sid == "out":
                safe = sanitize_terminal(data)
                if safe:
                    self.app.call_from_thread(panel.append, safe)
                    self.counter.add_sample(max(1, len(safe) // 4))
            elif data:
                stderr_buf.append(data)

        try:
            ret = proc.wait()
        except Exception:
            ret = proc.returncode if proc.returncode is not None else -1
        elapsed = time.time() - start
        self._proc = None
        self._worker_running = False

        meta = {"tokens": self.counter.total, "elapsed": f"{elapsed:.1f}s"}
        response_text = panel.stream if panel.stream else "(no response)"
        if self._cancelled:
            self.app.call_from_thread(panel.finish_cancelled)
            meta["cancelled"] = True
        elif ret != 0:
            err = sanitize_terminal("".join(stderr_buf)).strip() or f"exit {ret}"
            self.app.call_from_thread(panel.finish_error, err[:2000])
            meta["error"] = err
        else:
            self.app.call_from_thread(panel.finish, elapsed)
        self.app.call_from_thread(
            self.history.append,
            {"role": "assistant", "content": panel.stream, "metadata": meta},
        )
        # Forward response to webui via bridge — username "Big Model" so the
        # unified chat shows which voice said this.
        self._bridge_write({
            "id": str(uuid.uuid4()),
            "type": "response",
            "username": "Big Model",
            "content": response_text,
            "from": "tui",
            "ts": datetime.now().isoformat(),
            "meta": meta,
        })

    # ── Session bridge (TUI ↔ webui sync) ──────────────────────────────────
    def _bridge_poll(self) -> None:
        """Background thread: poll shared bridge for webui messages."""
        while not self._bridge_stop.is_set():
            try:
                events = _BRIDGE.read_new("tui")
            except Exception:
                events = []
            for ev in events:
                if ev.get("type") == "message":
                    content = ev.get("content", "").strip()
                    if content:
                        # Queue for main thread via call_from_thread
                        self.app.call_from_thread(self._send, content)
            self._bridge_stop.wait(timeout=2)

    def _bridge_write(self, event: Dict) -> None:
        """Write an event to the bridge for the webui to read."""
        try:
            _BRIDGE.write("tui", event)
        except Exception:
            pass

    def _build_context(self) -> str:
        parts = []
        for msg in self.history[-20:]:
            r, c = msg["role"], msg.get("content", "")
            if r == "user":
                parts.append(f"User: {c}")
            elif r == "assistant":
                parts.append(f"Assistant: {c}")
        return "\n".join(parts[-10:])

    # ── Actions ──
    def action_cancel_or_quit(self) -> None:
        if self._worker_running and self._proc is not None:
            self._cancelled = True
            try:
                self._proc.terminate()
            except Exception:
                pass
            self.notify("Cancelling…")
        else:
            self.app.exit()

    def action_scroll_down(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_down(animate=False)

    def action_scroll_up(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_up(animate=False)

    def action_clear(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        for w in list(chat.children):
            if w is not self._banner:
                w.remove()
        self.history.clear()
        self.counter = TokenCounter()
        self.active_panel = None
        self.notify("Chat cleared.")

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())


class CortexAgentApp(App):
    TITLE = "CortexAgent"
    CSS = CSS

    def __init__(self):
        super().__init__()
        self.register_theme(CORTEX_THEME)
        self.theme = "cortexagent"

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())

    def open_artifact(self, artifact) -> None:
        self.push_screen(ArtifactViewer(artifact))


# ── CLI helpers ─────────────────────────────────────────────────────────────
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


def _run_plain(prompt: Optional[str] = None) -> int:
    """One-shot claude -p with clean plain-text output (non-TTY / --plain)."""
    agent = os.environ.get("CORTEXAGENT_CLI", "claude")
    if prompt is None:
        prompt = sys.stdin.read()
    prompt = prompt.strip()
    if not prompt:
        print("No prompt given.", file=sys.stderr)
        return 1
    cmd = [agent, "-p", prompt]
    mcp = os.environ.get("CORTEXAGENT_MCP_CONFIG")
    if mcp:
        cmd += ["--mcp-config", mcp]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        print("Agent binary not found. Check CORTEXAGENT_CLI.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("Request timed out after 300s.", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(proc.stderr.strip() or f"exit {proc.returncode}", file=sys.stderr)
        return proc.returncode
    blocks = collapse(parse_response(proc.stdout))
    print(render_plain(blocks))
    return 0


def main() -> None:
    flags = set(a for a in sys.argv[1:] if a.startswith("-"))
    if "--help" in flags or "-h" in flags:
        _print_help()
        return
    if "--web" in flags:
        _print_web_url()
        return
    if "--plain" in flags:
        rest = [a for a in sys.argv[1:] if a != "--plain"]
        sys.exit(_run_plain(rest[0] if rest else None))
    if not _check_terminal():
        port = os.environ.get("CORTEXAGENT_WEBUI_PORT", "8090")
        bind = os.environ.get("CORTEXAGENT_WEBUI_BIND", "127.0.0.1")
        print("CortexAgent TUI requires a real terminal (256-color, TTY).",
              file=sys.stderr)
        print(f"Use --plain for non-interactive output, or the web UI at: "
              f"http://{bind}:{port}/", file=sys.stderr)
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

    blocks = parse_response("Intro\n```python\nprint(1)\n```\nOutro")
    arts = [b for b in blocks if isinstance(b, ArtifactBlock)]
    assert len(arts) == 1 and arts[0].artifact.language == "python"
    assert sanitize_terminal("\x1b[31mhi\x1b[0m") == "hi"
    long = collapse(parse_response("word " * 1000))
    assert any(isinstance(b, DisclosureBlock) for b in long)
    print(f"  response_model: {len(blocks)} blocks parsed, ok")
    print("tui: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    main()
