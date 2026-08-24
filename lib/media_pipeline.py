#!/usr/bin/env python3

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


REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                 str(Path.home() / ".cortexagent")))
QUEUE_FILE = STATE_DIR / "overseer_queue.json"
LOG_FILE = STATE_DIR / "logs" / "media_pipeline.log"






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
        "vram_gb": 4.0,
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


    _instance: Optional["MediaPipeline"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._tasks: List[Dict] = []
        self._results: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._initialized = True



    def detect_media_request(self, prompt: str) -> Optional[Dict]:

        lower = prompt.lower()


        if any(kw in lower for kw in [
            "generate image", "create an image", "draw", "picture of",
            "image of", "make an image", "image gen", "img:",
        ]):
            support = _check_model_support("image")
            if not support["supported"]:
                return None
            return {"type": "image", "model": MODELS["image"], "prompt": prompt}


        if any(kw in lower for kw in [
            "generate video", "create a video", "animation", "video of",
            "make a video", "video gen", "anim:",
        ]):
            support = _check_model_support("video")
            if not support["supported"]:
                return None
            return {"type": "video", "model": MODELS["video"], "prompt": prompt}

        return None

    def detect_text_request(self, prompt: str) -> bool:

        media = self.detect_media_request(prompt)
        return media is None



    def _swap_to(self, model: Dict) -> bool:

        engine = model.get("engine")
        if engine == "diffusers":
            return _check_model_support(
                "video" if model["type"] == "video" else "image")["supported"]
        if engine == "llama_server":
            return Path(model["path"]).exists()
        return False

    def _swap_to_main(self) -> bool:
               return True



    def _generate_image(self, prompt: str) -> Optional[Dict]:

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



    def submit(self, prompt: str, model_type: str = "auto") -> Dict:

        task_id = f"T-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self._tasks)}"


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


        result = self._process_task(task)

        with self._lock:
            self._results[task_id] = result

        return result

    def submit_async(self, prompt: str, model_type: str = "auto",
                     callback: Optional[Callable] = None) -> str:

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



    def _process_task(self, task: Dict) -> Dict:

        task_id = task["id"]
        prompt = task["prompt"]
        gen_type = task["type"]

        _log(f"Task {task_id}: processing [{gen_type}] {prompt[:60]}...", "🔄")

        result = {"task_id": task_id, "type": gen_type}


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


            if gen_type == "image":
                gen_result = self._generate_image(prompt)
            else:
                gen_result = self._generate_video(prompt)
            result.update(gen_result)


            result["swap_out"] = "pending"
            swapped_back = self._swap_to_main()
            result["swap_out"] = {
                "status": "success" if swapped_back else "failed",
                "message": "Restored main model" if swapped_back else "Main model restore failed",
            }

        else:

            result["swap_in"] = "skipped"
            result["swap_out"] = "skipped"
            gen_result = self._generate_text(prompt)
            result.update(gen_result)

        result["status"] = gen_result.get("status", "completed")
        _log(f"Task {task_id}: {result.get('status', 'done')}",
             "✅" if result.get("status") == "completed" else "❌")

        return result



    def status(self) -> Dict:

        with self._lock:
            tasks = list(self._tasks)
            results = dict(self._results)

        return {
            "total_tasks": len(tasks),
            "completed": len([t for t in tasks if t.get("status") in ("completed", "failed")]),
            "tasks": tasks[-20:],
            "recent_results": dict(list(results.items())[-10:]),
        }

    def list_models(self) -> List[Dict]:

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

        with self._lock:
            self._tasks.clear()
            self._results.clear()




def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {emoji} {msg}", file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass




def main():

    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    pipeline = MediaPipeline()

    if cmd == "run":

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
