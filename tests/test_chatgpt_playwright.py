import json
import sys

import pytest

from clawbridge.adapters.chatgpt_playwright import (
    ChatDriverError,
    ChatHealth,
    PlaywrightChatDriver,
)
from clawbridge.config import ChatConfig
from clawbridge.cli import _chat_browser


class ScreenshotPage:
    url = "https://chatgpt.com/"

    def title(self):
        return "ChatGPT"

    def screenshot(self, *, path, full_page):
        assert full_page is True
        with open(path, "wb") as handle:
            handle.write(b"png")


def test_driver_state_transitions(tmp_path) -> None:
    driver = PlaywrightChatDriver(ChatConfig(profile_dir=tmp_path / "profile"))
    assert driver.stage == "IDLE"
    for stage in ("BROWSER_STARTING", "BROWSER_READY", "PAGE_READY", "COMPOSER_FOUND"):
        driver._set_stage(stage)
        assert driver.stage == stage
    with pytest.raises(ValueError):
        driver._set_stage("UNKNOWN")


def test_diagnostics_preserve_original_error(tmp_path) -> None:
    driver = PlaywrightChatDriver(
        ChatConfig(profile_dir=tmp_path / "profile"),
        diagnostics_dir=tmp_path / "diagnostics",
    )
    driver._page = ScreenshotPage()
    with pytest.raises(ChatDriverError) as caught:
        driver._fail("COMPOSER_FOUND", RuntimeError("synthetic failure"))
    assert caught.value.reason == "synthetic failure"
    folders = list((tmp_path / "diagnostics").iterdir())
    payload = json.loads((folders[0] / "error.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "COMPOSER_FOUND"
    assert payload["reason"] == "synthetic failure"
    assert payload["url"] == "https://chatgpt.com/"
    assert payload["current_url"] == "https://chatgpt.com/"
    assert payload["page_title"] == "ChatGPT"
    assert (folders[0] / "screenshot.png").read_bytes() == b"png"


def test_health_maps_driver_error_without_real_browser(tmp_path, monkeypatch) -> None:
    driver = PlaywrightChatDriver(ChatConfig(profile_dir=tmp_path / "profile"))

    def fail():
        raise ChatDriverError("PAGE_READY", "login required", "https://chatgpt.com/")

    monkeypatch.setattr(driver, "ensure_ready", fail)
    health = driver.health()
    assert health.ready is False
    assert health.stage == "FAILED"
    assert health.reason == "login required"
    assert health.auth_state == "UNKNOWN"


def test_doctor_output_maps_success_without_real_browser(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(PlaywrightChatDriver, "chrome_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        PlaywrightChatDriver,
        "health",
        lambda self: ChatHealth(
            "COMPOSER_FOUND", True, "PASS", True, "https://chatgpt.com/",
            browser_launched=True, reachable=True, page_ready=True,
        ),
    )
    assert _chat_browser(False, False) == 0
    output = capsys.readouterr().out
    assert "Chrome executable     PASS" in output
    assert "Browser launch        PASS" in output
    assert "ChatGPT session       PASS" in output
    assert "Composer              PASS" in output


class FakeItem:
    def __init__(self, *, visible=True, editable=True, text=""):
        self.visible = visible
        self.editable = editable
        self.text = text
        self.inner_text_timeouts = []

    def is_visible(self, timeout=0):
        return self.visible

    def is_editable(self, timeout=0):
        return self.editable

    def fill(self, value):
        self.value = value

    def press(self, key):
        self.key = key

    def inner_text(self, timeout=None):
        self.inner_text_timeouts.append(timeout)
        return self.text


class FakeLocator:
    def __init__(self, items):
        self.items = items

    @property
    def first(self):
        return self.items[0] if self.items else FakeItem(visible=False, editable=False)

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class FakePage:
    url = "https://chatgpt.com/"

    def __init__(self, mapping=None, on_wait=None):
        self.mapping = mapping or {}
        self.on_wait = on_wait
        self.wait_count = 0
        self.elapsed = 0.0

    def locator(self, selector):
        return FakeLocator(self.mapping.get(selector, []))

    def goto(self, url, wait_until=None):
        self.url = url

    def title(self):
        return "ChatGPT"

    def wait_for_timeout(self, milliseconds):
        self.wait_count += 1
        self.elapsed += milliseconds / 1000
        if self.on_wait:
            self.on_wait(self)

    def screenshot(self, *, path, full_page):
        with open(path, "wb") as handle:
            handle.write(b"png")


def _driver_with_page(tmp_path, page, *, timeout=1, reply_timeout=180):
    driver = PlaywrightChatDriver(
        ChatConfig(
            profile_dir=tmp_path / "profile",
            startup_timeout_seconds=timeout,
            reply_timeout_seconds=reply_timeout,
        ),
        diagnostics_dir=tmp_path / "diagnostics",
    )
    driver._page = page
    driver._context = object()
    driver._start = lambda: None
    return driver


def _send_ready_driver(tmp_path, monkeypatch, page, *, reply_timeout=180):
    driver = _driver_with_page(tmp_path, page, reply_timeout=reply_timeout)
    monkeypatch.setattr(driver, "ensure_ready", lambda: None)
    monkeypatch.setattr(
        "clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed
    )
    return driver


def test_send_fast_response_uses_reply_deadline(tmp_path, monkeypatch) -> None:
    composer = FakeItem()
    assistant = FakeItem(text="done")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [composer],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })

    def reveal(current):
        if current.elapsed >= 5:
            current.mapping[PlaywrightChatDriver.ASSISTANT_MESSAGES[0]] = [assistant]

    page.on_wait = reveal
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("hello")
    assert reply.text == "done"
    assert assistant.inner_text_timeouts
    assert 173_000 <= assistant.inner_text_timeouts[0] <= 175_000


def test_send_response_after_default_30_seconds_passes(tmp_path, monkeypatch) -> None:
    assistant = FakeItem(text="late response")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })

    def reveal(current):
        if current.elapsed >= 45:
            current.mapping[PlaywrightChatDriver.ASSISTANT_MESSAGES[0]] = [assistant]

    page.on_wait = reveal
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("slow")
    assert reply.text == "late response"
    assert assistant.inner_text_timeouts[0] > 30_000


def test_streaming_over_30_seconds_uses_declining_remaining_timeout(tmp_path, monkeypatch) -> None:
    assistant = FakeItem(text="part")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
        PlaywrightChatDriver.GENERATION_MARKERS[0]: [FakeItem()],
    })

    def stream(current):
        current.mapping[PlaywrightChatDriver.ASSISTANT_MESSAGES[0]] = [assistant]
        if current.elapsed >= 45:
            assistant.text = "complete"
            current.mapping[PlaywrightChatDriver.GENERATION_MARKERS[0]] = []
        elif current.elapsed >= 1:
            assistant.text = f"part {int(current.elapsed)}"

    page.on_wait = stream
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("stream")
    assert reply.text == "complete"
    assert max(assistant.inner_text_timeouts) > 30_000
    assert assistant.inner_text_timeouts[-1] < assistant.inner_text_timeouts[0]


def test_stable_text_completes_after_two_seconds(tmp_path, monkeypatch) -> None:
    assistant = FakeItem(text="quick")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })
    page.on_wait = lambda current: current.mapping.__setitem__(
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0], [assistant]
    )
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("hello")
    assert reply.text == "quick"
    assert 2 <= page.elapsed < 3


def test_growing_text_does_not_complete_early(tmp_path, monkeypatch) -> None:
    assistant = FakeItem(text="a")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })

    def grow(current):
        current.mapping[PlaywrightChatDriver.ASSISTANT_MESSAGES[0]] = [assistant]
        if current.elapsed < 3:
            assistant.text += "b"

    page.on_wait = grow
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("grow")
    assert reply.text.startswith("ab")
    assert page.elapsed >= 4.75


def test_completion_marker_allows_stable_reply_despite_generation_marker(
    tmp_path, monkeypatch
) -> None:
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
        PlaywrightChatDriver.GENERATION_MARKERS[0]: [FakeItem()],
        PlaywrightChatDriver.COMPLETION_MARKERS[0]: [FakeItem()],
    })
    assistant = FakeItem(text="done")
    page.on_wait = lambda current: current.mapping.__setitem__(
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0], [assistant]
    )
    reply = _send_ready_driver(tmp_path, monkeypatch, page).send("hello")
    assert reply.text == "done"
    assert 2 <= page.elapsed < 3


def test_stale_generation_marker_has_bounded_grace_wx418_equivalent(
    tmp_path, monkeypatch
) -> None:
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
        PlaywrightChatDriver.GENERATION_MARKERS[0]: [FakeItem()],
    })
    assistant = FakeItem(text="WX-418")
    page.on_wait = lambda current: current.mapping.__setitem__(
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0], [assistant]
    )
    reply = _send_ready_driver(tmp_path, monkeypatch, page, reply_timeout=180).send("remember")
    assert reply.text == "WX-418"
    assert 4 <= page.elapsed < 5


def test_continuously_changing_text_reaches_reply_timeout(tmp_path, monkeypatch) -> None:
    assistant = FakeItem(text="a")
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })
    def keep_changing(current):
        current.mapping[PlaywrightChatDriver.ASSISTANT_MESSAGES[0]] = [assistant]
        assistant.text += "a"
    page.on_wait = keep_changing
    driver = _send_ready_driver(tmp_path, monkeypatch, page, reply_timeout=2)
    with pytest.raises(ChatDriverError, match="REPLY_TIMEOUT"):
        driver.send("never stable")
    payload = json.loads(next((tmp_path / "diagnostics").iterdir()).joinpath("error.json").read_text())
    assert payload["final_text_length"] > 0
    assert payload["last_text_change_at"] is not None
    assert payload["text_stable_seconds"] < 2


def test_reply_timeout_is_business_error_with_diagnostics(tmp_path, monkeypatch) -> None:
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    })
    driver = _send_ready_driver(tmp_path, monkeypatch, page, reply_timeout=2)
    with pytest.raises(ChatDriverError, match="REPLY_TIMEOUT") as caught:
        driver.send("never answered")
    assert caught.value.stage == "PROMPT_SENT"
    payload = json.loads(next((tmp_path / "diagnostics").iterdir()).joinpath("error.json").read_text())
    assert payload["configured_reply_timeout_seconds"] == 2
    assert payload["elapsed_response_seconds"] >= 2
    assert payload["assistant_count_before"] == 0
    assert payload["assistant_count_after"] == 0
    assert payload["response_started"] is False


def test_response_started_capture_timeout_is_business_error(tmp_path, monkeypatch) -> None:
    page = FakePage()

    class BlockingAssistant(FakeItem):
        def inner_text(self, timeout=None):
            self.inner_text_timeouts.append(timeout)
            page.elapsed += timeout / 1000
            raise TimeoutError("synthetic Playwright timeout")

    assistant = BlockingAssistant()
    page.mapping = {
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0]: [],
    }
    page.on_wait = lambda current: current.mapping.__setitem__(
        PlaywrightChatDriver.ASSISTANT_MESSAGES[0], [assistant]
    )
    driver = _send_ready_driver(tmp_path, monkeypatch, page, reply_timeout=2)
    with pytest.raises(ChatDriverError, match="REPLY_TIMEOUT") as caught:
        driver.send("started but never captured")
    assert caught.value.stage == "RESPONSE_STARTED"
    payload = json.loads(next((tmp_path / "diagnostics").iterdir()).joinpath("error.json").read_text())
    assert payload["response_started"] is True
    assert payload["assistant_count_before"] == 0
    assert payload["assistant_count_after"] == 1
    assert assistant.inner_text_timeouts == [1750]


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ({PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()]}, "PASS"),
        ({PlaywrightChatDriver.LOGIN_MARKERS[0]: [FakeItem()]}, "FAIL"),
        ({}, "UNKNOWN"),
    ],
)
def test_session_state_uses_auth_markers_not_composer(tmp_path, mapping, expected) -> None:
    driver = _driver_with_page(tmp_path, FakePage(mapping))
    assert driver._auth_snapshot()["state"] == expected


def test_composer_fallback_requires_visible_editable_match(tmp_path) -> None:
    page = FakePage({
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem(visible=False)],
        PlaywrightChatDriver.COMPOSERS[1]: [FakeItem(visible=True, editable=True)],
    })
    driver = _driver_with_page(tmp_path, page)
    composer, details = driver._composer_snapshot()
    assert composer is page.mapping[PlaywrightChatDriver.COMPOSERS[1]][0]
    assert details[PlaywrightChatDriver.COMPOSERS[0]]["match_count"] == 1
    assert details[PlaywrightChatDriver.COMPOSERS[0]]["visible_count"] == 0


def test_readiness_waits_for_late_composer(tmp_path, monkeypatch) -> None:
    mapping = {PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()]}

    def reveal(page):
        if page.wait_count == 1:
            page.mapping[PlaywrightChatDriver.COMPOSERS[0]] = [FakeItem()]

    page = FakePage(mapping, reveal)
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    health = driver.ensure_ready()
    assert page.wait_count == 1
    assert health.ready is True


def test_open_thread_ready_preserves_requested_url(tmp_path, monkeypatch) -> None:
    target = "https://chatgpt.com/c/existing"
    page = FakePage({
        PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()],
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
    })
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    driver.open_thread(target)
    assert page.url == target
    assert driver._last_observation["requested_thread_url"] == target
    assert driver._last_observation["final_url"] == target


def test_open_thread_waits_for_late_composer_without_false_unavailable(tmp_path, monkeypatch) -> None:
    target = "https://chatgpt.com/c/existing"
    page = FakePage({PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()]})
    page.on_wait = lambda current: current.mapping.__setitem__(
        PlaywrightChatDriver.COMPOSERS[0], [FakeItem()]
    )
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    driver.open_thread(target)
    assert driver.stage == "COMPOSER_FOUND"


def test_open_thread_timeout_without_unavailable_marker_is_page_ready_timeout(
    tmp_path, monkeypatch
) -> None:
    target = "https://chatgpt.com/c/existing"
    page = FakePage({PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()]})
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    with pytest.raises(ChatDriverError, match="PAGE_READY_TIMEOUT"):
        driver.open_thread(target)
    payloads = [
        json.loads(path.read_text())
        for path in (tmp_path / "diagnostics").glob("*/error.json")
    ]
    payload = payloads[-1]
    assert payload["requested_thread_url"] == target
    assert payload["final_url"] == target
    assert payload["unavailable_marker_found"] is False
    assert payload["elapsed_startup_seconds"] >= 1


def test_open_thread_explicit_unavailable_marker_is_thread_unavailable(
    tmp_path, monkeypatch
) -> None:
    page = FakePage({PlaywrightChatDriver.UNAVAILABLE_MARKERS[0]: [FakeItem()]})
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    with pytest.raises(ChatDriverError, match="THREAD_UNAVAILABLE"):
        driver.open_thread("https://chatgpt.com/c/missing")


def test_open_thread_unavailable_marker_wins_even_if_composer_exists(
    tmp_path, monkeypatch
) -> None:
    page = FakePage({
        PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()],
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
        PlaywrightChatDriver.UNAVAILABLE_MARKERS[0]: [FakeItem()],
    })
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    with pytest.raises(ChatDriverError, match="THREAD_UNAVAILABLE"):
        driver.open_thread("https://chatgpt.com/c/missing")


def test_open_thread_redirect_to_new_chat_is_thread_unavailable(tmp_path, monkeypatch) -> None:
    class RedirectPage(FakePage):
        def goto(self, url, wait_until=None):
            self.url = "https://chatgpt.com/"

    page = RedirectPage({
        PlaywrightChatDriver.ACCOUNT_MARKERS[0]: [FakeItem()],
        PlaywrightChatDriver.COMPOSERS[0]: [FakeItem()],
    })
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    with pytest.raises(ChatDriverError, match="THREAD_UNAVAILABLE"):
        driver.open_thread("https://chatgpt.com/c/missing")


def test_missing_composer_does_not_become_auth_fail(tmp_path, monkeypatch) -> None:
    page = FakePage()
    driver = _driver_with_page(tmp_path, page)
    monkeypatch.setattr("clawbridge.adapters.chatgpt_playwright.time.monotonic", lambda: page.elapsed)
    health = driver.health()
    assert health.auth_state == "UNKNOWN"
    assert health.composer_found is False
    payload = json.loads(next((tmp_path / "diagnostics").iterdir()).joinpath("error.json").read_text())
    assert payload["auth_state"] == "UNKNOWN"
    assert set(payload["composer_selectors"]) == set(PlaywrightChatDriver.COMPOSERS)


def test_keep_open_is_explicit(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(PlaywrightChatDriver, "chrome_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        PlaywrightChatDriver,
        "health",
        lambda self: ChatHealth(
            "COMPOSER_FOUND", True, "PASS", True, "https://chatgpt.com/",
            browser_launched=True, reachable=True, page_ready=True,
        ),
    )
    calls = []
    monkeypatch.setattr(PlaywrightChatDriver, "wait_until_closed", lambda self: calls.append("wait"))
    monkeypatch.setattr(PlaywrightChatDriver, "close", lambda self: calls.append("close"))
    assert _chat_browser(False, False, False) == 0
    assert calls == ["close"]
    calls.clear()
    assert _chat_browser(False, False, True) == 0
    assert calls == ["wait", "close"]
    assert "Browser kept open for inspection" in capsys.readouterr().out


def test_setup_does_not_import_playwright_driver(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delitem(sys.modules, "clawbridge.adapters.chatgpt_playwright", raising=False)
    launched = []
    monkeypatch.setattr(
        "clawbridge.adapters.chatgpt_bootstrap.find_chrome_executable",
        lambda configured_browser="chrome": tmp_path / "chrome.exe",
    )
    monkeypatch.setattr(
        "clawbridge.adapters.chatgpt_bootstrap.subprocess.Popen",
        lambda command: launched.append(command),
    )

    assert _chat_browser(True) == 0
    assert "clawbridge.adapters.chatgpt_playwright" not in sys.modules
    assert launched[0][0] == str(tmp_path / "chrome.exe")
    assert f"--user-data-dir={tmp_path / 'ClawBridge' / 'browser' / 'chrome-profile'}" in launched[0]
    assert "https://chatgpt.com/" in launched[0]
    assert "python -m clawbridge chat-browser doctor" in capsys.readouterr().out
