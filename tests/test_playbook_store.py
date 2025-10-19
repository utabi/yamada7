from __future__ import annotations

from pathlib import Path

from yamada7.ace.playbook import PlaybookDelta, PlaybookStore


def make_store(tmp_path: Path) -> PlaybookStore:
    return PlaybookStore(
        root=tmp_path,
        context_limit=2,
        context_chars=200,
        max_sections=3,
    )


def test_apply_delta_add_and_stats(tmp_path):
    store = make_store(tmp_path)
    delta = PlaybookDelta(
        target="survival_playbook",
        change_type="add",
        content="## demo\n- foo\n",
        priority=0.8,
    )

    applied, events = store.apply_deltas([delta], tick=1)
    assert len(applied) == 1
    assert applied[0].status == "applied"
    assert events and events[0].payload["status"] == "applied"

    context = store.get_context()
    assert context and "demo" in context[0]

    stats = store.stats()
    assert stats["files"] == 1
    assert stats["sections"] == 1


def test_refine_archives_old_sections(tmp_path):
    store = make_store(tmp_path)
    target = "alert_notes"
    for idx in range(5):
        delta = PlaybookDelta(
            target=target,
            change_type="add",
            content=f"## note {idx}\n- example\n",
        )
        store.apply_deltas([delta], tick=idx)

    event = store.refine(note="test")
    assert event.payload["level"] == "info"
    stats = store.stats()
    assert stats["sections"] <= store.max_sections
    archive_files = list((tmp_path / "archive").glob("*.md"))
    assert archive_files, "refine should move old sections into archive"
