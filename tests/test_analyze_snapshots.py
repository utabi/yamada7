from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_snapshots import analyse_files


def create_snapshot_file(path: Path, rewards, targets):
    with path.open("w", encoding="utf-8") as fh:
        for reward in rewards:
            entry = {
                "reward": {"external": reward, "internal": 0.0},
                "playbook_updates": [{"target": t, "change_type": "add"} for t in targets],
                "playbook_stats": {"files": 1, "sections": 2, "characters": 100},
            }
            fh.write(json.dumps(entry) + "\n")


def test_analyse_files(tmp_path):
    file_path = tmp_path / "episode.jsonl"
    create_snapshot_file(file_path, rewards=[0.1, -0.2], targets=["alert_notes", "alert_notes"])

    report = analyse_files([file_path], top_targets=3)
    assert report["episodes"] == 1
    assert abs(report["average_total_reward"] - (-0.05)) < 1e-6
    assert report["playbook_top_targets"][0][0] == "alert_notes"
    assert report["playbook_stats_latest"]["files"] == 1
