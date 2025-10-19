from argparse import Namespace
from pathlib import Path
import json

import scripts.run_sim as run_sim


def test_apply_config_overrides(tmp_path):
    parser = run_sim.build_parser()
    defaults = parser.parse_args([])
    args = parser.parse_args(["--ticks", "10"])  # CLI override
    config_path = tmp_path / "run_config.json"
    config_data = {
        "ticks": 99,
        "episodes": 3,
        "enable_ace": True,
        "linger": 15,
        "tick_delay": 5.0,
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    run_sim.apply_config_overrides(args, defaults, config_data)
    assert args.ticks == 10  # CLI should win
    assert args.episodes == 3
    assert args.enable_ace is True
    assert args.linger == 15
    assert args.tick_delay == 5.0


def test_parse_args_with_config(tmp_path):
    config = {
        "ticks": 70,
        "headless": True,
        "linger": 5,
        "tick_delay": 1.5,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    args = run_sim.parse_args(["--config", str(config_path)])
    assert args.ticks == 70
    assert args.headless is True
    assert args.linger == 5
    assert args.tick_delay == 1.5
