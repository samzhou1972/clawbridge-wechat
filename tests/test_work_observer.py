import json
from pathlib import Path

from steerwx.observers.work import (
    format_result,
    format_status,
    latest_work,
    latest_work_for_project,
    parse_work_rollout,
)


def _write_rollout(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def test_parse_completed_work_rollout(tmp_path: Path) -> None:
    path = tmp_path / "2026" / "08" / "26" / "rollout-test.jsonl"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "session_id": "session-1",
                "originator": "codex_work_desktop",
                "cwd": r"D:\code\example",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-1",
                "started_at": 1_787_720_000,
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "AgentMessage",
                    "content": [{"type": "Text", "text": "正在执行测试"}],
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-1",
                "started_at": 1_787_720_000,
                "completed_at": 1_787_720_060,
                "last_agent_message": "全部完成，测试通过。",
            },
        },
    ]
    _write_rollout(path, records)

    snapshot = parse_work_rollout(path)
    assert snapshot is not None
    assert snapshot.state == "complete"
    assert snapshot.cwd == r"D:\code\example"
    assert snapshot.turn_id == "turn-1"
    assert snapshot.result == "全部完成，测试通过。"
    assert "COMPLETE" in format_status(snapshot)
    assert "全部完成" in format_result(snapshot)


def test_latest_work_skips_non_work_rollout(tmp_path: Path) -> None:
    non_work = tmp_path / "2026" / "08" / "26" / "rollout-new.jsonl"
    work = tmp_path / "2026" / "08" / "25" / "rollout-old.jsonl"
    _write_rollout(
        non_work,
        [{"type": "session_meta", "payload": {"originator": "codex_cli"}}],
    )
    _write_rollout(
        work,
        [
            {
                "type": "session_meta",
                "payload": {
                    "session_id": "work-2",
                    "originator": "codex_work_desktop",
                    "cwd": r"D:\code\work",
                },
            },
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t2"}},
        ],
    )
    snapshot = latest_work(tmp_path)
    assert snapshot is not None
    assert snapshot.session_id == "work-2"
    assert snapshot.state == "running"


def test_latest_work_for_project_skips_newer_other_project(tmp_path: Path) -> None:
    other = tmp_path / "2026" / "08" / "26" / "rollout-other.jsonl"
    matching = tmp_path / "2026" / "08" / "25" / "rollout-match.jsonl"
    for path, session, cwd in (
        (other, "other", r"D:\code\other"),
        (matching, "match", r"D:\code\steerwx"),
    ):
        _write_rollout(path, [{
            "type": "session_meta",
            "payload": {"session_id": session, "originator": "codex_work_desktop", "cwd": cwd},
        }])
    other.touch()
    snapshot = latest_work_for_project(Path(r"D:\code\steerwx"), tmp_path)
    assert snapshot is not None
    assert snapshot.session_id == "match"
