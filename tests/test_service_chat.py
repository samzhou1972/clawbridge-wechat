from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from steerwx.config import AppConfig, ChatConfig
from steerwx.conversation import ConversationService as CoreConversationService
from steerwx.conversation import ConversationSession, RecentMessage, SessionStore, conversation_prompt
from steerwx.observers.work import WorkSnapshot
from steerwx import service


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_text(self, token, base_url, sender, context, text):
        self.sent.append(text)
        return f"sent-{len(self.sent)}"


class ImmediateExecutor:
    def submit(self, function):
        function()


def config(tmp_path, projects=None):
    return AppConfig(
        code_root=tmp_path,
        codex_executable=None,
        chat=ChatConfig(profile_dir=tmp_path / "profile"),
        projects=projects or {},
        config_path=tmp_path / "config.toml",
    )


@pytest.fixture(autouse=True)
def isolated_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(service, "load_config", lambda: config(tmp_path, {"demo": tmp_path}))
    monkeypatch.setattr(service, "_CHAT_EXECUTOR", ImmediateExecutor())
    monkeypatch.setattr(service, "WeixinClient", FakeClient)
    SessionStore().save(ConversationSession(current_project="demo"))
    if service._CHAT_LOCK.locked():
        service._CHAT_LOCK.release()
    yield
    if service._CHAT_LOCK.locked():
        service._CHAT_LOCK.release()


def handle(text, client=None):
    client = client or FakeClient()
    service._handle_chat(text, "token", "base", "sender", "context", client=client)
    return client


def test_chat_usage_status_and_reset_do_not_start_browser(monkeypatch):
    store = SessionStore()
    store.save(ConversationSession(
        current_project="demo",
        browser_thread_url="https://chatgpt.com/c/existing",
        recent_messages=[RecentMessage("user", "kept", "t")],
    ))
    monkeypatch.setattr(service, "ConversationService", lambda *a, **k: (_ for _ in ()).throw(AssertionError("browser started")))
    assert "/chat use <project>" in handle("/chat").sent[0]
    status = handle("/chat status").sent[0]
    assert "demo" in status and "ACTIVE" in status and "1" in status
    reset = handle("/chat reset").sent[0]
    assert "demo" in reset and "下一条" in reset
    saved = store.load()
    assert saved.current_project == "demo"
    assert saved.browser_thread_url is None and saved.recent_messages == []


def test_first_chat_and_chat_after_reset_create_threads_without_rebinding(monkeypatch):
    created = []

    class Driver:
        def __init__(self):
            self.started = 0
            self.opened = []
            self.prompts = []
            self.closed = False

        def start_new_thread(self):
            self.started += 1

        def open_thread(self, url):
            self.opened.append(url)

        def send(self, prompt):
            self.prompts.append(prompt)
            return SimpleNamespace(text="answer")

        def current_thread_url(self):
            return f"https://chatgpt.com/c/new-{len(created)}"

        def close(self):
            self.closed = True

    def conversation_factory(chat_config, *, store):
        driver = Driver()
        created.append(driver)
        return CoreConversationService(chat_config, store=store, driver_factory=lambda cfg: driver)

    monkeypatch.setattr(service, "ConversationService", conversation_factory)
    monkeypatch.setattr(service, "prepare_message", lambda cfg, store, message: ("project prompt", None))
    assert handle("/chat hello").sent == ["answer"]
    saved = SessionStore().load()
    assert saved.current_project == "demo"
    assert saved.browser_thread_url == "https://chatgpt.com/c/new-1"
    assert [(item.role, item.text) for item in saved.recent_messages] == [
        ("user", "hello"), ("assistant", "answer"),
    ]
    assert created[0].started == 1 and created[0].opened == []
    assert created[0].prompts == ["project prompt"] and created[0].closed

    assert "下一条" in handle("/chat reset").sent[0]
    reset = SessionStore().load()
    assert reset.current_project == "demo"
    assert reset.browser_thread_url is None and reset.recent_messages == []
    assert handle("/chat again").sent == ["answer"]
    assert created[1].started == 1 and created[1].opened == []
    assert created[1].prompts == ["project prompt"] and created[1].closed
    assert SessionStore().load().current_project == "demo"
    assert SessionStore().load().browser_thread_url == "https://chatgpt.com/c/new-2"


def test_chat_without_project_binding_prompts_before_browser(monkeypatch):
    SessionStore().save(ConversationSession())
    monkeypatch.setattr(service, "ConversationService", lambda *a, **k: pytest.fail("browser started"))
    assert handle("/chat 项目进展？").sent == [service.CHAT_PROJECT_REQUIRED]
    assert SessionStore().load().current_project is None


def test_chat_use_preserves_thread_and_history(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(service, "load_config", lambda: config(tmp_path, {"demo": root}))
    store = SessionStore()
    store.save(ConversationSession(
        browser_thread_url="https://chatgpt.com/c/existing",
        recent_messages=[RecentMessage("user", "kept", "t")],
    ))
    reply = handle("/chat use demo").sent[0]
    saved = store.load()
    assert "demo" in reply and str(root) in reply
    assert saved.browser_thread_url == "https://chatgpt.com/c/existing"
    assert saved.recent_messages[0].text == "kept"


def test_chat_use_unknown_and_status_suffix_is_normal_message(monkeypatch):
    assert handle("/chat use unknown").sent == ["项目未配置：\nunknown"]
    calls = []

    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            calls.append((message, prompt))
            return type("Result", (), {"reply": "answer"})()

    outbound = FakeClient()
    monkeypatch.setattr(service, "ConversationService", Conversation)
    handle("/chat status怎么样？", outbound)
    assert calls[0][0] == "status怎么样？"
    assert "[SteerWX Conversation Mode]" in calls[0][1]
    assert outbound.sent == ["answer"]


def test_chat_calls_conversation_once_and_does_not_route_locally(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "prepare_message", lambda cfg, store, message: ("envelope", None))

    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            calls.append((message, prompt))
            return type("Result", (), {"reply": "final only"})()

    outbound = FakeClient()
    monkeypatch.setattr(service, "ConversationService", Conversation)
    handle("/chat hello", outbound)
    assert calls == [("hello", "envelope")]
    assert outbound.sent == ["final only"]


def test_recovered_chat_sends_one_notice_with_answer(monkeypatch):
    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            return SimpleNamespace(reply="answer", recovered=True)

    monkeypatch.setattr(service, "ConversationService", Conversation)
    outbound = handle("/chat hello")
    assert outbound.sent == [service.CHAT_RECOVERY_NOTICE + "\n\nanswer"]


@pytest.mark.parametrize("length", [100, 999, 1000, 1001])
def test_reply_is_one_message_with_1000_char_hard_cap(length):
    outbound = FakeClient()
    service._send_chat_text(
        outbound, "token", "base", "sender", "context", "中" * length,
        purpose="boundary",
    )
    assert len(outbound.sent) == 1
    assert len(outbound.sent[0]) <= 1000
    assert "�" not in outbound.sent[0]
    assert "[1/" not in outbound.sent[0]


@pytest.mark.parametrize("length", [800, 1000])
def test_codex_handoff_within_limit_is_complete(length):
    text = service.CODEX_HANDOFF_MARKER + "中" * (length - len(service.CODEX_HANDOFF_MARKER))
    outbound = FakeClient()
    service._send_chat_text(outbound, "t", "b", "s", "c", text, purpose="handoff")
    assert outbound.sent == [text]


@pytest.mark.parametrize("length", [1001, 5000])
def test_codex_handoff_over_limit_is_replaced_whole(length):
    text = service.CODEX_HANDOFF_MARKER + "中" * (length - len(service.CODEX_HANDOFF_MARKER))
    outbound = FakeClient()
    service._send_chat_text(outbound, "t", "b", "s", "c", text, purpose="handoff")
    assert outbound.sent == [service.CODEX_HANDOFF_COMPLEXITY_MESSAGE]
    assert service.CODEX_HANDOFF_MARKER not in outbound.sent[0]


@pytest.mark.parametrize(("reason", "expected"), [
    ("REPLY_TIMEOUT", "回复超时"),
    ("PAGE_READY_TIMEOUT", "页面暂时未准备好"),
    ("THREAD_UNAVAILABLE", "对话不可用"),
])
def test_conversation_failures_map_without_traceback(reason, expected, monkeypatch):
    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            raise RuntimeError(f"{reason}: internal selector secret")

    outbound = FakeClient()
    monkeypatch.setattr(service, "ConversationService", Conversation)
    handle("/chat hello", outbound)
    assert expected in outbound.sent[0]
    assert "selector" not in outbound.sent[0]


def test_chat_busy_does_not_call_conversation(monkeypatch):
    service._CHAT_LOCK.acquire()
    monkeypatch.setattr(service, "ConversationService", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert "正在处理" in handle("/chat second").sent[0]
    assert "正在处理" in handle("/chat reset").sent[0]
    assert "正在处理" in handle("/chat use demo").sent[0]
    service._CHAT_LOCK.release()


def test_outbound_failure_does_not_repeat_conversation(monkeypatch):
    calls = []

    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            calls.append(message)
            return type("Result", (), {"reply": "answer"})()

    class FailingClient(FakeClient):
        def send_text(self, *args):
            raise RuntimeError("outbound failed")

    monkeypatch.setattr(service, "ConversationService", Conversation)
    handle("/chat hello", FailingClient())
    assert calls == ["hello"]


def test_message_identity_dedup_is_bounded():
    service._SEEN_MESSAGE_IDS.clear()
    service._SEEN_MESSAGE_ORDER.clear()
    message = {"message_id": "same"}
    assert service._mark_message_seen(message) is True
    assert service._mark_message_seen(message) is False


class BridgeClient:
    def __init__(self, messages):
        self.messages = messages
        self.sent = []
        self.polls = 0

    def notify_start(self, *args):
        return None

    def notify_stop(self, *args):
        return None

    def get_updates(self, *args, **kwargs):
        self.polls += 1
        if self.polls == 1:
            return {"msgs": self.messages}
        raise KeyboardInterrupt()

    def send_text(self, token, base_url, sender, context, text):
        self.sent.append(text)
        return "sent"


class RecordingRouteStore:
    def __init__(self):
        self.saved = []

    def save_route(self, sender, context):
        self.saved.append((sender, context))


@pytest.mark.parametrize(("bound_user", "sender", "reason"), [
    (None, "allowed", "BOUND_USER_UNAVAILABLE"),
    ("allowed", "other", "SENDER_MISMATCH"),
])
def test_rejected_inbound_cannot_route_or_save_state(monkeypatch, capsys, bound_user, sender, reason):
    bridge_client = BridgeClient([{
        "message_id": "message-1", "message_type": 1, "from_user_id": sender,
        "context_token": "ctx", "item_list": [{"type": 1, "text_item": {"text": "/chat confidential text"}}],
    }])
    route_store = RecordingRouteStore()
    monkeypatch.setattr(service, "CredentialStore", lambda: SimpleNamespace(load=lambda: (SimpleNamespace(user_id=bound_user, base_url="base"), "token")))
    monkeypatch.setattr(service, "WeixinClient", lambda: bridge_client)
    monkeypatch.setattr(service, "RouteStore", lambda: route_store)
    monkeypatch.setattr(service, "_check_watch", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_handle_chat", lambda *args, **kwargs: pytest.fail("chat routed"))
    monkeypatch.setattr(service, "_start_codex", lambda *args, **kwargs: pytest.fail("codex routed"))
    assert service.run_bridge() == 130
    output = capsys.readouterr().out
    assert f"authorization=REJECTED reason={reason}" in output
    assert "confidential text" not in output
    assert route_store.saved == []


def test_authorized_inbound_still_saves_route_and_routes_work(monkeypatch):
    bridge_client = BridgeClient([{
        "message_id": "message-2", "message_type": 1, "from_user_id": "allowed",
        "context_token": "ctx", "item_list": [{"type": 1, "text_item": {"text": "/work status"}}],
    }])
    route_store = RecordingRouteStore()
    monkeypatch.setattr(service, "CredentialStore", lambda: SimpleNamespace(load=lambda: (SimpleNamespace(user_id="allowed", base_url="base"), "token")))
    monkeypatch.setattr(service, "WeixinClient", lambda: bridge_client)
    monkeypatch.setattr(service, "RouteStore", lambda: route_store)
    monkeypatch.setattr(service, "_check_watch", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_work_reply", lambda text, store: "work result")
    assert service.run_bridge() == 130
    assert route_store.saved == [("allowed", "ctx")]
    assert bridge_client.sent == ["work result"]


@pytest.mark.parametrize("execution_request", [
    "请修改代码", "请运行 pytest", "请 git commit", "请部署",
])
def test_chat_execution_requests_stay_on_conversation_path(execution_request, monkeypatch):
    calls = {"conversation": 0, "codex": 0, "subprocess": 0}
    monkeypatch.setattr(service, "prepare_message", lambda cfg, store, message: (conversation_prompt(message), None))

    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            calls["conversation"] += 1
            assert "[SteerWX Conversation Mode]" in prompt
            return type("Result", (), {"reply": "【Codex 执行指令】\n如需执行，请通过显式 /codex 命令提交该任务。"})()

    monkeypatch.setattr(service, "ConversationService", Conversation)
    monkeypatch.setattr(service, "run_readonly", lambda *a, **k: calls.__setitem__("codex", 1))
    monkeypatch.setattr("steerwx.project_context.subprocess.run", lambda *a, **k: calls.__setitem__("subprocess", 1))
    outbound = FakeClient()
    handle(f"/chat {execution_request}", outbound)
    assert calls == {"conversation": 1, "codex": 0, "subprocess": 0}
    assert "Codex 执行指令" in outbound.sent[0]


def test_async_chat_reply_reuses_supplied_outbound_client(monkeypatch):
    class Conversation:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, message, *, prompt):
            return type("Result", (), {"reply": "answer"})()

    monkeypatch.setattr(service, "ConversationService", Conversation)
    monkeypatch.setattr(
        service, "WeixinClient",
        lambda: (_ for _ in ()).throw(AssertionError("created an ad-hoc outbound client")),
    )
    outbound = FakeClient()
    handle("/chat hello", outbound)
    assert outbound.sent == ["answer"]


class FakeRouteStore:
    def __init__(self):
        self.route = type("Route", (), {
            "watch_enabled": True, "last_notified": None, "user_id": "user",
        })()

    def load_route(self):
        return self.route

    def context_token(self, route):
        return "ctx"

    def mark_notified(self, marker):
        self.route.last_notified = marker


def work_snapshot(tmp_path, state, result="very long result"):
    return WorkSnapshot(
        session_id="session", turn_id="turn", cwd=r"D:\code\steerwx",
        state=state, started_at=1, completed_at=2 if state == "complete" else None,
        updated_at=2, last_message=result, result=result if state == "complete" else None,
        source_path=tmp_path / "rollout.jsonl",
    )


@pytest.mark.parametrize("state", ["running", "pending", "failed", "partial"])
def test_work_watch_only_notifies_complete(tmp_path, monkeypatch, state):
    route_store = FakeRouteStore()
    client = FakeClient()
    monkeypatch.setattr(service, "RouteStore", lambda: route_store)
    monkeypatch.setattr(service, "latest_work", lambda: work_snapshot(tmp_path, state))
    service._check_watch(client, "token", "base")
    assert client.sent == []


def test_work_watch_defers_proactive_without_consuming_complete_marker(tmp_path, monkeypatch):
    route_store = FakeRouteStore()
    client = FakeClient()
    snapshot = work_snapshot(tmp_path, "complete")
    monkeypatch.setattr(service, "RouteStore", lambda: route_store)
    monkeypatch.setattr(service, "latest_work", lambda: snapshot)

    service._check_watch(client, "token", "base", suppress_proactive=True)
    assert client.sent == []
    assert route_store.route.last_notified is None

    service._check_watch(client, "token", "base")
    assert client.sent == ["项目：steerwx\n任务：turn\n状态：完成"]
    assert route_store.route.last_notified == snapshot.task_key


def test_work_watch_complete_is_short_idempotent_and_persistent(tmp_path, monkeypatch, capsys):
    route_store = FakeRouteStore()
    client = FakeClient()
    snapshot = work_snapshot(tmp_path, "complete", "result body " * 1000)
    monkeypatch.setattr(service, "RouteStore", lambda: route_store)
    monkeypatch.setattr(service, "latest_work", lambda: snapshot)
    service._check_watch(client, "token", "base")
    service._check_watch(client, "token", "base")
    assert client.sent == ["项目：steerwx\n任务：turn\n状态：完成"]
    assert "result body" not in client.sent[0]
    assert route_store.route.last_notified == snapshot.task_key
    output = capsys.readouterr().out
    assert "outbound_kind=PROACTIVE" in output
    assert "delivery=ACCEPTED_UNCONFIRMED" in output


def test_work_watch_restored_last_notified_prevents_repeat(tmp_path, monkeypatch):
    snapshot = work_snapshot(tmp_path, "complete")
    restored = FakeRouteStore()
    restored.route.last_notified = snapshot.task_key
    client = FakeClient()
    monkeypatch.setattr(service, "RouteStore", lambda: restored)
    monkeypatch.setattr(service, "latest_work", lambda: snapshot)
    service._check_watch(client, "token", "base")
    assert client.sent == []
