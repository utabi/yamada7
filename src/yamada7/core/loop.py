from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from typing import TYPE_CHECKING

from ..config import LoopConfig, DEFAULT_CONFIG
from ..env.base import Environment
from ..llm.thinker import LLMThinker
from .execution import ExecutionEngine
from .memory import MemoryManager
from .models import Channel, ExecutionEvent, LoopSnapshot, Observation
from .result_formatter import ResultFormatter
from .reward import RewardSynthesizer
from .state_formatter import StateFormatter

if TYPE_CHECKING:
    from ..ace import ACECurator, ACEReflector, PlaybookStore


DashboardPublisher = Callable[[LoopSnapshot], None]


@dataclass
class FeedbackLoop:
    """Main orchestrator that connects environment, LLM thinker, and support systems."""

    environment: Environment
    state_formatter: StateFormatter
    result_formatter: ResultFormatter
    reward_synthesizer: RewardSynthesizer
    memory_manager: MemoryManager
    execution_engine: ExecutionEngine
    thinker: LLMThinker
    config: LoopConfig = field(default_factory=LoopConfig)
    playbook_store: Optional[PlaybookStore] = None
    ace_reflector: Optional[ACEReflector] = None
    ace_curator: Optional[ACECurator] = None
    dashboard_handlers: List[DashboardPublisher] = field(default_factory=list)
    _ace_history: List[float] = field(default_factory=list, init=False)

    def run(self, max_ticks: Optional[int] = None) -> List[LoopSnapshot]:
        tick_limit = max_ticks or self.config.tick_limit
        snapshots: List[LoopSnapshot] = []

        observation = self.environment.reset()
        previous_unknown = observation.data.get("unknown", 0.0)

        for _ in range(tick_limit):
            highlights = self.memory_manager.highlights(observation)
            formatted_state = self.state_formatter.format(observation, highlights)
            memory_dump = self.memory_manager.export()
            playbook_context = self.playbook_store.get_context() if self.playbook_store else []
            if playbook_context:
                memory_dump["playbook"] = playbook_context
            plan = self.thinker.plan(formatted_state, list(self.environment.action_schema), memory_dump)

            execution_result, new_observation, action_reward, step_observations = self.execution_engine.execute(
                self.environment, plan
            )
            events = self.execution_engine.emit_events(plan, execution_result)
            events.extend(self._observation_events(step_observations))

            curiosity_signal = max(0.0, previous_unknown - (new_observation.data.get("unknown", 0.0) or 0.0))
            reward_observation = Observation(
                tick=new_observation.tick,
                data=new_observation.data,
                reward=action_reward,
                done=new_observation.done,
                info=new_observation.info,
            )
            reward_breakdown = self.reward_synthesizer.synthesize(reward_observation, curiosity_signal)
            summary_payload = self.result_formatter.build_summary(reward_observation, execution_result)
            reflection = self.thinker.reflect(summary_payload, reward_breakdown)
            self.memory_manager.update(reflection)

            snapshot = LoopSnapshot(
                tick=new_observation.tick,
                observation=reward_observation,
                formatted_state=formatted_state,
                action_plan=plan,
                execution=execution_result,
                reward=reward_breakdown,
                reflection=reflection,
            )
            playbook_updates, ace_events = self._handle_ace(snapshot, playbook_context)
            if ace_events:
                events.extend(ace_events)
            snapshot.events = events
            snapshot.playbook_updates = playbook_updates
            if self.playbook_store:
                snapshot.playbook_stats = self.playbook_store.stats()
            snapshots.append(snapshot)

            for handler in self.dashboard_handlers:
                handler(snapshot)

            observation = new_observation
            previous_unknown = observation.data.get("unknown", 0.0)

            if observation.done:
                break

        return snapshots

    def attach_dashboard(self, handler: DashboardPublisher):
        self.dashboard_handlers.append(handler)

    def _handle_ace(
        self,
        snapshot: LoopSnapshot,
        playbook_context: List[str],
    ) -> Tuple[List[Dict[str, Any]], List[ExecutionEvent]]:
        if not (
            self.config.ace.enabled
            and self.playbook_store
            and self.ace_reflector
            and self.ace_curator
        ):
            return [], []

        deltas = self.ace_reflector.propose(snapshot, playbook_context)
        if not deltas:
            return [], []

        result = self.ace_curator.curate(deltas, self.playbook_store)
        updates: List[Dict[str, Any]] = []
        events: List[ExecutionEvent] = []

        if result.rejected:
            for item in result.rejected:
                events.append(
                    ExecutionEvent(
                        timestamp=datetime.utcnow(),
                        channel=Channel.EVENTS,
                        payload={
                            "level": "warn",
                            "message": f"Playbook delta rejected: {item.delta.target}",
                            "reason": item.reason,
                            "tick": snapshot.tick,
                        },
                    )
                )
                updates.append(
                    {
                        "target": item.delta.target,
                        "change_type": item.delta.change_type,
                        "status": "rejected",
                        "reason": item.reason,
                        "content": item.delta.content,
                        "priority": item.delta.priority,
                        "tags": item.delta.tags,
                    }
                )

        if result.accepted:
            applied, applied_events = self.playbook_store.apply_deltas(result.accepted, snapshot.tick)
            updates.extend(record.to_dict() for record in applied)
            events.extend(applied_events)

        if (
            self.config.ace.refine_interval
            and self.config.ace.refine_interval > 0
            and snapshot.tick % self.config.ace.refine_interval == 0
        ):
            events.append(self.playbook_store.refine(note=f"tick {snapshot.tick}"))

        return updates, events

    @staticmethod
    def _observation_events(observations: List[Observation]) -> List[ExecutionEvent]:
        timeline: List[ExecutionEvent] = []
        for obs in observations:
            messages = obs.data.get("events") or []
            for message in messages:
                timeline.append(
                    ExecutionEvent(
                        timestamp=datetime.utcnow(),
                        channel=Channel.STATE,
                        payload={
                            "tick": obs.tick,
                            "message": message,
                            "life": obs.data.get("life"),
                            "resources": obs.data.get("resources"),
                            "danger": obs.data.get("danger"),
                            "unknown": obs.data.get("unknown"),
                        },
                    )
                )
        return timeline
