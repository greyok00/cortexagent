#!/usr/bin/env python3
"""MediaPipeline — background media-generation orchestrator for CortexAgent.

Handles image/video generation in the background. The CLI session stays stable
— no restart, no disconnect.

Flow:
  1. Detect media request (image/video) from task queue or user prompt
  2. Ensure the diffusers backend is ready (in-process, same CUDA device)
  3. Execute generation task through lib.diffusion_backend
  4. Report result back to session

The main LLM (Qwen3.6) stays loaded the whole time — image/video no longer
swap into the LLM slot (that was broken; llama-server can't host diffusion).
diffusion runs **in-process** via HuggingFace diffusers on the same GPU; the
daemon's idle-unload still governs the big LLM.

Models:
  - 🧠 Main:    Qwen3.6-35B  (14.3 GB VRAM) — llama-server port 8080 (proxy :8081)
  - 🎨 Image:   SD 1.5 / SDXL via diffusers (in-process, fp16)
  - 🎬 Video:   LTX-Video via diffusers (HF repo, group-offloaded to fit 16 GB)

Usage:
    from lib.media_pipeline import MediaPipeline
    pipeline = MediaPipeline()

    # Register a task and let it run in the background
    result = pipeline.submit("Generate image: a zebra in a pink sweater",
                             model_type="image", prompt="zebra pink sweater")

    # Or use the CLI
    # python3 media_pipeline.py run --type image --prompt "zebra in pink sweater"
    # python3 media_pipeline.py run --type video --prompt "wave animation"
    # python3 media_pipeline.py status
    # python3 media_pipeline.py models
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                 str(Path.home() / ".cortexagent")))
QUEUE_FILE = STATE_DIR / "overseer_queue.json"
LOG_FILE = STATE_DIR / "logs" / "media_pipeline.log"

# ── Model Configuration ──────────────────────────────────────────────────────
# Image/video no longer swap into the LLM slot — they run in-process through
# HuggingFace diffusers via lib.diffusion_backend (#28 fix: llama-server can't
# host diffusion). "main" stays on llama-server; the daemon owns its lifecycle
# + idle unload. diffusion shares the same CUDA device (managed VRAM budget).
from lib import diffusion_backend as _db  # noqa: E402

MODELS = {
    "main": {
        "name": "Qwen3.6-35B",
        "emoji": "🧠",
        "path": str(Path.home() / "models/qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf"),
        "vram_gb": 14.3,
        "type": "llm",
        "engine": "llama_server",
        "port": 8080,
    },
    "image": {
        "name": "Stable Diffusion (diffusers)",
        "emoji": "🎨",
        "path": "checkpoint (see CORTEXAGENT_IMAGE_MODEL)",
        "vram_gb": 4.0,   # SD 1.5 default; SDXL ~8
        "type": "image",
        "engine": "diffusers",
    },
    "video": {
        "name": "LTX-Video (diffusers)",
        "emoji": "🎬",
        "path": "HF repo Lightricks/LTX-Video (see CORTEXAGENT_VIDEO_MODEL)",
        "vram_gb": 10.0,
        "type": "video",
        "engine": "diffusers",
    },
}


def _check_model_support(model_key: str) -> dict:
    """Check if a model is actually usable (file/backend available)."""
    model = MODELS[model_key]
    info = {"exists": True, "tools": []}
    st = _db.status()

    if model_key == "image":
        ready = st["diffusers_ready"]
        info["tools"].append("diffusers" if ready else None)
        info["supported"] = ready
        info["missing"] = (
            None if ready else
            f"diffusers backend not ready — torch+CUDA available + a checkpoint "
            f"in {st['checkpoint_dir']} (set CORTEXAGENT_IMAGE_MODEL)")
    elif model_key == "video":
        ready = st["cuda"] and st["video_cached"]
        info["tools"].append("diffusers" if ready else None)
        info["supported"] = ready
        info["missing"] = (
            None if ready else
            f"LTX-Video ({st['video_model']}) not cached yet — run gen-video "
            f"once to download it, or set CORTEXAGENT_VIDEO_MODEL to a local "
            f"path. Needs torch+CUDA.")
    elif model_key == "main":
        info["supported"] = True
        info["tools"] = ["llama_server"]
    return info

class MediaPipeline:
    """Background orchestrator for model-swapping media generation.

    Manages the full lifecycle: detect request → swap model → generate →
    swap back → report. Runs in background without disrupting the CLI session.
    """

    def __init__(self):
        self._tasks: List[Dict] = []
        self._results: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # ── Detection ──────────────────────────────────────────────────────────

    def detect_media_request(self, prompt: str) -> Optional[Dict]:
        """Detect if a prompt requires image or video generation.

        Returns task info dict or None for text-only tasks.
        """
        lower = prompt.lower()

        # Image generation patterns
        if any(kw in lower for kw in [
            "generate image", "create an image", "draw", "picture of",
            "image of", "make an image", "image gen", "img:",
        ]):
            support = _check_model_support("image")
            if not support["supported"]:
                return None  # Not available
            return {"type": "image", "model": MODELS["image"], "prompt": prompt}

        # Video generation patterns
        if any(kw in lower for kw in [
            "generate video", "create a video", "animation", "video of",
            "make a video", "video gen", "anim:",
        ]):
            support = _check_model_support("video")
            if not support["supported"]:
                return None  # Not available
            return {"type": "video", "model": MODELS["video"], "prompt": prompt}

        return None

    def detect_text_request(self, prompt: str) -> bool:
        """Check if prompt is a text/LLM request (not media)."""
        media = self.detect_media_request(prompt)
        return media is None

    # ── Model Swapping ─────────────────────────────────────────────────────

    def _swap_to(self, model: Dict) -> bool:
        """Prepare the target media backend.

        Image/video run in-process through diffusers (no LLM slot swap). For
        ``diffusers`` engines this just checks the backend can resolve a model;
        the main LLM stays loaded. The daemon's idle-unload still governs the
        big model.
        """
        engine = model.get("engine")
        if engine == "diffusers":
            return _check_model_support(
                "video" if model["type"] == "video" else "image")["supported"]
        if engine == "llama_server":
            return Path(model["path"]).exists()
        return False

    def _swap_to_main(self) -> bool:
        """Main model stays resident — nothing to swap back to."""
        return True

    # ── Generation ─────────────────────────────────────────────────────────

    def _generate_image(self, prompt: str) -> Optional[Dict]:
        """Generate an image via the diffusers backend (in-process)."""
        out_path = str(Path.home() / "media" / "images" /
                       f"img_{int(time.time())}.png")
        try:
            if _db.gen_image(prompt, output=out_path):
                return {
                    "status": "completed",
                    "message": f"Image generated: {out_path}",
                    "output": out_path,
                }
            return {
                "status": "failed",
                "message": ("Image generation failed — is the diffusers backend "
                            "ready? (torch+CUDA + a checkpoint in "
                            f"{_db.CHECKPOINT_DIR}; set CORTEXAGENT_IMAGE_MODEL)"),
            }
        except Exception as e:
            return {"status": "error", "message": f"Image generation error: {e}"}

    def _generate_video(self, prompt: str) -> Optional[Dict]:
        """Generate a video via the diffusers backend (LTX-Video, in-process).

        Needs the LTX-Video model cached (HF repo Lightricks/LTX-Video by
        default — downloaded on first gen-video run) or a local path via
        CORTEXAGENT_VIDEO_MODEL. GGUF is incompatible with diffusers.
        """
        out_path = str(Path.home() / "media" / "video" /
                       f"vid_{int(time.time())}.mp4")
        try:
            if _db.gen_video(prompt, output=out_path):
                return {
                    "status": "completed",
                    "message": f"Video generated: {out_path}",
                    "output": out_path,
                }
            return {
                "status": "not_available",
                "message": (
                    "Video gen needs the LTX-Video model cached "
                    f"({_db._resolve_video_model()}) — run gen-video once to "
                    "download it, or set CORTEXAGENT_VIDEO_MODEL to a local "
                    "path. GGUF is incompatible with diffusers."),
                "prompt": prompt,
            }
        except Exception as e:
            return {"status": "error", "message": f"Video generation error: {e}"}

    def _generate_text(self, prompt: str) -> Optional[Dict]:
        """Generate text using main model via llama-server (grammar proxy :8081)."""
        try:
            proxy_port = int(os.environ.get("CORTEXAGENT_PROXY_PORT", "8081"))
            req = urllib.request.Request(
                f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
                data=json.dumps({
                    "model": "cortexagent",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1024,
                    "temperature": 0.7,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                return {
                    "status": "completed",
                    "message": result["choices"][0]["message"]["content"],
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Generation failed: {e}",
            }

    # ── Task Submission ────────────────────────────────────────────────────

    def submit(self, prompt: str, model_type: str = "auto") -> Dict:
        """Submit a task for background processing.

        Args:
            prompt: The task prompt (e.g., "Generate image: a zebra")
            model_type: "auto", "image", "video", or "text"

        Returns:
            Dict with task_id, status, and initial result (sync).
            For async background processing, use submit_async().
        """
        task_id = f"T-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self._tasks)}"

        # Determine model type
        if model_type == "auto":
            media = self.detect_media_request(prompt)
            model_type = media["type"] if media else "text"

        task = {
            "id": task_id,
            "prompt": prompt,
            "type": model_type,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        with self._lock:
            self._tasks.append(task)

        # Execute inline for now (async via thread available)
        result = self._process_task(task)

        with self._lock:
            self._results[task_id] = result

        return result

    def submit_async(self, prompt: str, model_type: str = "auto",
                     callback: Optional[Callable] = None) -> str:
        """Submit a task for background processing (non-blocking).

        Returns task_id immediately. Callback fires when complete.
        """
        task_id = f"T-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self._tasks)}"

        task = {
            "id": task_id,
            "prompt": prompt,
            "type": model_type,
            "status": "queued",
            "created_at": datetime.now().isoformat(),
        }

        with self._lock:
            self._tasks.append(task)

        def _run():
            try:
                result = self._process_task(task)
                with self._lock:
                    self._results[task_id] = result
                if callback:
                    callback(task_id, result)
            except Exception as e:
                result = {"status": "error", "message": str(e)}
                with self._lock:
                    self._results[task_id] = result
                if callback:
                    callback(task_id, result)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return task_id

    # ── Processing ─────────────────────────────────────────────────────────

    def _process_task(self, task: Dict) -> Dict:
        """Process a single task: swap model, generate, swap back, report."""
        task_id = task["id"]
        prompt = task["prompt"]
        gen_type = task["type"]

        _log(f"Task {task_id}: processing [{gen_type}] {prompt[:60]}...", "🔄")

        result = {"task_id": task_id, "type": gen_type}

        # Step 1: Swap to target model
        if gen_type in ("image", "video"):
            model_key = "image" if gen_type == "image" else "video"
            model = MODELS[model_key]

            result["swap_in"] = "pending"
            swapped = self._swap_to(model)
            result["swap_in"] = {
                "status": "success" if swapped else "failed",
                "message": f"Loaded {model['name']}" if swapped else "Model swap unavailable",
            }

            if not swapped:
                result["status"] = "not_available"
                sup = _check_model_support(model_key)
                result["message"] = (
                    f"{model['name']} not available. "
                    f"{sup.get('missing') or 'backend not ready'}"
                )
                self._swap_to_main()
                return result

            # Step 2: Generate
            if gen_type == "image":
                gen_result = self._generate_image(prompt)
            else:
                gen_result = self._generate_video(prompt)
            result.update(gen_result)

            # Step 3: Swap back
            result["swap_out"] = "pending"
            swapped_back = self._swap_to_main()
            result["swap_out"] = {
                "status": "success" if swapped_back else "failed",
                "message": "Restored main model" if swapped_back else "Main model restore failed",
            }

        else:
            # Text generation — no swap needed
            result["swap_in"] = "skipped"
            result["swap_out"] = "skipped"
            gen_result = self._generate_text(prompt)
            result.update(gen_result)

        result["status"] = gen_result.get("status", "completed")
        _log(f"Task {task_id}: {result.get('status', 'done')}",
             "✅" if result.get("status") == "completed" else "❌")

        return result

    # ── Status ─────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        """Get pipeline status."""
        with self._lock:
            tasks = list(self._tasks)
            results = dict(self._results)

        return {
            "total_tasks": len(tasks),
            "completed": len([t for t in tasks if t.get("status") in ("completed", "failed")]),
            "tasks": tasks[-20:],  # last 20
            "recent_results": dict(list(results.items())[-10:]),
        }

    def list_models(self) -> List[Dict]:
        """List configured models and their availability."""
        models = []
        for key, model in MODELS.items():
            support = _check_model_support(key)
            models.append({
                "key": key,
                "name": f"{model['emoji']} {model['name']}",
                "vram_gb": model["vram_gb"],
                "file": model["path"],
                "exists": support["exists"],
                "supported": support["supported"],
                "engine": model["engine"],
                "tools": support.get("tools", []),
                "missing": support.get("missing"),
            })
        return models

    def reset(self) -> None:
        """Clear all tasks and results."""
        with self._lock:
            self._tasks.clear()
            self._results.clear()


# ── Logging ──────────────────────────────────────────────────────────────────

def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {emoji} {msg}", file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for MediaPipeline."""
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    pipeline = MediaPipeline()

    if cmd == "run":
        # python3 media_pipeline.py run --type image --prompt "a cat"
        model_type = "auto"
        prompt = " ".join(sys.argv[2:])
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                model_type = sys.argv[idx + 1]
                prompt = " ".join(sys.argv[idx + 2:])
        result = pipeline.submit(prompt, model_type=model_type)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "completed" else 1

    elif cmd == "status":
        print(json.dumps(pipeline.status(), indent=2))
        return 0

    elif cmd == "models":
        for m in pipeline.list_models():
            status = "✅" if m["exists"] and m["supported"] else "❌"
            print(f"  {status} {m['name']} — {m['vram_gb']}GB VRAM "
                  f"[{m['engine']}] {'exists' if m['exists'] else 'MISSING'}")
        return 0

    elif cmd == "detect":
        # python3 media_pipeline.py detect "generate image of a zebra"
        prompt = " ".join(sys.argv[2:])
        detection = pipeline.detect_media_request(prompt)
        if detection:
            print(json.dumps({
                "is_media": True,
                "type": detection["type"],
                "model": detection["model"]["name"],
            }, indent=2))
        else:
            print(json.dumps({"is_media": False, "type": "text"}, indent=2))
        return 0

    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
