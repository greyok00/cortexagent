
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional



STAGE_STATE = ("complete", "active", "queued", "skipped", "failed")
BLOCK_CATEGORY = ("system", "user", "history", "memory", "retrieval",
                  "tool_schema", "tool_output", "attachment", "reasoning",
                  "output_contract", "other")
BLOCK_PRIORITY = ("pinned", "high", "compressible", "discardable")



@dataclass
class ModelIdentity:

    model: str = "unknown"
    route: str = "cortex-big"
    backend: str = "unknown"

    source: str = "none"

    def display_model(self) -> str:

        m = self.model
        if m.lower().endswith(".gguf"):
            m = m[:-5]
        return m or "unknown"



@dataclass
class TokenComponent:

    id: str
    category: str = "other"
    source: str = ""
    tokens: int = 0
    order: int = 0
    sensitivity: bool = False
    optimizable: bool = True
    pinned: bool = False
    priority: str = "compressible"



@dataclass
class ComposeResult:

    policy: str = "coding-agent / strict-tools"
    input_budget: int = 0
    output_reserved: int = 0
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



@dataclass
class SlimTokenAction:

    block_id: str = ""
    category: str = "other"
    action: str = "preserved"
    reason: str = ""
    tokens_before: int = 0
    tokens_after: int = 0


@dataclass
class SlimTokenResult:

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



@dataclass
class FinalizeResult:

    valid: bool = True
    template_applied: bool = False
    schema_valid: bool = False
    input_tokens: int = 0
    max_output_tokens: int = 0
    context_window: int = 0
    fits: bool = True
    generation_params: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)



@dataclass
class PipelineStage:

    name: str
    state: str = "queued"
    elapsed_ms: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    detail: str = ""

    payload: Any = None






PATHWAY_GROUPS: List[str] = [
    "prompt_intake",
    "frame_assemble",
    "frame_of_ref",
    "memory_check",
    "slimtoken_minify",
    "tool_routing",
    "context_fit",
    "prefill",
    "decode",
    "stream_out",
    "cost_ledger",
]


@dataclass
class PathwayNode:

    key: str
    state: str = "queued"
    detail: str = ""
    in_text: Optional[str] = None
    out_text: Optional[str] = None



@dataclass
class InferenceTelemetry:

    context_used: Optional[int] = None
    context_window: Optional[int] = None
    input_tps: Optional[float] = None
    output_tps: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_pct: Optional[float] = None
    reused_pct: Optional[float] = None
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



@dataclass
class BackendCapabilities:

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



@dataclass
class SettingValue:
    key: str
    label: str
    value: Any
    kind: str = "text"
    options: List[str] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    group: str = "runtime"
    supported: bool = True
    disruptive: bool = False
    tooltip: str = ""


@dataclass
class SettingsState:

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



@dataclass
class SchedulerTask:
    id: str
    name: str
    cron: str = ""
    humanized: str = ""
    status: str = "active"
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



@dataclass
class TestRun:
    id: str
    label: str
    started_at: str = ""
    elapsed_s: Optional[float] = None
    model: str = "unknown"
    route: str = "cortex-big"
    backend: str = "unknown"
    settings_used: str = "active"
    slimtoken_on: bool = True
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    input_tps: Optional[float] = None
    output_tps: Optional[float] = None
    saved_pct: Optional[float] = None
    stages: List[PipelineStage] = field(default_factory=list)
    output_preview: str = ""
    errors: List[str] = field(default_factory=list)
    status: str = "running"



@dataclass
class RuntimeSnapshot:

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
