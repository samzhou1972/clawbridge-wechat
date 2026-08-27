from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

WORK_ORIGINATOR = "codex_work_desktop"


@dataclass(slots=True)
class WorkSnapshot:
    session_id: str
    turn_id: str | None
    cwd: str | None
    state: str
    started_at: float | None
    completed_at: float | None
    updated_at: float
    last_message: str | None
    result: str | None
    source_path: Path

    @property
    def task_key(self) -> str:
        return f"{self.session_id}:{self.turn_id or '-'}"


def default_sessions_root() -> Path:
    override = os.getenv("CLAWBRIDGE_CODEX_SESSIONS")
    if override:
        return Path(override)
    return Path.home() / ".codex" / "sessions"


def _iter_recent_rollouts(root: Path, limit: int = 50) -> Iterable[Path]:
    if not root.exists():
        return []
    files = sorted(
        root.rglob("rollout-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[:limit]


def _read_json_lines(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def parse_work_rollout(path: Path) -> WorkSnapshot | None:
    records = _read_json_lines(path)
    if not records:
        return None
    meta = records[0]
    if meta.get("type") != "session_meta":
        return None
    payload = meta.get("payload") or {}
    if payload.get("originator") != WORK_ORIGINATOR:
        return None

    session_id = payload.get("session_id") or payload.get("id") or path.stem
    cwd = payload.get("cwd")
    state = "idle"
    turn_id: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    last_message: str | None = None
    result: str | None = None
    event_updated_at: float | None = None

    for record in records:
        record_time = _iso_seconds(record.get("timestamp"))
        if record_time is not None:
            event_updated_at = record_time
        if record.get("type") != "event_msg":
            continue
        event = record.get("payload") or {}
        event_type = str(event.get("type") or "")
        if event_type == "task_started":
            turn_id = event.get("turn_id")
            started_at = _as_seconds(event.get("started_at"))
            completed_at = None
            result = None
            state = "running"
        elif event_type == "item_completed":
            item = event.get("item") or {}
            if item.get("type") == "AgentMessage":
                content = item.get("content") or []
                text_parts = [
                    part.get("text")
                    for part in content
                    if isinstance(part, dict) and part.get("type") in {"Text", "text"}
                ]
                text = "\n".join(part for part in text_parts if part)
                if text:
                    last_message = text
        elif event_type == "task_complete":
            turn_id = event.get("turn_id") or turn_id
            started_at = _as_seconds(event.get("started_at")) or started_at
            completed_at = _as_seconds(event.get("completed_at"))
            result = event.get("last_agent_message") or last_message
            if result:
                last_message = result
            state = "complete"
        elif any(word in event_type for word in ("failed", "aborted", "error")):
            state = "failed"

    return WorkSnapshot(
        session_id=session_id,
        turn_id=turn_id,
        cwd=cwd,
        state=state,
        started_at=started_at,
        completed_at=completed_at,
        updated_at=event_updated_at or path.stat().st_mtime,
        last_message=last_message,
        result=result,
        source_path=path,
    )


def _iso_seconds(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _as_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric / 1000 if numeric > 10_000_000_000 else numeric


def latest_work(root: Path | None = None) -> WorkSnapshot | None:
    sessions_root = root or default_sessions_root()
    for path in _iter_recent_rollouts(sessions_root):
        snapshot = parse_work_rollout(path)
        if snapshot is not None:
            return snapshot
    return None


def latest_work_for_project(project_root: Path, root: Path | None = None) -> WorkSnapshot | None:
    """Return the newest Work snapshot whose cwd is the selected project root."""
    sessions_root = root or default_sessions_root()
    expected = os.path.normcase(os.path.abspath(project_root))
    for path in _iter_recent_rollouts(sessions_root):
        snapshot = parse_work_rollout(path)
        if snapshot is None or not snapshot.cwd:
            continue
        actual = os.path.normcase(os.path.abspath(snapshot.cwd))
        if actual == expected:
            return snapshot
    return None


def _local_time(value: float | None) -> str:
    if value is None:
        return "未知"
    return datetime.fromtimestamp(value).astimezone().strftime("%m-%d %H:%M:%S")


def _truncate(text: str | None, limit: int = 900) -> str:
    if not text:
        return "暂无"
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def format_status(snapshot: WorkSnapshot | None) -> str:
    if snapshot is None:
        return "未发现可识别的 Work 任务。"
    lines = [
        f"Work 状态：{snapshot.state.upper()}",
        f"项目：{snapshot.cwd or '未知'}",
        f"开始：{_local_time(snapshot.started_at)}",
        f"最后活动：{_local_time(snapshot.updated_at)}",
    ]
    if snapshot.completed_at:
        lines.append(f"完成：{_local_time(snapshot.completed_at)}")
    lines.append(f"进度：{_truncate(snapshot.last_message, 500)}")
    return "\n".join(lines)


def format_last(snapshot: WorkSnapshot | None) -> str:
    if snapshot is None:
        return "未发现可识别的 Work 任务。"
    return (
        f"最近 Work：{snapshot.state.upper()}\n"
        f"项目：{snapshot.cwd or '未知'}\n"
        f"最后活动：{_local_time(snapshot.updated_at)}\n"
        f"{_truncate(snapshot.last_message)}"
    )


def format_result(snapshot: WorkSnapshot | None) -> str:
    if snapshot is None:
        return "未发现可识别的 Work 任务。"
    if snapshot.state != "complete":
        return f"最近 Work 尚未完成，当前状态：{snapshot.state.upper()}。"
    return (
        f"任务：{snapshot.turn_id or snapshot.session_id}\n"
        "状态：完成\n"
        f"摘要：{_truncate(snapshot.result, 700)}\n"
        "详细结果请在 PC 端查看。"
    )
