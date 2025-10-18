from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .models import Observation, RewardBreakdown


@dataclass
class RewardSynthesizer:
    """Combines external and internal rewards into a single signal."""

    curiosity_weight: float = 0.2

    def synthesize(self, observation: Observation, curiosity_signal: float) -> RewardBreakdown:
        external = observation.reward
        internal = curiosity_signal * self.curiosity_weight
        components: Dict[str, float] = {
            "external": external,
            "internal_curiosity": internal,
        }
        return RewardBreakdown(external_reward=external, internal_reward=internal, components=components)

