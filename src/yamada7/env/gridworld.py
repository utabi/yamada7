from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple

from ..core.models import Observation
from .base import Environment


Coord = Tuple[int, int]


@dataclass
class GridWorldEnvironment(Environment):
    """Lightweight survival-focused grid environment for rapid iteration."""

    width: int = 5
    height: int = 5
    max_ticks: int = 200
    seed: int = 1234
    hazard_rate: float = 0.1
    resource_rate: float = 0.2
    base_life: float = 1.0
    hazard_damage: float = 0.15
    gather_reward: float = 0.05
    move_cost: float = -0.01

    rng: random.Random = field(init=False)
    agent_pos: Coord = field(init=False)
    tick: int = field(default=0, init=False)
    life: float = field(init=False)
    resources: float = field(default=0.0, init=False)
    visited: Set[Coord] = field(default_factory=set, init=False)
    hazards: Set[Coord] = field(default_factory=set, init=False)
    resource_tiles: Dict[Coord, float] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.reset()

    def reset(self) -> Observation:
        self.agent_pos = (self.width // 2, self.height // 2)
        self.tick = 0
        self.life = self.base_life
        self.resources = 0.0
        self.visited = {self.agent_pos}
        self.hazards = set()
        self.resource_tiles = {}

        for x in range(self.width):
            for y in range(self.height):
                coord = (x, y)
                if coord == self.agent_pos:
                    continue
                if self.rng.random() < self.hazard_rate:
                    self.hazards.add(coord)
                elif self.rng.random() < self.resource_rate:
                    self.resource_tiles[coord] = round(self.rng.uniform(0.05, 0.2), 3)

        return self._observe(reward=0.0, events=["reset"], done=False)

    @property
    def action_schema(self) -> Iterable[str]:
        return ["move_north", "move_south", "move_east", "move_west", "gather", "wait"]

    def step(self, action_id: str, **params) -> Observation:
        self.tick += 1
        events: List[str] = [f"action={action_id}"]
        reward = 0.0
        done = False

        if action_id.startswith("move_"):
            moved = self._move(action_id)
            reward += self.move_cost
            if moved:
                events.append(f"moved to {self.agent_pos}")
            else:
                events.append("blocked by border")
        elif action_id == "gather":
            gathered = self.resource_tiles.pop(self.agent_pos, 0.0)
            if gathered > 0:
                self.resources += gathered
                reward += gathered + self.gather_reward
                events.append(f"gathered {gathered:.2f}")
            else:
                reward -= 0.02
                events.append("nothing to gather")
        elif action_id == "wait":
            reward += 0.0
            events.append("waited")
        else:
            reward -= 0.05
            events.append("invalid action")

        self.visited.add(self.agent_pos)
        hazard_penalty = 0.0
        if self.agent_pos in self.hazards:
            hazard_penalty = self.hazard_damage
            self.life -= hazard_penalty
            reward -= hazard_penalty
            events.append("hazard damage")

        if self.life <= 0 or self.tick >= self.max_ticks:
            done = True
            events.append("terminated")

        observation = self._observe(reward=reward, events=events, done=done)
        return observation

    def _move(self, action_id: str) -> bool:
        x, y = self.agent_pos
        if action_id == "move_north":
            target = (x, y - 1)
        elif action_id == "move_south":
            target = (x, y + 1)
        elif action_id == "move_east":
            target = (x + 1, y)
        else:
            target = (x - 1, y)

        tx, ty = target
        if not (0 <= tx < self.width and 0 <= ty < self.height):
            return False

        self.agent_pos = target
        return True

    def _observe(self, reward: float, events: List[str], done: bool) -> Observation:
        unknown_tiles = self.width * self.height - len(self.visited)
        unknown_ratio = unknown_tiles / (self.width * self.height)
        danger = 1.0 if self.agent_pos in self.hazards else self._nearest_hazard_distance()
        data = {
            "life": round(self.life, 3),
            "resources": round(self.resources, 3),
            "danger": round(danger, 3),
            "unknown": round(unknown_ratio, 3),
            "position": self.agent_pos,
            "events": events,
        }
        return Observation(tick=self.tick, data=data, reward=reward, done=done, info={})

    def _nearest_hazard_distance(self) -> float:
        if not self.hazards:
            return 0.0
        ax, ay = self.agent_pos
        min_distance = min(abs(ax - hx) + abs(ay - hy) for hx, hy in self.hazards)
        # Normalize to 0-1 with Manhattan distance
        max_distance = self.width + self.height
        return 1.0 - (min_distance / max_distance)

