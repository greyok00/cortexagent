"""CortexAgent Workflow Engine — Type Definitions"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto


class EngineType(Enum):
    LLM_REASONING = auto()
    LLM_CODE = auto()
    WEB_RESEARCH = auto()
    IMAGE_GEN = auto()
    SYSTEM_EXEC = auto()
    DOCKER = auto()
    FILE_OPS = auto()


class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()
    RETRYING = auto()


@dataclass
class Task:
    id: str
    name: str
    engine: EngineType
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchGroup:
    engine: EngineType
    tasks: list[Task]
    batch_id: str


@dataclass
class WorkflowPlan:
    goal: str
    expanded_goal: str
    tasks: list[Task]
    batch_groups: list[BatchGroup]
    metadata: dict = field(default_factory=dict)


@dataclass
class ProgressEvent:
    phase: str
    task_id: Optional[str]
    status: TaskStatus
    message: str
    progress_pct: float
