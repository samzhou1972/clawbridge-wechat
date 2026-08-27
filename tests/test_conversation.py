import json

import pytest

from clawbridge.cli import _chat_local
from clawbridge.config import AppConfig, ChatConfig
from clawbridge.conversation import (
    MAX_RECENT_MESSAGES,
    ConversationService,
    ConversationSession,
    RecentMessage,
    SessionStore,
    normalize_thread_url,
    prepare_message,
)
from clawbridge.project_context import (
    GitContextProvider,
    WorkContextProvider,
    build_project_context,
    select_context,
)
from clawbridge.observers.work import WorkSnapshot


class Reply:
    def __init__(self, text):
        self.text = text


class FakeDriver:
    stage = "IDLE"

    def __init__(self, *, url="https://chatgpt.com/c/new-thread", fail=None):
        self.url = url
        self.fail = fail
        self.opened = None
        self.started = False
        self.closed = False

    def start_new_thread(self):
        self.started = True

    def open_thread(self, url):
        self.opened = url
        if self.fail == "open":
            raise RuntimeError("THREAD_UNAVAILABLE")

    def send(self, prompt):
        if self.fail == "send":
            raise RuntimeError("send failed")
        if self.fail == "capture":
            raise RuntimeError("capture failed")
        return Reply(f"reply: {prompt}")

    def current_thread_url(self):
        if self.fail == "url":
            raise RuntimeError("THREAD_URL_NOT_CREATED")
        return normalize_thread_url(self.url)

    def close(self):
        self.closed = True


def service(tmp_path, driver):
    store = SessionStore(tmp_path / "chat" / "session.json")
    value = ConversationService(
        ChatConfig(profile_dir=tmp_path / "profile"),
        store=store,
        driver_factory=lambda config: driver,
    )
    return value, store


def test_missing_session_creates_default_state_in_memory(tmp_path):
    session = SessionStore(tmp_path / "session.json").load()
    assert session.session_id == "default"
    assert session.browser_thread_url is None
    assert session.recent_messages == []


def test_first_message_creates_session_and_saves_thread(tmp_path):
    driver = FakeDriver(url="https://chatgpt.com/c/abc?temporary=true")
    conversation, store = service(tmp_path, driver)
    result = conversation.send("hello")
    saved = store.load()
    assert driver.started is True
    assert result.resumed is False
    assert saved.browser_thread_url == "https://chatgpt.com/c/abc"
    assert [(item.role, item.text) for item in saved.recent_messages] == [
        ("user", "hello"),
        ("assistant", "reply: hello"),
    ]
    assert driver.closed is True


def test_second_process_reuses_saved_thread(tmp_path):
    first, store = service(tmp_path, FakeDriver(url="https://chatgpt.com/c/abc"))
    first.send("one")
    second_driver = FakeDriver(url="https://chatgpt.com/c/abc")
    second = ConversationService(
        ChatConfig(profile_dir=tmp_path / "profile"),
        store=SessionStore(store.path),
        driver_factory=lambda config: second_driver,
    )
    result = second.send("two")
    assert result.resumed is True
    assert second_driver.opened == "https://chatgpt.com/c/abc"
    assert len(store.load().recent_messages) == 4


def test_recent_messages_trim_oldest_entries(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    old = [RecentMessage("user", str(index), "t") for index in range(MAX_RECENT_MESSAGES)]
    store.save(ConversationSession(recent_messages=old))
    driver = FakeDriver()
    ConversationService(
        ChatConfig(profile_dir=tmp_path / "profile"),
        store=store,
        driver_factory=lambda config: driver,
    ).send("latest")
    messages = store.load().recent_messages
    assert len(messages) == MAX_RECENT_MESSAGES
    assert messages[0].text == "2"
    assert messages[-2].text == "latest"


@pytest.mark.parametrize("failure", ["open", "send", "capture", "url"])
def test_failure_preserves_existing_session_and_closes_driver(tmp_path, failure):
    store = SessionStore(tmp_path / "session.json")
    original = ConversationSession(
        browser_thread_url="https://chatgpt.com/c/original",
        recent_messages=[RecentMessage("user", "kept", "t")],
    )
    store.save(original)
    before = store.path.read_bytes()
    driver = FakeDriver(url="https://chatgpt.com/c/original", fail=failure)
    conversation = ConversationService(
        ChatConfig(profile_dir=tmp_path / "profile"),
        store=store,
        driver_factory=lambda config: driver,
    )
    with pytest.raises(RuntimeError):
        conversation.send("not saved")
    assert store.path.read_bytes() == before
    assert driver.closed is True


def test_reset_clears_thread_and_history_but_keeps_default(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save(ConversationSession(
        current_project="clawbridge",
        browser_thread_url="https://chatgpt.com/c/abc",
        recent_messages=[RecentMessage("user", "hello", "t")],
    ))
    reset = store.reset()
    assert reset.session_id == "default"
    assert reset.browser_thread_url is None
    assert reset.recent_messages == []
    assert reset.current_project == "clawbridge"


@pytest.mark.parametrize(
    "url",
    [
        "http://chatgpt.com/c/abc",
        "https://example.com/c/abc",
        "https://chatgpt.com/",
        "https://chatgpt.com/c/",
        "https://chatgpt.com:443/c/abc",
        "https://someone@chatgpt.com/c/abc",
    ],
)
def test_invalid_thread_urls_are_rejected(url):
    with pytest.raises(ValueError):
        normalize_thread_url(url)


def test_session_save_is_atomic_and_leaves_no_temp_file(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "session.json")
    store.save(ConversationSession())
    calls = []
    monkeypatch.setattr("clawbridge.conversation.os.replace", lambda source, target: calls.append((source, target)))
    store.save(ConversationSession())
    assert len(calls) == 1
    assert calls[0][0].parent == store.path.parent
    assert calls[0][1] == store.path
    assert not calls[0][0].exists()


def test_failed_atomic_replace_preserves_old_session(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "session.json")
    store.save(ConversationSession(recent_messages=[RecentMessage("user", "old", "t")]))
    before = store.path.read_bytes()
    monkeypatch.setattr(
        "clawbridge.conversation.os.replace",
        lambda source, target: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        store.save(ConversationSession(recent_messages=[RecentMessage("user", "new", "t")]))
    assert store.path.read_bytes() == before
    assert list(store.path.parent.glob("*.tmp")) == []


def test_saved_json_has_only_session_fields(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save(ConversationSession())
    assert set(json.loads(store.path.read_text(encoding="utf-8"))) == {
        "session_id", "current_project", "browser_thread_url", "recent_messages",
        "created_at", "updated_at"
    }


def test_status_does_not_construct_browser_driver(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "clawbridge.conversation.ConversationService._default_driver",
        lambda config: (_ for _ in ()).throw(AssertionError("browser started")),
    )
    assert _chat_local("status") == 0
    assert "Thread                NONE" in capsys.readouterr().out


def test_prompt_envelope_is_not_saved_as_recent_user_message(tmp_path):
    driver = FakeDriver()
    conversation, store = service(tmp_path, driver)
    conversation.send("原始消息", prompt="[ClawBridge Local Facts]\nsecret facts")
    assert store.load().recent_messages[0].text == "原始消息"


def test_context_routing_is_deterministic():
    assert select_context("你觉得这个方案有什么风险？").names == ()
    assert select_context("当前Work任务进展怎么样？").names == ("Work",)
    assert select_context("当前项目有没有未提交修改？").names == ("Git",)
    assert select_context("最近Work和Git状态怎么样？").names == ("Work", "Git")


class StubWork:
    def read(self, root):
        return "work fact"


class StubGit:
    def read(self, root):
        return "git fact"


def test_context_envelope_marks_facts_and_original_message(tmp_path):
    result = build_project_context(
        "demo", tmp_path, "Work和Git状态", work_provider=StubWork(), git_provider=StubGit()
    )
    assert result.selection.names == ("Work", "Git")
    assert "[ClawBridge Local Facts]" in result.envelope
    assert "Work:\nwork fact" in result.envelope
    assert "Git:\ngit fact" in result.envelope
    assert result.envelope.endswith("[User Message]\nWork和Git状态")


def test_provider_failure_is_visible_but_context_still_builds(tmp_path):
    class Broken:
        def read(self, root):
            raise RuntimeError("fixture failed")

    result = build_project_context("demo", tmp_path, "Work状态", work_provider=Broken())
    assert "Work context unavailable: fixture failed" in result.envelope
    assert result.warnings


def test_git_provider_clean_dirty_branch_commit_and_no_shell(tmp_path, monkeypatch):
    calls = []
    outputs = iter([
        (0, "", ""),
        (0, "main\n", ""),
        (0, "abc123\tinitial commit\n", ""),
        (0, " M file.txt\n?? new.txt\n", ""),
        (0, "main\n", ""),
        (0, "abc123\tinitial commit\n", ""),
    ])

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        code, stdout, stderr = next(outputs)
        return __import__("subprocess").CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr("clawbridge.project_context.subprocess.run", fake_run)
    clean = GitContextProvider().read(tmp_path)
    dirty = GitContextProvider().read(tmp_path)
    assert "status: OK" in clean
    assert "working_tree: CLEAN" in clean
    assert "working_tree: DIRTY" in dirty
    assert "changed_file_count: 2" in dirty
    assert "branch: main" in clean and "last_commit_short_hash: abc123" in clean
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all(isinstance(args, list) for args, _ in calls)


def test_git_provider_non_repository(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        return __import__("subprocess").CompletedProcess(
            args, 128, "", "fatal: not a git repository"
        )

    monkeypatch.setattr("clawbridge.project_context.subprocess.run", fake_run)
    assert GitContextProvider().read(tmp_path) == "status: NOT_A_GIT_REPOSITORY"


def test_work_provider_does_not_inject_other_project(tmp_path):
    provider = WorkContextProvider(loader=lambda root: None)
    result = provider.read(tmp_path)
    assert "status: NO_MATCH" in result
    assert "current observer" in result
    assert "does not prove that no Work task exists" in result


def test_work_provider_matching_snapshot_keeps_normal_output(tmp_path):
    snapshot = WorkSnapshot(
        session_id="session",
        turn_id="turn",
        cwd=str(tmp_path),
        state="ACTIVE",
        started_at=1.0,
        completed_at=None,
        updated_at=1_700_000_000.0,
        last_message="working",
        result=None,
        source_path=tmp_path / "rollout.jsonl",
    )
    result = WorkContextProvider(loader=lambda root: snapshot).read(tmp_path)
    assert "State: ACTIVE" in result
    assert "Last message: working" in result
    assert "status: NO_MATCH" not in result


def test_git_provider_no_commits_keeps_status_and_branch(tmp_path, monkeypatch):
    outputs = iter([
        (0, " M file.txt\n?? new.txt\n", ""),
        (0, "main\n", ""),
        (128, "", "fatal: your current branch 'main' does not have any commits yet"),
    ])

    def fake_run(args, **kwargs):
        code, stdout, stderr = next(outputs)
        return __import__("subprocess").CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr("clawbridge.project_context.subprocess.run", fake_run)
    result = GitContextProvider().read(tmp_path)
    assert "status: PARTIAL" in result
    assert "branch: main" in result
    assert "working_tree: DIRTY" in result
    assert "changed_file_count: 2" in result
    assert "last_commit_reason: NO_COMMITS" in result


def test_git_provider_clean_repository_without_commits_is_partial(tmp_path, monkeypatch):
    outputs = iter([
        (0, "", ""),
        (0, "main\n", ""),
        (128, "", "fatal: your current branch 'main' does not have any commits yet"),
    ])

    def fake_run(args, **kwargs):
        code, stdout, stderr = next(outputs)
        return __import__("subprocess").CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr("clawbridge.project_context.subprocess.run", fake_run)
    result = GitContextProvider().read(tmp_path)
    assert "status: PARTIAL" in result
    assert "working_tree: CLEAN" in result
    assert "changed_file_count: 0" in result
    assert "last_commit_reason: NO_COMMITS" in result


def test_git_provider_log_failure_is_partial(tmp_path, monkeypatch):
    outputs = iter([(0, "", ""), (0, "main\n", ""), (1, "", "log failed")])
    monkeypatch.setattr(
        "clawbridge.project_context.subprocess.run",
        lambda args, **kwargs: __import__("subprocess").CompletedProcess(args, *next(outputs)),
    )
    result = GitContextProvider().read(tmp_path)
    assert "status: PARTIAL" in result
    assert "working_tree: CLEAN" in result
    assert "last_commit_reason: COMMAND_FAILED" in result


def test_git_provider_status_failure_keeps_branch_and_commit(tmp_path, monkeypatch):
    outputs = iter([(1, "", "status failed"), (0, "main\n", ""), (0, "abc\tmessage\n", "")])
    monkeypatch.setattr(
        "clawbridge.project_context.subprocess.run",
        lambda args, **kwargs: __import__("subprocess").CompletedProcess(args, *next(outputs)),
    )
    result = GitContextProvider().read(tmp_path)
    assert "status: PARTIAL" in result
    assert "branch: main" in result
    assert "working_tree: NOT_AVAILABLE" in result
    assert "last_commit_short_hash: abc" in result


def test_git_provider_all_fact_commands_fail_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clawbridge.project_context.subprocess.run",
        lambda args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git missing")),
    )
    result = GitContextProvider().read(tmp_path)
    assert result.startswith("status: UNAVAILABLE")


def _app_config(tmp_path, projects):
    return AppConfig(
        code_root=tmp_path,
        codex_executable=None,
        chat=ChatConfig(profile_dir=tmp_path / "profile"),
        projects=projects,
        config_path=tmp_path / "config.toml",
    )


def test_chat_local_use_saves_project_without_changing_conversation(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("clawbridge.cli.load_config", lambda: _app_config(tmp_path, {"demo": root}))
    store = SessionStore()
    store.save(ConversationSession(
        browser_thread_url="https://chatgpt.com/c/existing",
        recent_messages=[RecentMessage("user", "kept", "t")],
    ))
    monkeypatch.setattr(
        "clawbridge.conversation.ConversationService._default_driver",
        lambda config: (_ for _ in ()).throw(AssertionError("browser started")),
    )
    assert _chat_local("use", project="demo") == 0
    saved = store.load()
    assert saved.current_project == "demo"
    assert saved.browser_thread_url == "https://chatgpt.com/c/existing"
    assert saved.recent_messages[0].text == "kept"
    assert "Project root" in capsys.readouterr().out


def test_chat_local_use_rejects_unknown_and_missing_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    missing = tmp_path / "missing"
    monkeypatch.setattr("clawbridge.cli.load_config", lambda: _app_config(tmp_path, {"gone": missing}))
    assert _chat_local("use", project="unknown") == 2
    assert "PROJECT_NOT_CONFIGURED" in capsys.readouterr().err
    assert _chat_local("use", project="gone") == 2
    assert "PROJECT_ROOT_NOT_FOUND" in capsys.readouterr().err


def test_status_shows_project_without_running_providers(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("clawbridge.cli.load_config", lambda: _app_config(tmp_path, {"demo": root}))
    SessionStore().save(ConversationSession(current_project="demo"))
    monkeypatch.setattr(
        "clawbridge.cli.build_project_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider ran")),
    )
    assert _chat_local("status") == 0
    output = capsys.readouterr().out
    assert "Project               demo" in output
    assert str(root) in output


def test_show_context_reports_selection_and_original_send(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("clawbridge.cli.load_config", lambda: _app_config(tmp_path, {"demo": root}))
    SessionStore().save(ConversationSession(current_project="demo"))
    calls = []

    class FakeService:
        def __init__(self, config, store):
            pass

        def send(self, message, *, prompt=None):
            calls.append((message, prompt))
            return type("Result", (), {"resumed": False, "reply": "ok"})()

    monkeypatch.setattr("clawbridge.cli.ConversationService", FakeService)
    assert _chat_local("当前项目有没有未提交修改？", show_context=True) == 0
    output = capsys.readouterr().out
    assert "Selected project      demo" in output
    assert "Selected providers    Git" in output
    assert calls[0][0] == "当前项目有没有未提交修改？"
    assert "[ClawBridge Local Facts]" in calls[0][1]


def test_chat_without_project_does_not_build_context(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("clawbridge.cli.load_config", lambda: _app_config(tmp_path, {}))
    calls = []

    class FakeService:
        def __init__(self, config, store):
            pass

        def send(self, message, *, prompt=None):
            calls.append((message, prompt))
            return type("Result", (), {"resumed": False, "reply": "ok"})()

    monkeypatch.setattr("clawbridge.cli.ConversationService", FakeService)
    monkeypatch.setattr(
        "clawbridge.cli.build_project_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("context built")),
    )
    assert _chat_local("普通聊天") == 0
    assert calls[0][0] == "普通聊天"
    assert "[ClawBridge Conversation Mode]" in calls[0][1]
    assert calls[0][1].endswith("[User Message]\n普通聊天")


def test_conversation_policy_is_separate_and_not_saved(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    driver = FakeDriver()
    prompt, context = prepare_message(_app_config(tmp_path, {}), store, "请修改代码")
    assert context is None
    assert prompt.startswith("[ClawBridge Conversation Mode]")
    assert "explicit /codex" in prompt
    ConversationService(
        ChatConfig(profile_dir=tmp_path / "profile"),
        store=store,
        driver_factory=lambda config: driver,
    ).send("请修改代码", prompt=prompt)
    assert store.load().recent_messages[0].text == "请修改代码"
    assert "ClawBridge Conversation Mode" not in store.load().recent_messages[0].text
