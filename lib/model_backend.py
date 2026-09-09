#!/usr/bin/env python3

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


    def is_healthy(self, timeout: float = 3.0) -> bool:

        try:
            req = urllib.request.Request(self.health_url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False


    def start(self, timeout: Optional[int] = None) -> bool:

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
            "--jinja",
        ] + self.extra_args

        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = ":".join(
            p for p in [f"{self.llama_dir}/bin", env.get("LD_LIBRARY_PATH", "")] if p
        )

        # Retry on transient port-bind races: a dying previous server briefly
        # holds the port, so the fresh spawn exits with "couldn't bind HTTP
        # server socket". That resolves in a second or two. Hard failures (OOM,
        # bad model) are NOT retried — they won't resolve and each attempt is
        # expensive. Bounded to 3 attempts with a short backoff.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            ok = self._spawn_and_wait(cmd, env, timeout)
            if ok:
                return True
            if attempt < max_attempts and self._is_transient_port_bind():
                print(f"[model_backend] {self.name}: transient port-bind race — "
                      f"retrying ({attempt}/{max_attempts - 1})", file=sys.stderr)
                time.sleep(2 * attempt)
                continue
            return False
        return False

    def _spawn_and_wait(self, cmd: List[str], env: dict, timeout: int) -> bool:

        try:
            self._spawn_log_offset = self.log_file.stat().st_size
        except OSError:
            self._spawn_log_offset = 0
        log_fh = open(self.log_file, "ab")
        self.proc = subprocess.Popen(
            cmd, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        log_fh.close()

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

    def _is_transient_port_bind(self) -> bool:

        try:
            with open(self.log_file, "rb") as fh:
                fh.seek(self._spawn_log_offset)
                text = fh.read().decode("utf-8", errors="replace")
        except Exception:
            return False
        return any(marker in text for marker in (
            "couldn't bind HTTP server socket",
            "Address already in use",
            "port already in use",
            "EADDRINUSE",
        ))

    def stop(self) -> bool:

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

        self._kill_port_server()
        return True

    def restart(self) -> bool:
        self.stop()
        time.sleep(1)
        return self.start()

    def _kill_port_server(self) -> bool:

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

                        if os.path.exists(f"/proc/{pid}"):
                            os.kill(pid, 9)
                    except (ProcessLookupError, ValueError, OSError):
                        pass
        except Exception:
            return False
        return True



def _cli() -> int:
    if len(sys.argv) < 2:
        print("usage: model_backend.py {start|stop|health} [name]", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "big"
    if name == "big":
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