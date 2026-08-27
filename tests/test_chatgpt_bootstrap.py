from pathlib import Path

import pytest

from clawbridge.adapters.chatgpt_bootstrap import (
    CHATGPT_URL,
    ChromeBootstrapError,
    launch_manual_login,
)
from clawbridge.config import ChatConfig


def test_launches_normal_chrome_with_isolated_profile(tmp_path) -> None:
    chrome = tmp_path / "chrome.exe"
    profile = tmp_path / "custom-profile"
    calls = []

    command = launch_manual_login(
        ChatConfig(profile_dir=profile),
        executable_finder=lambda configured: chrome,
        process_launcher=lambda args: calls.append(args),
    )

    assert calls == [command]
    assert command == [
        str(chrome),
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        CHATGPT_URL,
    ]
    assert "--enable-automation" not in command
    assert not any("remote-debugging-port" in item for item in command)
    assert profile.is_dir()


def test_missing_chrome_has_clear_error(tmp_path) -> None:
    with pytest.raises(ChromeBootstrapError, match="未找到 Google Chrome"):
        launch_manual_login(
            ChatConfig(profile_dir=tmp_path / "profile"),
            executable_finder=lambda configured: None,
            process_launcher=lambda args: pytest.fail("must not launch"),
        )


def test_profile_in_use_has_clear_error(tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").touch()
    with pytest.raises(ChromeBootstrapError, match="profile 正在使用"):
        launch_manual_login(
            ChatConfig(profile_dir=profile),
            executable_finder=lambda configured: Path("chrome.exe"),
            process_launcher=lambda args: pytest.fail("must not launch"),
        )
