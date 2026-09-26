from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from steerwx.observers.work import WorkSnapshot, latest_work_for_project


WORK_KEYWORDS = (
    "work", "任务", "进展", "执行到哪", "运行情况", "当前任务", "完成了吗", "结果",
)
GIT_KEYWORDS = (
    "git", "分支", "branch", "commit", "提交", "未提交", "working tree", "工作区",
    "改动", "修改文件",
)


@dataclass(frozen=True, slots=True)
class ContextSelection:
    work: bool
    git: bool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(name for name, selected in (("Work", self.work), ("Git", self.git)) if selected)


@dataclass(frozen=True, slots=True)
class ProjectContext:
    project: str
    root: Path
    selection: ContextSelection
    envelope: str
    warnings: tuple[str, ...] = ()


def select_context(message: str) -> ContextSelection:
    value = message.casefold()
    git = any(keyword in value for keyword in GIT_KEYWORDS)
    work = any(keyword in value for keyword in WORK_KEYWORDS)
    if "状态" in value and not git:
        work = True
    return ContextSelection(work=work, git=git)


def _local_time(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def format_work(snapshot: WorkSnapshot | None) -> str:
    if snapshot is None:
        return "\n".join((
            "status: NO_MATCH",
            "scope: active/recent",
            "meaning: No matching Work task was found by the current observer for this project.",
            "limitation: This does not prove that no Work task exists.",
        ))
    lines = [
        f"State: {snapshot.state}",
        f"Cwd: {snapshot.cwd or '-'}",
        f"Updated at: {_local_time(snapshot.updated_at)}",
        f"Last message: {snapshot.last_message or '-'}",
        f"Result: {snapshot.result or '-'}",
    ]
    return "\n".join(lines)


class WorkContextProvider:
    def __init__(self, loader: Callable[[Path], WorkSnapshot | None] = latest_work_for_project) -> None:
        self.loader = loader

    def read(self, project_root: Path) -> str:
        return format_work(self.loader(project_root))


class GitContextProvider:
    @staticmethod
    def _run(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )

    def read(self, project_root: Path) -> str:
        results: dict[str, subprocess.CompletedProcess[str] | Exception] = {}
        for name, arguments in (
            ("status", ("status", "--porcelain")),
            ("branch", ("branch", "--show-current")),
            ("commit", ("log", "-1", "--pretty=%h%x09%s")),
        ):
            try:
                results[name] = self._run(project_root, *arguments)
            except Exception as exc:
                results[name] = exc

        completed = [value for value in results.values() if isinstance(value, subprocess.CompletedProcess)]
        combined = "\n".join(
            f"{value.stdout}\n{value.stderr}" for value in completed
        ).casefold()
        if "not a git repository" in combined:
            return "status: NOT_A_GIT_REPOSITORY"

        status = results["status"]
        branch = results["branch"]
        commit = results["commit"]
        status_ok = isinstance(status, subprocess.CompletedProcess) and status.returncode == 0
        branch_ok = isinstance(branch, subprocess.CompletedProcess) and branch.returncode == 0
        commit_ok = isinstance(commit, subprocess.CompletedProcess) and commit.returncode == 0
        no_commits = (
            isinstance(commit, subprocess.CompletedProcess)
            and commit.returncode != 0
            and "does not have any commits yet" in f"{commit.stdout}\n{commit.stderr}".casefold()
        )
        reliable = sum((status_ok, branch_ok, commit_ok or no_commits))
        overall = "OK" if reliable == 3 and commit_ok else "PARTIAL" if reliable else "UNAVAILABLE"
        lines = [f"status: {overall}"]
        lines.append(
            f"branch: {branch.stdout.strip() or '(detached)'}" if branch_ok else "branch: NOT_AVAILABLE"
        )
        if status_ok:
            changes = [line for line in status.stdout.splitlines() if line]
            lines.extend((
                f"working_tree: {'CLEAN' if not changes else 'DIRTY'}",
                f"changed_file_count: {len(changes)}",
            ))
        else:
            lines.extend(("working_tree: NOT_AVAILABLE", "changed_file_count: NOT_AVAILABLE"))
        if commit_ok:
            commit_parts = commit.stdout.strip().split("\t", 1)
            lines.extend((
                f"last_commit_short_hash: {commit_parts[0] if commit_parts else '-'}",
                f"last_commit_subject: {commit_parts[1] if len(commit_parts) > 1 else '-'}",
            ))
        elif no_commits:
            lines.extend(("last_commit_status: NOT_AVAILABLE", "last_commit_reason: NO_COMMITS"))
        else:
            lines.extend(("last_commit_status: NOT_AVAILABLE", "last_commit_reason: COMMAND_FAILED"))
        return "\n".join(lines)


def build_project_context(
    project: str,
    root: Path,
    message: str,
    *,
    work_provider: WorkContextProvider | None = None,
    git_provider: GitContextProvider | None = None,
) -> ProjectContext:
    selection = select_context(message)
    blocks = [f"Project:\n{project}", f"Root:\n{root}"]
    warnings: list[str] = []
    if selection.work:
        try:
            work = (work_provider or WorkContextProvider()).read(root)
        except Exception as exc:
            work = f"Work context unavailable: {exc}"
            warnings.append(work)
        blocks.append(f"Work:\n{work}")
    if selection.git:
        try:
            git = (git_provider or GitContextProvider()).read(root)
        except Exception as exc:
            git = f"Git context unavailable: {exc}"
            warnings.append(git)
        blocks.append(f"Git:\n{git}")
    envelope = "[SteerWX Local Facts]\n\n" + "\n\n".join(blocks)
    envelope += f"\n\n[User Message]\n{message}"
    return ProjectContext(project, root, selection, envelope, tuple(warnings))
