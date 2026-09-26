from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from steerwx.adapters.chatgpt_bootstrap import find_chrome_executable
from steerwx.adapters.codex import find_codex
from steerwx.channels.credentials import CredentialStore
from steerwx.config import AppConfig, load_config
from steerwx.runtime import data_roots, local_app_data


def _emit(stream: TextIO, label: str, status: str, detail: str) -> None:
    print(f"{label:<22} {status:<6} {detail}", file=stream)


def run_doctor(
    config: AppConfig | None = None,
    *,
    stream: TextIO | None = None,
) -> int:
    """Run non-destructive first-run checks for optional SteerWX capabilities."""
    stream = stream or sys.stdout
    config = config or load_config()
    errors = 0

    print("SteerWX doctor", file=stream)
    print(f"Runtime data           {local_app_data()}", file=stream)
    current, legacy = data_roots()
    if local_app_data() == legacy and not current.exists():
        print("Migration              legacy data in use; run 'python -m steerwx migrate-data' after stopping the service", file=stream)
    print(f"Config path            {config.config_path}", file=stream)

    if config.config_path.exists():
        _emit(stream, "Config file", "PASS", "found")
    else:
        _emit(stream, "Config file", "SETUP", "copy config.example.toml first")

    if not config.projects:
        _emit(stream, "Projects", "SETUP", "no configured projects")
    else:
        missing = [name for name, root in config.projects.items() if not root.is_dir()]
        if missing:
            errors += 1
            _emit(stream, "Projects", "ERROR", "missing roots: " + ", ".join(missing))
        else:
            _emit(stream, "Projects", "PASS", f"{len(config.projects)} configured")

    try:
        bound = CredentialStore().load()
    except Exception as exc:
        errors += 1
        _emit(stream, "WeChat binding", "ERROR", str(exc))
    else:
        if bound:
            _emit(stream, "WeChat binding", "PASS", "credentials available")
        else:
            _emit(stream, "WeChat binding", "SETUP", "run python -m steerwx login")

    try:
        chrome = find_chrome_executable(config.chat.browser)
    except Exception as exc:
        _emit(stream, "Chrome", "SETUP", str(exc))
    else:
        _emit(stream, "Chrome", "PASS", str(chrome))

    if config.chat.profile_dir.exists():
        _emit(
            stream,
            "ChatGPT profile",
            "PASS",
            "found; use 'python -m steerwx chat-browser doctor' to verify login",
        )
    else:
        _emit(stream, "ChatGPT profile", "SETUP", "run python -m steerwx chat-browser setup")

    try:
        codex = find_codex()
    except Exception:
        _emit(stream, "Codex CLI", "SETUP", "not found; only /codex needs it")
    else:
        _emit(stream, "Codex CLI", "PASS", str(Path(codex)))

    print("", file=stream)
    if errors:
        print(f"Result                 ERROR ({errors} inconsistent local setting(s))", file=stream)
        return 2

    print("Result                 CHECKED", file=stream)
    print("Tip                    Missing optional capabilities are shown as SETUP.", file=stream)
    return 0
