from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

WEIXIN_MAX_OUTBOUND_CHARS = 1000
WEIXIN_TRUNCATION_NOTICE = "\n\n内容较长，已省略。请在 PC 端查看完整内容。"


def _safe_server_error(value: object) -> str:
    return str(value or "NONE")[:160]


def bound_outbound_text(text: str, limit: int = WEIXIN_MAX_OUTBOUND_CHARS) -> str:
    """Return one Unicode-safe WeChat message within the transport hard cap."""
    if len(text) <= limit:
        return text
    content_limit = max(0, limit - len(WEIXIN_TRUNCATION_NOTICE))
    candidate = text[:content_limit]
    search_start = max(0, content_limit // 2)
    cuts = [candidate.rfind("\n\n", search_start), candidate.rfind("\n", search_start)]
    cuts.extend(candidate.rfind(mark, search_start) + 1 for mark in ("。", "！", "？", ".", "!", "?"))
    cut = max(cuts)
    if cut <= 0:
        cut = content_limit
    return candidate[:cut].rstrip() + WEIXIN_TRUNCATION_NOTICE

API_BASE = "https://ilinkai.weixin.qq.com"
BOT_TYPE = "3"
APP_ID = "bot"
CHANNEL_VERSION = "0.2.0"
BOT_AGENT = "SteerWX/0.2.0"
STALE_TOKEN_ERRCODE = -14


class ILinkStaleTokenError(RuntimeError):
    """Raised when iLink reports a stale/expired bot token (errcode=-14)."""


def _client_version(version: str = CHANNEL_VERSION) -> int:
    parts = [int(p) for p in version.split(".")[:3]]
    parts += [0] * (3 - len(parts))
    major, minor, patch = parts
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def _wechat_uin() -> str:
    value = str(secrets.randbits(32)).encode("utf-8")
    return base64.b64encode(value).decode("ascii")


def _base_info() -> dict[str, str]:
    return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}


def _common_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": APP_ID,
        "iLink-App-ClientVersion": str(_client_version()),
    }


def _post_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _wechat_uin(),
        **_common_headers(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


@dataclass(slots=True)
class LoginSession:
    qrcode: str
    qrcode_url: str


@dataclass(slots=True)
class LoginResult:
    status: str
    bot_token: str | None = None
    account_id: str | None = None
    base_url: str | None = None
    user_id: str | None = None
    redirect_host: str | None = None


class WeixinClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.http = session or requests.Session()

    def start_login(self, local_tokens: list[str] | None = None) -> LoginSession:
        response = self.http.post(
            _url(API_BASE, f"ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"),
            headers=_post_headers(),
            json={"local_token_list": local_tokens or []},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return LoginSession(data["qrcode"], data["qrcode_img_content"])


    def poll_login(
        self,
        qrcode: str,
        *,
        base_url: str = API_BASE,
        verify_code: str | None = None,
    ) -> LoginResult:
        path = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        if verify_code:
            path += f"&verify_code={quote(verify_code)}"
        try:
            response = self.http.get(
                _url(base_url, path),
                headers=_common_headers(),
                timeout=40,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            self.last_login_diagnostics = {"status": "wait", "transient_error": "Timeout"}
            return LoginResult(status="wait")
        except requests.RequestException as exc:
            self.last_login_diagnostics = {
                "status": "wait",
                "transient_error": type(exc).__name__,
            }
            return LoginResult(status="wait")
        self.last_login_diagnostics = {
            "status": data.get("status", "unknown"),
            "transient_error": None,
        }
        return LoginResult(
            status=data.get("status", "unknown"),
            bot_token=data.get("bot_token"),
            account_id=data.get("ilink_bot_id"),
            base_url=data.get("baseurl"),
            user_id=data.get("ilink_user_id"),
            redirect_host=data.get("redirect_host"),
        )


    def get_updates(
        self,
        token: str,
        base_url: str,
        cursor: str = "",
        timeout: int = 40,
    ) -> dict[str, Any]:
        try:
            response = self.http.post(
                _url(base_url, "ilink/bot/getupdates"),
                headers=_post_headers(token),
                json={"get_updates_buf": cursor, "base_info": _base_info()},
                timeout=timeout,
            )
            response.raise_for_status()
        except requests.Timeout:
            return {"ret": 0, "msgs": [], "get_updates_buf": cursor}
        data = response.json()
        ret = data.get("ret", 0)
        errcode = data.get("errcode")
        if errcode == STALE_TOKEN_ERRCODE:
            raise ILinkStaleTokenError(
                f"getupdates stale token: errcode={errcode} "
                f"errmsg={_safe_server_error(data.get('errmsg'))}"
            )
        if ret != 0 or errcode not in (None, 0):
            raise RuntimeError(
                f"getupdates failed: ret={ret} "
                f"errcode={errcode} errmsg={_safe_server_error(data.get('errmsg'))}"
            )
        return data

    def send_text(
        self,
        token: str,
        base_url: str,
        to_user_id: str,
        context_token: str,
        text: str,
    ) -> str:
        if len(text) > WEIXIN_MAX_OUTBOUND_CHARS:
            raise ValueError("WeChat outbound text exceeds 1000 characters")
        client_id = f"steerwx-{secrets.token_hex(12)}"
        self.last_send_diagnostics = {"client_id": client_id}
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": _base_info(),
        }
        response = self.http.post(
            _url(base_url, "ilink/bot/sendmessage"),
            headers=_post_headers(token),
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        self.last_send_diagnostics = {
            "client_id": client_id,
            "http_status": getattr(response, "status_code", "UNKNOWN"),
            "ret": data.get("ret"),
            "errcode": data.get("errcode"),
            "errmsg": _safe_server_error(data.get("errmsg")),
            "response_keys": sorted(str(key) for key in data),
        }
        if data.get("ret", 0) != 0:
            raise RuntimeError(
                f"sendmessage failed: ret={data.get('ret')} errmsg={_safe_server_error(data.get('errmsg'))}"
            )
        return client_id

    def notify_start(self, token: str, base_url: str) -> dict[str, Any]:
        return self._notify(token, base_url, "notifystart")

    def notify_stop(self, token: str, base_url: str) -> dict[str, Any]:
        return self._notify(token, base_url, "notifystop")

    def _notify(self, token: str, base_url: str, action: str) -> dict[str, Any]:
        response = self.http.post(
            _url(base_url, f"ilink/bot/msg/{action}"),
            headers=_post_headers(token),
            json={"base_info": _base_info()},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        diagnostics = {
            "http_status": getattr(response, "status_code", "UNKNOWN"),
            "ret": data.get("ret"),
            "errcode": data.get("errcode"),
            "errmsg": _safe_server_error(data.get("errmsg")),
            "response_keys": sorted(str(key) for key in data),
        }
        self.last_notify_diagnostics = diagnostics
        print(
            f"[notify] action={action} http_status={diagnostics['http_status']} "
            f"ret={diagnostics['ret']} errcode={diagnostics['errcode']} "
            f"errmsg={diagnostics['errmsg']!r} response_keys={diagnostics['response_keys']}",
            flush=True,
        )
        return data


def safe_send_text(
    client: WeixinClient,
    token: str,
    base_url: str,
    sender: str,
    context: str,
    text: str,
    *,
    purpose: str,
    outbound_kind: str,
) -> str | None:
    """Attempt one outbound message without terminating the bridge or retrying."""
    bounded = bound_outbound_text(text)
    try:
        client_id = client.send_text(token, base_url, sender, context, bounded)
        diagnostics = getattr(client, "last_send_diagnostics", {})
        print(
            f"[send] purpose={purpose} outbound_kind={outbound_kind} chars={len(bounded)} "
            f"http_status={diagnostics.get('http_status', 'UNKNOWN')} "
            f"ret={diagnostics.get('ret', 'UNKNOWN')} errcode={diagnostics.get('errcode', 'NONE')} "
            f"errmsg={diagnostics.get('errmsg', 'NONE')!r} "
            f"response_keys={diagnostics.get('response_keys', [])} client_id={client_id} "
            f"delivery=ACCEPTED_UNCONFIRMED",
            flush=True,
        )
        return client_id
    except Exception as exc:
        diagnostics = getattr(client, "last_send_diagnostics", {})
        print(
            f"[send] purpose={purpose} outbound_kind={outbound_kind} chars={len(bounded)} "
            f"http_status={diagnostics.get('http_status', 'UNKNOWN')} "
            f"ret={diagnostics.get('ret', 'UNKNOWN')} errcode={diagnostics.get('errcode', 'NONE')} "
            f"errmsg={diagnostics.get('errmsg', 'NONE')!r} "
            f"response_keys={diagnostics.get('response_keys', [])} "
            f"client_id={diagnostics.get('client_id', 'UNKNOWN')} "
            f"delivery=FAILED error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


def extract_text(message: dict[str, Any]) -> str | None:
    if message.get("message_type") != 1:
        return None
    parts: list[str] = []
    for item in message.get("item_list") or []:
        if item.get("type") != 1:
            continue
        text = (item.get("text_item") or {}).get("text")
        if text:
            parts.append(str(text))
    joined = "\n".join(parts).strip()
    return joined or None
