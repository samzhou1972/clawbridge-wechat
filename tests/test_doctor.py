from pathlib import Path

from steerwx import doctor
from steerwx.channels.credentials import WeixinCredentials
from steerwx.config import load_config


def _raise(message: str):
    raise RuntimeError(message)


def test_doctor_reports_setup_gaps(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = load_config(tmp_path / "missing.toml")
    monkeypatch.setattr(doctor.CredentialStore, "load", lambda self: None)
    monkeypatch.setattr(
        doctor,
        "find_chrome_executable",
        lambda configured_browser="chrome": _raise("Chrome not found"),
    )
    monkeypatch.setattr(doctor, "find_codex", lambda: _raise("Codex not found"))

    assert doctor.run_doctor(config) == 0
    output = capsys.readouterr().out
    assert "Config file" in output and "SETUP" in output
    assert "WeChat binding" in output
    assert "Result                 CHECKED" in output


def test_doctor_reports_ready_local_components(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    project = tmp_path / "demo"
    project.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[projects.demo]\nroot = "' + str(project).replace("\\", "\\\\") + '"\n',
        encoding="utf-8",
    )
    config = load_config(config_path)
    config.chat.profile_dir.mkdir(parents=True)

    monkeypatch.setattr(
        doctor.CredentialStore,
        "load",
        lambda self: (
            WeixinCredentials("account", "https://example.invalid", "user"),
            "token",
        ),
    )
    monkeypatch.setattr(doctor, "find_chrome_executable", lambda configured_browser="chrome": Path("chrome.exe"))
    monkeypatch.setattr(doctor, "find_codex", lambda: Path("codex.exe"))

    assert doctor.run_doctor(config) == 0
    output = capsys.readouterr().out
    assert "1 configured" in output
    assert "WeChat binding" in output and "PASS" in output
    assert "Codex CLI" in output
