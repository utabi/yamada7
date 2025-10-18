from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..core.models import Observation


class Environment(ABC):
    """Abstract base environment used by the feedback loop."""

    @abstractmethod
    def reset(self) -> Observation:
        ...

    @abstractmethod
    def step(self, action_id: str, **params) -> Observation:
        ...

    @property
    @abstractmethod
    def action_schema(self) -> Iterable[str]:
        ...

