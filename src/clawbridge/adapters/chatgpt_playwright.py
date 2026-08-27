from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from clawbridge.config import ChatConfig, local_app_data
from clawbridge.conversation import normalize_thread_url


STAGES = (
    "IDLE", "BROWSER_STARTING", "BROWSER_READY", "PAGE_READY",
    "COMPOSER_FOUND", "PROMPT_ENTERED", "PROMPT_SENT",
    "RESPONSE_STARTED", "RESPONSE_COMPLETE", "FAILED",
)


@dataclass(frozen=True, slots=True)
class ChatHealth:
    stage: str
    ready: bool
    auth_state: str
    composer_found: bool
    url: str
    reason: str = ""
    browser_launched: bool = False
    reachable: bool = False
    page_ready: bool = False

    @property
    def logged_in(self) -> bool:
        return self.auth_state == "PASS"


@dataclass(frozen=True, slots=True)
class ChatReply:
    text: str
    url: str
    stage: str = "RESPONSE_COMPLETE"


class ChatDriverError(RuntimeError):
    def __init__(self, stage: str, reason: str, url: str = "") -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.url = url


class PlaywrightChatDriver:
    TEXT_STABLE_SECONDS = 2.0
    GENERATION_MARKER_GRACE_SECONDS = 2.0
    COMPOSERS = (
        "#prompt-textarea",
        "[contenteditable='true'][role='textbox']",
        "form [data-testid='prompt-textarea']",
    )
    ACCOUNT_MARKERS = (
        "[data-testid='accounts-profile-button']",
        "[data-testid='profile-button']",
        "button[aria-label*='Profile']",
    )
    LOGIN_MARKERS = (
        "a[href^='/auth/login']",
        "button:has-text('Log in')",
        "a:has-text('Sign up')",
    )
    ASSISTANT_MESSAGES = (
        "[data-message-author-role='assistant']",
        "article[data-turn='assistant']",
    )
    GENERATION_MARKERS = (
        "button[data-testid='stop-button']",
        "button[aria-label*='Stop']",
        "[data-testid='stop-button']",
    )
    COMPLETION_MARKERS = (
        "[data-message-author-role='assistant'] button[data-testid*='copy']",
        "[data-message-author-role='assistant'] button[aria-label*='Copy']",
        "[data-message-author-role='assistant'] [data-testid*='thumb']",
    )
    UNAVAILABLE_MARKERS = (
        "text=Unable to load conversation",
        "text=Conversation not found",
        "text=You do not have access to this conversation",
    )

    def __init__(
        self,
        config: ChatConfig,
        *,
        diagnostics_dir: Path | None = None,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self.diagnostics_dir = diagnostics_dir or local_app_data() / "diagnostics"
        self._factory = playwright_factory
        self.stage = "IDLE"
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._last_observation: dict[str, Any] = {}
        self._response_observation: dict[str, Any] = {}
        self._requested_thread_url = ""
        self._startup_started_at: float | None = None

    @property
    def url(self) -> str:
        return str(getattr(self._page, "url", "") or "")

    @staticmethod
    def chrome_available() -> bool:
        candidates = (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        )
        return any(path.is_file() for path in candidates) or shutil.which("chrome") is not None

    def _set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"Unknown browser stage: {stage}")
        self.stage = stage

    def _start(self) -> None:
        if self._context is not None:
            return
        self._set_stage("BROWSER_STARTING")
        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            if self._factory is None:
                from playwright.sync_api import sync_playwright
                self._factory = sync_playwright
            self._playwright = self._factory().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.profile_dir),
                channel=self.config.browser,
                headless=self.config.headless,
            )
            self._context.set_default_timeout(self.config.startup_timeout_seconds * 1000)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._set_stage("BROWSER_READY")
        except Exception as exc:
            self._fail("BROWSER_STARTING", exc)

    @staticmethod
    def _locator_counts(locator: Any) -> tuple[int, int]:
        try:
            count = locator.count()
        except Exception:
            return 0, 0
        visible = 0
        for index in range(count):
            try:
                if locator.nth(index).is_visible(timeout=100):
                    visible += 1
            except Exception:
                continue
        return count, visible

    def _marker_snapshot(self, selectors: tuple[str, ...]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for selector in selectors:
            count, visible = self._locator_counts(self._page.locator(selector))
            result[selector] = {"match_count": count, "visible_count": visible}
        return result

    def _auth_snapshot(self) -> dict[str, Any]:
        account = self._marker_snapshot(self.ACCOUNT_MARKERS)
        login = self._marker_snapshot(self.LOGIN_MARKERS)
        url = self.url.lower()
        account_visible = any(item["visible_count"] for item in account.values())
        login_visible = any(item["visible_count"] for item in login.values())
        if account_visible:
            state = "PASS"
        elif "/auth/" in url or login_visible:
            state = "FAIL"
        else:
            state = "UNKNOWN"
        return {"state": state, "account_markers": account, "login_markers": login}

    def _composer_snapshot(self) -> tuple[Any | None, dict[str, dict[str, int]]]:
        details: dict[str, dict[str, int]] = {}
        selected = None
        for selector in self.COMPOSERS:
            all_matches = self._page.locator(selector)
            count, visible = self._locator_counts(all_matches)
            details[selector] = {"match_count": count, "visible_count": visible}
            locator = all_matches.first
            try:
                if (
                    selected is None
                    and locator.is_visible(timeout=100)
                    and locator.is_editable(timeout=100)
                ):
                    selected = locator
            except Exception:
                continue
        return selected, details

    def _composer(self) -> Any | None:
        return self._composer_snapshot()[0]

    def _page_title(self) -> str:
        try:
            return str(self._page.title() or "")
        except Exception:
            return ""

    def _observe_readiness(self) -> tuple[Any | None, dict[str, Any]]:
        auth = self._auth_snapshot()
        composer, composers = self._composer_snapshot()
        unavailable = self._marker_snapshot(self.UNAVAILABLE_MARKERS)
        observation = {
            "requested_thread_url": self._requested_thread_url,
            "final_url": self.url,
            "current_url": self.url,
            "page_title": self._page_title(),
            "auth_state": auth["state"],
            "account_markers": auth["account_markers"],
            "login_markers": auth["login_markers"],
            "composer_selectors": composers,
            "composer_found": composer is not None,
            "composer_count": sum(item["match_count"] for item in composers.values()),
            "composer_visible_count": sum(item["visible_count"] for item in composers.values()),
            "unavailable_markers": unavailable,
            "unavailable_marker_found": any(
                item["visible_count"] for item in unavailable.values()
            ),
            "readiness_markers": {
                "composer": composer is not None,
                "authenticated": auth["state"] == "PASS",
            },
            "page_ready": composer is not None or auth["state"] != "UNKNOWN",
        }
        if self._startup_started_at is not None:
            observation["elapsed_startup_seconds"] = round(
                max(0.0, time.monotonic() - self._startup_started_at), 3
            )
        self._last_observation = observation
        return composer, observation

    def _assistant_locator(self) -> Any:
        for selector in self.ASSISTANT_MESSAGES:
            locator = self._page.locator(selector)
            if locator.count():
                return locator
        return self._page.locator(self.ASSISTANT_MESSAGES[0])

    def ensure_ready(self) -> ChatHealth:
        try:
            if self._startup_started_at is None:
                self._startup_started_at = time.monotonic()
            self._start()
            if not self.url.startswith("https://chatgpt.com"):
                self._page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
            deadline = time.monotonic() + self.config.startup_timeout_seconds
            composer = None
            observation: dict[str, Any] = {}
            while time.monotonic() < deadline:
                composer, observation = self._observe_readiness()
                if observation["auth_state"] == "FAIL":
                    raise ChatDriverError("PAGE_READY", "ChatGPT session is explicitly logged out", self.url)
                if composer is not None and observation["auth_state"] == "PASS":
                    break
                self._page.wait_for_timeout(250)
            else:
                composer, observation = self._observe_readiness()
            self._set_stage("PAGE_READY")
            if composer is None:
                if observation.get("unavailable_marker_found"):
                    raise ChatDriverError("PAGE_READY", "THREAD_UNAVAILABLE", self.url)
                raise ChatDriverError("PAGE_READY", "PAGE_READY_TIMEOUT", self.url)
            if observation["auth_state"] != "PASS":
                raise ChatDriverError("PAGE_READY", "ChatGPT session could not be determined", self.url)
            self._set_stage("COMPOSER_FOUND")
            return ChatHealth(
                self.stage, True, "PASS", True, self.url,
                browser_launched=True, reachable=True, page_ready=True,
            )
        except ChatDriverError as exc:
            self._fail(exc.stage, exc)
        except Exception as exc:
            self._fail(self.stage, exc)
        raise AssertionError("unreachable")

    def health(self) -> ChatHealth:
        try:
            return self.ensure_ready()
        except ChatDriverError as exc:
            observation = self._last_observation
            return ChatHealth(
                "FAILED",
                False,
                str(observation.get("auth_state", "UNKNOWN")),
                bool(observation.get("composer_found", False)),
                exc.url,
                exc.reason,
                browser_launched=self._context is not None,
                reachable=exc.url.startswith("https://chatgpt.com"),
                page_ready=bool(observation.get("page_ready", False)),
            )

    def reset_thread(self) -> None:
        self._start()
        self._page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
        self._set_stage("PAGE_READY")

    def start_new_thread(self) -> None:
        self.reset_thread()

    def open_thread(self, url: str) -> None:
        target = normalize_thread_url(url)
        self._requested_thread_url = target
        self._startup_started_at = time.monotonic()
        try:
            self._start()
            self._page.goto(target, wait_until="domcontentloaded")
            self.ensure_ready()
            if self._last_observation.get("unavailable_marker_found"):
                raise ChatDriverError("PAGE_READY", "THREAD_UNAVAILABLE", self.url)
            try:
                final = normalize_thread_url(self.url)
            except ValueError:
                raise ChatDriverError("PAGE_READY", "THREAD_UNAVAILABLE", self.url)
            if final != target:
                raise ChatDriverError("PAGE_READY", "THREAD_UNAVAILABLE", self.url)
        except ChatDriverError as exc:
            if self.stage == "FAILED":
                raise
            self._fail(exc.stage, exc)
        except Exception as exc:
            self._fail("PAGE_READY", exc)

    def current_thread_url(self) -> str:
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while time.monotonic() < deadline:
            try:
                return normalize_thread_url(self.url)
            except ValueError:
                self._page.wait_for_timeout(250)
        self._fail("RESPONSE_COMPLETE", ChatDriverError("RESPONSE_COMPLETE", "THREAD_URL_NOT_CREATED", self.url))
        raise AssertionError("unreachable")

    @staticmethod
    def _remaining_timeout_ms(deadline: float) -> int:
        return max(1, int((deadline - time.monotonic()) * 1000))

    def _reply_timeout(self, stage: str, started_at: float) -> ChatDriverError:
        elapsed = max(0.0, time.monotonic() - started_at)
        self._response_observation["elapsed_response_seconds"] = round(elapsed, 3)
        return ChatDriverError(
            stage,
            (
                "REPLY_TIMEOUT: assistant response exceeded configured reply timeout "
                f"({self.config.reply_timeout_seconds}s; elapsed={elapsed:.3f}s)"
            ),
            self.url,
        )

    def _visible_marker(self, selectors: tuple[str, ...]) -> bool:
        return any(
            item["visible_count"] > 0
            for item in self._marker_snapshot(selectors).values()
        )

    def send(self, prompt: str) -> ChatReply:
        clean = prompt.strip()
        if not clean:
            raise ValueError("Prompt must not be empty")
        try:
            self.ensure_ready()
            messages = self._assistant_locator()
            previous_count = messages.count()
            composer = self._composer()
            if composer is None:
                raise ChatDriverError("PAGE_READY", "ChatGPT composer disappeared", self.url)
            composer.fill(clean)
            self._set_stage("PROMPT_ENTERED")
            composer.press("Enter")
            self._set_stage("PROMPT_SENT")
            started_at = time.monotonic()
            deadline = started_at + self.config.reply_timeout_seconds
            self._response_observation = {
                "configured_reply_timeout_seconds": self.config.reply_timeout_seconds,
                "elapsed_response_seconds": 0.0,
                "assistant_count_before": previous_count,
                "assistant_count_after": previous_count,
                "response_started": False,
                "response_started_at": None,
                "first_nonempty_text_at": None,
                "last_text_change_at": None,
                "final_text_length": 0,
                "text_stable_seconds": 0.0,
                "generation_marker_visible": False,
                "completion_marker_visible": False,
            }
            while time.monotonic() < deadline:
                messages = self._assistant_locator()
                current_count = messages.count()
                self._response_observation["assistant_count_after"] = current_count
                if current_count > previous_count:
                    self._set_stage("RESPONSE_STARTED")
                    self._response_observation["response_started"] = True
                    self._response_observation["response_started_at"] = round(
                        time.monotonic() - started_at, 3
                    )
                    break
                self._page.wait_for_timeout(250)
            else:
                raise self._reply_timeout("PROMPT_SENT", started_at)

            last_text = ""
            stable_since = time.monotonic()
            while time.monotonic() < deadline:
                try:
                    text = messages.nth(messages.count() - 1).inner_text(
                        timeout=self._remaining_timeout_ms(deadline)
                    ).strip()
                except Exception:
                    if time.monotonic() >= deadline:
                        raise self._reply_timeout("RESPONSE_STARTED", started_at)
                    raise
                now = time.monotonic()
                generating = self._visible_marker(self.GENERATION_MARKERS)
                complete_ui = self._visible_marker(self.COMPLETION_MARKERS)
                if text != last_text:
                    last_text = text
                    stable_since = now
                    self._response_observation["last_text_change_at"] = round(
                        now - started_at, 3
                    )
                    if text and self._response_observation["first_nonempty_text_at"] is None:
                        self._response_observation["first_nonempty_text_at"] = round(
                            now - started_at, 3
                        )
                stable_for = max(0.0, now - stable_since) if last_text else 0.0
                self._response_observation.update({
                    "final_text_length": len(last_text),
                    "text_stable_seconds": round(stable_for, 3),
                    "generation_marker_visible": generating,
                    "completion_marker_visible": complete_ui,
                    "elapsed_response_seconds": round(now - started_at, 3),
                })
                stable = last_text and stable_for >= self.TEXT_STABLE_SECONDS
                stale_generation = stable_for >= (
                    self.TEXT_STABLE_SECONDS + self.GENERATION_MARKER_GRACE_SECONDS
                )
                if stable and (not generating or complete_ui or stale_generation):
                    self._set_stage("RESPONSE_COMPLETE")
                    return ChatReply(last_text, self.url)
                self._page.wait_for_timeout(250)
            raise self._reply_timeout("RESPONSE_STARTED", started_at)
        except ChatDriverError as exc:
            self._fail(exc.stage, exc)
        except Exception as exc:
            self._fail(self.stage, exc)
        raise AssertionError("unreachable")

    def _fail(self, stage: str, exc: Exception) -> None:
        reason = str(exc) or type(exc).__name__
        url = self.url
        self._set_stage("FAILED")
        try:
            stamp = datetime.now(timezone.utc).strftime("chat-%Y%m%d-%H%M%S-%f")
            target = self.diagnostics_dir / stamp
            target.mkdir(parents=True, exist_ok=False)
            payload = {
                "stage": stage,
                "reason": reason,
                "url": url,
                "current_url": url,
                "page_title": self._page_title() if self._page is not None else "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **self._last_observation,
                **self._response_observation,
            }
            (target / "error.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if self._page is not None:
                self._page.screenshot(path=str(target / "screenshot.png"), full_page=True)
        except Exception:
            pass
        raise ChatDriverError(stage, reason, url) from exc

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            if self._playwright is not None:
                self._playwright.stop()
            self._playwright = None
            self._page = None
            self._set_stage("IDLE")

    def wait_until_closed(self) -> None:
        """Keep the Playwright process alive until the user closes its browser."""
        if self._context is None:
            return
        try:
            while self._context.pages:
                self._context.pages[0].wait_for_timeout(250)
        except Exception:
            return
