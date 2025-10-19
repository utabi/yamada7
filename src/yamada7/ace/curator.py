from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .playbook import PlaybookDelta, PlaybookStore


@dataclass
class RejectedDelta:
    delta: PlaybookDelta
    reason: str


@dataclass
class CurationResult:
    accepted: List[PlaybookDelta]
    rejected: List[RejectedDelta]


class ACECurator:
    """Reflectorからの差分を検証し、安全なものだけをプレイブックに適用する。"""

    def __init__(self, max_per_tick: int = 3):
        self.max_per_tick = max_per_tick

    def curate(self, deltas: List[PlaybookDelta], store: PlaybookStore) -> CurationResult:
        accepted: List[PlaybookDelta] = []
        rejected: List[RejectedDelta] = []

        # 優先度の高い順に処理
        ordered = sorted(deltas, key=lambda d: d.priority, reverse=True)
        for delta in ordered:
            if len(accepted) >= self.max_per_tick:
                rejected.append(RejectedDelta(delta=delta, reason="max_per_tick_reached"))
                continue
            if not delta.content.strip():
                rejected.append(RejectedDelta(delta=delta, reason="empty_content"))
                continue
            if store.contains(delta):
                rejected.append(RejectedDelta(delta=delta, reason="duplicate_in_playbook"))
                continue
            accepted.append(delta)

        return CurationResult(accepted=accepted, rejected=rejected)

