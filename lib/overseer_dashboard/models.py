"""lib/overseer_dashboard/models.py — typed view models for the Overseer dashboard.

Every UI surface reads a typed model rather than poking raw JSON. These
dataclasses are the single source of truth for what the dashboard can render.
They are deliberately plain (stdlib dataclasses) so the UI, the test harness,
and the pipeline logic all share one vocabulary.

The spec's core rule: never invent metrics. If a field is absent from the
underlying telemetry it stays ``None`` and the UI renders ``—`` / "Unavailable"
rather than a fabricated zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── Enums (kept as plain strings so they serialize cleanly) ─────────────────
STAGE_STATE = ("complete", "active", "queued", "skipped", "failed")
BLOCK_CATEGORY = ("system", "user", "history", "memory", "retrieval",
                  "tool_schema", "tool_output", "attachment", "reasoning",
                  "output_contract", "other")
BLOCK_PRIORITY = ("pinned", "high", "compressible", "discardable")


# ── Model identity ─────────────────────────────────────────────────────────
@dataclass
class ModelIdentity:
    """Concrete serving model, route alias, and backend as separate fields.

    ``model`` is the resolved concrete model name (never a route alias unless
    nothing better exists). ``route`` is the route/profile alias. ``backend``
    is the provider (Ollama / llama.cpp / etc).
    """
    model: str = "unknown"
    route: str = "cortex-big"
    backend: str = "unknown"
    # How the model name was resolved, for diagnostics.
    source: str = "none"

    def display_model(self) -> str:
        """Strip ``.gguf`` for presentation but keep quantization identity."""
        m = self.model
        if m.lower().endswith(".gguf"):
            m = m[:-5]
        return m or "unknown"


# ── Token component (typed block metadata) ──────────────────────────────────
@dataclass
class TokenComponent:
    """One typed block of the request context.

    Instrumented at request-construction time (never estimated in the UI
    thread). ``optimizable`` is whether SlimToken may touch it; ``pinned``
    means it is protected and must survive unchanged.
    """
    id: str
    category: str = "other"
    source: str = ""
    tokens: int = 0
    order: int = 0
    sensitivity: bool = False
    optimizable: bool = True
    pinned: bool = False
    priority: str = "compressible"  # pinned|high|compressible|discardable


# ── Compose result ──────────────────────────────────────────────────────────
@dataclass
class ComposeResult:
    """Output of the Compose stage: policy framing + protection + budget."""
    policy: str = "coding-agent / strict-tools"
    input_budget: int = 0          # contextWindow - maxOutputTokens
    output_reserved: int = 0       # maxOutputTokens
    blocks: List[TokenComponent] = field(default_factory=list)
    pinned: List[TokenComponent] = field(default_factory=list)
    compressible: List[TokenComponent] = field(default_factory=list)
    discardable: List[TokenComponent] = field(default_factory=list)
    total_tokens: int = 0
    valid: bool = True
    errors: List[str] = field(default_factory=list)

    @property
    def pinned_tokens(self) -> int:
        return sum(b.tokens for b in self.pinned)

    @property
    def compressible_tokens(self) -> int:
        return sum(b.tokens for b in self.compressible)

    @property
    def discardable_tokens(self) -> int:
        return sum(b.tokens for b in self.discardable)


# ── SlimToken result ────────────────────────────────────────────────────────
@dataclass
class SlimTokenAction:
    """One optimization action applied (or proposed) by SlimToken."""
    block_id: str = ""
    category: str = "other"
    action: str = "preserved"      # removed|compacted|deduplicated|summarized|preserved
    reason: str = ""
    tokens_before: int = 0
    tokens_after: int = 0


@dataclass
class SlimTokenResult:
    """Before/after + actions + diff for the SlimToken stage."""
    enabled: bool = True
    policy: str = "balanced"
    before_tokens: int = 0
    after_tokens: int = 0
    saved_tokens: int = 0
    saved_pct: float = 0.0
    actions: List[SlimTokenAction] = field(default_factory=list)
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def removed(self) -> int:
        return sum(1 for a in self.actions if a.action == "removed")

    @property
    def compacted(self) -> int:
        return sum(1 for a in self.actions if a.action == "compacted")

    @property
    def deduplicated(self) -> int:
        return sum(1 for a in self.actions if a.action == "deduplicated")

    @property
    def summarized(self) -> int:
        return sum(1 for a in self.actions if a.action == "summarized")

    @property
    def preserved(self) -> int:
        return sum(1 for a in self.actions if a.action == "preserved")


# ── Finalize result ─────────────────────────────────────────────────────────
@dataclass
class FinalizeResult:
    """Output of the Finalize stage: the immutable provider-ready payload."""
    valid: bool = True
    template_applied: bool = False
    schema_valid: bool = False
    input_tokens: int = 0
    max_output_tokens: int = 0
    context_window: int = 0
    fits: bool = True
    generation_params: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ── Pipeline stage ──────────────────────────────────────────────────────────
@dataclass
class PipelineStage:
    """One stage of COLLECT → COMPOSE → SLIMTOKEN → FINALIZE → PREFILL →
    DECODE → DELIVER."""
    name: str
    state: str = "queued"          # complete|active|queued|skipped|failed
    elapsed_ms: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    detail: str = ""
    # Stage-specific payload (e.g. ComposeResult / SlimTokenResult).
    payload: Any = None


# ── Pathway groups (broader-scale prompt path for the bottom strip) ──────────
# Eleven grouped stages, mapped to existing PipelineStage names where they
# share data. Stages not backed by an existing telemetry stage render as
# "queued" until a richer data path lands.
PATHWAY_GROUPS: List[str] = [
    "prompt_intake",     # → COLLECT
    "frame_assemble",    # → COMPOSE
    "frame_of_ref",      # derived from snap.model.route / system_profile
    "memory_check",      # derived from snap.minify runs / overseer write-check
    "slimtoken_minify",  # → SLIMTOKEN
    "tool_routing",      # derived from overseer tool-call activity
    "context_fit",       # → FINALIZE
    "prefill",           # → PREFILL
    "decode",            # → DECODE
    "stream_out",        # → DELIVER
    "cost_ledger",       # derived from inference input+output tokens
]


@dataclass
class PathwayNode:
    """State for a single pathway-strip node."""
    key: str
    state: str = "queued"           # complete|active|queued|skipped|failed
    detail: str = ""
    in_text: Optional[str] = None
    out_text: Optional[str] = None


# ── Live inference telemetry ────────────────────────────────────────────────
@dataclass
class InferenceTelemetry:
    """Real-time prefill/decode/context/cache numbers. None = not instrumented."""
    context_used: Optional[int] = None
    context_window: Optional[int] = None
    input_tps: Optional[float] = None      # prefill/input speed
    output_tps: Optional[float] = None     # decode/output speed
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_pct: Optional[float] = None      # only if real
    reused_pct: Optional[float] = None      # only if real
    vram_used_mib: Optional[int] = None
    vram_total_mib: Optional[int] = None
    gpu_util_pct: Optional[float] = None
    ram_used_mib: Optional[int] = None
    queue_depth: Optional[int] = None
    active_request: Optional[str] = None
    last_request_status: Optional[str] = None
    session_count: Optional[int] = None
    active: bool = False

    @property
    def context_pct(self) -> Optional[float]:
        if self.context_used is None or not self.context_window:
            return None
        return round(self.context_used / self.context_window * 100, 1)


# ── Backend capabilities ────────────────────────────────────────────────────
@dataclass
class BackendCapabilities:
    """What the active backend actually supports. Drives which controls render."""
    supports_temperature: bool = True
    supports_top_p: bool = True
    supports_top_k: bool = True
    supports_repeat_penalty: bool = True
    supports_seed: bool = True
    supports_stop: bool = True
    supports_streaming: bool = True
    supports_cache_reuse: bool = False
    supports_warmup: bool = False
    supports_context_switch: bool = True
    local: bool = True
    paid: bool = False


# ── Settings ────────────────────────────────────────────────────────────────
@dataclass
class SettingValue:
    key: str
    label: str
    value: Any
    kind: str = "text"             # text|number|slider|select|toggle
    options: List[str] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    group: str = "runtime"        # runtime|slimtoken|service
    supported: bool = True
    disruptive: bool = False       # changing interrupts active work
    tooltip: str = ""


@dataclass
class SettingsState:
    """activeSettings vs pendingSettings, kept separate."""
    active: Dict[str, Any] = field(default_factory=dict)
    pending: Dict[str, Any] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)
    definitions: Dict[str, SettingValue] = field(default_factory=dict)

    @property
    def changed_keys(self) -> List[str]:
        return [k for k in self.pending
                if self.pending.get(k) != self.active.get(k)]

    @property
    def has_pending(self) -> bool:
        return bool(self.changed_keys)

    def pending_differs(self) -> bool:
        return self.has_pending


# ── Scheduler ────────────────────────────────────────────────────────────────
@dataclass
class SchedulerTask:
    id: str
    name: str
    cron: str = ""
    humanized: str = ""
    status: str = "active"        # active|paused|error
    next_run: str = ""
    task_type: str = ""


@dataclass
class SchedulerState:
    enabled: bool = True
    healthy: bool = True
    active_count: int = 0
    paused_count: int = 0
    tasks: List[SchedulerTask] = field(default_factory=list)
    stale: bool = False
    stale_detail: str = ""
    error: str = ""


# ── Test run ────────────────────────────────────────────────────────────────
@dataclass
class TestRun:
    id: str
    label: str
    started_at: str = ""
    elapsed_s: Optional[float] = None
    model: str = "unknown"
    route: str = "cortex-big"
    backend: str = "unknown"
    settings_used: str = "active"     # active|pending
    slimtoken_on: bool = True
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    input_tps: Optional[float] = None
    output_tps: Optional[float] = None
    saved_pct: Optional[float] = None
    stages: List[PipelineStage] = field(default_factory=list)
    output_preview: str = ""
    errors: List[str] = field(default_factory=list)
    status: str = "running"           # running|complete|failed|cancelled


# ── Runtime snapshot (top-level) ─────────────────────────────────────────────
@dataclass
class RuntimeSnapshot:
    """The full live state the dashboard renders on one refresh tick."""
    connected: bool = True
    data_age_s: float = 0.0
    stale: bool = False
    stale_detail: str = ""
    model: ModelIdentity = field(default_factory=ModelIdentity)
    big_healthy: bool = False
    tiny_healthy: bool = False
    proxy_up: bool = False
    backend_healthy: bool = False
    inference: InferenceTelemetry = field(default_factory=InferenceTelemetry)
    pipeline: List[PipelineStage] = field(default_factory=list)
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)
    settings: SettingsState = field(default_factory=SettingsState)
    scheduler: SchedulerState = field(default_factory=SchedulerState)
    minify: Dict[str, Any] = field(default_factory=dict)
    queue_pending: int = 0
    queue_total: int = 0
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    last_successful: Optional[Dict[str, Any]] = None
    error_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
