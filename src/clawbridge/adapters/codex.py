from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from clawbridge.config import AppConfig, load_config, resolve_configured_project


@dataclass(slots=True)
class CodexResult:
    ok: bool
    project: Path
    message: str
    returncode: int
def find_codex() -> Path:
    configured = os.getenv("CLAWBRIDGE_CODEX")
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    discovered = shutil.which("codex")
    if discovered:
        return Path(discovered)
    bundled = Path.home() / ".codex" / ".sandbox-bin" / "codex.exe"
    if bundled.exists():
        return bundled
    raise RuntimeError("Codex CLI not found")


def run_readonly(
    project_name: str,
    prompt: str,
    timeout: int = 900,
    *,
    config: AppConfig | None = None,
) -> CodexResult:
    project = resolve_configured_project(config or load_config(), project_name)
    codex = find_codex()
    temp_root = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ClawBridge" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="codex-last-", dir=temp_root,
        delete=False, encoding="utf-8"
    ) as handle:
        output_path = Path(handle.name)
    command = [
        str(codex), "exec", "--sandbox", "read-only", "--color", "never",
        "-C", str(project), "-o", str(output_path), prompt,
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CodexResult(False, project, "Codex 执行超时。", 124)
    finally:
        pass
    try:
        final = output_path.read_text(encoding="utf-8").strip()
    except OSError:
        final = ""
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass
    if completed.returncode == 0 and final:
        return CodexResult(True, project, final, 0)
    fallback = (completed.stderr or completed.stdout or final or "Codex 未返回结果").strip()
    return CodexResult(False, project, fallback[-2000:], completed.returncode)
