from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring

from steerwx.channels.credentials import CredentialStore

ROUTE_SERVICE = "SteerWX Route"
LEGACY_ROUTE_SERVICE = "ClawBridge Route"


@dataclass(slots=True)
class ReplyRoute:
    user_id: str
    watch_enabled: bool = False
    watch_baseline: str | None = None
    last_notified: str | None = None


class RouteStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or CredentialStore._default_home()
        self.path = self.home / "route-state.json"

    def save_route(self, user_id: str, context_token: str) -> ReplyRoute:
        current = self.load_route()
        route = current or ReplyRoute(user_id=user_id)
        route.user_id = user_id
        self._write(route)
        keyring.set_password(ROUTE_SERVICE, user_id, context_token)
        return route

    def load_route(self) -> ReplyRoute | None:
        if not self.path.exists():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return ReplyRoute(**raw)

    def context_token(self, route: ReplyRoute | None = None) -> str | None:
        selected = route or self.load_route()
        if selected is None:
            return None
        return (keyring.get_password(ROUTE_SERVICE, selected.user_id)
                or keyring.get_password(LEGACY_ROUTE_SERVICE, selected.user_id))

    def set_watch(self, enabled: bool, baseline: str | None) -> ReplyRoute | None:
        route = self.load_route()
        if route is None:
            return None
        route.watch_enabled = enabled
        route.watch_baseline = baseline
        if enabled:
            route.last_notified = baseline
        self._write(route)
        return route

    def mark_notified(self, task_key: str) -> None:
        route = self.load_route()
        if route is None:
            return
        route.last_notified = task_key
        self._write(route)

    def _write(self, route: ReplyRoute) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(route), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
