from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring

SERVICE_NAME = "ClawBridge Weixin"


@dataclass(slots=True)
class WeixinCredentials:
    account_id: str
    base_url: str
    user_id: str | None = None


class CredentialStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or self._default_home()
        self.metadata_path = self.home / "weixin-account.json"

    @staticmethod
    def _default_home() -> Path:
        override = os.getenv("CLAWBRIDGE_HOME")
        if override:
            return Path(override)
        if os.name == "nt" and os.getenv("LOCALAPPDATA"):
            return Path(os.environ["LOCALAPPDATA"]) / "ClawBridge"
        return Path.home() / ".clawbridge"

    def save(self, credentials: WeixinCredentials, bot_token: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(
            json.dumps(asdict(credentials), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        keyring.set_password(SERVICE_NAME, credentials.account_id, bot_token)

    def load(self) -> tuple[WeixinCredentials, str] | None:
        if not self.metadata_path.exists():
            return None
        raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        credentials = WeixinCredentials(**raw)
        token = keyring.get_password(SERVICE_NAME, credentials.account_id)
        if not token:
            raise RuntimeError(
                "Weixin metadata exists but its bot token is missing from the OS keyring."
            )
        return credentials, token

    def local_tokens(self) -> list[str]:
        loaded = self.load()
        return [loaded[1]] if loaded else []
