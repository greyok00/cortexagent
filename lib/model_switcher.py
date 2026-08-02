#!/usr/bin/env python3
"""model_switcher — swap between coding model and image/video generation models.

Manages VRAM by killing the main llama-server, loading Flux/LTX for gen,
then restoring the coding model. The heartbeat LLM (qwen2.5:0.5b) stays in
VRAM the entire time via Ollama.

Usage:
  python3 model_switcher.py gen-image "prompt" --output output.png
  python3 model_switcher.py gen-video "prompt" --output output.mp4
  python3 model_switcher.py status
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

LLAMA_DIR = os.environ.get("CORTEXAGENT_LLAMA_DIR", str(Path.home() / "llama.cpp" / "build"))
MODELS_DIR = os.environ.get("CORTEXAGENT_MODELS_DIR", str(Path.home() / "models"))
FLUX_MODEL = os.environ.get("CORTEXAGENT_FLUX_MODEL", str(MODELS_DIR) + "/flux/flux1-schnell-q4.gguf")
LTX_MODEL = os.environ.get("CORTEXAGENT_LTX_MODEL", str(MODELS_DIR) + "/ltx/ltx-video-q4.gguf")
MAIN_MODEL = os.environ.get("CORTEXAGENT_MODEL", "")
MAIN_PORT = int(os.environ.get("CORTEXAGENT_PORT", "8080"))
GEN_PORT = 8083
PROXY_PORT = int(os.environ.get("CORTEXAGENT_PROXY_PORT", "8081"))
LOG_DIR = Path.home() / ".cortexagent" / "logs"


def _log(msg: str) -> None:
    print(f"[model_switcher] {msg}", file=sys.stderr)


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port."""
    try:
        result = subprocess.run(
            ["ss", "-ltnp"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if f":{port} " in line:
                import re
                m = re.search(r'pid=(\d+)', line)
                if m:
                    pid = int(m.group(1))
                    os.kill(pid, signal.SIGTERM)
                    _log(f"Killed pid {pid} on port {port}")
                    time.sleep(1)
    except Exception as e:
        _log(f"Error killing port {port}: {e}")


def _wait_for_port(port: int, timeout: int = 60) -> bool:
    """Wait until a service is listening on the port."""
    for _ in range(timeout):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _start_llama(model: str, port: int, alias: str = "flux") -> Optional[int]:
    """Start llama-server with the given model on the given port."""
    if not Path(model).exists():
        _log(f"Model not found: {model}")
        return None

    server_bin = Path(LLAMA_DIR) / "bin" / "llama-server"
    if not server_bin.exists():
        _log(f"llama-server not found at {server_bin}")
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"llama-{alias}.log"

    cmd = [
        str(server_bin),
        "-m", model,
        "-c", "4096",  # small context for image gen
        "-ngl", "999",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]

    _log(f"Starting {alias} on port {port}...")
    with open(log_file, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)

    if _wait_for_port(port, timeout=120):
        _log(f"{alias} ready (pid {proc.pid})")
        return proc.pid
    else:
        _log(f"{alias} failed to start")
        proc.kill()
        return None


def _stop_process(pid: int) -> None:
    """Stop a process by PID."""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
    except ProcessLookupError:
        pass


def _swap_and_generate(model: str, alias: str, endpoint: str,
                       payload: dict, output: str) -> bool:
    """Kill main model, load gen model, generate, unload, restore."""
    _log(f"Swapping to {alias}...")

    # 1. Kill main model and proxy
    _kill_port(MAIN_PORT)
    _kill_port(PROXY_PORT)
    time.sleep(2)

    # 2. Start gen model
    gen_pid = _start_llama(model, GEN_PORT, alias=alias)
    if gen_pid is None:
        _log(f"Failed to start {alias}")
        return False

    # 3. Generate
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{GEN_PORT}{endpoint}",
            data=data, method="POST",
        )
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
            img_data = result.get("data", [{}])[0].get("b64_json", "")
            if img_data:
                import base64
                Path(output).write_bytes(base64.b64decode(img_data))
                _log(f"Output saved to {output}")
            else:
                _log("No data in response")
                return False
    except Exception as e:
        _log(f"Generation failed: {e}")
        return False
    finally:
        _stop_process(gen_pid)
        _kill_port(GEN_PORT)
        time.sleep(1)

    _log(f"{alias} unloaded. Restart cortexagent to resume coding.")
    return True


def gen_image(prompt: str, output: str = "output.png") -> bool:
    """Generate an image using Flux Schnell (4-step)."""
    return _swap_and_generate(
        model=FLUX_MODEL,
        alias="flux",
        endpoint="/v1/image/generate",
        payload={"prompt": prompt, "n_predict": 128, "size": "512x512"},
        output=output,
    )


def gen_video(prompt: str, output: str = "output.mp4") -> bool:
    """Generate a video using LTX-Video (fast, with audio)."""
    return _swap_and_generate(
        model=LTX_MODEL,
        alias="ltx",
        endpoint="/v1/video/generate",
        payload={"prompt": prompt, "n_predict": 256, "size": "512x512", "audio": True},
        output=output,
    )


def status() -> dict:
    """Check what models are loaded."""
    result = {"main_model": False, "flux_model": False, "heartbeat": False}

    # Check main model
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/health")
        with urllib.request.urlopen(req, timeout=2):
            result["main_model"] = True
    except Exception:
        pass

    # Check Flux
    try:
        req = urllib.request.Request("http://127.0.0.1:8083/health")
        with urllib.request.urlopen(req, timeout=2):
            result["flux_model"] = True
    except Exception:
        pass

    # Check heartbeat (Ollama)
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            result["heartbeat"] = any("qwen2.5:0.5b" in m["name"] for m in data.get("models", []))
    except Exception:
        pass

    return result


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "gen-image":
        if len(sys.argv) < 3:
            print("Usage: model_switcher.py gen-image 'prompt' [--output file.png]")
            return 1
        prompt = sys.argv[2]
        output = "output.png"
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output = sys.argv[idx + 1]
        ok = gen_image(prompt, output)
        return 0 if ok else 1

    elif cmd == "gen-video":
        if len(sys.argv) < 3:
            print("Usage: model_switcher.py gen-video 'prompt' [--output file.mp4]")
            return 1
        prompt = sys.argv[2]
        output = "output.mp4"
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output = sys.argv[idx + 1]
        ok = gen_video(prompt, output)
        return 0 if ok else 1

    elif cmd == "status":
        s = status()
        print(f"Main model:  {'RUNNING' if s['main_model'] else 'STOPPED'}")
        print(f"Flux model:  {'RUNNING' if s['flux_model'] else 'STOPPED'}")
        print(f"Heartbeat:   {'RUNNING' if s['heartbeat'] else 'STOPPED'}")
        return 0

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
