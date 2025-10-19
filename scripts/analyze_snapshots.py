#!/usr/bin/env python3
"""Summarise yamada7 ACE snapshot logs (JSONL) produced by run_sim.py."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyse yamada7 run logs")
    parser.add_argument(
        "path",
        nargs="+",
        help="JSONL ファイルまたはディレクトリ (複数指定可)。ディレクトリの場合は *.jsonl を再帰的に読み込む。",
    )
    parser.add_argument(
        "--top-playbook-targets",
        type=int,
        default=5,
        help="プレイブック更新対象の上位N件を表示 (default: 5)。",
    )
    return parser.parse_args()


def collect_files(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for item in paths:
        path = Path(item)
        if not path.exists():
            raise FileNotFoundError(f"入力パスが存在しません: {item}")
        if path.is_file():
            files.append(path)
        else:
            files.extend(sorted(path.rglob("*.jsonl")))
    return files


def analyse_files(files: Iterable[Path], top_targets: int) -> Dict[str, Any]:
    episodes = 0
    ticks = 0
    total_reward = 0.0
    playbook_counter = Counter()
    stats_history: List[Dict[str, Any]] = []

    for file_path in files:
        episode_ticks = 0
        episode_reward = 0.0
        with file_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                episode_ticks += 1
                snapshot_reward = data.get("reward", {}).get("external", 0.0) + data.get("reward", {}).get("internal", 0.0)
                episode_reward += snapshot_reward
                for update in data.get("playbook_updates", []):
                    playbook_counter.update([update.get("target", "unknown")])
                stats = data.get("playbook_stats")
                if stats:
                    stats_history.append(stats)
        if episode_ticks == 0:
            continue
        episodes += 1
        ticks += episode_ticks
        total_reward += episode_reward

    aggregated_stats = {
        "episodes": episodes,
        "average_ticks": ticks / episodes if episodes else 0,
        "average_total_reward": total_reward / episodes if episodes else 0.0,
        "playbook_top_targets": playbook_counter.most_common(top_targets) if episodes else [],
        "playbook_stats_latest": stats_history[-1] if stats_history else {},
    }
    return aggregated_stats


def main():
    args = parse_args()
    files = collect_files(args.path)
    if not files:
        print("対象となるJSONLファイルが見つかりませんでした。")
        return
    report = analyse_files(files, args.top_playbook_targets)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
