#!/usr/bin/env python3
"""Run the yamada7 feedback loop with the built-in grid world simulator."""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from yamada7.config import ACEConfig, DEFAULT_CONFIG, LLMConfig, LoopConfig
from yamada7.core import (
    ExecutionEngine,
    FeedbackLoop,
    MemoryManager,
    ResultFormatter,
    RewardSynthesizer,
    StateFormatter,
    LoopSnapshot,
    ExecutionEvent,
)
from yamada7.env import GridWorldEnvironment
from yamada7.llm import ClaudeCodeClient, LLMThinker

try:
    from yamada7.ace import ACECurator, ACEReflector, PlaybookStore
except ImportError:  # pragma: no cover - fallback when ACE is not installed
    ACECurator = ACEReflector = PlaybookStore = None

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("yamada7.runner")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run yamada7 survival loop")
    parser.add_argument("--ticks", type=int, default=50, help="Maximum ticks to simulate")
    parser.add_argument("--dashboard", action="store_true", help="Start dashboard server")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for environment/thinker")
    parser.add_argument(
        "--llm-mode",
        choices=["heuristic", "claude-cli"],
        default="heuristic",
        help="LLM planner mode. 'claude-cli' は Claude Code CLI を呼び出す。",
    )
    parser.add_argument("--claude-binary", default=None, help="Claude Code CLI バイナリパス (例: claude)")
    parser.add_argument("--claude-model", default=None, help="Claude Code モデル名")
    parser.add_argument("--claude-timeout", type=int, default=None, help="Claude CLI タイムアウト秒数")
    parser.add_argument(
        "--claude-extra-arg",
        action="append",
        default=None,
        help="Claude CLI にそのまま渡す追加引数 (繰り返し指定可)",
    )
    parser.add_argument(
        "--claude-allow-permissions",
        action="store_true",
        help="--dangerously-skip-permissions を無効化する場合に指定。",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=1,
        help="実行するエピソード数。各エピソードは環境をリセットして再開する。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="ダッシュボードを起動せずにCLI実行のみ行う。",
    )
    parser.add_argument(
        "--save-run",
        default=None,
        help="スナップショットを保存するディレクトリ。未指定の場合は保存しない。",
    )
    parser.add_argument(
        "--save-report",
        default=None,
        help="集計結果をJSONで保存するパス。未指定の場合は標準出力のみ。",
    )
    parser.add_argument(
        "--linger",
        type=float,
        default=0.0,
        help="実行完了後に指定秒数だけプロセスを残す（ダッシュボード観察などに利用）。",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="JSONファイルからオプションを読み込む。CLI引数が優先される。",
    )
    parser.add_argument("--enable-ace", action="store_true", help="ACEプレイブック更新を有効化する")
    parser.add_argument(
        "--ace-mode",
        choices=["auto", "heuristic", "llm"],
        default="auto",
        help="ACE Reflector のモード。auto は LLM モードに追従。",
    )
    parser.add_argument("--playbook-root", default=None, help="プレイブック保存先ディレクトリ")
    parser.add_argument(
        "--playbook-refine-every",
        type=int,
        default=None,
        help="Grow-and-Refine を実行するターン間隔（0以下で無効）。",
    )
    parser.add_argument(
        "--ace-max-deltas",
        type=int,
        default=None,
        help="1ターンで適用するプレイブック差分の上限（未指定時は設定値を利用）。",
    )
    parser.add_argument(
        "--playbook-context-limit",
        type=int,
        default=None,
        help="計画生成時に参照するプレイブック断片の数 (default: config値)。",
    )
    parser.add_argument(
        "--playbook-context-chars",
        type=int,
        default=None,
        help="1断片あたりの最大文字数 (default: config値)。",
    )
    parser.add_argument(
        "--playbook-max-sections",
        type=int,
        default=None,
        help="Grow-and-Refine時に保持するセクション数 (default: config値)。",
    )
    return parser


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    defaults = parser.parse_args([])
    args = parser.parse_args(argv)
    if args.config:
        config_data = load_config_file(Path(args.config))
        apply_config_overrides(args, defaults, config_data)
    return args


def _extra_args(value: Optional[List[str]]) -> List[str]:
    if not value:
        return []
    return value


def build_config(args: argparse.Namespace) -> LoopConfig:
    llm_cfg = LLMConfig(
        mode=args.llm_mode,
        claude_binary=args.claude_binary or DEFAULT_CONFIG.llm.claude_binary,
        claude_model=args.claude_model or DEFAULT_CONFIG.llm.claude_model,
        claude_timeout=args.claude_timeout or DEFAULT_CONFIG.llm.claude_timeout,
        claude_extra_args=_extra_args(args.claude_extra_arg),
        claude_skip_permissions=not args.claude_allow_permissions,
    )
    ace_mode = args.ace_mode
    if ace_mode == "auto":
        ace_mode = "llm" if llm_cfg.mode == "claude-cli" else "heuristic"
    playbook_root = Path(args.playbook_root) if args.playbook_root else DEFAULT_CONFIG.ace.playbook_root
    refine_interval = (
        args.playbook_refine_every
        if args.playbook_refine_every is not None
        else DEFAULT_CONFIG.ace.refine_interval
    )
    max_deltas = (
        args.ace_max_deltas if args.ace_max_deltas is not None else DEFAULT_CONFIG.ace.max_deltas_per_tick
    )
    context_limit = (
        args.playbook_context_limit
        if args.playbook_context_limit is not None
        else DEFAULT_CONFIG.ace.playbook_context_limit
    )
    context_chars = (
        args.playbook_context_chars
        if args.playbook_context_chars is not None
        else DEFAULT_CONFIG.ace.playbook_context_chars
    )
    max_sections = (
        args.playbook_max_sections
        if args.playbook_max_sections is not None
        else DEFAULT_CONFIG.ace.playbook_max_sections
    )
    ace_cfg = ACEConfig(
        enabled=args.enable_ace,
        mode=ace_mode,
        playbook_root=playbook_root,
        refine_interval=max(0, refine_interval),
        max_deltas_per_tick=max(1, max_deltas),
        playbook_context_limit=max(1, context_limit),
        playbook_context_chars=max(80, context_chars),
        playbook_max_sections=max(1, max_sections),
    )
    cfg = LoopConfig(
        tick_limit=args.ticks,
        dashboard_host=DEFAULT_CONFIG.dashboard_host,
        dashboard_port=DEFAULT_CONFIG.dashboard_port,
        memory_root=DEFAULT_CONFIG.memory_root,
        playground_path=DEFAULT_CONFIG.playground_path,
        enabled_channels=DEFAULT_CONFIG.enabled_channels,
        llm=llm_cfg,
        ace=ace_cfg,
    )
    return cfg


def main():
    args = parse_args()
    config = build_config(args)

    if config.ace.enabled and (ACECurator is None or ACEReflector is None or PlaybookStore is None):
        raise RuntimeError("ACEモジュールが読み込めません。インストール状況を確認してください。")

    memory_path = Path(config.memory_root)
    memory_path.mkdir(parents=True, exist_ok=True)

    state_formatter = StateFormatter()
    result_formatter = ResultFormatter()
    reward_synthesizer = RewardSynthesizer()
    memory_manager = MemoryManager(root=memory_path)
    claude_client = None
    if config.llm.mode == "claude-cli":
        claude_client = ClaudeCodeClient(
            binary=config.llm.claude_binary,
            model=config.llm.claude_model,
            timeout=config.llm.claude_timeout,
            extra_args=config.llm.claude_extra_args,
            skip_permissions=config.llm.claude_skip_permissions,
        )
        logger.info(
            "Claude CLI モードを使用します (binary=%s, model=%s, timeout=%ss, extra=%s, skip_permissions=%s)",
            config.llm.claude_binary,
            config.llm.claude_model,
            config.llm.claude_timeout,
            config.llm.claude_extra_args,
            config.llm.claude_skip_permissions,
        )

    thinker = LLMThinker(config=config.llm, seed=args.seed, claude_client=claude_client)

    playbook_store = None
    ace_reflector = None
    ace_curator = None
    if config.ace.enabled:
        playbook_store = PlaybookStore(
            config.ace.playbook_root,
            context_limit=config.ace.playbook_context_limit,
            context_chars=config.ace.playbook_context_chars,
            max_sections=config.ace.playbook_max_sections,
        )
        ace_reflector = ACEReflector(
            mode=config.ace.mode,
            claude_client=claude_client if config.ace.mode == "llm" else None,
        )
        ace_curator = ACECurator(max_per_tick=config.ace.max_deltas_per_tick)

    dashboard_publisher = None
    if args.dashboard and not args.headless:
        try:
            from yamada7.dashboard import DashboardServer
        except ModuleNotFoundError as exc:  # pragma: no cover - missing optional dependency
            raise RuntimeError("ダッシュボードを利用するには fastapi と uvicorn が必要です。") from exc

        dashboard = DashboardServer(config=config)
        dashboard.run_in_thread()
        dashboard_publisher = dashboard.publisher()
        logger.info("Dashboard server running at http://%s:%s", config.dashboard_host, config.dashboard_port)

    summaries: List[Dict[str, float]] = []
    base_seed = args.seed
    save_root = Path(args.save_run) if args.save_run else None
    if save_root:
        save_root.mkdir(parents=True, exist_ok=True)

    for episode_index in range(max(1, args.episodes)):
        episode_seed = base_seed + episode_index
        environment = GridWorldEnvironment(seed=episode_seed)
        execution_engine = ExecutionEngine(allowed_actions=environment.action_schema)
        loop = FeedbackLoop(
            environment=environment,
            state_formatter=state_formatter,
            result_formatter=result_formatter,
            reward_synthesizer=reward_synthesizer,
            memory_manager=memory_manager,
            execution_engine=execution_engine,
            thinker=thinker,
            config=config,
            playbook_store=playbook_store,
            ace_reflector=ace_reflector,
            ace_curator=ace_curator,
        )
        if dashboard_publisher:
            loop.attach_dashboard(dashboard_publisher)

        snapshots = loop.run(max_ticks=config.tick_limit)
        summary = summarize_episode(snapshots, episode_index)
        summaries.append(summary)

        logger.info(
            "Episode %d finished: ticks=%s total_reward=%.3f final_life=%s final_unknown=%s",
            episode_index + 1,
            summary["ticks"],
            summary["total_reward"],
            summary["final_life"],
            summary["final_unknown"],
        )

        if save_root:
            save_episode_snapshots(save_root, episode_index, snapshots)

    report = aggregate_summaries(summaries)
    logger.info(
        "Aggregated: episodes=%d avg_ticks=%.2f avg_reward=%.3f",
        report["episodes"],
        report["avg_ticks"],
        report["avg_reward"],
    )
    if args.save_report:
        save_report(Path(args.save_report), report)

    if args.linger > 0:
        logger.info("Linger for %.1f seconds before exit", args.linger)
        time.sleep(args.linger)


def summarize_episode(snapshots: List[LoopSnapshot], episode_index: int) -> Dict[str, float]:
    if not snapshots:
        return {
            "episode": episode_index + 1,
            "ticks": 0,
            "total_reward": 0.0,
            "final_life": 0.0,
            "final_unknown": 0.0,
        }

    total_reward = sum(s.reward.external_reward + s.reward.internal_reward for s in snapshots)
    final = snapshots[-1]
    return {
        "episode": episode_index + 1,
        "ticks": len(snapshots),
        "total_reward": total_reward,
        "final_life": final.observation.data.get("life", 0.0),
        "final_unknown": final.observation.data.get("unknown", 0.0),
    }


def aggregate_summaries(summaries: List[Dict[str, float]]) -> Dict[str, float]:
    episodes = len(summaries)
    if episodes == 0:
        return {"episodes": 0, "avg_ticks": 0.0, "avg_reward": 0.0, "total_reward": 0.0}
    avg_ticks = sum(item["ticks"] for item in summaries) / episodes
    avg_reward = sum(item["total_reward"] for item in summaries) / episodes
    total_reward = sum(item["total_reward"] for item in summaries)
    return {
        "episodes": episodes,
        "avg_ticks": avg_ticks,
        "avg_reward": avg_reward,
        "total_reward": total_reward,
    }


def save_report(path: Path, report: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def load_config_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def apply_config_overrides(args: argparse.Namespace, defaults: argparse.Namespace, config_data: Dict[str, Any]):
    for key, value in config_data.items():
        if not hasattr(args, key):
            continue
        if getattr(args, key) == getattr(defaults, key):
            setattr(args, key, value)


def save_episode_snapshots(root: Path, episode_index: int, snapshots: List[LoopSnapshot]):
    if not snapshots:
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    file_path = root / f"episode-{episode_index + 1}-{timestamp}.jsonl"
    with file_path.open("w", encoding="utf-8") as fh:
        for snapshot in snapshots:
            fh.write(json.dumps(serialize_snapshot(snapshot), ensure_ascii=False) + "\n")


def serialize_snapshot(snapshot: LoopSnapshot) -> Dict:
    def serialize_events(events: List[ExecutionEvent]) -> List[Dict[str, Any]]:
        return [
            {
                "timestamp": event.timestamp.isoformat(),
                "channel": event.channel.value,
                "payload": event.payload,
            }
            for event in events
        ]

    return {
        "tick": snapshot.tick,
        "observation": asdict(snapshot.observation),
        "formatted_state": {
            "summary": snapshot.formatted_state.summary,
            "slots": snapshot.formatted_state.slots,
            "memory_highlights": snapshot.formatted_state.memory_highlights,
        },
        "action_plan": {
            "intent": snapshot.action_plan.intent,
            "sub_goals": snapshot.action_plan.sub_goals,
            "actions": [
                {
                    "action_id": action.action_id,
                    "parameters": action.parameters,
                    "confidence": action.confidence,
                    "risk_estimate": action.risk_estimate,
                }
                for action in snapshot.action_plan.actions
            ],
            "notes": snapshot.action_plan.notes,
        },
        "reward": {
            "external": snapshot.reward.external_reward,
            "internal": snapshot.reward.internal_reward,
            "components": snapshot.reward.components,
        },
        "reflection": {
            "summary": snapshot.reflection.summary,
            "alert_updates": snapshot.reflection.fear_updates,
            "exploration_updates": snapshot.reflection.curiosity_updates,
            "next_bias": snapshot.reflection.next_bias,
        },
        "events": serialize_events(snapshot.events),
        "playbook_updates": snapshot.playbook_updates,
        "playbook_stats": snapshot.playbook_stats,
    }


if __name__ == "__main__":
    main()
