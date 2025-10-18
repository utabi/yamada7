from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .models import ExecutionResult, Observation


@dataclass
class ResultFormatter:
    """Summarises executed actions and their effects for reflection."""

    max_entries: int = 5

    def build_summary(self, observation: Observation, execution: ExecutionResult) -> Dict[str, List[str]]:
        successes = [self._format_entry(entry) for entry in execution.successes[: self.max_entries]]
        failures = [self._format_entry(entry) for entry in execution.failures[: self.max_entries]]
        warnings = execution.warnings[: self.max_entries]

        return {
            "reward": f"{observation.reward:.3f}",
            "state_change": self._format_state_change(observation),
            "successes": successes,
            "failures": failures,
            "warnings": warnings,
        }

    @staticmethod
    def _format_entry(entry: Dict[str, str]) -> str:
        action = entry.get("action") or entry.get("action_id") or "unknown"
        detail = entry.get("detail") or entry.get("message") or ""
        return f"{action}: {detail}".strip()

    @staticmethod
    def _format_state_change(observation: Observation) -> str:
        data = observation.data
        return (
            f"life={data.get('life')}, resources={data.get('resources')}, "
            f"dang={data.get('danger')}, unknown={data.get('unknown')}"
        )

