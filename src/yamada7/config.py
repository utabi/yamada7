from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class LLMConfig:
    """Configuration for LLM planner integration."""

    mode: str = "heuristic"  # or "claude-cli"
    claude_binary: str = "claude"
    claude_model: str = "claude-4-5-sonnet-latest"
    claude_timeout: int = 90
    claude_extra_args: List[str] = field(default_factory=list)
    claude_skip_permissions: bool = True


@dataclass
class LoopConfig:
    """Config handles runtime parameters for the main feedback loop."""

    tick_limit: int = 100
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    memory_root: Path = Path("./data/memory")
    playground_path: Path = Path("./playground")
    enabled_channels: List[str] = field(default_factory=lambda: ["state", "actions", "metrics"])
    llm: LLMConfig = field(default_factory=LLMConfig)


DEFAULT_CONFIG = LoopConfig()
