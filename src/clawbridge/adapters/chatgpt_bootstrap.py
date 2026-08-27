from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from clawbridge.config import ChatConfig


CHATGPT_URL = "https://chatgpt.com/"


class ChromeBootstrapError(RuntimeError):
    pass


def find_chrome_executable(configured_browser: str = "chrome") -> Path | None:
    configured_path = Path(os.path.expandvars(configured_browser)).expanduser()
    if configured_browser.strip().lower() != "chrome" and configured_path.is_file():
        return configured_path

    candidates = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "Google/Chrome/Application/chrome.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("chrome") or shutil.which("chrome.exe")
    return Path(discovered) if discovered else None


def _profile_in_use(profile_dir: Path) -> bool:
    return any(
        (profile_dir / marker).exists()
        for marker in ("SingletonLock", "SingletonCookie", "SingletonSocket")
    )


def launch_manual_login(
    config: ChatConfig,
    *,
    executable_finder=None,
    process_launcher=None,
) -> list[str]:
    executable_finder = executable_finder or find_chrome_executable
    process_launcher = process_launcher or subprocess.Popen
    executable = executable_finder(config.browser)
    if executable is None:
        raise ChromeBootstrapError(
            "未找到 Google Chrome。请安装 Chrome，或在 [chat] browser 中配置 chrome.exe 的完整路径。"
        )
    if _profile_in_use(config.profile_dir):
        raise ChromeBootstrapError(
            "ClawBridge Chrome profile 正在使用，请先关闭该专用 Chrome 后重试。"
        )

    config.profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        f"--user-data-dir={config.profile_dir}",
        "--profile-directory=Default",
        CHATGPT_URL,
    ]
    try:
        process_launcher(command)
    except OSError as exc:
        raise ChromeBootstrapError(f"无法启动 Google Chrome：{exc}") from exc
    return command
