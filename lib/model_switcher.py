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

# ── Colors ────────────────────────────────────────────────────────────────
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"


def _log(msg: str, emoji: str = "", color: str = "") -> None:
    prefix = f"{color}{emoji} {BOLD}heartbeat{RST} {DIM}{color}|{RST}"
    print(f"{prefix} {color}{msg}{RST}", file=sys.stderr)


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
                    _log(f"Killed process on port {port} (pid {pid})", "🛑", YELLOW)
                    time.sleep(1)
    except Exception as e:
        _log(f"Error killing port {port}: {e}", "⚠️", RED)


def _wait_for_port(port: int, timeout: int = 60) -> bool:
    """Wait until a service is listening on the port."""
    for i in range(timeout):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        if i % 10 == 0 and i > 0:
            _log(f"Still waiting for port {port}... ({i}s)", "⏳", YELLOW)
        time.sleep(1)
    return False


def _start_llama(model: str, port: int, alias: str = "flux") -> Optional[int]:
    """Start llama-server with the given model on the given port."""
    if not Path(model).exists():
        _log(f"Model not found: {model}", "❌", RED)
        return None

    server_bin = Path(LLAMA_DIR) / "bin" / "llama-server"
    if not server_bin.exists():
        _log(f"llama-server not found at {server_bin}", "❌", RED)
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"llama-{alias}.log"

    cmd = [
        str(server_bin),
        "-m", model,
        "-c", "4096",
        "-ngl", "999",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]

    _log(f"Loading {alias} model into VRAM...", "📦", CYAN)
    with open(log_file, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)

    if _wait_for_port(port, timeout=120):
        _log(f"{alias} model ready (pid {proc.pid})", "✅", GREEN)
        return proc.pid
    else:
        _log(f"{alias} model failed to load", "❌", RED)
        proc.kill()
        return None


def _stop_process(pid: int) -> None:
    """Stop a process by PID."""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
    except ProcessLookupError:
        pass


def _restore_main_model() -> bool:
    """Restart the main coding model and grammar proxy after generation."""
    _log("Restoring main coding model...", "🔄", CYAN)

    # Find the main model path from env or default
    model = MAIN_MODEL
    if not model:
        # Try to find the default model
        default = Path(MODELS_DIR) / "qwen3.6-35b-iq3s" / "Qwen3.6-35B-A3B-UD-IQ3_S.gguf"
        if default.exists():
            model = str(default)
        else:
            _log("No main model configured (set CORTEXAGENT_MODEL)", "❌", RED)
            return False

    main_pid = _start_llama(model, MAIN_PORT, alias="cortexagent")
    if main_pid is None:
        return False

    # Start grammar proxy
    _log("Starting grammar proxy...", "🔗", CYAN)
    proxy_script = Path(__file__).resolve().parent / "grammar_proxy.py"
    if proxy_script.exists():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        proxy_log = LOG_DIR / "proxy.log"
        subprocess.Popen(
            ["python3", str(proxy_script), str(PROXY_PORT)],
            stdout=open(proxy_log, "a"), stderr=subprocess.STDOUT,
        )
        time.sleep(2)
        _log("Grammar proxy ready", "✅", GREEN)
    else:
        _log(f"grammar_proxy.py not found at {proxy_script}", "⚠️", YELLOW)

    _log("Main coding model restored — you can resume using cortexagent", "🚀", GREEN)
    return True


def _swap_and_generate(model: str, alias: str, endpoint: str,
                       payload: dict, output: str) -> bool:
    """Kill main model, load gen model, generate, unload, restore."""
    # Safety check: model must exist
    if not Path(model).exists():
        _log(f"Model not found: {model}", "❌", RED)
        _log(f"Download it first, then try again.", "📥", YELLOW)
        return False

    _log(f"Preparing to generate with {alias}...", "🎯", MAGENTA)
    _log(f"Prompt: {payload.get('prompt', '')[:100]}", "💬", DIM)

    # 1. Kill main model and proxy
    _log("Unloading main coding model to free VRAM...", "🛑", YELLOW)
    _kill_port(MAIN_PORT)
    _kill_port(PROXY_PORT)
    _log("VRAM freed — main model unloaded", "✅", GREEN)
    time.sleep(1)

    # 2. Start gen model
    _log(f"Loading {alias} into VRAM...", "📦", CYAN)
    gen_pid = _start_llama(model, GEN_PORT, alias=alias)
    if gen_pid is None:
        _log(f"Failed to load {alias}", "❌", RED)
        _restore_main_model()
        return False

    # 3. Generate
    _log(f"Generating... (this may take a moment)", "🎨", MAGENTA)
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
                _log(f"Output saved to {output}", "💾", GREEN)
            else:
                _log("No data in response", "⚠️", YELLOW)
                return False
    except Exception as e:
        _log(f"Generation failed: {e}", "❌", RED)
        return False
    finally:
        _log(f"Unloading {alias} from VRAM...", "🛑", YELLOW)
        _stop_process(gen_pid)
        _kill_port(GEN_PORT)
        _log(f"{alias} unloaded", "✅", GREEN)
        time.sleep(1)

    # 4. Restore main model automatically
    _restore_main_model()
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
    result = {"main_model": False, "gen_model": False, "heartbeat": False}

    try:
        req = urllib.request.Request("http://127.0.0.1:8080/health")
        with urllib.request.urlopen(req, timeout=2):
            result["main_model"] = True
    except Exception:
        pass

    try:
        req = urllib.request.Request("http://127.0.0.1:8083/health")
        with urllib.request.urlopen(req, timeout=2):
            result["gen_model"] = True
    except Exception:
        pass

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
        print(f"Gen model:   {'RUNNING' if s['gen_model'] else 'STOPPED'}")
        print(f"Heartbeat:   {'RUNNING' if s['heartbeat'] else 'STOPPED'}")
        return 0

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
