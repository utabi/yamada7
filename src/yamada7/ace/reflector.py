from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from ..core.models import LoopSnapshot
from ..llm.claude_cli import ClaudeCodeClient
from .playbook import PlaybookDelta


@dataclass
class ACEReflector:
    """Executorの行動結果からプレイブック差分を生成する。"""

    mode: str = "heuristic"  # heuristic / llm
    claude_client: Optional[ClaudeCodeClient] = None
    max_items: int = 3

    def propose(
        self,
        snapshot: LoopSnapshot,
        playbook_context: Iterable[str],
    ) -> List[PlaybookDelta]:
        if self.mode == "llm" and self.claude_client:
            try:
                return self._propose_with_claude(snapshot, playbook_context)
            except Exception as exc:
                print(f"[ACEReflector] Claude CLI 呼び出しに失敗しました: {exc}")
        return self._heuristic(snapshot, list(playbook_context))

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------
    def _propose_with_claude(
        self,
        snapshot: LoopSnapshot,
        playbook_context: Iterable[str],
    ) -> List[PlaybookDelta]:
        payload = {
            "tick": snapshot.tick,
            "state_summary": snapshot.formatted_state.summary,
            "state_slots": snapshot.formatted_state.slots,
            "actions": [entry.get("action") for entry in snapshot.execution.successes],
            "successes": snapshot.execution.successes,
            "failures": snapshot.execution.failures,
            "warnings": snapshot.execution.warnings,
            "reward": {
                "external": snapshot.reward.external_reward,
                "internal": snapshot.reward.internal_reward,
                "total": snapshot.reward.external_reward + snapshot.reward.internal_reward,
            },
            "reflection": {
                "summary": snapshot.reflection.summary,
                "updates": {
                    "alert": snapshot.reflection.fear_updates,
                    "exploration": snapshot.reflection.curiosity_updates,
                },
            },
            "playbook_context": list(playbook_context),
        }
        raw = self.claude_client.generate_playbook_deltas(payload)
        deltas: List[PlaybookDelta] = []
        for entry in raw:
            content = (entry.get("content") or "").strip()
            target = entry.get("target") or "general"
            change_type = entry.get("change_type") or "add"
            if not content:
                continue
            deltas.append(
                PlaybookDelta(
                    target=target,
                    change_type=change_type,
                    content=content,
                    evidence=entry.get("evidence") or [],
                    priority=float(entry.get("priority", 0.5)),
                    tags=list(entry.get("tags") or []),
                )
            )
        return deltas[: self.max_items]

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------
    def _heuristic(self, snapshot: LoopSnapshot, playbook_context: List[str]) -> List[PlaybookDelta]:
        deltas: List[PlaybookDelta] = []
        reward_total = snapshot.reward.external_reward + snapshot.reward.internal_reward
        successes = snapshot.execution.successes
        failures = snapshot.execution.failures
        warnings = snapshot.execution.warnings
        context_note = playbook_context[0][:160] if playbook_context else ""

        if successes and reward_total > 0:
            content = textwrap.dedent(
                f"""
                ## Tick {snapshot.tick} 成功戦術
                - 状況: {snapshot.formatted_state.summary}
                - 実行アクション: {', '.join(s.get('action') for s in successes if s.get('action'))}
                - 獲得報酬: 外部={snapshot.reward.external_reward:.3f}, 内部={snapshot.reward.internal_reward:.3f}
                - 反省要約: {snapshot.reflection.summary}
                {f'- 参考プレイブック抜粋: {context_note}' if context_note else ''}
                """
            ).strip()
            deltas.append(
                PlaybookDelta(
                    target="survival_playbook",
                    change_type="add",
                    content=content,
                    evidence=[w for w in warnings[:2]],
                    priority=min(0.9, 0.5 + reward_total),
                    tags=["success", "tactics"],
                )
            )

        if failures or warnings:
            notes = []
            for failure in failures[:3]:
                notes.append(f"- 行動 {failure.get('action')} は失敗: {failure.get('detail')}")
            for warning in warnings[:2]:
                notes.append(f"- 注意: {warning}")
            content = textwrap.dedent(
                f"""
                ## Tick {snapshot.tick} 調整メモ
                - 状況: {snapshot.formatted_state.summary}
                {chr(10).join(notes)}
                - 次の方針: {snapshot.reflection.summary}
                {f'- 参考プレイブック抜粋: {context_note}' if context_note else ''}
                """
            ).strip()
            deltas.append(
                PlaybookDelta(
                    target="alert_notes",
                    change_type="add",
                    content=content,
                    evidence=[snapshot.formatted_state.summary],
                    priority=0.6,
                    tags=["alert", "risk"],
                )
            )

        return deltas[: self.max_items]
