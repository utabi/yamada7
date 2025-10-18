from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from ..env.base import Environment
from .models import ActionPlan, Channel, ExecutionEvent, ExecutionResult, Observation

logger = logging.getLogger(__name__)


@dataclass
class ExecutionEngine:
    """Translates action plans into environment commands via a whitelist."""

    allowed_actions: Iterable[str]

    def __post_init__(self):
        self._allowed = set(self.allowed_actions)

    def execute(
        self, env: Environment, plan: ActionPlan
    ) -> Tuple[ExecutionResult, Observation, float, List[Observation]]:
        result = ExecutionResult()
        final_observation: Optional[Observation] = None
        step_observations: List[Observation] = []
        accumulated_reward = 0.0
        for candidate in plan.actions:
            if candidate.action_id not in self._allowed:
                detail = {
                    "action": candidate.action_id,
                    "detail": "blocked - not in whitelist",
                    "risk": candidate.risk_estimate,
                }
                result.failures.append(detail)
                logger.warning("Blocking disallowed action %s", candidate.action_id)
                continue

            # Placeholder: assume success but note risk
            final_observation = env.step(candidate.action_id, **candidate.parameters)
            step_observations.append(final_observation)
            accumulated_reward += final_observation.reward
            detail = {
                "action": candidate.action_id,
                "detail": f"params={candidate.parameters}",
                "risk": candidate.risk_estimate,
            }
            result.successes.append(detail)

            if candidate.risk_estimate > 0.7:
                result.warnings.append(f"High risk action {candidate.action_id} (risk={candidate.risk_estimate:.2f})")

            if final_observation.done:
                result.warnings.append("Environment reached terminal state.")
                break

        if not plan.actions:
            logger.info("Plan contained no actions; issuing wait.")
            if "wait" in self._allowed:
                final_observation = env.step("wait")
                step_observations.append(final_observation)
                accumulated_reward += final_observation.reward
                result.successes.append({"action": "wait", "detail": "auto wait", "risk": 0.0})
            else:
                result.failures.append({"action": "wait", "detail": "no wait action available", "risk": 0.0})

        if final_observation is None:
            # fallback to no-op observation (env should provide)
            final_observation = (
                env.step("wait")
                if "wait" in self._allowed
                else Observation(
                    tick=-1,
                    data={},
                    reward=0.0,
                    done=False,
                    info={},
                )
            )
            step_observations.append(final_observation)
            accumulated_reward += final_observation.reward

        return result, final_observation, accumulated_reward, step_observations

    def emit_events(self, plan: ActionPlan, result: ExecutionResult) -> List[ExecutionEvent]:
        timestamp = datetime.utcnow()
        events = [
            ExecutionEvent(
                timestamp=timestamp,
                channel=Channel.ACTIONS,
                payload={"intent": plan.intent, "actions": [a.action_id for a in plan.actions]},
            )
        ]
        for success in result.successes:
            events.append(
                ExecutionEvent(
                    timestamp=timestamp,
                    channel=Channel.LOGS,
                    payload={"level": "info", "message": f"action {success['action']} completed"},
                )
            )
        for warning in result.warnings:
            events.append(
                ExecutionEvent(
                    timestamp=timestamp,
                    channel=Channel.EVENTS,
                    payload={"level": "warn", "message": warning},
                )
            )
        for failure in result.failures:
            events.append(
                ExecutionEvent(
                    timestamp=timestamp,
                    channel=Channel.EVENTS,
                    payload={"level": "error", "message": f"{failure['action']} blocked"},
                )
            )
        return events
