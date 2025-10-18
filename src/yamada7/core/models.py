from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Channel(str, Enum):
    STATE = "state"
    ACTIONS = "actions"
    METRICS = "metrics"
    EVENTS = "events"
    LOGS = "logs"


@dataclass
class Observation:
    """Raw observation received from the environment."""

    tick: int
    data: Dict[str, Any]
    reward: float
    done: bool
    info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FormattedState:
    """LLM-ready representation of the current situation."""

    summary: str
    slots: Dict[str, Any]
    memory_highlights: List[str] = field(default_factory=list)


@dataclass
class ActionCandidate:
    """Potential action emitted from the LLM planner."""

    action_id: str
    parameters: Dict[str, Any]
    confidence: float
    risk_estimate: float


@dataclass
class ActionPlan:
    """Executable plan for the upcoming turn."""

    intent: str
    sub_goals: List[str]
    actions: List[ActionCandidate]
    notes: Optional[str] = None


@dataclass
class ExecutionEvent:
    """Single execution event for dashboard/logging."""

    timestamp: datetime
    channel: Channel
    payload: Dict[str, Any]


@dataclass
class ExecutionResult:
    """Result of executing an action plan."""

    successes: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    interrupted: bool = False


@dataclass
class Reflection:
    """LLM generated reflection after observing results."""

    summary: str
    fear_updates: List[str]
    curiosity_updates: List[str]
    next_bias: Dict[str, Any]


@dataclass
class RewardBreakdown:
    """Detailed information about reward synthesis."""

    external_reward: float
    internal_reward: float
    components: Dict[str, float]


@dataclass
class LoopSnapshot:
    """Snapshot of all key data for a single loop iteration."""

    tick: int
    observation: Observation
    formatted_state: FormattedState
    action_plan: ActionPlan
    execution: ExecutionResult
    reward: RewardBreakdown
    reflection: Reflection
    events: List[ExecutionEvent] = field(default_factory=list)
