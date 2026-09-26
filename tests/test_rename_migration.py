import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from steerwx.channels.credentials import CredentialStore
from steerwx.config import load_config
from steerwx.runtime import local_app_data, migrate_data
from steerwx.state import RouteStore


def test_new_and_legacy_runtime_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("STEERWX_HOME", raising=False)
    monkeypatch.delenv("CLAWBRIDGE_HOME", raising=False)
    old = tmp_path / "ClawBridge"
    new = tmp_path / "SteerWX"
    assert local_app_data() == new
    old.mkdir()
    assert local_app_data() == old
    assert load_config().config_path == old / "config.toml"
    assert CredentialStore().home == old
    assert RouteStore().home == old
    new.mkdir()
    assert local_app_data() == new


def test_copy_legacy_data_preserves_source_and_remaps_default_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("STEERWX_HOME", raising=False)
    monkeypatch.delenv("CLAWBRIDGE_HOME", raising=False)
    old = tmp_path / "ClawBridge"
    profile = old / "browser" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"sample")
    (old / "chat").mkdir()
    (old / "chat" / "session.json").write_text('{"browser_thread_url": "https://chatgpt.com/c/abc"}')
    (old / "weixin-account.json").write_text('{"account_id": "a", "base_url": "b"}')
    (old / "route-state.json").write_text('{"user_id": "u"}')
    (old / "config.toml").write_text('[chat]\nprofile_dir = "' + str(profile).replace('\\', '\\\\') + '"\n')
    source, target = migrate_data()
    assert (source, target) == (old, tmp_path / "SteerWX")
    assert (target / "browser" / "chrome-profile" / "Cookies").read_bytes() == b"sample"
    assert (target / "chat" / "session.json").exists()
    assert (target / "weixin-account.json").exists()
    assert (target / "route-state.json").exists()
    assert (source / "browser" / "chrome-profile" / "Cookies").read_bytes() == b"sample"
    assert load_config().chat.profile_dir == target / "browser" / "chrome-profile"
    with pytest.raises(RuntimeError, match="Target already exists"):
        migrate_data()


def test_migration_refuses_active_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("STEERWX_HOME", raising=False)
    monkeypatch.delenv("CLAWBRIDGE_HOME", raising=False)
    profile = tmp_path / "ClawBridge" / "browser" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / "SingletonLock").touch()
    with pytest.raises(RuntimeError, match="Close the dedicated"):
        migrate_data()
    assert not (tmp_path / "SteerWX").exists()


def test_legacy_keyring_entries_are_read(monkeypatch, tmp_path):
    from steerwx.channels import credentials
    from steerwx import state

    metadata = CredentialStore(tmp_path)
    metadata.metadata_path.write_text(json.dumps({"account_id": "a", "base_url": "b", "user_id": "u"}))
    route = RouteStore(tmp_path)
    route.path.write_text(json.dumps({"user_id": "u"}))
    seen = []

    def get_password(service, user):
        seen.append((service, user))
        return {("ClawBridge Weixin", "a"): "bot", ("ClawBridge Route", "u"): "context"}.get((service, user))

    monkeypatch.setattr(credentials.keyring, "get_password", get_password)
    monkeypatch.setattr(state.keyring, "get_password", get_password)
    assert metadata.load()[1] == "bot"
    assert route.context_token() == "context"
    assert ("SteerWX Weixin", "a") in seen and ("SteerWX Route", "u") in seen


def test_doctor_explains_legacy_home(monkeypatch, tmp_path, capsys):
    from steerwx import doctor

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "ClawBridge").mkdir()
    monkeypatch.setattr(doctor.CredentialStore, "load", lambda self: None)
    monkeypatch.setattr(doctor, "find_chrome_executable", lambda browser: Path("chrome.exe"))
    monkeypatch.setattr(doctor, "find_codex", lambda: Path("codex.exe"))
    assert doctor.run_doctor(load_config()) == 0
    output = capsys.readouterr().out
    assert "legacy data in use" in output
    assert str(tmp_path / "ClawBridge") in output


@pytest.mark.parametrize("module", ["steerwx", "clawbridge"])
def test_module_cli_help(module):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run([sys.executable, "-m", module, "--help"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "steerwx" in result.stdout


def test_distribution_metadata_has_primary_and_legacy_entries():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert project["project"]["name"] == "steerwx"
    assert project["project"]["version"] == "0.2.0"
    assert project["project"]["scripts"]["steerwx"] == "steerwx.cli:main"
    assert project["project"]["scripts"]["clawbridge"] == "steerwx.cli:main"
