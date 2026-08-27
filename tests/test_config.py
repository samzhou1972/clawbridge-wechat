from pathlib import Path

import pytest

from clawbridge.config import load_config, resolve_configured_project


def test_config_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = load_config(tmp_path / "missing.toml")
    assert config.code_root == Path(r"D:\code")
    assert config.chat.browser == "chrome"
    assert config.chat.headless is False
    assert config.chat.profile_dir == tmp_path / "ClawBridge" / "browser" / "chrome-profile"


def test_config_toml_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "config.toml"
    path.write_text(
        '[paths]\ncode_root = "E:\\\\work"\n'
        '[chat]\nprofile_dir = "E:\\\\profiles\\\\claw"\nheadless = true\n'
        'startup_timeout_seconds = 12\nreply_timeout_seconds = 45\n'
        '[projects.demo]\nroot = "E:\\\\work\\\\demo"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.code_root == Path(r"E:\work")
    assert config.chat.profile_dir == Path(r"E:\profiles\claw")
    assert config.chat.headless is True
    assert config.chat.startup_timeout_seconds == 12
    assert config.chat.reply_timeout_seconds == 45
    assert config.projects["demo"] == Path(r"E:\work\demo")


def test_profile_environment_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAWBRIDGE_CHAT_PROFILE", str(tmp_path / "profile"))
    assert load_config(tmp_path / "missing.toml").chat.profile_dir == tmp_path / "profile"


def test_configured_project_resolver_uses_allowlist_and_existing_root(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path = tmp_path / "config.toml"
    path.write_text(
        '[projects.demo]\nroot = "' + str(root).replace("\\", "\\\\") + '"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert resolve_configured_project(config, "demo") == root.resolve()
    with pytest.raises(ValueError, match="PROJECT_NOT_CONFIGURED"):
        resolve_configured_project(config, "unknown")
