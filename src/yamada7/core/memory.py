from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Iterable, List

from .models import Observation, Reflection


@dataclass
class MemoryManager:
    """In-memory + file-backed storage for fear/curiosity knowledge."""

    root: Path
    max_entries: int = 200
    _fear_log: Deque[str] = field(default_factory=lambda: deque(maxlen=200))
    _curiosity_log: Deque[str] = field(default_factory=lambda: deque(maxlen=200))

    def __post_init__(self):
        self.root.mkdir(parents=True, exist_ok=True)

    def highlights(self, observation: Observation) -> List[str]:
        highlights: List[str] = []
        if self._fear_log:
            highlights.append(f"Top fear: {self._fear_log[-1]}")
        if self._curiosity_log:
            highlights.append(f"Curiosity: {self._curiosity_log[-1]}")
        events = observation.data.get("events") or []
        for event in events[-2:]:
            highlights.append(f"Recent event: {event}")
        return highlights[: self.max_entries]

    def update(self, reflection: Reflection):
        for note in reflection.fear_updates:
            self._fear_log.append(note)
        for note in reflection.curiosity_updates:
            self._curiosity_log.append(note)
        self._persist("fear.log", self._fear_log)
        self._persist("curiosity.log", self._curiosity_log)

    def _persist(self, name: str, data: Iterable[str]):
        path = self.root / name
        path.write_text("\n".join(data), encoding="utf-8")

    def export(self) -> Dict[str, List[str]]:
        return {"fear": list(self._fear_log), "curiosity": list(self._curiosity_log)}

