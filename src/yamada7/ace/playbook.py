from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..core.models import Channel, ExecutionEvent


@dataclass
class PlaybookDelta:
    """Reflectorが生成するプレイブック差分。"""

    target: str
    change_type: str  # add / update / retire
    content: str
    evidence: List[str] = field(default_factory=list)
    priority: float = 0.5
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "target": self.target,
            "change_type": self.change_type,
            "content": self.content,
            "evidence": self.evidence,
            "priority": self.priority,
            "tags": self.tags,
        }


@dataclass
class AppliedDelta:
    delta: PlaybookDelta
    status: str  # applied / skipped / deferred
    reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "target": self.delta.target,
            "change_type": self.delta.change_type,
            "status": self.status,
            "reason": self.reason,
            "priority": self.delta.priority,
            "tags": self.delta.tags,
            "content": self.delta.content,
        }


SEPARATOR = "\n\n---\n\n"


class PlaybookStore:
    """ACEが利用するプレイブック保存領域の管理。"""

    def __init__(
        self,
        root: Path,
        *,
        context_limit: int = 3,
        context_chars: int = 400,
        max_sections: int = 6,
    ):
        self.root = root
        self.context_limit = context_limit
        self.context_chars = context_chars
        self.max_sections = max_sections
        self.current_dir = self.root / "current"
        self.delta_dir = self.root / "deltas"
        self.archive_dir = self.root / "archive"
        self.metadata_file = self.root / "metadata.json"
        self.delta_log = self.delta_dir / "history.jsonl"
        self._ensure_structure()

    def _ensure_structure(self):
        for path in [self.root, self.current_dir, self.delta_dir, self.archive_dir]:
            path.mkdir(parents=True, exist_ok=True)
        if not self.metadata_file.exists():
            self.metadata_file.write_text(json.dumps({"version": 1, "created_at": datetime.utcnow().isoformat()}), encoding="utf-8")

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def get_context(self) -> List[str]:
        candidates = sorted(self.current_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        snippets: List[str] = []
        for path in candidates[: self.context_limit]:
            text = path.read_text(encoding="utf-8").strip()
            snippets.append(text[: self.context_chars])
        return snippets

    def contains(self, delta: PlaybookDelta) -> bool:
        target_path = self._target_path(delta.target)
        if not target_path.exists():
            return False
        text = target_path.read_text(encoding="utf-8")
        return delta.content.strip() in text

    def apply_deltas(self, deltas: Iterable[PlaybookDelta], tick: int) -> Tuple[List[AppliedDelta], List[ExecutionEvent]]:
        applied: List[AppliedDelta] = []
        events: List[ExecutionEvent] = []
        for delta in deltas:
            record = self._apply_single(delta)
            applied.append(record)
            self._append_delta_log(delta, tick, record.status, record.reason)
            events.append(
                ExecutionEvent(
                    timestamp=datetime.utcnow(),
                    channel=Channel.EVENTS,
                    payload={
                        "level": "info" if record.status == "applied" else "warn",
                        "message": f"Playbook {record.status}: {delta.target}",
                        "target": delta.target,
                        "status": record.status,
                        "reason": record.reason,
                        "tick": tick,
                    },
                )
            )
        return applied, events

    def refine(self, note: str) -> ExecutionEvent:
        pruned_sections = 0
        archived_files: List[str] = []
        for path in self.current_dir.glob("*.md"):
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            sections = [segment.strip() for segment in content.split(SEPARATOR) if segment.strip()]
            if len(sections) <= self.max_sections:
                continue
            keep = sections[-self.max_sections :]
            retired = sections[: -self.max_sections]
            path.write_text(SEPARATOR.join(keep) + "\n", encoding="utf-8")
            archive_path = self._archive_path(path.stem + "_refine")
            archive_path.write_text(SEPARATOR.join(retired) + "\n", encoding="utf-8")
            pruned_sections += len(retired)
            archived_files.append(path.name)
        timestamp = datetime.utcnow()
        payload = {
            "level": "info",
            "message": f"Playbook refined: {note}",
            "pruned_sections": pruned_sections,
            "files": archived_files,
        }
        return ExecutionEvent(timestamp=timestamp, channel=Channel.LOGS, payload=payload)

    def stats(self) -> Dict[str, int]:
        files = list(self.current_dir.glob("*.md"))
        sections = 0
        characters = 0
        for path in files:
            text = path.read_text(encoding="utf-8")
            characters += len(text)
            if text.strip():
                sections += len([segment for segment in text.split(SEPARATOR) if segment.strip()])
        return {
            "files": len(files),
            "sections": sections,
            "characters": characters,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _apply_single(self, delta: PlaybookDelta) -> AppliedDelta:
        target_path = self._target_path(delta.target)
        if delta.change_type not in {"add", "update", "retire"}:
            return AppliedDelta(delta=delta, status="skipped", reason="unsupported_change_type")

        if delta.change_type == "retire":
            if not target_path.exists():
                return AppliedDelta(delta=delta, status="skipped", reason="target_not_found")
            archive_path = self._archive_path(delta.target)
            archive_path.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")
            target_path.unlink(missing_ok=True)
            return AppliedDelta(delta=delta, status="applied")

        # add / update
        existing = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        if delta.content.strip() in existing:
            return AppliedDelta(delta=delta, status="skipped", reason="duplicate_content")

        new_text = self._compose_text(existing, delta.content, delta.change_type)
        target_path.write_text(new_text, encoding="utf-8")
        return AppliedDelta(delta=delta, status="applied")

    def _compose_text(self, existing: str, content: str, change_type: str) -> str:
        if not existing.strip():
            header = ""
            return header + content.strip() + "\n"
        return existing.rstrip() + SEPARATOR + content.strip() + "\n"

    def _append_delta_log(self, delta: PlaybookDelta, tick: int, status: str, reason: Optional[str]):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "tick": tick,
            "status": status,
            "reason": reason,
            **delta.to_dict(),
        }
        with self.delta_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _target_path(self, target: str) -> Path:
        safe = target.replace("/", "_")
        return self.current_dir / f"{safe}.md"

    def _archive_path(self, target: str) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        safe = target.replace("/", "_")
        return self.archive_dir / f"{safe}_{timestamp}.md"
