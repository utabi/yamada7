from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping

from .models import FormattedState, Observation


@dataclass
class StateFormatter:
    """Converts raw environment observations and memory extracts into LLM-friendly context."""

    max_slot_items: int = 5

    def format(self, observation: Observation, memory_highlights: List[str]) -> FormattedState:
        data = observation.data
        slots: Mapping[str, str] = {
            "tick": observation.tick,
            "life": data.get("life"),
            "resources": data.get("resources"),
            "danger": data.get("danger"),
            "unknown": data.get("unknown"),
            "recent_events": self._join(data.get("events", [])),
        }

        summary = (
            f"Tick {observation.tick}: life={data.get('life')}, "
            f"dang={data.get('danger')}, resources={data.get('resources')}, "
            f"unknown={data.get('unknown')}."
        )

        trimmed_highlights = memory_highlights[: self.max_slot_items]
        return FormattedState(summary=summary, slots=dict(slots), memory_highlights=trimmed_highlights)

    @staticmethod
    def _join(items):
        if isinstance(items, list):
            return ", ".join(str(item) for item in items[:5])
        return items

