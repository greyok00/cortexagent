#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple









PREFERRED_IMAGE_MODELS = ["sd_xl_base_1.0.safetensors",
                          "v1-5-pruned-emaonly.safetensors"]
DEFAULT_IMAGE_MODEL = "v1-5-pruned-emaonly.safetensors"
DEFAULT_VIDEO_MODEL = "Lightricks/LTX-Video"
DEFAULT_IMAGE_W, DEFAULT_IMAGE_H = 3840, 2160
DEFAULT_VIDEO_W, DEFAULT_VIDEO_H = 3840, 2160
UPSCALER = os.environ.get("CORTEXAGENT_UPSCALER", "lanczos").lower()




NATIVE_MP = {"sdxl": 2.07, "sd15": 0.60, "ltx": 0.59}

NATIVE_MP["sdxl"] = float(os.environ.get("CORTEXAGENT_SDXL_NATIVE_MP",
                                          NATIVE_MP["sdxl"]))
NATIVE_MP["sd15"] = float(os.environ.get("CORTEXAGENT_SD15_NATIVE_MP",
                                          NATIVE_MP["sd15"]))
NATIVE_MP["ltx"] = float(os.environ.get("CORTEXAGENT_LTX_NATIVE_MP",
                                         NATIVE_MP["ltx"]))

CHECKPOINT_DIR = os.environ.get(
    "CORTEXAGENT_CHECKPOINT_DIR",
    str(Path.home() / "ComfyUI" / "models" / "checkpoints"))
DEVICE = os.environ.get("CORTEXAGENT_DIFFUSION_DEVICE", "cuda")
CUDNN = os.environ.get("CORTEXAGENT_DIFFUSION_CUDNN", "0").lower() in (
    "1", "true", "yes", "on")


def _ckpt_complete(path: Path) -> bool:

    if not path.exists() or path.suffix.lower() != ".safetensors":
        return path.exists()
    try:
        import struct, json
        key = (str(path), path.stat().st_mtime, path.stat().st_size)
        cached = _CKPT_CACHE.get(key)
        if cached is not None:
            return cached
        with open(path, "rb") as f:
            (hlen,) = struct.unpack("<Q", f.read(8))
            hdr = json.loads(f.read(hlen))
        max_end = 0
        for v in hdr.values():
            if isinstance(v, dict) and "data_offsets" in v:
                max_end = max(max_end, v["data_offsets"][1])
        ok = (8 + hlen + max_end) == path.stat().st_size
        _CKPT_CACHE[key] = ok
        return ok
    except Exception:
        return False


_CKPT_CACHE: dict = {}


def _resolve_image_model() -> str:

    m = os.environ.get("CORTEXAGENT_IMAGE_MODEL")
    if m:
        return os.path.basename(m) if ("/" in m or "\\" in m) else m
    legacy = os.environ.get("CORTEXAGENT_FLUX_MODEL", "")
    if legacy and legacy.lower().endswith(".safetensors"):
        return os.path.basename(legacy)

    for cand in PREFERRED_IMAGE_MODELS:
        p = Path(CHECKPOINT_DIR) / cand
        if _ckpt_complete(p):
            return cand
    return DEFAULT_IMAGE_MODEL


def _resolve_image_path() -> Optional[Path]:

    name = _resolve_image_model()
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    cand = Path(CHECKPOINT_DIR) / name
    return cand if cand.exists() else None


def _resolve_video_model() -> str:

    m = os.environ.get("CORTEXAGENT_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL


    legacy = os.environ.get("CORTEXAGENT_LTX_MODEL", "")
    if legacy and not os.environ.get("CORTEXAGENT_VIDEO_MODEL"):
        lp = Path(legacy)
        if lp.suffix.lower() == ".safetensors" or lp.is_dir():
            m = legacy
    return m


def _video_is_hf_repo(model: str) -> bool:

    return "/" in model and not Path(model).exists()


def _hf_repo_cached(repo_id: str) -> bool:

    if "/" not in repo_id:
        return False
    cache_root = os.environ.get("HUGGINGFACE_HUB_CACHE",
                                str(Path.home() / ".cache" / "huggingface" / "hub"))
    repo_dir = Path(cache_root) / ("models--" + repo_id.replace("/", "--"))
    snap = repo_dir / "snapshots"
    return snap.is_dir() and any(snap.iterdir())


def _detect_kind(ckpt_name: str) -> str:

    n = ckpt_name.lower()
    if "sd_xl" in n or "sdxl" in n or "xl-base" in n:
        return "sdxl"
    return "sd15"


def _defaults_for(ckpt_name: str) -> Tuple[int, int, int, float]:

    if _detect_kind(ckpt_name) == "sdxl":
        return DEFAULT_IMAGE_W, DEFAULT_IMAGE_H, 40, 7.0
    return DEFAULT_IMAGE_W, DEFAULT_IMAGE_H, 30, 8.0


def _native_gen_size(target_w: int, target_h: int, kind: str) -> Tuple[int, int]:

    cap_mp = NATIVE_MP.get(kind, 1.0)
    if target_w * target_h <= cap_mp * 1e6:

        return (target_w - target_w % 32) or 32, (target_h - target_h % 32) or 32
    scale = (cap_mp * 1e6 / (target_w * target_h)) ** 0.5
    nw = max(32, (round(target_w * scale / 32)) * 32)
    nh = max(32, (round(target_h * scale / 32)) * 32)

    while nw * nh > cap_mp * 1e6 * 1.02:
        nw = max(32, nw - 32)
    return nw, nh


def _upscale(img, target_w: int, target_h: int):

    if img.size == (target_w, target_h):
        return img
    if UPSCALER == "realesrgan":
        try:
            return _upscale_realesrgan(img, target_w, target_h)
        except Exception as e:
            _log(f"realesrgan upscaler unavailable ({e}); using lanczos",
                 "⚠️", YELLOW)
    import cv2, numpy as np
    arr = np.array(img)
    if arr.ndim == 2:
        arr = cv2.resize(arr, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    else:
        arr = cv2.resize(arr[:, :, ::-1], (target_w, target_h),
                         interpolation=cv2.INTER_LANCZOS4)[:, :, ::-1]
    from PIL import Image
    return Image.fromarray(arr)


def _upscale_realesrgan(img, target_w: int, target_h: int):

    import cv2, numpy as np
    from PIL import Image
    global _ESRGAN
    if _ESRGAN is None:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        import torch
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                        num_block=23, num_grow_ch=32, scale=4)
        _ESRGAN = RealESRGANer(
            scale=4, model_path="RealESRGAN_x4plus.pth", model=model,
            tile=0, tile_pad=10, pre_pad=0, half=torch.cuda.is_available())
    arr = np.array(img)[:, :, ::-1]
    out, _ = _ESRGAN.enhance(arr, outscale=max(target_w / img.size[0],
                                              target_h / img.size[1]))
    out = cv2.resize(out, (target_w, target_h),
                     interpolation=cv2.INTER_LANCZOS4)[:, :, ::-1]
    return Image.fromarray(out)


_ESRGAN = None



CYAN, GREEN, YELLOW, RED, MAGENTA, DIM = (
    "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[35m", "\033[2m")
BOLD, RST = "\033[1m", "\033[0m"


def _log(msg: str, emoji: str = "", color: str = "") -> None:
    prefix = f"{color}{emoji} {BOLD}diffusion{RST} {DIM}{color}|{RST}"
    print(f"{prefix} {color}{msg}{RST}", file=sys.stderr)



_TORCH_OK: Optional[bool] = None


def _torch():

    global _TORCH_OK
    import torch
    if not CUDNN:


        torch.backends.cudnn.enabled = False
    _TORCH_OK = True
    return torch


def _torch_available() -> bool:

    if _TORCH_OK is True:
        return True
    if _TORCH_OK is False:
        return False
    try:
        import torch  # noqa: F401
        return bool(torch.cuda.is_available())
    except Exception:
        return False



_PIPES: dict = {}
_PIPE_KIND: dict = {}


def _image_pipe_key(ckpt_path: Path) -> str:
    return f"img:{ckpt_path}"


def _get_image_pipe(ckpt_path: Path):

    key = _image_pipe_key(ckpt_path)
    if key in _PIPES:
        return _PIPES[key]
    torch = _torch()
    from diffusers import (StableDiffusionPipeline,
                          StableDiffusionXLPipeline)
    kind = _detect_kind(ckpt_path.name)
    cls = StableDiffusionXLPipeline if kind == "sdxl" else StableDiffusionPipeline
    _log(f"loading {kind} from {ckpt_path.name} (fp16, {DEVICE})…",
         "📦", CYAN)
    t0 = time.time()
    pipe = cls.from_single_file(str(ckpt_path), torch_dtype=torch.float16)
    pipe = pipe.to(DEVICE)




    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass
    try:
        pipe.enable_vae_slicing()
        pipe.enable_vae_tiling()
    except Exception:
        pass
    _log(f"loaded in {time.time()-t0:.1f}s | peak VRAM "
         f"{torch.cuda.max_memory_allocated()/1e9:.2f} GB", "✅", GREEN)
    _PIPES[key] = pipe
    _PIPE_KIND[key] = "image"
    return pipe


def _get_video_pipe():

    key = "video:ltx"
    if key in _PIPES:
        return _PIPES[key]
    torch = _torch()
    from diffusers import LTXPipeline
    model = _resolve_video_model()
    offload = os.environ.get("CORTEXAGENT_VIDEO_OFFLOAD", "1").lower() in (
        "1", "true", "yes", "on")
    _log(f"loading LTX-Video ({'HF ' + model if _video_is_hf_repo(model) else model}, "
         f"bf16, {DEVICE}, offload={offload})…", "🎬", CYAN)
    t0 = time.time()
    kwargs = dict(torch_dtype=torch.bfloat16)
    if _video_is_hf_repo(model):
        pipe = LTXPipeline.from_pretrained(model, **kwargs)
    else:

        pipe = LTXPipeline.from_pretrained(model, **kwargs)




    offloaded = False
    if offload:
        if hasattr(pipe, "enable_group_offload"):
            try:
                pipe.enable_group_offload(onload_device=torch.device(DEVICE))
                _log("group offload enabled (fits 16 GB alongside the big model)", "💾", DIM)
                offloaded = True
            except Exception as e:
                _log(f"group offload failed ({e}); trying model_cpu_offload", "⚠️", YELLOW)
        if not offloaded and hasattr(pipe, "enable_model_cpu_offload"):
            try:
                pipe.enable_model_cpu_offload()
                _log("model CPU offload enabled", "💾", DIM)
                offloaded = True
            except Exception as e:
                _log(f"model_cpu_offload failed ({e}); full GPU load", "⚠️", YELLOW)
    if not offloaded:
        pipe = pipe.to(DEVICE)
    _log(f"loaded in {time.time()-t0:.1f}s | peak VRAM "
         f"{torch.cuda.max_memory_allocated()/1e9:.2f} GB", "✅", GREEN)
    _PIPES[key] = pipe
    _PIPE_KIND[key] = "video"
    return pipe


def unload() -> None:

    global _PIPES
    for p in _PIPES.values():
        try:
            del p
        except Exception:
            pass
    _PIPES = {}
    _PIPE_KIND.clear()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass



def is_running(timeout: float = 2) -> bool:

    if not _torch_available():
        return False
    return _resolve_image_path() is not None


def gen_image(prompt: str, output: str = "output.png",
              model: Optional[str] = None, width: Optional[int] = None,
              height: Optional[int] = None, steps: Optional[int] = None,
              cfg: Optional[float] = None, seed: Optional[int] = None,
              negative: str = "", timeout: int = 600) -> bool:

    ckpt_name = model or _resolve_image_model()

    if model and Path(model).is_absolute():
        ckpt_path = Path(model) if Path(model).exists() else None
    elif model:
        ckpt_path = (Path(CHECKPOINT_DIR) / model
                     if (Path(CHECKPOINT_DIR) / model).exists() else None)
    else:
        ckpt_path = _resolve_image_path()
    if ckpt_path is None or not ckpt_path.exists():
        _log(f"checkpoint not found: {ckpt_name} in {CHECKPOINT_DIR}", "❌", RED)
        return False

    dw, dh, ds, dcfg = _defaults_for(ckpt_path.name)
    width = int(width or os.environ.get("CORTEXAGENT_IMAGE_WIDTH") or dw)
    height = int(height or os.environ.get("CORTEXAGENT_IMAGE_HEIGHT") or dh)
    steps = int(steps or os.environ.get("CORTEXAGENT_IMAGE_STEPS") or ds)
    cfg = float(cfg or os.environ.get("CORTEXAGENT_IMAGE_CFG") or dcfg)
    seed = int(seed) if seed is not None else (int(time.time()) % (2**32))

    kind = _detect_kind(ckpt_path.name)
    nat_w, nat_h = _native_gen_size(width, height, kind)
    upscale_needed = (nat_w, nat_h) != (width, height)

    _log(f"txt2img  ckpt={ckpt_path.name}  native={nat_w}x{nat_h}"
         f"{' → upscale to '+str(width)+'x'+str(height) if upscale_needed else ''}"
         f"  steps={steps}  cfg={cfg}  seed={seed}  cudnn={'on' if CUDNN else 'off'}",
         "🎨", MAGENTA)
    _log(f"prompt: {prompt[:120]}", "💬", DIM)

    try:
        pipe = _get_image_pipe(ckpt_path)
        t0 = time.time()
        out = pipe(prompt=prompt, negative_prompt=negative or None,
                  num_inference_steps=steps, guidance_scale=cfg,
                  height=nat_h, width=nat_w, generator=None)
        img = out.images[0]
    except Exception as e:
        _log(f"image generation failed: {e}", "❌", RED)
        return False

    if upscale_needed:
        try:
            img = _upscale(img, width, height)
        except Exception as e:
            _log(f"upscale failed ({e}); saving native {nat_w}x{nat_h}",
                 "⚠️", YELLOW)

    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    try:
        import torch
        vram = torch.cuda.max_memory_allocated() / 1e9
    except Exception:
        vram = 0.0
    _log(f"generated in {time.time()-t0:.1f}s | saved {out_path} "
         f"({out_path.stat().st_size//1024} KB) | peak VRAM {vram:.2f} GB",
         "💾", GREEN)
    return True


def gen_video(prompt: str, output: str = "output.mp4",
              model: Optional[str] = None, width: Optional[int] = None,
              height: Optional[int] = None, steps: Optional[int] = None,
              cfg: Optional[float] = None, seed: Optional[int] = None,
              negative: str = "", timeout: int = 1200) -> bool:

    if model:
        os.environ["CORTEXAGENT_VIDEO_MODEL"] = model
    vid_model = _resolve_video_model()


    if _video_is_hf_repo(vid_model):
        cached = _hf_repo_cached(vid_model)
        if not cached:
            _log(f"LTX-Video ({vid_model}) not in HF cache yet. First run "
                 f"downloads it (~few GB). Set CORTEXAGENT_VIDEO_MODEL to a local "
                 f"path, or run gen-video once to fetch.", "🎬", YELLOW)
            return False
    else:
        if not Path(vid_model).exists():
            _log(f"video model path not found: {vid_model}", "❌", RED)
            return False

    width = int(width or os.environ.get("CORTEXAGENT_VIDEO_WIDTH") or DEFAULT_VIDEO_W)
    height = int(height or os.environ.get("CORTEXAGENT_VIDEO_HEIGHT") or DEFAULT_VIDEO_H)


    nat_w, nat_h = _native_gen_size(width, height, "ltx")
    upscale_needed = (nat_w, nat_h) != (width, height)
    frames = int(os.environ.get("CORTEXAGENT_VIDEO_FRAMES") or 161)
    frames = frames - ((frames - 1) % 8)
    steps = int(steps or os.environ.get("CORTEXAGENT_VIDEO_STEPS") or 20)
    cfg = float(cfg or os.environ.get("CORTEXAGENT_VIDEO_CFG") or 3.0)
    seed = int(seed) if seed is not None else (int(time.time()) % (2**32))
    fps = int(os.environ.get("CORTEXAGENT_VIDEO_FPS") or 24)

    _log(f"txt2video  model={vid_model}  native={nat_w}x{nat_h}"
         f"{' → frame-upscale to '+str(width)+'x'+str(height) if upscale_needed else ''}"
         f"  frames={frames}  steps={steps}  cfg={cfg}  seed={seed}", "🎬", MAGENTA)
    _log(f"prompt: {prompt[:120]}", "💬", DIM)

    try:
        pipe = _get_video_pipe()
        t0 = time.time()
        out = pipe(prompt=prompt, negative_prompt=negative or None,
                   num_frames=frames, height=nat_h, width=nat_w,
                   num_inference_steps=steps, guidance_scale=cfg)
        frames_list = out.frames[0]
    except Exception as e:
        _log(f"video generation failed: {e}", "❌", RED)
        return False

    if upscale_needed:
        _log(f"upscaling {len(frames_list)} frames to {width}x{height}…",
             "⏳", CYAN)
        try:
            frames_list = [_upscale(fr, width, height) for fr in frames_list]
        except Exception as e:
            _log(f"frame upscale failed ({e}); encoding native {nat_w}x{nat_h}",
                 "⚠️", YELLOW)

    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    saved = _export_video(frames_list, str(out_path), fps)
    if not saved:
        _log("failed to encode mp4 (install imageio/imageio-ffmpeg, or ffmpeg)",
             "❌", RED)
        return False
    try:
        import torch
        vram = torch.cuda.max_memory_allocated() / 1e9
    except Exception:
        vram = 0.0
    _log(f"generated in {time.time()-t0:.1f}s | saved {out_path} "
         f"({out_path.stat().st_size//1024} KB) | peak VRAM {vram:.2f} GB",
         "💾", GREEN)
    return True


def _export_video(frames, path: str, fps: int) -> bool:

    try:
        from diffusers.utils import export_to_video
        export_to_video(frames, path, fps=fps)
        return Path(path).exists() and Path(path).stat().st_size > 0
    except Exception as e:
        _log(f"export_to_video unavailable ({e}); trying ffmpeg+pil", "⚠️", DIM)
    try:
        import tempfile
        from PIL import Image
        tmp = Path(tempfile.mkdtemp(prefix="ca-ltx-"))
        for i, fr in enumerate(frames):
            fr.save(tmp / f"f{i:05d}.png")
        import subprocess
        r = subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "f%05d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
            capture_output=True, timeout=300)
        return Path(path).exists() and Path(path).stat().st_size > 0
    except Exception as e:
        _log(f"ffmpeg encode failed: {e}", "❌", RED)
        return False


def status() -> dict:

    img_name = _resolve_image_model()
    img_path = _resolve_image_path()
    vid_model = _resolve_video_model()
    cuda_ok = _torch_available()
    video_cached = False
    if _video_is_hf_repo(vid_model):
        video_cached = _hf_repo_cached(vid_model)
    else:
        video_cached = Path(vid_model).exists()
    return {
        "diffusers_ready": cuda_ok and img_path is not None,
        "device": DEVICE if cuda_ok else "unavailable",
        "cuda": cuda_ok,
        "cudnn_enabled": CUDNN,
        "checkpoint_dir": CHECKPOINT_DIR,
        "image_model": img_name,
        "image_kind": _detect_kind(img_name),
        "image_model_path": str(img_path) if img_path else "",
        "image_model_exists": img_path is not None,
        "video_model": vid_model,
        "video_cached": video_cached,
        "loaded_pipes": list(_PIPES.keys()),

        "comfyui_running": cuda_ok and img_path is not None,
        "host": "in-process",
        "port": 0,
        "dir": CHECKPOINT_DIR,
    }



def _cli() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "status":
        print(json.dumps(status(), indent=2))
        s = status()
        return 0 if s["diffusers_ready"] else 1
    if cmd == "unload":
        unload()
        print("unloaded all diffusion pipelines")
        return 0
    if cmd in ("gen-image", "image"):
        prompt, out = "", "output.png"
        for i, a in enumerate(sys.argv[2:], start=2):
            if a in ("-p", "--prompt") and i + 1 < len(sys.argv):
                prompt = sys.argv[i + 1]
            elif a in ("-o", "--output") and i + 1 < len(sys.argv):
                out = sys.argv[i + 1]
            elif a in ("-m", "--model") and i + 1 < len(sys.argv):
                os.environ["CORTEXAGENT_IMAGE_MODEL"] = sys.argv[i + 1]
            elif a in ("-W", "--width") and i + 1 < len(sys.argv):
                os.environ["CORTEXAGENT_IMAGE_WIDTH"] = sys.argv[i + 1]
            elif a in ("-H", "--height") and i + 1 < len(sys.argv):
                os.environ["CORTEXAGENT_IMAGE_HEIGHT"] = sys.argv[i + 1]
            elif a in ("-s", "--steps") and i + 1 < len(sys.argv):
                os.environ["CORTEXAGENT_IMAGE_STEPS"] = sys.argv[i + 1]
        if not prompt:
            print("usage: diffusion_backend gen-image -p PROMPT [-o out.png]",
                  file=sys.stderr)
            return 1
        return 0 if gen_image(prompt, output=out) else 1
    if cmd in ("gen-video", "video"):
        prompt, out = "", "output.mp4"
        for i, a in enumerate(sys.argv[2:], start=2):
            if a in ("-p", "--prompt") and i + 1 < len(sys.argv):
                prompt = sys.argv[i + 1]
            elif a in ("-o", "--output") and i + 1 < len(sys.argv):
                out = sys.argv[i + 1]
        if not prompt:
            print("usage: diffusion_backend gen-video -p PROMPT [-o out.mp4]",
                  file=sys.stderr)
            return 1
        return 0 if gen_video(prompt, output=out) else 1
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_cli())