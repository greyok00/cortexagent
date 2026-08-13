#!/usr/bin/env python3
"""lib/domain_embed.py — all-MiniLM-L6-v2 embeddings via onnxruntime.

Lazy singleton: no model loads until the first embed call. Model + tokenizer
files are expected at ~/.cortexagent/models/all-MiniLM-L6-v2/ (downloaded on
first use, one-time ~90MB). Runs on GPU when the VRAM budget allows (see
lib/vram.py) and onnxruntime has a CUDA provider; otherwise CPU. The GPU is
never taken from the required residents (big model, overseer, whisper) — the
budget is free VRAM minus the locked buffer, so when the big model is loaded
the embedder silently stays on CPU.

Usage:
  python3 lib/domain_embed.py --smoke
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402
from lib import vram  # noqa: E402

MODEL_DIR = CFG.state_dir / "models" / "all-MiniLM-L6-v2"
_BASE = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"
_FILES = {
    "model.onnx": f"{_BASE}/onnx/model.onnx",
    "tokenizer.json": f"{_BASE}/tokenizer.json",
    "config.json": f"{_BASE}/config.json",
    "tokenizer_config.json": f"{_BASE}/tokenizer_config.json",
    "special_tokens_map.json": f"{_BASE}/special_tokens_map.json",
}
EMBED_DIM = 384
MAX_SEQ = 256
# VRAM the GPU path may reserve: the onnxruntime CUDA arena is capped at this
# via gpu_mem_limit (default would be 2GB — enough to evict the big model's
# headroom). The budget check uses the same number so the GPU path only
# engages when there is real headroom and never starves a required resident.
EMBED_VRAM_MB = 512


def _ensure_cuda_libs() -> None:
    """Preload the nvidia-cudnn pip package's libs so onnxruntime-gpu works.

    onnxruntime-gpu needs cuDNN 9 at load time, but the nvidia-cudnn wheel
    installs it under site-packages where the dynamic loader never looks.
    Setting LD_LIBRARY_PATH mid-process is useless (the loader reads it at
    startup), so the libs are loaded explicitly via ctypes in dependency
    order; onnxruntime's dlopen then finds them already resident. No-op when
    the package is absent (CPU-only install).
    """
    try:
        import ctypes
        import importlib.util
        spec = importlib.util.find_spec("nvidia.cudnn")
        if not (spec and spec.submodule_search_locations):
            return
        d = Path(list(spec.submodule_search_locations)[0]) / "lib"
        if not d.is_dir():
            return
        # Stub first, then the versioned impls it dlopens.
        for name in ("libcudnn.so.9", "libcudnn_ops.so.9", "libcudnn_cnn.so.9",
                     "libcudnn_adv.so.9", "libcudnn_graph.so.9",
                     "libcudnn_heuristic.so.9",
                     "libcudnn_engines_precompiled.so.9",
                     "libcudnn_engines_runtime_compiled.so.9"):
            p = d / name
            if p.is_file():
                ctypes.CDLL(str(p))
    except Exception:
        pass


class DomainEmbedder:
    """Lazy all-MiniLM-L6-v2 embedder (tokenizers + onnxruntime, CPU). Singleton."""

    _instance: Optional["DomainEmbedder"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_loaded"):
            self._sess = None
            self._tok = None
            self._loaded = False

    def _ensure_downloaded(self) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        for name, url in _FILES.items():
            target = MODEL_DIR / name
            if target.exists() and target.stat().st_size > 0:
                continue
            # Download to a temp file and atomically rename on success — a
            # partial or corrupt download never persists as the final file,
            # so a retry re-downloads instead of choking on a bad onnx.
            part = MODEL_DIR / (name + ".part")
            print(f"[domain_embed] downloading {name}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
                    shutil.copyfileobj(r, f)
                if part.stat().st_size == 0:
                    raise OSError(f"downloaded {name} is empty")
                os.replace(part, target)
            except BaseException:
                part.unlink(missing_ok=True)
                raise

    def _load(self) -> None:
        if self._loaded:
            return
        self._ensure_downloaded()
        _ensure_cuda_libs()
        import numpy as np  # noqa: F401
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self._tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        self._tok.enable_truncation(max_length=MAX_SEQ)
        self._tok.enable_padding(pad_id=0, pad_token="[PAD]")
        # GPU only when the budget allows AND onnxruntime has a CUDA provider
        # (onnxruntime-gpu installed). Otherwise CPU — never evict a resident.
        providers = ["CPUExecutionProvider"]
        provider_options = [{}]
        if vram.can_fit(EMBED_VRAM_MB):
            try:
                if "CUDAExecutionProvider" in ort.get_available_providers():
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    # Cap the CUDA arena so the embedder never reserves the
                    # default 2GB — that would starve the big model.
                    provider_options = [{"gpu_mem_limit": EMBED_VRAM_MB * 1024 * 1024}, {}]
            except Exception:
                pass
        self._sess = ort.InferenceSession(
            str(MODEL_DIR / "model.onnx"), providers=providers,
            provider_options=provider_options)
        self._loaded = True

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch-embed texts → list of 384-dim L2-normalized vectors."""
        self._load()
        import numpy as np
        enc = self._tok.encode_batch([t or " " for t in texts])
        input_ids = np.array([e.ids for e in enc], dtype=np.int64)
        attn = np.array([e.attention_mask for e in enc], dtype=np.int64)
        ttype = np.zeros_like(input_ids)
        out = self._sess.run(["last_hidden_state"], {
            "input_ids": input_ids, "attention_mask": attn,
            "token_type_ids": ttype})[0]
        mask = attn[:, :, None].astype(np.float32)
        emb = (out * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
        emb = emb / np.clip(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9, None)
        return emb.tolist()


_EMBEDDER = DomainEmbedder()


def _smoke() -> int:
    fails = 0
    vec = _EMBEDDER.embed("CortexAgent overseer is running")
    if len(vec) != EMBED_DIM:
        print(f"❌ embed dim {len(vec)} != {EMBED_DIM}")
        fails += 1
    import numpy as np
    n = float(np.linalg.norm(vec))
    if not (0.99 < n < 1.01):
        print(f"❌ embed not L2-normalized: {n}")
        fails += 1
    batch = _EMBEDDER.embed_batch(["a", "b", "c"])
    if len(batch) != 3 or any(len(v) != EMBED_DIM for v in batch):
        print("❌ embed_batch shape")
        fails += 1
    sim = float(np.dot(vec, _EMBEDDER.embed("CortexAgent overseer is running")))
    if sim < 0.99:
        print(f"❌ same-text similarity too low: {sim}")
        fails += 1
    print("domain_embed smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/domain_embed.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
