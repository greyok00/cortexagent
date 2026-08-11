#!/usr/bin/env python3
"""lib/model_backend.py — manage a single llama-server process.

One ``LlamaServer`` instance = one GGUF model on one TCP port. Used for:
  - the big coding model   (port 8080 — managed by the daemon in the new arch)
  - the tiny LFM2.5-1.2B overseer model (port 8082 — managed by lib/overseer.py)

No Ollama. Pure subprocess + HTTP ``/health`` polling. All paths resolve
through ``lib/config.py`` (env → conf → default), so nothing here is hardcoded
to a home directory.

Usage::

    from lib.model_backend import LlamaServer
    srv = LlamaServer("tiny", CFG.tiny_model, port=CFG.tiny_model_port, ctx=4096)
    srv.start()          # spawn + wait for /health
    srv.is_healthy()     # True/False
    srv.stop()           # terminate → free VRAM
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402


class LlamaServer:
    """Owns one llama-server process for the lifetime of this object."""

    def __init__(
        self,
        name: str,
        model_path: str,
        port: int,
        ctx: int = 4096,
        ngl: int = 999,
        alias: Optional[str] = None,
        host: str = "127.0.0.1",
        extra_args: Optional[List[str]] = None,
        log_file: Optional[str] = None,
        llama_dir: Optional[str] = None,
        startup_timeout: int = 180,
    ) -> None:
        self.name = name
        self.model_path = str(model_path)
        self.port = int(port)
        self.ctx = int(ctx)
        self.ngl = int(ngl)
        self.alias = alias or f"cortexagent-{name}"
        self.host = host
        self.extra_args = list(extra_args or [])
        self.llama_dir = Path(llama_dir) if llama_dir else CFG.llama_dir
        self.log_file = Path(log_file) if log_file else (CFG.logs_dir / f"{name}-server.log")
        self.startup_timeout = int(startup_timeout)
        self.proc: Optional[subprocess.Popen] = None

    # ── paths / urls ──────────────────────────────────────────────────────────
    @property
    def binary(self) -> Path:
        return self.llama_dir / "bin" / "llama-server"

    @property
    def health_url(self) -> str:
        return f"http://{self.host}:{self.port}/health"

    @property
    def pid(self) -> Optional[int]:
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ── health ─────────────────────────────────────────────────────────────────
    def is_healthy(self, timeout: float = 3.0) -> bool:
        """True iff llama-server answers /health with HTTP 200."""
        try:
            req = urllib.request.Request(self.health_url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self, timeout: Optional[int] = None) -> bool:
        """Spawn llama-server and wait for /health. Reuses an already-healthy server.

        Returns True if the server is healthy (either pre-existing or freshly
        started), False on any failure. Safe to call repeatedly.
        """
        if self.is_healthy():
            return True
        timeout = int(timeout if timeout is not None else self.startup_timeout)

        if not self.binary.exists():
            print(f"[model_backend] {self.name}: llama-server not found at {self.binary}",
                  file=sys.stderr)
            return False
        if not Path(self.model_path).exists():
            print(f"[model_backend] {self.name}: model not found at {self.model_path}",
                  file=sys.stderr)
            return False

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self.binary),
            "-m", self.model_path,
            "-c", str(self.ctx),
            "-ngl", str(self.ngl),
            "--alias", self.alias,
            "--host", self.host,
            "--port", str(self.port),
        ] + self.extra_args

        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = ":".join(
            p for p in [f"{self.llama_dir}/bin", env.get("LD_LIBRARY_PATH", "")] if p
        )
        log_fh = open(self.log_file, "ab")
        # start_new_session: decouple from the caller's process group so the
        # server survives a SIGINT to the parent (e.g. Ctrl-C in a foreground
        # CLI). The caller is expected to stop() it explicitly to free VRAM.
        self.proc = subprocess.Popen(
            cmd, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        log_fh.close()  # parent's fd no longer needed — child has a dup'd copy

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                print(f"[model_backend] {self.name}: llama-server exited early "
                      f"(code {self.proc.returncode}); see {self.log_file}",
                      file=sys.stderr)
                return False
            if self.is_healthy(timeout=2):
                return True
            time.sleep(1)
        print(f"[model_backend] {self.name}: not ready in {timeout}s; see {self.log_file}",
              file=sys.stderr)
        return False

    def stop(self) -> bool:
        """Terminate the server (SIGTERM → SIGKILL) to free VRAM.

        If we don't own the handle (e.g. the server was started by a previous
        daemon instance), fall back to killing any llama-server bound to our
        port by best-effort ps matching.
        """
        if self.proc is None:
            return self._kill_port_server()
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception as e:
            print(f"[model_backend] {self.name} stop error: {e}", file=sys.stderr)
        self.proc = None
        # Belt-and-suspenders: ensure nothing is left holding the port/VRAM.
        self._kill_port_server()
        return True

    def restart(self) -> bool:
        self.stop()
        time.sleep(1)
        return self.start()

    def _kill_port_server(self) -> bool:
        """Best-effort: kill any llama-server bound to our --port.

        Uses a regex with word boundaries to avoid substring collisions
        (``--port 8080`` must NOT match ``--port 80808``), and handles both
        ``--port 8080`` and ``--port=8080`` syntax. After SIGTERM, verifies
        the PID still exists via ``/proc/<pid>`` before sending SIGKILL to
        prevent a PID-reuse race.
        """
        import re as _re
        pat = _re.compile(rf'--port[=\s]+{self.port}\b')
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid,args"], capture_output=True, text=True,
            ).stdout
            for line in out.splitlines():
                if "grep" in line or "llama-server" not in line:
                    continue
                if pat.search(line):
                    try:
                        pid = int(line.split()[0])
                        os.kill(pid, 15)
                        time.sleep(1)
                        # Verify PID wasn't recycled before SIGKILL.
                        if os.path.exists(f"/proc/{pid}"):
                            os.kill(pid, 9)
                    except (ProcessLookupError, ValueError, OSError):
                        pass
        except Exception:
            return False
        return True


# ── CLI smoke ─────────────────────────────────────────────────────────────────
def _cli() -> int:
    if len(sys.argv) < 2:
        print("usage: model_backend.py {start|stop|health} [name]", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "tiny"
    if name == "tiny":
        srv = LlamaServer("tiny", CFG.tiny_model, port=CFG.tiny_model_port,
                          ctx=2048, alias="cortexagent-tiny",
                          extra_args=["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-np", "1"])
    elif name == "big":
        srv = LlamaServer("big", CFG.big_model, port=CFG.big_model_port,
                          ctx=int(CFG.big_ctx), ngl=999, alias="cortexagent")
    else:
        print(f"unknown server name: {name}", file=sys.stderr)
        return 2
    if cmd == "start":
        ok = srv.start()
        print(f"{name} start: {'OK' if ok else 'FAIL'} (pid {srv.pid})")
        return 0 if ok else 1
    if cmd == "stop":
        srv.stop()
        print(f"{name} stop: done")
        return 0
    if cmd == "health":
        ok = srv.is_healthy()
        print(f"{name} health: {'OK' if ok else 'DOWN'}")
        return 0 if ok else 1
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli())