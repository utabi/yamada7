from __future__ import annotations

import json
import shlex
import subprocess
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..core.models import ActionCandidate, ActionPlan, Reflection


def _extract_json_blob(text: str) -> str:
    """Best-effort extraction of the first JSON object present in text."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise ValueError("JSON blob not found in Claude response")


def _coerce_float(value: Optional[float], default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class ClaudeCodeClient:
    """Bridge for invoking Claude Code CLI with structured prompts."""

    binary: str = "claude"
    model: str = "claude-4-5-sonnet-latest"
    timeout: int = 90
    extra_args: List[str] = field(default_factory=list)
    skip_permissions: bool = True

    def generate_plan(
        self,
        formatted_state: Dict,
        allowed_actions: List[str],
        memory_blurbs: Dict[str, List[str]],
    ) -> Tuple[Optional[ActionPlan], Optional[Reflection]]:
        prompt = self._build_prompt(formatted_state, allowed_actions, memory_blurbs)
        response = self._invoke(prompt)
        if not response:
            return None, None
        plan_dict = response.get("plan")
        reflection_dict = response.get("reflection")
        plan = self._plan_from_dict(plan_dict) if plan_dict else None
        reflection = self._reflection_from_dict(reflection_dict) if reflection_dict else None
        return plan, reflection

    # internal helpers
    def _build_prompt(self, state: Dict, allowed_actions: List[str], memory: Dict[str, List[str]]) -> str:
        template = textwrap.dedent(
            """
            あなたは自分の生存を最優先するエージェントの頭脳です。
            現在の状態と利用できるアクション候補、警戒ログと探査ログを渡します。
            以下のJSON形式のみで回答してください。

            {{
              "plan": {{
                "intent": string,
                "sub_goals": [string],
                "actions": [
                  {{"action_id": string, "parameters": object, "confidence": number, "risk_estimate": number}}
                ],
                "notes": string
              }},
              "reflection": {{
                "summary": string,
                "fear_updates": [string],
                "curiosity_updates": [string],
                "next_bias": {{"risk_tolerance": number, "explore_priority": number}}
              }}
            }}

            状態: {state}
            アクション: {actions}
            メモ: {memory}
            """
        ).strip()
        rendered = template.format(
            state=json.dumps(state, ensure_ascii=False),
            actions=json.dumps(allowed_actions, ensure_ascii=False),
            memory=json.dumps(memory, ensure_ascii=False),
        )
        return rendered

    def _invoke(self, prompt: str) -> Optional[Dict]:
        cmd = [
            self.binary,
            "code",
            "--model",
            self.model,
            "--output-format",
            "json",
        ]
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if self.extra_args:
            cmd.extend(self.extra_args)

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Claude CLI '{shlex.join(cmd)}' が見つかりません。インストールを確認してください。") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Claude CLI 呼び出しがタイムアウトしました。") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI がエラー終了しました (code={result.returncode}). stderr={result.stderr.strip()}"
            )

        output = result.stdout.strip()
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            blob = _extract_json_blob(output)
            data = json.loads(blob)
        return data

    @staticmethod
    def _plan_from_dict(data: Dict) -> ActionPlan:
        actions = []
        for entry in data.get("actions", []):
            actions.append(
                ActionCandidate(
                    action_id=entry.get("action_id", "wait"),
                    parameters=entry.get("parameters") or {},
                    confidence=_coerce_float(entry.get("confidence"), 0.5),
                    risk_estimate=_coerce_float(entry.get("risk_estimate"), 0.5),
                )
            )
        return ActionPlan(
            intent=data.get("intent", "unknown"),
            sub_goals=list(entry for entry in data.get("sub_goals", []) if isinstance(entry, str)),
            actions=actions,
            notes=data.get("notes"),
        )

    @staticmethod
    def _reflection_from_dict(data: Dict) -> Reflection:
        bias = data.get("next_bias") or {}
        return Reflection(
            summary=data.get("summary", ""),
            fear_updates=[entry for entry in data.get("fear_updates", []) if isinstance(entry, str)],
            curiosity_updates=[entry for entry in data.get("curiosity_updates", []) if isinstance(entry, str)],
            next_bias={
                "risk_tolerance": _coerce_float(bias.get("risk_tolerance"), 0.4),
                "explore_priority": _coerce_float(bias.get("explore_priority"), 0.5),
            },
        )
