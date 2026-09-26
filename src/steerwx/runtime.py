"""Runtime location and opt-in copy of pre-0.2.0 local state."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def data_roots() -> tuple[Path, Path]:
    base = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    return base / "SteerWX", base / "ClawBridge"


def local_app_data() -> Path:
    """Use existing state until its owner explicitly copies it to the new home."""
    override = os.getenv("STEERWX_HOME") or os.getenv("CLAWBRIDGE_HOME")
    if override:
        return Path(override).expanduser()
    current, legacy = data_roots()
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    return current


def migrate_data() -> tuple[Path, Path]:
    """Copy all local state without overwriting or removing either home."""
    if os.getenv("STEERWX_HOME") or os.getenv("CLAWBRIDGE_HOME"):
        raise RuntimeError("Unset STEERWX_HOME and CLAWBRIDGE_HOME before migration")
    current, legacy = data_roots()
    if not legacy.is_dir():
        raise RuntimeError(f"Legacy data directory not found: {legacy}")
    if current.exists():
        raise RuntimeError(f"Target already exists; no files were overwritten: {current}")
    profile = legacy / "browser" / "chrome-profile"
    if any((profile / marker).exists() for marker in ("SingletonLock", "SingletonCookie", "SingletonSocket")):
        raise RuntimeError("Close the dedicated ChatGPT Chrome profile before migration")
    staging = current.with_name(current.name + ".migrating")
    if staging.exists():
        raise RuntimeError(f"Incomplete staging directory exists; inspect it first: {staging}")
    try:
        shutil.copytree(legacy, staging)
        staging.rename(current)
    except Exception:
        # Retain the incomplete copy for inspection; never touch the legacy source.
        raise
    return legacy, current
