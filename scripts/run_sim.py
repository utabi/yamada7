#!/usr/bin/env python3
"""Run the yamada7 feedback loop with the built-in grid world simulator."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from yamada7.config import DEFAULT_CONFIG, LLMConfig, LoopConfig
from yamada7.core import (
    ExecutionEngine,
    FeedbackLoop,
    MemoryManager,
    ResultFormatter,
    RewardSynthesizer,
    StateFormatter,
)
from yamada7.dashboard import DashboardServer
from yamada7.env import GridWorldEnvironment
from yamada7.llm import ClaudeCodeClient, LLMThinker

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("yamada7.runner")


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


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
    cfg = LoopConfig(
        tick_limit=args.ticks,
        dashboard_host=DEFAULT_CONFIG.dashboard_host,
        dashboard_port=DEFAULT_CONFIG.dashboard_port,
        memory_root=DEFAULT_CONFIG.memory_root,
        playground_path=DEFAULT_CONFIG.playground_path,
        enabled_channels=DEFAULT_CONFIG.enabled_channels,
        llm=llm_cfg,
    )
    return cfg


def main():
    args = parse_args()
    config = build_config(args)

    memory_path = Path(config.memory_root)
    memory_path.mkdir(parents=True, exist_ok=True)

    environment = GridWorldEnvironment(seed=args.seed)
    state_formatter = StateFormatter()
    result_formatter = ResultFormatter()
    reward_synthesizer = RewardSynthesizer()
    memory_manager = MemoryManager(root=memory_path)
    execution_engine = ExecutionEngine(allowed_actions=environment.action_schema)
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

    loop = FeedbackLoop(
        environment=environment,
        state_formatter=state_formatter,
        result_formatter=result_formatter,
        reward_synthesizer=reward_synthesizer,
        memory_manager=memory_manager,
        execution_engine=execution_engine,
        thinker=thinker,
        config=config,
    )

    if args.dashboard:
        dashboard = DashboardServer(config=config)
        dashboard.run_in_thread()
        loop.attach_dashboard(dashboard.publisher())
        logger.info("Dashboard server running at http://%s:%s", config.dashboard_host, config.dashboard_port)

    snapshots = loop.run(max_ticks=config.tick_limit)
    logger.info("Simulation completed with %d snapshots", len(snapshots))

    if snapshots:
        last = snapshots[-1]
        logger.info(
            "Final state: tick=%s life=%s resources=%s danger=%s unknown=%s reward=%.3f",
            last.tick,
            last.observation.data.get("life"),
            last.observation.data.get("resources"),
            last.observation.data.get("danger"),
            last.observation.data.get("unknown"),
            last.reward.external_reward + last.reward.internal_reward,
        )


if __name__ == "__main__":
    main()
