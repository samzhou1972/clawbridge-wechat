from types import SimpleNamespace

import pytest
import requests

from steerwx import cli
from steerwx.channels.weixin import (
    API_BASE,
    ILinkStaleTokenError,
    LoginResult,
    LoginSession,
    WeixinClient,
)


class Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class QueueSession:
    def __init__(self, *, posts=None, gets=None):
        self.posts = list(posts or [])
        self.gets = list(gets or [])
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append(("POST", url, json))
        value = self.posts.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url, *, headers, timeout):
        self.calls.append(("GET", url, None))
        value = self.gets.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_qr_fetch_uses_fixed_official_base_and_local_tokens():
    session = QueueSession(posts=[Response({"qrcode": "q", "qrcode_img_content": "u"})])
    result = WeixinClient(session=session).start_login(["old-token"])
    assert result == LoginSession("q", "u")
    method, url, body = session.calls[0]
    assert method == "POST"
    assert url.startswith(API_BASE)
    assert body == {"local_token_list": ["old-token"]}


def test_qr_poll_network_error_is_soft_wait():
    session = QueueSession(gets=[requests.ConnectionError("gateway down")])
    client = WeixinClient(session=session)
    result = client.poll_login("qr")
    assert result.status == "wait"
    assert client.last_login_diagnostics["transient_error"] == "ConnectionError"


def test_getupdates_timeout_is_soft_empty_response():
    session = QueueSession(posts=[requests.Timeout("long poll boundary")])
    result = WeixinClient(session=session).get_updates("token", API_BASE, "cursor")
    assert result == {"ret": 0, "msgs": [], "get_updates_buf": "cursor"}


def test_getupdates_stale_token_is_not_silently_accepted():
    session = QueueSession(posts=[Response({"ret": 0, "errcode": -14, "errmsg": "stale"})])
    with pytest.raises(ILinkStaleTokenError, match="errcode=-14"):
        WeixinClient(session=session).get_updates("token", API_BASE)


def test_getupdates_other_errcode_is_failure():
    session = QueueSession(posts=[Response({"ret": 0, "errcode": -99, "errmsg": "bad"})])
    with pytest.raises(RuntimeError, match="errcode=-99"):
        WeixinClient(session=session).get_updates("token", API_BASE)


def test_notify_parses_and_logs_response(capsys):
    session = QueueSession(posts=[Response({"ret": 0})])
    client = WeixinClient(session=session)
    result = client.notify_start("token", API_BASE)
    assert result == {"ret": 0}
    assert client.last_notify_diagnostics["ret"] == 0
    output = capsys.readouterr().out
    assert "[notify] action=notifystart" in output
    assert "ret=0" in output


class FakeCredentialStore:
    def __init__(self):
        self.saved = SimpleNamespace(base_url="https://saved.example", account_id="bot", user_id="user")

    def load(self):
        return self.saved, "existing-token"

    def save(self, credentials, bot_token):
        raise AssertionError("binded_redirect must not overwrite existing credentials")


class FakeLoginClient:
    def __init__(self):
        self.start_tokens = None
        self.poll_bases = []
        self.results = [LoginResult(status="binded_redirect")]
        self.last_login_diagnostics = {}

    def start_login(self, local_tokens=None):
        self.start_tokens = list(local_tokens or [])
        return LoginSession("qrcode", "https://qr.example")

    def poll_login(self, qrcode, *, base_url=API_BASE, verify_code=None):
        self.poll_bases.append(base_url)
        return self.results.pop(0)


def test_cli_binded_redirect_is_successful_noop(monkeypatch, capsys):
    client = FakeLoginClient()
    monkeypatch.setattr(cli, "WeixinClient", lambda: client)
    monkeypatch.setattr(cli, "CredentialStore", FakeCredentialStore)
    monkeypatch.setattr(cli, "_print_qr", lambda value: None)

    assert cli._login() == 0
    assert client.start_tokens == ["existing-token"]
    assert client.poll_bases == [API_BASE]
    assert "无需重复绑定" in capsys.readouterr().out


def test_cli_redirect_without_host_keeps_polling_current_host(monkeypatch, capsys):
    client = FakeLoginClient()
    client.results = [
        LoginResult(status="scaned_but_redirect"),
        LoginResult(status="binded_redirect"),
    ]
    monkeypatch.setattr(cli, "WeixinClient", lambda: client)
    monkeypatch.setattr(cli, "CredentialStore", FakeCredentialStore)
    monkeypatch.setattr(cli, "_print_qr", lambda value: None)

    assert cli._login() == 0
    assert client.poll_bases == [API_BASE, API_BASE]
    captured = capsys.readouterr()
    assert "缺少 redirect_host" in captured.err
