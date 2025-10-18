from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..config import LLMConfig
from ..core.models import ActionCandidate, ActionPlan, FormattedState, Reflection, RewardBreakdown
from .claude_cli import ClaudeCodeClient


@dataclass
class LLMThinker:
    """
    LLM プランナー管理クラス。

    - mode="heuristic": 内蔵ヒューリスティックで行動計画を生成
    - mode="claude-cli": Claude Code CLI を呼び出し JSON 応答から計画と反省を復元
    """

    config: LLMConfig
    seed: int = 42
    claude_client: Optional[ClaudeCodeClient] = None
    rng: random.Random = field(init=False)
    _cached_reflection: Optional[Reflection] = field(default=None, init=False)

    def __post_init__(self):
        self.rng = random.Random(self.seed)

    def plan(
        self,
        state: FormattedState,
        allowed_actions: List[str],
        memory_blurbs: Dict[str, List[str]],
    ) -> ActionPlan:
        if self.config.mode == "claude-cli" and self.claude_client:
            plan, reflection = self._plan_with_claude(state, allowed_actions, memory_blurbs)
            if plan:
                self._cached_reflection = reflection
                return plan
        plan = self._heuristic_plan(state, allowed_actions, memory_blurbs)
        self._cached_reflection = None
        return plan

    def reflect(self, summary: Dict[str, List[str]], reward: RewardBreakdown) -> Reflection:
        if self._cached_reflection:
            reflection = self._cached_reflection
            self._cached_reflection = None
            return reflection
        return self._heuristic_reflection(summary, reward)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _plan_with_claude(
        self,
        state: FormattedState,
        allowed_actions: List[str],
        memory_blurbs: Dict[str, List[str]],
    ) -> Tuple[Optional[ActionPlan], Optional[Reflection]]:
        formatted_state = {
            "summary": state.summary,
            "slots": state.slots,
            "memory_highlights": state.memory_highlights,
        }
        try:
            return self.claude_client.generate_plan(formatted_state, allowed_actions, memory_blurbs)
        except Exception as exc:
            print(f"[LLMThinker] Claude CLI 呼び出しに失敗しました: {exc}")
            return None, None

    def _heuristic_plan(
        self,
        state: FormattedState,
        allowed_actions: List[str],
        memory_blurbs: Dict[str, List[str]],
    ) -> ActionPlan:
        danger = state.slots.get("danger") or 0.0
        unknown = state.slots.get("unknown") or 0.0

        primary_intent = "preserve life" if danger and danger > 0.6 else "explore unknown"
        sub_goals: List[str] = []
        if primary_intent == "preserve life":
            sub_goals.append("exit hazardous zone")
        if unknown and unknown > 0.3:
            sub_goals.append("map unexplored tiles")
        if state.slots.get("resources") < 0.5:
            sub_goals.append("gather resources")

        candidates: List[ActionCandidate] = []
        move_actions = [a for a in allowed_actions if a.startswith("move_")]
        if primary_intent == "preserve life" and move_actions:
            candidates.append(
                ActionCandidate(
                    action_id=self.rng.choice(move_actions),
                    parameters={},
                    confidence=0.7,
                    risk_estimate=min(0.9, float(danger) if danger else 0.2),
                )
            )
        elif unknown and unknown > 0.1 and move_actions:
            candidates.append(
                ActionCandidate(
                    action_id=self.rng.choice(move_actions),
                    parameters={},
                    confidence=0.6,
                    risk_estimate=float(danger) if danger else 0.1,
                )
            )

        if "gather" in allowed_actions:
            candidates.append(
                ActionCandidate(
                    action_id="gather",
                    parameters={},
                    confidence=0.4,
                    risk_estimate=0.2,
                )
            )

        if not candidates and allowed_actions:
            candidates.append(
                ActionCandidate(
                    action_id=self.rng.choice(allowed_actions),
                    parameters={},
                    confidence=0.3,
                    risk_estimate=float(danger) if danger else 0.1,
                )
            )

        notes = ""
        if memory_blurbs.get("fear"):
            notes += f"Recent fear: {memory_blurbs['fear'][-1]}. "
        if memory_blurbs.get("curiosity"):
            notes += f"Curiosity focus: {memory_blurbs['curiosity'][-1]}."

        return ActionPlan(intent=primary_intent, sub_goals=sub_goals, actions=candidates, notes=notes.strip())

    def _heuristic_reflection(self, summary: Dict[str, List[str]], reward: RewardBreakdown) -> Reflection:
        reward_total = reward.external_reward + reward.internal_reward
        if reward_total < -0.1:
            fear_updates = [f"Loss observed, adjust plan. External={reward.external_reward:.2f}"]
        else:
            fear_updates = [f"Stable. External={reward.external_reward:.2f}"]

        curiosity_signal = reward.components.get("internal_curiosity", 0.0)
        curiosity_updates = [f"Curiosity delta {curiosity_signal:.2f}"]

        bias = {
            "risk_tolerance": 0.3 if reward_total < 0 else 0.5,
            "explore_priority": 0.7 if curiosity_signal > 0.1 else 0.4,
        }

        summary_text = (
            f"Reward={reward_total:.2f}, state_change={summary['state_change']}, "
            f"successes={len(summary['successes'])}, failures={len(summary['failures'])}"
        )

        return Reflection(summary=summary_text, fear_updates=fear_updates, curiosity_updates=curiosity_updates, next_bias=bias)

