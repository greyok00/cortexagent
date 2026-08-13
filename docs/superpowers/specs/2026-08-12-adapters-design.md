# CortexAgent — Step 4: Multimodal Adapters Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

Part of the SlimToken orchestration layer (see
`2026-08-12-slimtoken-orchestration-design.md`). This spec designs **step 4**:
the multimodal adapters that convert image / audio / document input to plain
text, so the text-only overseer model can reason about them.

---

## 1. Goal

The overseer model (LFM2.5-1.2B) is text-only. Any non-text input must be
converted to text *before* it enters the ReAct loop. Three adapters, all CPU:

| Adapter | Tool | Model | Converts |
|---|---|---|---|
| Image | `describe_image` | Moondream 2 (0.5B) | image → caption / VQA answer |
| Audio | `transcribe_audio` | faster-whisper `small` | audio → transcript |
| Document | `parse_document` | Docling (fallback: pdftotext) | PDF/DOCX/PPTX/XLSX/scanned → text |

All run on **CPU** (GPU stays reserved for the big model). All are
lazy-loaded singletons — no model loads until first use. Their output feeds
the same text pipeline: the ReAct loop reasons over it, and `ingest_domain`
(step 3) can store it in a domain DB.

---

## 2. Architecture

```
ReAct loop (overseer :8082)
   │  tool_calls
   ▼
Tool registry
   ├── describe_image(image, prompt?)  → lib/image_adapter.py   (Moondream, CPU)
   ├── transcribe_audio(file)          → lib/stt.py             (faster-whisper, CPU)
   └── parse_document(file)            → lib/document_adapter.py (Docling → pdftotext)
   │
   ▼
plain text → back into the loop → (optionally) ingest_domain → domain DB
```

- **In-process, not sidecar.** Lazy-loaded singletons (same pattern as
  `lib/diffusion_backend.py` and `lib/stt.py`). No separate service process
  to manage — simpler, matches the codebase style.
- **CPU forced** — `device="cpu"` / `compute_type="int8"` everywhere. torch
  must not grab CUDA.

---

## 3. Image adapter — `lib/image_adapter.py`

```python
class ImageAdapter:
    """Moondream 2 (0.5B) via transformers, CPU, lazy singleton."""

    def describe(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        """Caption or answer a VQA prompt about the image."""

    def point(self, image_path: str, object: str) -> str:
        """Return normalized coordinates of an object (Moondream pointing)."""
```

- Model: `vikhyatk/moondream2` (~0.5B, ~1.7GB fp16 / ~900MB int8), loaded via
  `transformers` + `torch` (both installed), `device="cpu"`.
- Downloaded on first use to `~/.cache/huggingface/` (one-time).
- `describe` = captioning / VQA. `point` = object localization (returns
  normalized x,y coords) — useful for "where is X in this image".
- **Backend note:** the big model (:8080) is natively multimodal. A
  configurable backend (`moondream` CPU default | `big` native) is reserved
  in the tool schema, but Moondream is the default per the user's adapter
  directive. The overseer can't see images itself, so it needs the text.

### 3.1 `describe_image` tool

```json
{
  "name": "describe_image",
  "description": "Describe an image or answer a question about it (returns text)",
  "parameters": {
    "type": "object",
    "properties": {
      "image": {"type": "string", "description": "path to the image file"},
      "prompt": {"type": "string", "description": "caption request or VQA question"}
    },
    "required": ["image"]
  }
}
```

---

## 4. Audio adapter — reuse `lib/stt.py`

`lib/stt.py` already exists (created 2026-08-12, uncommitted): faster-whisper
`small` (~487MB), CPU, `compute_type="int8"`, lazy singleton. The
`transcribe_audio` tool wraps its `transcribe()`:

```python
# lib/stt.py (existing)
def transcribe(audio) -> str: ...   # faster-whisper, CPU

# tool handler
def _transcribe_audio(file: str) -> dict:
    text = stt.transcribe(file)
    return {"ok": bool(text), "output": text, "error": None}
```

### 4.1 `transcribe_audio` tool

```json
{
  "name": "transcribe_audio",
  "description": "Transcribe an audio file to text (faster-whisper, CPU)",
  "parameters": {
    "type": "object",
    "properties": {
      "file": {"type": "string", "description": "path to the audio file"}
    },
    "required": ["file"]
  }
}
```

No new model, no new engine — the STT work already chose faster-whisper
`small`. This tool is the pipeline entry point for audio *files* (the STT
daemon handles live mic input separately).

---

## 5. Document adapter — `lib/document_adapter.py`

```python
def parse_document(file: str) -> dict:
    """Extract text from a document. Docling if installed, else fallbacks."""
```

| Format | Primary (Docling) | Fallback |
|---|---|---|
| PDF | Docling (tables, reading order, OCR for scans) | `pdftotext -layout` (via `lib/pdf_knowledge.py`, binary present) |
| DOCX / PPTX / XLSX | Docling | `python-docx` / `python-pptx` / `openpyxl` if present, else error |
| Web page | — | `lib/fast_extract.py` (brave_fetch) |

- **Docling is optional.** It's a heavy install (pulls torch, transformers,
  easyocr, onnxruntime). The adapter imports it lazily; if missing, it falls
  back to `pdftotext` for PDFs. This keeps the adapter functional with zero
  new deps, and Docling upgrades it when installed.
- **Scanned PDFs** (no text layer) need OCR — Docling's OCR path, or
  `tesseract` if present. Fallback: return the pdftotext result (possibly
  empty) + a note that OCR is unavailable.

### 5.1 `parse_document` tool

```json
{
  "name": "parse_document",
  "description": "Extract text from a document (PDF/DOCX/PPTX/XLSX/scanned)",
  "parameters": {
    "type": "object",
    "properties": {
      "file": {"type": "string", "description": "path to the document"}
    },
    "required": ["file"]
  }
}
```

---

## 6. Tool registration

The three stubs registered in step 1 (`describe_image`, `transcribe_audio`,
`parse_document`) get real handlers via `register_tool`:

```python
from lib.tool_registry import register_tool
from lib import image_adapter, stt, document_adapter

register_tool("describe_image",   DESCRIBE_IMAGE_SCHEMA,   image_adapter.describe)
register_tool("transcribe_audio", TRANSCRIBE_AUDIO_SCHEMA, stt.transcribe)
register_tool("parse_document",   PARSE_DOCUMENT_SCHEMA,   document_adapter.parse_document)
```

The ReAct loop (step 2) can then call them like any other tool. Their text
output flows back into the loop, and the loop can call `ingest_domain`
(step 3) to store extracted knowledge.

---

## 7. Error handling

| Failure | Behavior |
|---|---|
| Model not downloaded | Auto-download on first use (one-time); log + retry |
| torch tries to grab CUDA | Forced `device="cpu"`; assert no CUDA in smoke test |
| Unsupported image format | Return error; loop feeds it back to the model |
| Audio decode failure | faster-whisper error → return error; loop recovers |
| Docling missing | Fall back to pdftotext (PDFs) — adapter still works |
| Scanned PDF, no OCR | Return pdftotext result (possibly empty) + "OCR unavailable" note |
| Adapter model load OOM (system RAM) | Lazy singleton unloads on failure; log; next call retries |

**Fallback rule:** every adapter degrades gracefully. Image → error text.
Audio → error text. Document → pdftotext. The loop treats adapter errors as
observations and recovers.

---

## 8. Testing

| Test | What it proves |
|---|---|
| `lib/image_adapter.py --smoke` | Describes a bundled sample image → non-empty caption; asserts CPU (no CUDA) |
| `lib/stt.py --test` | Transcribes a generated sample wav → non-empty text (already in STT design) |
| `lib/document_adapter.py --smoke` | Parses a sample PDF → non-empty text via pdftotext fallback |
| `describe_image` tool | Registry call describes an image end-to-end |
| `transcribe_audio` tool | Registry call transcribes a wav end-to-end |
| `parse_document` tool | Registry call parses a PDF end-to-end |
| Adapter → ingest_domain | Parse a doc, ingest the text into a domain DB, search finds it |
| Smoke gate | `cortexagent doctor` + `tests/run_smoke.py` extended |

---

## 9. Files

| File | Change |
|---|---|
| `lib/image_adapter.py` | NEW — Moondream 2 via transformers, CPU, lazy singleton |
| `lib/document_adapter.py` | NEW — Docling (optional) + pdftotext fallback |
| `lib/stt.py` | EXISTS (uncommitted) — wire `transcribe_audio` handler to it |
| `lib/tool_registry.py` | FILL `describe_image` / `transcribe_audio` / `parse_document` stubs |
| `tests/run_smoke.py` | ADD adapter checks |
| `docs/superpowers/specs/2026-08-10-daily-changelog.md` | ADD row |

---

## 10. Out of scope (later steps)

- Domain-DB search polish + ingestion job library (step 5).
- Android accessibility (Phase 2).
- Florence-2 (structured grounding) — Moondream covers captioning + VQA +
  pointing; Florence-2 is a later enhancement if bounding-box/OCR grounding
  is needed.
- Docling install — optional upgrade, not a step-4 blocker (pdftotext
  fallback covers PDFs).

---

## 11. Tracking

- This file = `docs/superpowers/specs/2026-08-12-adapters-design.md`
- Master spec = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
