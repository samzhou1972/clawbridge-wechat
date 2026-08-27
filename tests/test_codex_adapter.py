from pathlib import Path
import subprocess

import pytest

import clawbridge.adapters.codex as codex
from clawbridge.config import AppConfig, ChatConfig


def configured(tmp_path: Path, projects: dict[str, Path]) -> AppConfig:
    return AppConfig(
        code_root=tmp_path,
        codex_executable=None,
        chat=ChatConfig(profile_dir=tmp_path / "profile"),
        projects=projects,
        config_path=tmp_path / "config.toml",
    )


def test_run_readonly_closes_stdin(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    monkeypatch.setattr(codex, "find_codex", lambda: Path("codex"))

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        output = Path(command[command.index("-o") + 1])
        output.write_text("M2_OK", encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    result = codex.run_readonly(
        "demo", "inspect", timeout=5, config=configured(tmp_path, {"demo": tmp_path})
    )
    assert result.ok
    assert result.message == "M2_OK"
    assert captured["stdin"] is subprocess.DEVNULL


def test_run_readonly_uses_configured_project_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "configured-root"
    root.mkdir()
    captured = {}
    monkeypatch.setattr(codex, "find_codex", lambda: Path("codex"))

    def fake_run(command, **kwargs):
        captured["command"] = command
        Path(command[command.index("-o") + 1]).write_text("OK", encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    result = codex.run_readonly("logical", "inspect", config=configured(tmp_path, {"logical": root}))
    assert result.ok
    assert captured["command"][captured["command"].index("-C") + 1] == str(root.resolve())


def test_run_readonly_rejects_unknown_or_missing_configured_project(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="PROJECT_NOT_CONFIGURED"):
        codex.run_readonly("unknown", "inspect", config=configured(tmp_path, {}))
    with pytest.raises(ValueError, match="PROJECT_ROOT_NOT_FOUND"):
        codex.run_readonly("missing", "inspect", config=configured(tmp_path, {"missing": missing}))
