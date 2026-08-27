from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from uuid import uuid4

import requests

from clawbridge.adapters.codex import run_readonly
from clawbridge.channels.credentials import CredentialStore
from clawbridge.channels.weixin import (
    ILinkStaleTokenError,
    WEIXIN_MAX_OUTBOUND_CHARS,
    WeixinClient,
    bound_outbound_text,
    extract_text,
    safe_send_text,
)
from clawbridge.config import load_config
from clawbridge.conversation import ConversationService, SessionStore, bind_project, prepare_message
from clawbridge.observers.work import (
    WorkSnapshot,
    format_last,
    format_result,
    format_status,
    latest_work,
)
from clawbridge.state import RouteStore

_CODEX_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clawbridge-codex")
_CODEX_LOCK = Lock()
_CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clawbridge-chat")
_CHAT_LOCK = Lock()
_SEEN_MESSAGE_IDS: set[str] = set()
_SEEN_MESSAGE_ORDER: deque[str] = deque()
_MAX_SEEN_MESSAGE_IDS = 512
CODEX_HANDOFF_MARKER = "【Codex 执行指令】"
CODEX_HANDOFF_COMPLEXITY_MESSAGE = (
    "这个任务的执行约束较多，完整 Codex 指令会超过微信端长度限制。\n\n"
    "为避免遗漏关键约束，本次不生成精简版 handoff。建议回到 PC 端继续该开发任务。"
)

_safe_send_text = safe_send_text


def _message_identity(message: dict) -> str | None:
    for key in ("message_id", "msg_id", "event_id", "client_id"):
        if message.get(key):
            return f"{key}:{message[key]}"
    return None


def _inbound_authorization_reason(credentials, sender: str | None) -> str | None:
    if not credentials.user_id:
        return "BOUND_USER_UNAVAILABLE"
    if sender != credentials.user_id:
        return "SENDER_MISMATCH"
    return None


def _mark_message_seen(message: dict) -> bool:
    identity = _message_identity(message)
    if identity is None:
        return True
    if identity in _SEEN_MESSAGE_IDS:
        return False
    _SEEN_MESSAGE_IDS.add(identity)
    _SEEN_MESSAGE_ORDER.append(identity)
    while len(_SEEN_MESSAGE_ORDER) > _MAX_SEEN_MESSAGE_IDS:
        _SEEN_MESSAGE_IDS.discard(_SEEN_MESSAGE_ORDER.popleft())
    return True


def _send_chat_text(client, token, base_url, sender, context, text, *, purpose) -> bool:
    if CODEX_HANDOFF_MARKER in text and len(text) > WEIXIN_MAX_OUTBOUND_CHARS:
        text = CODEX_HANDOFF_COMPLEXITY_MESSAGE
    sent = _safe_send_text(
        client, token, base_url, sender, context, text,
        purpose=purpose, outbound_kind="REPLY",
    )
    return sent is not None


def _chat_error_message(exc: Exception) -> str:
    detail = f"{getattr(exc, 'stage', '')} {exc}".upper()
    if "PROJECT_NOT_CONFIGURED" in detail:
        return "项目未配置，请先检查 ClawBridge config。"
    if "PROJECT_ROOT_NOT_FOUND" in detail:
        return "项目目录不存在或不可访问。"
    if "THREAD_UNAVAILABLE" in detail:
        return "当前 ChatGPT 对话不可用。\n可执行 `/chat reset` 创建新对话。"
    if "PAGE_READY_TIMEOUT" in detail:
        return "ChatGPT 页面暂时未准备好，请稍后重试。"
    if "REPLY_TIMEOUT" in detail:
        return "ChatGPT 回复超时，请稍后重试。"
    if any(value in detail for value in ("BROWSER", "LOGIN", "AUTH")):
        return "ChatGPT 浏览器不可用，请在开发机检查：\npython -m clawbridge chat-browser doctor"
    return "ChatGPT 请求失败，请查看 ClawBridge diagnostics。"


def _handle_chat(
    text: str,
    token: str,
    base_url: str,
    sender: str,
    context: str,
    *,
    client=None,
    inbound_id: str | None = None,
) -> None:
    client = client or WeixinClient()
    stripped = text.strip()
    lower = stripped.lower()
    config = load_config()
    store = SessionStore()
    usage = "用法：\n/chat use <project>\n/chat <message>\n/chat status\n/chat reset"
    if lower == "/chat":
        _send_chat_text(client, token, base_url, sender, context, usage, purpose="chat_usage")
        return
    if lower == "/chat status":
        session = store.load()
        reply = f"当前 Chat 项目：{session.current_project or 'NONE'}\n对话状态：{'ACTIVE' if session.browser_thread_url else 'NONE'}\n最近消息：{len(session.recent_messages)}"
        _send_chat_text(client, token, base_url, sender, context, reply, purpose="chat_status")
        return
    if lower == "/chat reset":
        if _CHAT_LOCK.locked():
            _send_chat_text(client, token, base_url, sender, context, "当前已有 ChatGPT 请求正在处理，请稍后再试。", purpose="chat_busy")
            return
        session = store.reset()
        _send_chat_text(client, token, base_url, sender, context, f"Chat conversation reset.\nCurrent project: {session.current_project or 'NONE'}", purpose="chat_reset")
        return
    if lower.startswith("/chat use "):
        if _CHAT_LOCK.locked():
            _send_chat_text(client, token, base_url, sender, context, "当前已有 ChatGPT 请求正在处理，请稍后再试。", purpose="chat_busy")
            return
        project = stripped[len("/chat use "):].strip()
        try:
            bind_project(config, store, project)
            reply = f"当前项目已切换为：\n{project}\n\n路径：\n{config.projects[project]}"
        except Exception as exc:
            reply = f"项目未配置：\n{project}" if "PROJECT_NOT_CONFIGURED" in str(exc) else _chat_error_message(exc)
        _send_chat_text(client, token, base_url, sender, context, reply, purpose="chat_use")
        return
    if not lower.startswith("/chat ") or not stripped[len("/chat "):].strip():
        _send_chat_text(client, token, base_url, sender, context, usage, purpose="chat_usage")
        return
    message = stripped[len("/chat "):].strip()
    if not _CHAT_LOCK.acquire(blocking=False):
        _send_chat_text(client, token, base_url, sender, context, "当前已有 ChatGPT 请求正在处理，请稍后再试。", purpose="chat_busy")
        return
    request_id = uuid4().hex

    def run_chat() -> None:
        try:
            prompt, context_result = prepare_message(config, store, message)
            providers = ",".join(context_result.selection.names) if context_result else "NONE"
            print(f"[chat] inbound_id={inbound_id or 'UNAVAILABLE'} request_id={request_id} session=default project={store.load().current_project or 'NONE'} providers={providers} stage=START", flush=True)
            result = ConversationService(config.chat, store=store).send(message, prompt=prompt)
            sent = _send_chat_text(client, token, base_url, sender, context, result.reply, purpose="chat_reply")
            state = "ACCEPTED_UNCONFIRMED" if sent else "CHAT_COMPLETED_OUTBOUND_FAILED"
            print(f"[chat] request_id={request_id} stage=COMPLETE result={state}", flush=True)
        except Exception as exc:
            print(f"[chat] request_id={request_id} stage={getattr(exc, 'stage', 'CHAT')} result=FAILED error={type(exc).__name__}: {exc}", flush=True)
            _send_chat_text(client, token, base_url, sender, context, _chat_error_message(exc), purpose="chat_error")
        finally:
            _CHAT_LOCK.release()

    _CHAT_EXECUTOR.submit(run_chat)


def _watch_marker(snapshot: WorkSnapshot | None) -> str | None:
    if snapshot is None or snapshot.state != "complete":
        return None
    return snapshot.task_key


def _work_reply(text: str, route_store: RouteStore) -> str | None:
    command = text.strip().lower()
    snapshot = latest_work()
    if command == "/work status":
        return format_status(snapshot)
    if command == "/work last":
        return format_last(snapshot)
    if command == "/work result":
        return format_result(snapshot)
    if command == "/work watch":
        marker = _watch_marker(snapshot)
        route_store.set_watch(True, marker)
        return "Work 主动通知已开启。开发任务首次完整完成时会尝试推送一条简短通知。"
    if command in {"/work unwatch", "/work watch off"}:
        route_store.set_watch(False, None)
        return "Work 主动通知已关闭。"
    if command.startswith("/work"):
        return (
            "可用命令：/work status · /work last · /work result · "
            "/work watch · /work unwatch"
        )
    return None


def _start_codex(
    text: str,
    token: str,
    base_url: str,
    sender: str,
    context: str,
) -> None:
    parts = text.strip().split(maxsplit=2)
    client = WeixinClient()
    if len(parts) < 3:
        _safe_send_text(
            client, token, base_url, sender, context,
            "用法：/codex <project> <task>", purpose="codex_usage", outbound_kind="REPLY",
        )
        return
    if not _CODEX_LOCK.acquire(blocking=False):
        _safe_send_text(
            client, token, base_url, sender, context,
            "已有 Codex 任务运行中，请稍后再试。", purpose="codex_busy", outbound_kind="REPLY",
        )
        return
    project, prompt = parts[1], parts[2]
    _safe_send_text(
        client, token, base_url, sender, context,
        f"Codex 已接收（只读）\n项目：{project}", purpose="codex_accepted", outbound_kind="REPLY",
    )

    def run_task() -> None:
        try:
            result = run_readonly(project, prompt)
            label = "COMPLETE" if result.ok else "FAILED"
            summary = bound_outbound_text(result.message, 700)
            message = (
                f"Codex {label}\n项目：{project}\n摘要：{summary}\n"
                "详细结果请在 PC 端查看。"
            )
            _safe_send_text(
                WeixinClient(), token, base_url, sender, context,
                message, purpose="codex_result", outbound_kind="REPLY",
            )
        except Exception as exc:
            _safe_send_text(
                WeixinClient(), token, base_url, sender, context,
                f"Codex FAILED\n项目：{project}\n原因：{type(exc).__name__}: {exc}\n详细信息请在 PC 端查看。",
                purpose="codex_error", outbound_kind="REPLY",
            )
        finally:
            _CODEX_LOCK.release()

    _CODEX_EXECUTOR.submit(run_task)

def _send_saved_route(text: str, *, purpose: str) -> bool:
    credentials_loaded = CredentialStore().load()
    if not credentials_loaded:
        raise RuntimeError("Weixin is not logged in")
    credentials, token = credentials_loaded
    route_store = RouteStore()
    route = route_store.load_route()
    context_token = route_store.context_token(route)
    if route is None or not context_token:
        raise RuntimeError("No WeChat reply route is known yet")
    return _safe_send_text(
        WeixinClient(),
        token,
        credentials.base_url,
        route.user_id,
        context_token,
        text,
        purpose=purpose,
        outbound_kind="PROACTIVE",
    ) is not None


def send_work_notification(status: str, summary: str) -> None:
    label = status.strip().upper()
    if label != "COMPLETE":
        return
    _send_saved_route("Work COMPLETE\n状态：完成", purpose="work_manual_complete")


def _check_watch(
    client: WeixinClient,
    token: str,
    base_url: str,
    *,
    suppress_proactive: bool = False,
) -> None:
    if suppress_proactive:
        return
    route_store = RouteStore()
    route = route_store.load_route()
    if route is None or not route.watch_enabled:
        return
    context_token = route_store.context_token(route)
    if not context_token:
        return
    snapshot = latest_work()
    marker = _watch_marker(snapshot)
    if snapshot is None or marker is None or marker == route.last_notified:
        return
    project = Path(snapshot.cwd).name if snapshot.cwd else "未知"
    task = snapshot.turn_id or snapshot.session_id
    text = (
        f"项目：{project}\n"
        f"任务：{task}\n"
        "状态：完成"
    )
    route_store.mark_notified(marker)
    _safe_send_text(
        client, token, base_url, route.user_id, context_token,
        text, purpose="work_watch", outbound_kind="PROACTIVE",
    )


def run_bridge() -> int:
    loaded = CredentialStore().load()
    if not loaded:
        raise RuntimeError("尚未登录，请先执行 clawbridge login。")
    credentials, token = loaded
    client = WeixinClient()
    outbound_client = WeixinClient()
    route_store = RouteStore()

    cursor = ""
    print("ClawBridge 已启动。微信可使用 /work、/codex、/chat。")
    client.notify_start(token, credentials.base_url)
    try:
        while True:
            try:
                data = client.get_updates(token, credentials.base_url, cursor, timeout=40)
            except requests.Timeout:
                print("[poll] timeout; retrying", flush=True)
                _check_watch(
                    client,
                    token,
                    credentials.base_url,
                    suppress_proactive=_CHAT_LOCK.locked() or _CODEX_LOCK.locked(),
                )
                continue
            except ILinkStaleTokenError as exc:
                print(f"[poll] stale token; bridge stopping: {exc}", flush=True)
                return 2
            cursor = data.get("get_updates_buf") or cursor
            messages = data.get("msgs") or []
            had_inbound_activity = False
            print(f"[poll] msgs={len(messages)} cursor={'set' if cursor else 'empty'}", flush=True)
            for message in messages:
                sender = message.get("from_user_id")
                context = message.get("context_token")
                text = extract_text(message)
                print(
                    f"[recv] message_type={message.get('message_type')} "
                    f"message_id={'set' if _message_identity(message) else 'missing'} "
                    f"sender={'set' if sender else 'missing'} context={'set' if context else 'missing'} "
                    f"text_chars={len(text) if text else 0}",
                    flush=True,
                )
                if not sender or not context or not text:
                    print("[skip] missing sender/context/text", flush=True)
                    continue
                authorization_reason = _inbound_authorization_reason(credentials, sender)
                if authorization_reason:
                    print(
                        f"[authorization] authorization=REJECTED reason={authorization_reason}",
                        flush=True,
                    )
                    continue
                if not _mark_message_seen(message):
                    print("[skip] duplicate inbound message", flush=True)
                    continue
                had_inbound_activity = True
                route_store.save_route(sender, context)
                lower = text.strip().lower()
                if lower.startswith('/codex'):
                    _start_codex(text, token, credentials.base_url, sender, context)
                    continue
                if lower.startswith('/chat'):
                    _handle_chat(
                        text, token, credentials.base_url, sender, context,
                        client=outbound_client, inbound_id=_message_identity(message),
                    )
                    continue
                reply = _work_reply(text, route_store)
                print(f"[route] reply={'yes' if reply else 'no'}", flush=True)
                if reply:
                    print("[send] sending reply", flush=True)
                    client_id = _safe_send_text(
                        client, token, credentials.base_url, sender, context,
                        reply, purpose="work_reply", outbound_kind="REPLY",
                    )
                    if client_id is not None:
                        print(f"[send] reply API accepted client_id={client_id} delivery=ACCEPTED_UNCONFIRMED", flush=True)
            _check_watch(
                client,
                token,
                credentials.base_url,
                suppress_proactive=(
                    had_inbound_activity or _CHAT_LOCK.locked() or _CODEX_LOCK.locked()
                ),
            )
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            client.notify_stop(token, credentials.base_url)
        except Exception:
            pass
    return 0
