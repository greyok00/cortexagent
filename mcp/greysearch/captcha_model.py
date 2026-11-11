#!/usr/bin/env python3
"""captcha_model.py - THE captcha classifier loader (per-prompt grid library).

The vendored weights are hcaptcha-challenger's per-prompt binary tile
classifiers (GPL-3.0, downloaded and used locally; never redistributed -
see models/SOURCE). They live in a flat library at models/hcaptcha/*.onnx,
one ~300 KB ResNet per challenge label ("cat2309.onnx", "dog.onnx", ...),
git-ignored like all weight files and fetched + sha256-verified by
install.sh's vendor_captcha_model step. The decompiled graph contract every
one of them obeyed in decompile probes (6 models sampled, identical):

    input  "input.1": float32[1, 3, 64, 64]   NCHW, RGB square
    output (name varies, e.g. "78"): float32[1, 2]   raw 2-class logits

Decision rule (read off upstream behavior and confirmed on their own
ground-truth tile set, 40 tiles, 40/40 correct): tile matches the challenge
prompt iff logits[0] > logits[1] - class 0 is "relevant". Preprocessing is
NOT embedded in the graph (just a decode -> 64x64 squash -> /255); it lives
in models/FEATURIZER.py beside the weights.

One loader interface, unchanged shape: load_classifier(device) -> classifier
with .classify(images, prompt) -> 0-based tile picks. classify() matches the
challenge prompt to a library model (prompt-to-filename matching over the
on-disk stems - upstream's label aliases live in their own tree, so ours is
a fresh implementation, see _match_model_for_prompt), runs each tile through
that model one 64x64 frame at a time, and returns the argmax-positive
indices bounded by the tile count. A prompt with no library model answers
None, and missing models / missing onnxruntime / failed session init all
return None - the solver's ladder falls through and the lane skips honestly;
nothing here ever raises into a page flow. CPUExecutionProvider is the
DEFAULT and the honest floor; the CUDA provider loads only when
GREYSEARCH_CAPTCHA_GPU is explicitly on AND the gpu is actually free
(gpu-natural-mode rule: the resident lane owns VRAM otherwise)."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("greysearch.captcha.model")

_LIBRARY_DIR = "hcaptcha"
_CPU = "CPUExecutionProvider"
_GPU = "CUDAExecutionProvider"

# Prompt-to-model matching helpers (see _match_model_for_prompt).
_NON_WORD = re.compile(r"[^a-z0-9]+")
_DATE_SUFFIX = re.compile(r"(\d{4,5})$")
_VARIANT_PREFIXES = ("nested_", "please_click_on_the_")


def install_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_model_dir() -> Optional[Path]:
    """The model LIBRARY location: GREYSEARCH_CAPTCHA_MODEL_PATH (now a
    directory - the per-prompt .onnx library, not one file) or, unset, the
    tree path models/hcaptcha. Location oracle only, like the single-file
    path it replaced - a nonexistent path is still the location (the lane's
    presence decisions go through has_model(), true PRESENCE)."""
    env = os.environ.get("GREYSEARCH_CAPTCHA_MODEL_PATH", "").strip()
    if env:
        return Path(env)
    return install_root() / "models" / _LIBRARY_DIR


def library_stems(directory: Optional[Path]) -> List[str]:
    """Sorted classifier stems (cat2309, dog, ...) present in a library
    directory. Absent or unreadable directory -> empty list, never raises."""
    if directory is None or not directory.is_dir():
        return []
    try:
        return sorted(p.stem for p in directory.glob("*.onnx"))
    except OSError:
        return []


def has_model() -> bool:
    """True only when weights actually sit on disk in the library - true
    PRESENCE, never just the location (the ladder runs the cpu rung only
    when something can load)."""
    return bool(library_stems(resolve_model_dir()))


def gpu_free() -> bool:
    """True when nvidia-smi reports under half the VRAM in use; the tool
    missing or failing means NOT free - the GPU rung never guesses."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=5, text=True)
        line = (out.stdout or "").splitlines()
        if out.returncode != 0 or not line:
            return False
        used, total = line[0].split(",")
        return float(used) < 0.5 * float(total)
    except Exception:
        return False


def _gpu_loadable() -> bool:
    try:
        import onnxruntime as ort
        return _GPU in ort.get_available_providers()
    except Exception:
        return False


def _normalized_prompt(prompt: str) -> str:
    """"Please select all images containing a CAT." -> "please_select_all_
    images_containing_a_cat": lowercased, every non-word run collapsed to
    one underscore, trailing punctuation gone. Matching then works in
    underscore space with word boundaries, so "cat" cannot hit inside the
    word "catapult" while "cat_wearing_a_pirate_hat" still matches its
    full phrase."""
    text = (prompt or "").strip().lower()
    text = text.rstrip("!.?,;:")
    return _NON_WORD.sub("_", text).strip("_")


def _match_model_for_prompt(prompt: str,
                            stems: List[str]) -> Optional[str]:
    """Challenge prompt -> library stem, or None when no model speaks for
    it. Scored longest-phrase-first because a specific model must beat a
    generic one: "cat shaped cookie" in the prompt must pick the
    cat_shaped_cookie model over cat2309, and "largest cat" must reach
    nested_largest_cat2309 via its de-prefixed tail. A tie in phrase length
    prefers the DATED variant with the higher date (2310 over 2309 - newer
    training vintage, upstream's convention)."""
    norm = _normalized_prompt(prompt)
    if not norm:
        return None
    norm = f"_{norm}_"
    best: Optional[str] = None
    best_score: tuple = ()
    for stem in stems:
        base = _DATE_SUFFIX.sub("", stem.lower()).strip("_")
        if not base:
            base = stem.lower()
        keys = [base]
        for prefix in _VARIANT_PREFIXES:
            if base.startswith(prefix) and len(base) > len(prefix):
                # "nested_largest_cat" also speaks for a prompt that says
                # only "largest cat" - the model trains one label, the
                # prefix is challenge-shape bookkeeping.
                keys.append(base[len(prefix):])
        for key in keys:
            phrase = f"_{key}_"
            if phrase in norm:
                date = _DATE_SUFFIX.search(stem.lower())
                score = (len(key), int(date.group(1)) if date else 0)
                if score > best_score or best is None:
                    best, best_score = stem, score
                break
    return best


def load_classifier(device: str = "cpu") -> Optional[Any]:
    directory = resolve_model_dir()
    stems = library_stems(directory)
    if not stems:
        return None
    providers = [_CPU]
    if device == "gpu":
        if not (os.environ.get("GREYSEARCH_CAPTCHA_GPU", "").strip().lower()
                in ("1", "on", "true", "yes")
                and gpu_free() and _gpu_loadable()):
            return None
        providers = [_GPU, _CPU]
    try:
        import onnxruntime as ort
    except Exception as e:
        LOG.warning("captcha onnxruntime unavailable: %s", e)
        return None

    cache: dict = {}
    lock = threading.Lock()

    def _session(stem: str):
        with lock:
            sess = cache.get(stem)
            if sess is None:
                sess = ort.InferenceSession(
                    str(directory / f"{stem}.onnx"), providers=providers)
                cache[stem] = sess
            return sess

    class _Classifier:
        """Session-pool-backed classifier: classify(images, prompt) ->
        picks. One ort session per touched model, built lazily on first
        mention and reused for the ladder's later rounds."""

        @staticmethod
        def classify(images: List[bytes],
                     prompt: str) -> Optional[List[int]]:
            try:
                stem = _match_model_for_prompt(prompt, stems)
                if stem is None or not images:
                    # No model for this prompt: an honest miss, not an error
                    # - the ladder's next rung (or the skip record) decides.
                    return None
                return _run_stem(_session(stem), stem, images)
            except Exception as e:
                LOG.warning("captcha classify failed: %s", e)
                return None

    def _run_stem(sess: Any, stem: str, images: List[bytes]):
        """Every tile -> one [1,3,64,64] float frame through the featurizer,
        then one session run per tile (every library model pins a batch
        dimension of exactly 1). Tile i is picked iff logits[0] > logits[1]
        (decompiled graph semantics: class 0 = matches the prompt)."""
        rows = _featurize(images)
        in_name = sess.get_inputs()[0].name
        picks: List[int] = []

        def frame(row):
            """One flat 3x64x64 float row -> nested [[R][G][B]] 64x64
            planes, the shape the graph pins (batch 1, 3 planes, 64x64)."""
            return [
                [[row[p * 4096 + y * 64 + x] for x in range(64)]
                 for y in range(64)]
                for p in range(3)]

        for i, row in enumerate(rows):
            logits = sess.run(None, {in_name: [frame(row)]})[0][0]
            if float(logits[0]) > float(logits[1]):
                picks.append(i)
        return picks or None

    return _Classifier


def _featurize(images: List[bytes]) -> Any:
    """Bytes -> per-tile model input rows. The library documents its own
    preprocessing in models/FEATURIZER.py (vendored beside the weights)."""
    from models import FEATURIZER as _f  # vendored with the weights
    return _f.images_to_tensor(images)


# --------------------------------------------------------------------------
# The detection rung's vendored weights (models/yolo): YOLOv8 object
# detectors that answer COORDINATE challenges ("please click on the X" on
# one big image) with click POINTS on the boxes they find. See models/SOURCE
# for provenance; the decoding contract is documented in models/
# YOLO_FEATURIZER.py and the prompt-routing table rides in models/yolo/
# LABELS.yaml (upstream's ashes_of_war table, fetched + checksummed).
_YOLO_DIR = "yolo"

_KnobConf = "GREYSEARCH_CAPTCHA_YOLO_CONF"
_DEFAULT_CONF = 0.5            # upstream's own default threshold
_KnobMaxPoints = "GREYSEARCH_CAPTCHA_YOLO_MAX_POINTS"
_DEFAULT_MAX_POINTS = 8
_MASK_COEFFS = 32              # seg models carry 32 mask coefficients


def resolve_yolo_dir() -> Optional[Path]:
    """The detector weight directory: GREYSEARCH_CAPTCHA_YOLO_PATH or the
    tree path models/yolo. Location oracle only - presence is has_detector()."""
    env = os.environ.get("GREYSEARCH_CAPTCHA_YOLO_PATH", "").strip()
    if env:
        return Path(env)
    return install_root() / "models" / _YOLO_DIR


def detector_stems(directory: Optional[Path]) -> List[str]:
    """Sorted detector stems on disk; absent directory -> empty. The seven
    generic yolov5/v6 models deliberately never route (their anchor-grid
    output layout is a different decode; they carry no challenge labels
    either - disclosed in models/YOLO_FEATURIZER's docstring and models/
    SOURCE)."""
    skip = ("yolov5m6", "yolov5n6", "yolov5s6", "yolov6n", "yolov6s",
            "yolov6t")
    out: List[str] = []
    if directory is None or not directory.is_dir():
        return out
    try:
        for p in sorted(directory.glob("*.onnx")):
            # the anchor-layout and unknown-semantics models stay vendored
            # inventory, never routed (disclosed in models/SOURCE)
            if p.stem in skip or p.stem.startswith("onclick"):
                continue
            out.append(p.stem)
    except OSError:
        return []
    return out


def _detector_label_table() -> Dict[str, List[str]]:
    """models/yolo/objects2023.yaml (upstream's OWN data file, fetched +
    sha256-verified like the weights - see models/SOURCE) -> its
    ashes_of_war section as {stem: [labels]}. Unreadable / malformed /
    absent table -> empty dict: the DETECTOR rung then never routes (honest
    miss), never a wrong answer."""
    path = resolve_yolo_dir() / "objects2023.yaml"
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        rows = doc.get("ashes_of_war") if isinstance(doc, dict) else None
        if not isinstance(rows, dict):
            return {}
        table: Dict[str, List[str]] = {}
        for stem, labels in rows.items():
            if (isinstance(stem, str) and isinstance(labels, list)
                    and all(isinstance(r, str) for r in labels)):
                table[stem.replace(".onnx", "")] = list(labels)
        return table
    except Exception:
        return {}


def has_detector() -> bool:
    """True when at least one detector weight AND its label table sit on
    disk - true PRESENCE for the ladder's routing decision."""
    return bool(_detector_label_table() and detector_stems(resolve_yolo_dir()))


# Challenge phrasings that the LABELS.yaml phrases cannot express alone.
# Each special label maps to the prompt phrasing that routes to it, as a
# regex over the normalized prompt (underscores for non-words). Derived
# from upstream's matching rules; the DIGIT variants add the spelled-out
# number words the prompts actually use.
_SPECIAL_PHRASES: Dict[str, str] = {
    "not-animal": r"not_a(n)?_animal",
    "x-eaten": r"can_(_)?be_(_)?eaten|could_(_)?be_(_)?eaten|can_i_eat",
    "can-run": r"can_(_)?run",
    "the-one-piece": r"appears_(_)?only_(_)?once",
    "animal-head": r"head_(_)?of_(_)?the_(_)?animal",
    "hexagon": r"hexagon",
    "spiral-center": r"spiral|spiral_pattern",
    "star-bricks": r"star(_with_a_texture_of_bricks)?",
}
_NUMBER_WORDS = {"2": "two", "9": "nine"}


def _bounded(phrase: str) -> str:
    """Anchor a phrase against the alnum edges of the normalized prompt:
    the prompt travels in underscore space, but "cup" must still not hit
    inside "buttercup"."""
    return r"(?<![a-z0-9])" + phrase + r"(?![a-z0-9])"


def _label_phrases(label: str) -> List[str]:
    """One LABELS.yaml label -> the prompt phrase regex(es) it routes to.
    Plain labels match themselves (word-boundary anchored); head labels
    ("cat-head") match "head of the cat" phrasing per upstream's head rule;
    digits match their spelled-out number word and the bare digit; the
    special labels in _SPECIAL_PHRASES carry the phrasing whose prompt can
    never contain the label itself ("can be eaten" -> "x-eaten")."""
    text = (label or "").strip().lower()
    if not text:
        return []
    if text in _SPECIAL_PHRASES:
        return [_bounded(_SPECIAL_PHRASES[text])]
    if text.endswith("-head"):
        animal = text[:-5]
        return [_bounded(f"head_(_)?of_(_)?(the_(_)?|a_(_)?){animal}")]
    if text in _NUMBER_WORDS:
        word = _NUMBER_WORDS[text]
        return [_bounded(f"number_(_)?({word}|{text})|digit_(_)?{text}")]
    plain = _NON_WORD.sub("_", text).strip("_")
    return [_bounded(plain)] if plain else []


# Stem suffixes stripped before a stem is allowed to speak for itself (the
# dated vintages and the architecture tags; "2312" in can_be_eaten_2312 is
# a date, not the label).
_STEM_TAIL = re.compile(r"(_?\d{4,5})?_?yolov8[snm]?$|(-seg)$")


def _stem_phrase(stem: str) -> Optional[str]:
    """Detector stem -> its derived routing phrase (can_be_eaten_2310 ->
    "can_be_eaten", treasurechest2309 -> "treasurechest": the architecture
    tags and dated vintages stripped, iteratively down to the words). The
    generic-only stems ("animal", "animalhead") mean no single phrase and
    route nothing; "animal_<species>" and "animalhead_<species>" reduce to
    the species (the challenge asks for the fox, the zebra, the turtle...).
    None when nothing meaningful remains."""
    base = stem.lower()
    while True:
        stripped = re.sub(r"_?yolov[56][a-z0-9]?$|_?yolov8[snm]?$", "",
                          base).strip("_")
        stripped = stripped.replace("-seg", "").strip("_-")
        stripped = _DATE_SUFFIX.sub("", stripped).strip("_")
        if stripped == base:
            break
        base = stripped
    species = re.match(r"animal(?:head)?_(.+)$", base)
    if species:
        return species.group(1)
    if base in ("", "animal", "animalhead"):
        return None
    return base


def detector_for_prompt(prompt: str) -> Optional[str]:
    """Challenge prompt -> detector stem via the vendored table + the
    special-phrase rules, longest-label-first with the dated vintage tie
    (same convention the grid library's matcher uses). No route -> None:
    the ladder's next rung decides."""
    norm = _normalized_prompt(prompt)
    if not norm or not norm.strip("_"):
        return None
    norm = f"_{norm}_"
    stems = detector_stems(resolve_yolo_dir())
    table = _detector_label_table()
    candidates: List[tuple] = []          # (score, vintage, stem)
    for stem in stems:
        # the vintage tiebreak: the dated training vintage lives inside the
        # stem ("can_be_eaten_2310"), ahead of the architecture tag
        date = re.search(r"\d{4,5}", stem.lower())
        vintage = int(date.group(0)) if date else 0
        matched = False
        for label in table.get(stem, []):
            for phrase in _label_phrases(label):
                if re.search(phrase, norm):
                    candidates.append((len(label), vintage, stem))
                    matched = True
                    break
        # stem-derived route for stems whose table labels (if any) did
        # not already speak for this prompt
        if not matched:
            phrase = _stem_phrase(stem)
            if phrase and f"_{phrase}_" in norm:
                candidates.append((0, vintage, stem))
    if not candidates:
        return None
    # longest label wins; ties go to the newest vintage, then the
    # alphabetically first stem for determinism
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2]))
    return candidates[0][2]


def _matched_labels(prompt: str, stem: str) -> List[str]:
    """The routing labels of a routed stem that the prompt actually
    phrase-matched (longest first): the class filter needs the prompt's
    own label, not just the model file. Stems that routed through their
    derived phrase (animal_fox -> "fox") return that phrase."""
    norm = _normalized_prompt(prompt)
    if not norm or not norm.strip("_"):
        return []
    norm = f"_{norm}_"
    table = _detector_label_table()
    hits: List[str] = []
    for label in table.get(stem, []):
        for phrase in _label_phrases(label):
            if re.search(phrase, norm):
                hits.append(label)
                break
    if hits:
        return sorted(set(hits), key=lambda s: (-len(s), s))
    phrase = _stem_phrase(stem)
    return [phrase] if phrase and f"_{phrase}_" in norm else []


def _parse_yolo_names(raw: str) -> Optional[Dict[int, str]]:
    """The 'names' metadata YOLOv8 exports carry (class id -> label) parsed
    into {id: lowercased label}: the per-model class map the prompt's
    label must meet before any box may be clicked. Any failure -> None -
    the filter stands down, disclosed, rather than guessing ids."""
    try:
        import ast
    except Exception:
        return None
    try:
        obj = ast.literal_eval(raw)
    except Exception:
        try:
            import json
            obj = json.loads(raw)
        except Exception:
            return None
    if isinstance(obj, (list, tuple)):
        obj = {i: v for i, v in enumerate(obj)}
    if not isinstance(obj, dict):
        return None
    out: Dict[int, str] = {}
    for k, v in obj.items():
        try:
            out[int(str(k).strip())] = str(v).strip().lower()
        except (TypeError, ValueError):
            return None
    return out


# The class filter's one-time disclosures: a missing or unmapped class id
# keeps the UNFILTERED behavior only in full daylight - logged once per
# model/label/cause, exactly because it is the less exact path.
_DISCLOSED: set = set()
_DISCLOSURE_LOCK = threading.Lock()


def _class_filter_disclosure(stem: str, labels: List[str], why: str) -> None:
    key = f"{stem}|{','.join(labels)}|{why}"
    with _DISCLOSURE_LOCK:
        if key in _DISCLOSED:
            return
        _DISCLOSED.add(key)
    LOG.warning(
        "detector class filter stands down for %s (labels [%s]): %s - "
        "surviving boxes are NOT class-filtered",
        stem, ", ".join(labels), why)


def _class_targets(prompt: str, stem: str, sess: Any,
                   names_for) -> Optional[set]:
    """Prompt + routed session -> the set of graph class ids the challenge
    actually asks for, from the graph's own 'names' metadata crossed with
    the labels the routing phrase-matched. None means the filter stands
    down (no parseable names, or no routed label maps to a class id, the
    "-head" neighbor tried once for stem-derived species labels) and the
    decode keeps the pre-filter behavior - each stand-down disclosed, never
    silent."""
    matched = _matched_labels(prompt, stem)
    names = None
    try:
        names = names_for(stem, sess)
    except Exception:
        names = None
    if names and matched:
        label2id = {lab: cid for cid, lab in names.items()}
        resolved: List[int] = []
        unresolved: List[str] = []
        for lab in matched:
            if lab in label2id:
                resolved.append(label2id[lab])
            elif (not lab.endswith("-head")
                  and f"{lab}-head" in label2id):
                resolved.append(label2id[f"{lab}-head"])
            else:
                unresolved.append(lab)
        if resolved:
            if unresolved:
                _class_filter_disclosure(
                    stem, unresolved, "labels with no class id in the "
                    "graph's names metadata (resolved ones still filtered)")
            return set(resolved)
        _class_filter_disclosure(
            stem, matched, "no routed label maps to a class id in the "
            "graph's names metadata")
        return None
    if names is None:
        _class_filter_disclosure(
            stem, matched or ["<no routed label>"],
            "the graph carries no parseable names metadata")
    else:
        _class_filter_disclosure(
            stem, matched or ["<no routed label>"],
            "routing matched no label to filter by")
    return None


def _threshold_conf() -> float:
    """The detection confidence knob: GREYSEARCH_CAPTCHA_YOLO_CONF (default
    0.5, upstream's own threshold); clamped to (0, 1)."""
    try:
        v = float(os.environ.get(_KnobConf, "").strip() or _DEFAULT_CONF)
    except (TypeError, ValueError):
        v = _DEFAULT_CONF
    return min(max(v, 0.01), 0.99)


def _max_points() -> int:
    try:
        v = int(os.environ.get(_KnobMaxPoints, "").strip()
                or _DEFAULT_MAX_POINTS)
    except (TypeError, ValueError):
        v = _DEFAULT_MAX_POINTS
    return max(1, min(v, 24))


def detector_providers(device: str = "cpu") -> Optional[List[str]]:
    return _providers_for(device)


def _providers_for(device: str) -> Optional[List[str]]:
    """Provider list shared by every loader (grid, detector, clip): 'cpu'
    is the floor; 'gpu' only when the flag, free VRAM and the runtime all
    agree - otherwise None, an honest refusal."""
    if device == "gpu":
        if not (_gpu_flag_on() and gpu_free() and _gpu_loadable()):
            return None
        return [_GPU, _CPU]
    return [_CPU]


def _gpu_flag_on() -> bool:
    return (os.environ.get("GREYSEARCH_CAPTCHA_GPU", "").strip().lower()
            in ("1", "on", "true", "yes"))


def load_detector(device: str = "cpu") -> Optional[Any]:
    """One detector handles all coordinate challenges: load_detector("cpu")
    -> {locate(image, prompt) -> normalized [(x, y), ...] points}. The
    route (detector_for_prompt) picks the weight per prompt; sessions are
    pooled lazily like the grid classifier's. Bad images, missing numpy,
    absent weights, GPU misuse - all honest None, never an exception into
    the page flow."""
    stems = detector_stems(resolve_yolo_dir())
    table = _detector_label_table()
    if not stems or not table:
        return None
    providers = _providers_for(device)
    if providers is None:
        return None
    try:
        import onnxruntime as ort
    except Exception as e:
        LOG.warning("captcha onnxruntime unavailable: %s", e)
        return None
    from models import YOLO_FEATURIZER

    directory = resolve_yolo_dir()
    cache: dict = {}
    names_cache: dict = {}
    lock = threading.Lock()

    def _names_for(stem: str, sess: Any) -> Optional[Dict[int, str]]:
        """The detector graph's own 'names' metadata (YOLOv8 exports carry
        class id -> label), parsed once per stem and pooled: the exact
        per-model class map the prompt filter crosses. None when the export
        carries none - the filter stands down, disclosed."""
        with lock:
            if stem in names_cache:
                return names_cache[stem]
            names = None
            try:
                raw = sess.get_modelmeta().custom_metadata_map.get("names")
                names = _parse_yolo_names(raw) if raw else None
            except Exception:
                names = None
            names_cache[stem] = names
            return names

    def _session(stem: str):
        with lock:
            if stem not in cache:
                if f"{stem}.onnx" not in {p.name for p in directory.glob("*.onnx")}:
                    cache[stem] = None
                else:
                    try:
                        cache[stem] = ort.InferenceSession(
                            str(directory / f"{stem}.onnx"), providers=providers)
                    except Exception as e:
                        LOG.warning("detector session %s failed: %s", stem, e)
                        cache[stem] = None
            return cache[stem]

    class _Detector:
        """locate(image, prompt) -> normalized click points (floats 0..1 in
        the image's OWN aspect, mapped through the same distortion the
        featurizer applied) or None for an honest miss."""

        @staticmethod
        def locate(image: bytes, prompt: str) -> Optional[List[tuple]]:
            try:
                if not image or not prompt:
                    return None
                stem = detector_for_prompt(prompt)
                if stem is None:
                    return None
                sess = _session(stem)
                if sess is None:
                    return None
                tensor = YOLO_FEATURIZER.images_to_tensor([image])
                if tensor is None:
                    return None
                decoded = _decode_boxes(
                    sess, stem, tensor,
                    _class_targets(prompt, stem, sess, _names_for))
                if decoded is None:
                    return None
                side = float(tensor.shape[-1])
                out: List[tuple] = []
                for box in decoded["boxes"]:          # xywh in INPUT pixels
                    cx = float(box[0]) / side         # distortion makes
                    cy = float(box[1]) / side         # this exact mapping
                    out.append((round(cx, 6), round(cy, 6)))
                return out[:_max_points()] or None
            except Exception as e:
                LOG.warning("detector locate failed: %s", e)
                return None

    def _decode_boxes(sess: Any, stem: str, tensor: "Any",
                      targets: Optional[set] = None) -> Optional[dict]:
        """One graph run + the YOLOv8 head decode: predictions [1, C, N]
        -> transposed [N, C]; first 4 channels xywh in input pixels, the
        rest class scores (graph-sigmoided). Seg models deduct 32 mask
        coefficient channels; conf/NMS per the knobs. When the class filter
        resolved the prompt's class ids, ONLY boxes of those classes
        survive ("click the cat" can never click a person); None (the
        disclose-and-stand-down mode from _class_targets) keeps the old
        best-first behavior. Returns surviving best-score-first boxes in
        xywh (input-pixel space) plus the side, or None when a filter left
        nothing - an honest miss, not a near-miss click."""
        in_name = sess.get_inputs()[0].name
        outputs = sess.run(None, {in_name: tensor})
        if not outputs or outputs[0] is None:
            return None
        pred = np_squeeze(outputs[0])
        if pred is None or pred.ndim != 2:
            return None
        n_ch, n_anchor = pred.shape
        n_mask = _MASK_COEFFS if _is_seg(sess, stem) else 0
        n_cls = n_ch - 4 - n_mask
        if n_cls <= 0 or n_anchor == 0:
            return None
        side = float(tensor.shape[-1])           # the square input side
        conf = _threshold_conf()
        boxes_all = pred[:, :4]                  # xywh per anchor
        scores_all = pred[:, 4:4 + n_cls]
        best = scores_all.max(axis=1)
        keep = best >= conf
        if not keep.any():
            return {"size": (side, side), "boxes": []}
        boxes_all = boxes_all[keep]
        best = best[keep]
        cls_ids = scores_all[keep].argmax(axis=1)
        order = _nms_indices(boxes_all, best, cls_ids)
        if targets is not None:
            order = [i for i in order if int(cls_ids[i]) in targets]
            if not order:
                return None
        return {"size": (side, side),
                "boxes": [boxes_all[i] for i in order]}

    def _is_seg(sess: Any, stem: str) -> bool:
        if "-seg" in stem or "seg" in stem.lower().replace("-", "_"):
            return True
        try:
            return len(sess.get_outputs()) > 1
        except Exception:
            return False

    def np_squeeze(arr):
        try:
            import numpy as np
            return np.squeeze(arr).T
        except Exception:
            return arr.T if hasattr(arr, "T") else None

    def _nms_indices(boxes, scores, cls_ids):
        """Greedy multi-class NMS in xywh/absolute pixels: IoU over the
        corner form, same-class suppression only - the standard YOLOv8
        postprocess the decompile showed."""
        import numpy as np
        cx, cy, w, h = (boxes[:, 0], boxes[:, 1],
                        boxes[:, 2], boxes[:, 3])
        x1 = cx - w / 2.0
        y1 = cy - h / 2.0
        x2 = cx + w / 2.0
        y2 = cy + h / 2.0
        areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou_gate = 0.5
        order = np.argsort(-scores)
        alive: List[int] = []
        suppressed = np.zeros(len(scores), bool)
        for i in order:
            if suppressed[i]:
                continue
            alive.append(int(i))
            same_cls = cls_ids == cls_ids[i]
            xx1 = np.maximum(x1[i], x1)
            yy1 = np.maximum(y1[i], y1)
            xx2 = np.minimum(x2[i], x2)
            yy2 = np.minimum(y2[i], y2)
            inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
            union = areas[i] + areas - inter
            iou = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
            suppressed |= bool(same_cls[i]) * (iou > iou_gate)
        # best score first, capped upstream by _max_points()
        return alive

    return _Detector


def has_cpu_runway() -> bool:
    """The cpu rung is offerable when ANY vendored weight set can answer:
    the grid library, a detector route, or a CLIP pair - presence, not just
    the location."""
    return bool(has_model() or has_detector() or has_clip())


# --------------------------------------------------------------------------
# The CLIP rung's vendored weights (models/clip): a visual + textual encoder
# pair. When no grid model AND no detector speaks for a prompt, the clip
# matcher embeds the prompt SENTENCE and picks tiles whose cosine similarity
# to it clears a margin over the grid's own similarity spread - the
# multi-select semantic matching upstream reached for CLIP with.

_CLIP_DIR = "clip"
_KnobClipFamily = "GREYSEARCH_CAPTCHA_CLIP_FAMILY"
# the family id is the filename segment after "visual_CLIP"/"textual_CLIP":
# files are visual_CLIP_<family>.onnx, so the id carries the underscore
_DEFAULT_CLIP_FAMILY = "_ViT-B-32.openai"  # 9/9 threshold probe (bench)
_KnobClipMin = "GREYSEARCH_CAPTCHA_CLIP_MIN_SIM"
_DEFAULT_CLIP_MIN = 0.24                   # absolute floor (noise cut)
_CLIP_MARGIN = 0.5                         # sim >= mean + 0.5 * std


def resolve_clip_dir() -> Optional[Path]:
    env = os.environ.get("GREYSEARCH_CAPTCHA_CLIP_PATH", "").strip()
    if env:
        return Path(env)
    return install_root() / "models" / _CLIP_DIR


def clip_pairs(directory: Optional[Path]) -> List[str]:
    """Families with BOTH encoder halves on disk (visual_CLIP_<family>.onnx
    and textual_CLIP_<family>.onnx). A family whose visual half fails the
    onnx checker still lists here - it drops out at session build, which
    the matcher caches (see the ViT-L-14 disclosure in models/SOURCE)."""
    if directory is None or not directory.is_dir():
        return []
    try:
        names = {p.name for p in directory.glob("*.onnx")}
        out = []
        for name in sorted(names):
            if name.startswith("visual_CLIP"):
                fam = name[len("visual_CLIP"):-len(".onnx")]
                if f"textual_CLIP{fam}.onnx" in names:
                    out.append(fam)
        return out
    except OSError:
        return []


def has_clip() -> bool:
    return bool(clip_pairs(resolve_clip_dir()))


def load_clip(device: str = "cpu") -> Optional[Any]:
    """load_clip("cpu") -> {classify(images, prompt) -> [tile indices]}.
    The prompt sentence (untrusted data, capped) is embedded once; each
    tile's image embedding is L2-normalized and cosined against it; a tile
    is picked when its similarity clears the ABSOLUTE floor AND the grid's
    own mean + margin spread (so a prompt where everything scores alike
    picks nothing - honest, not a guess). None on any unavailable piece:
    no pair, no tokenizer vocabulary, no numpy, bad captures. Never a
    wrong answer from a degraded setup."""
    families = clip_pairs(resolve_clip_dir())
    if not families:
        return None
    family = (os.environ.get(_KnobClipFamily, "").strip()
              or _DEFAULT_CLIP_FAMILY)
    families = [family] + [f for f in families if f != family]
    providers = _providers_for(device)
    if providers is None:
        return None
    try:
        import onnxruntime as ort
    except Exception as e:
        LOG.warning("captcha onnxruntime unavailable: %s", e)
        return None
    from models import CLIP_FEATURIZER
    from models import CLIPTOKENIZER
    tokenizer = CLIPTOKENIZER.load_tokenizer()
    if tokenizer is None:
        return None

    def _clip_min() -> float:
        try:
            v = float(os.environ.get(_KnobClipMin, "").strip()
                      or _DEFAULT_CLIP_MIN)
        except (TypeError, ValueError):
            v = _DEFAULT_CLIP_MIN
        return min(max(v, 0.02), 0.95)

    directory = resolve_clip_dir()
    sessions: Dict[str, Optional[Any]] = {}
    lock = threading.Lock()

    def _pair(fam: str):
        with lock:
            if fam not in sessions:
                try:
                    vis = ort.InferenceSession(
                        str(directory / f"visual_CLIP{fam}.onnx"),
                        providers=providers)
                    txt = ort.InferenceSession(
                        str(directory / f"textual_CLIP{fam}.onnx"),
                        providers=providers)
                    sessions[fam] = (vis, txt)
                except Exception as e:
                    LOG.warning("clip pair %s unloaded: %s", fam, e)
                    sessions[fam] = None
            return sessions[fam]

    class _ClipMatcher:
        """classify(images, prompt) -> 0-based tile indices whose embedding
        is most similar to the prompt sentence, or None on an unusable
        setup; [] when no tile clears the bar (an honest nothing)."""

        @staticmethod
        def classify(images: List[bytes],
                     prompt: str) -> Optional[List[int]]:
            try:
                if not images or not prompt:
                    return None
                chosen = None
                for fam in families[:3]:   # default first, then fallbacks
                    pair = _pair(fam)
                    if pair is not None:
                        chosen = pair
                        break
                if chosen is None:
                    return None
                vis, txt = chosen
                batch = CLIP_FEATURIZER.images_to_tensor(images)
                if batch is None:
                    return None
                emb = vis.run(None, {vis.get_inputs()[0].name: batch})[0]
                row = tokenizer([str(prompt)[:160]])
                temb = txt.run(None, {txt.get_inputs()[0].name: row})[0]
                import numpy as np
                e = emb / np.linalg.norm(emb, axis=1, keepdims=True)
                t = temb / np.linalg.norm(temb, axis=1, keepdims=True)
                sims = (e @ t.T).reshape(-1)          # one prompt, N tiles
                floor = max(float(_clip_min()),
                            float(sims.mean() + _CLIP_MARGIN * sims.std()))
                picks = [i for i in range(len(images))
                         if sims[i] >= floor]
                return picks or None
            except Exception as ex:
                LOG.warning("clip classify failed: %s", ex)
                return None

    return _ClipMatcher

