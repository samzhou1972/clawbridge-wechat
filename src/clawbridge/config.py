from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def local_app_data() -> Path:
    return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ClawBridge"


@dataclass(frozen=True, slots=True)
class ChatConfig:
    browser: str = "chrome"
    profile_dir: Path = local_app_data() / "browser" / "chrome-profile"
    headless: bool = False
    startup_timeout_seconds: int = 30
    reply_timeout_seconds: int = 180


@dataclass(frozen=True, slots=True)
class AppConfig:
    code_root: Path
    codex_executable: Path | None
    chat: ChatConfig
    projects: dict[str, Path]
    config_path: Path


def resolve_configured_project(config: AppConfig, name: str) -> Path:
    """Resolve a logical project name from the configured project allowlist."""
    if not name or name not in config.projects:
        raise ValueError("PROJECT_NOT_CONFIGURED")
    root = config.projects[name].expanduser()
    if not root.is_dir():
        raise ValueError("PROJECT_ROOT_NOT_FOUND")
    return root.resolve()


def default_config_path() -> Path:
    return local_app_data() / "config.toml"


def _path(value: object, fallback: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return Path(os.path.expandvars(value)).expanduser()


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or Path(
        os.getenv("CLAWBRIDGE_CONFIG", str(default_config_path()))
    )
    raw: dict[str, Any] = {}
    try:
        with config_path.open("rb") as handle:
            value = tomllib.load(handle)
            if isinstance(value, dict):
                raw = value
    except FileNotFoundError:
        pass

    paths = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
    codex = raw.get("codex") if isinstance(raw.get("codex"), dict) else {}
    chat = raw.get("chat") if isinstance(raw.get("chat"), dict) else {}
    projects_raw = raw.get("projects") if isinstance(raw.get("projects"), dict) else {}
    base = local_app_data()
    default_code_root = Path(r"D:\code")
    code_root = _path(os.getenv("CLAWBRIDGE_CODE_ROOT", paths.get("code_root")), default_code_root)
    profile_dir = _path(
        os.getenv("CLAWBRIDGE_CHAT_PROFILE", chat.get("profile_dir")),
        base / "browser" / "chrome-profile",
    )
    executable_value = os.getenv("CLAWBRIDGE_CODEX") or codex.get("executable")
    executable = _path(executable_value, Path()) if executable_value else None
    project_paths: dict[str, Path] = {}
    for name, item in projects_raw.items():
        if isinstance(item, dict) and isinstance(item.get("root"), str):
            project_paths[str(name)] = _path(item["root"], code_root / str(name))
    return AppConfig(
        code_root=code_root,
        codex_executable=executable,
        chat=ChatConfig(
            browser=str(chat.get("browser", "chrome")),
            profile_dir=profile_dir,
            headless=bool(chat.get("headless", False)),
            startup_timeout_seconds=int(chat.get("startup_timeout_seconds", 30)),
            reply_timeout_seconds=int(chat.get("reply_timeout_seconds", 180)),
        ),
        projects=project_paths,
        config_path=config_path,
    )
