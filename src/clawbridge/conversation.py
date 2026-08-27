from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from clawbridge.config import AppConfig, ChatConfig, local_app_data
from clawbridge.project_context import ProjectContext, build_project_context


MAX_RECENT_MESSAGES = 24
CHAT_REPLY_SOFT_CHARS = 850

CONVERSATION_MODE_POLICY = f"""[ClawBridge Conversation Mode]

This channel is discussion/read-only.

You may analyze, discuss, plan, review, and prepare implementation instructions.
You must not modify files, run code or tests, execute shell or Git write commands,
use coding agents or remote desktop for execution, perform side-effecting local
actions, or claim that you performed such actions.

If the user requests implementation, code changes, tests, commands, deployment,
commits, or other execution work:
1. Do not execute it.
2. Clarify the plan only if necessary.
3. If sufficiently specified, return a concrete handoff headed
   【Codex 执行指令】 with Project, Goal, Current Truth / Background,
   Required Changes, Constraints / Forbidden Changes, Acceptance Criteria,
   Tests, and Final Report.
4. State clearly that execution requires an explicit /codex command. Never
   construct, submit, or invoke that command yourself.

For WeChat readability, keep the default total answer within about
{CHAT_REPLY_SOFT_CHARS} Chinese characters. Even when detail is requested, lead
with the core conclusion, main risks, and next step. If more is useful, answer
the most important part and invite the user to continue. Do not produce
multi-part long-form output by default."""


def conversation_prompt(user_message: str, local_facts: str | None = None) -> str:
    sections = [CONVERSATION_MODE_POLICY]
    if local_facts:
        sections.append(local_facts)
    sections.append(f"[User Message]\n{user_message}")
    return "\n\n".join(sections)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_thread_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname != "chatgpt.com"
        or parts.port is not None
        or parts.username is not None
        or parts.password is not None
        or not parts.path.startswith("/c/")
        or parts.path == "/c/"
    ):
        raise ValueError("Thread URL must be https://chatgpt.com/c/...")
    return urlunsplit(("https", "chatgpt.com", parts.path, "", ""))


@dataclass(frozen=True, slots=True)
class RecentMessage:
    role: str
    text: str
    timestamp: str


@dataclass(slots=True)
class ConversationSession:
    session_id: str = "default"
    current_project: str | None = None
    browser_thread_url: str | None = None
    recent_messages: list[RecentMessage] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or local_app_data() / "chat" / "session.json"

    def load(self) -> ConversationSession:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ConversationSession()
        if raw.get("session_id", "default") != "default":
            raise ValueError("Only the default conversation session is supported")
        messages = [RecentMessage(**item) for item in raw.get("recent_messages", [])]
        if any(item.role not in {"user", "assistant"} for item in messages):
            raise ValueError("Invalid role in recent_messages")
        thread_url = raw.get("browser_thread_url")
        if thread_url is not None:
            thread_url = normalize_thread_url(thread_url)
        return ConversationSession(
            session_id="default",
            current_project=raw.get("current_project"),
            browser_thread_url=thread_url,
            recent_messages=messages[-MAX_RECENT_MESSAGES:],
            created_at=str(raw.get("created_at") or utc_now()),
            updated_at=str(raw.get("updated_at") or utc_now()),
        )

    def save(self, session: ConversationSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(session)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def reset(self) -> ConversationSession:
        existing = self.load()
        now = utc_now()
        reset = ConversationSession(
            session_id="default",
            current_project=existing.current_project,
            created_at=existing.created_at,
            updated_at=now,
        )
        self.save(reset)
        return reset


class ConversationDriver(Protocol):
    stage: str

    def start_new_thread(self) -> None: ...
    def open_thread(self, url: str) -> None: ...
    def send(self, prompt: str): ...
    def current_thread_url(self) -> str: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ConversationResult:
    reply: str
    thread_url: str
    resumed: bool


class ConversationService:
    def __init__(
        self,
        chat_config: ChatConfig,
        *,
        store: SessionStore | None = None,
        driver_factory: Callable[[ChatConfig], ConversationDriver] | None = None,
    ) -> None:
        self.chat_config = chat_config
        self.store = store or SessionStore()
        self.driver_factory = driver_factory or self._default_driver

    @staticmethod
    def _default_driver(config: ChatConfig) -> ConversationDriver:
        from clawbridge.adapters.chatgpt_playwright import PlaywrightChatDriver
        return PlaywrightChatDriver(config)

    def send(self, message: str, *, prompt: str | None = None) -> ConversationResult:
        clean = message.strip()
        if not clean:
            raise ValueError("Message must not be empty")
        outbound = prompt.strip() if prompt is not None else clean
        if not outbound:
            raise ValueError("Prompt must not be empty")
        original = self.store.load()
        resumed = original.browser_thread_url is not None
        driver = self.driver_factory(self.chat_config)
        try:
            if original.browser_thread_url:
                driver.open_thread(original.browser_thread_url)
            else:
                driver.start_new_thread()
            reply = driver.send(outbound)
            thread_url = driver.current_thread_url()
            now = utc_now()
            messages = [
                *original.recent_messages,
                RecentMessage("user", clean, now),
                RecentMessage("assistant", reply.text, utc_now()),
            ][-MAX_RECENT_MESSAGES:]
            updated = ConversationSession(
                session_id=original.session_id,
                current_project=original.current_project,
                browser_thread_url=thread_url,
                recent_messages=messages,
                created_at=original.created_at,
                updated_at=utc_now(),
            )
            self.store.save(updated)
            return ConversationResult(reply.text, thread_url, resumed)
        finally:
            driver.close()


def bind_project(config: AppConfig, store: SessionStore, project: str) -> ConversationSession:
    if project not in config.projects:
        raise ValueError("PROJECT_NOT_CONFIGURED")
    if not config.projects[project].is_dir():
        raise ValueError("PROJECT_ROOT_NOT_FOUND")
    session = store.load()
    session.current_project = project
    session.updated_at = utc_now()
    store.save(session)
    return session


def prepare_message(
    config: AppConfig,
    store: SessionStore,
    message: str,
) -> tuple[str, ProjectContext | None]:
    session = store.load()
    if not session.current_project:
        return conversation_prompt(message), None
    root = config.projects.get(session.current_project)
    if root is None:
        raise ValueError("PROJECT_NOT_CONFIGURED")
    if not root.is_dir():
        raise ValueError("PROJECT_ROOT_NOT_FOUND")
    context = build_project_context(session.current_project, root, message)
    local_facts = context.envelope.split("\n\n[User Message]\n", 1)[0]
    return conversation_prompt(message, local_facts), context
