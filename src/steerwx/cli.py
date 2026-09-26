from __future__ import annotations

import argparse
import sys
import time

import qrcode

from steerwx.channels.credentials import CredentialStore, WeixinCredentials
from steerwx.channels.weixin import (
    API_BASE,
    ILinkStaleTokenError,
    WeixinClient,
    extract_text,
    safe_send_text,
)
from steerwx.config import load_config
from steerwx.conversation import ConversationService, SessionStore, bind_project, prepare_message
from steerwx.doctor import run_doctor
from steerwx.project_context import build_project_context  # compatibility for existing tests
from steerwx.service import run_bridge, send_work_notification
from steerwx.runtime import migrate_data


def _chat_browser(setup: bool, send: bool = False, keep_open: bool = False) -> int:
    config = load_config()
    print(f"Config                {config.config_path}")
    print(f"Profile directory     {config.chat.profile_dir}")
    if setup:
        from steerwx.adapters.chatgpt_bootstrap import (
            ChromeBootstrapError,
            launch_manual_login,
        )

        try:
            launch_manual_login(config.chat)
        except ChromeBootstrapError as exc:
            print(f"Browser setup         FAIL ({exc})", file=sys.stderr)
            return 2
        print("请在打开的 Chrome 中人工完成 ChatGPT 登录。")
        print("登录完成并确认可正常使用 ChatGPT 后，关闭该 Chrome，然后运行：")
        print("\npython -m steerwx chat-browser doctor")
        return 0

    from steerwx.adapters.chatgpt_playwright import PlaywrightChatDriver

    driver = PlaywrightChatDriver(config.chat)
    try:
        print(f"Chrome executable     {'PASS' if driver.chrome_available() else 'FAIL'}")
        try:
            config.chat.profile_dir.mkdir(parents=True, exist_ok=True)
            print("Profile directory     PASS")
        except OSError as exc:
            print(f"Profile directory     FAIL ({exc})", file=sys.stderr)
            return 2
        health = driver.health()
        print(f"Browser launch        {'PASS' if health.browser_launched else 'FAIL'}")
        print(f"ChatGPT reachable     {'PASS' if health.reachable else 'FAIL'}")
        print(f"ChatGPT session       {health.auth_state}")
        print(f"Page ready            {'PASS' if health.page_ready else 'FAIL'}")
        print(f"Composer              {'PASS' if health.composer_found else 'FAIL'}")
        if not health.ready:
            print(f"Doctor detail         {health.stage}: {health.reason}", file=sys.stderr)
            return 2
        if send:
            driver.reset_thread()
            reply = driver.send("请只回复 STEERWX_BROWSER_OK")
            print("Prompt sent           PASS")
            print("Response              PASS")
            print(f"\nReply:\n{reply.text}")
            return 0 if reply.text.strip() == "STEERWX_BROWSER_OK" else 3
        return 0
    except Exception as exc:
        stage = getattr(exc, "stage", driver.stage)
        print(f"Browser doctor        FAIL ({stage}: {exc})", file=sys.stderr)
        return 2
    finally:
        if keep_open:
            print("Browser kept open for inspection. Close it manually when finished.")
            driver.wait_until_closed()
        driver.close()


def _project_root(config, project: str | None):
    return config.projects.get(project) if project else None


def _chat_local(value: str, *, project: str | None = None, show_context: bool = False) -> int:
    config = load_config()
    store = SessionStore()
    if value == "use":
        try:
            session = bind_project(config, store, project or "")
        except ValueError as exc:
            print("Project               FAIL", file=sys.stderr)
            print(f"Reason                {exc}", file=sys.stderr)
            return 2
        root = config.projects[project]
        print(f"Session               {session.session_id}")
        print(f"Project               {project}")
        print(f"Project root          {root}")
        return 0
    if value == "status":
        session = store.load()
        root = _project_root(config, session.current_project)
        print(f"Session               {session.session_id}")
        print(f"Project               {session.current_project or 'NONE'}")
        print(f"Project root          {root or '-'}")
        print(f"Thread                {'ACTIVE' if session.browser_thread_url else 'NONE'}")
        print(f"Recent messages       {len(session.recent_messages)}")
        print(f"Updated               {session.updated_at}")
        return 0
    if value == "reset":
        session = store.reset()
        print("Session               default")
        print(f"Project               {session.current_project or 'NONE'}")
        print("Thread                NONE")
        print("Recent messages       0")
        return 0
    session = store.load()
    try:
        prompt, context = prepare_message(config, store, value)
    except ValueError as exc:
        print("Response              FAIL", file=sys.stderr)
        print(f"Reason                {exc}", file=sys.stderr)
        return 2
    if context:
        for warning in context.warnings:
            print(f"Warning               {warning}", file=sys.stderr)
    if show_context:
        print(f"Selected project      {session.current_project or 'NONE'}")
        providers = ", ".join(context.selection.names) if context else "NONE"
        print(f"Selected providers    {providers or 'NONE'}")
        print("\nContext envelope:")
        print(context.envelope if context else "(none)")
    service = ConversationService(config.chat, store=store)
    try:
        result = service.send(value, prompt=prompt)
    except Exception as exc:
        print(f"Response              FAIL", file=sys.stderr)
        print(f"Stage                 {getattr(exc, 'stage', 'SESSION')}", file=sys.stderr)
        print(f"Reason                {exc}", file=sys.stderr)
        return 2
    print("Session               default")
    print(f"Thread                {'RESUMED' if result.resumed else 'NEW'}")
    print("Response              PASS")
    print(f"\nReply:\n{result.reply}")
    return 0


def _print_qr(value: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(value)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    for row in matrix:
        print("".join("██" if cell else "  " for cell in row))
    print(f"\nQR URL: {value}\n")


def _login() -> int:
    client = WeixinClient()
    store = CredentialStore()
    existing = store.load()
    local_tokens = [existing[1]] if existing else []
    session = client.start_login(local_tokens)
    print("请用手机微信扫描以下二维码：")
    _print_qr(session.qrcode_url)

    poll_base = API_BASE
    verify_code: str | None = None
    last_status: str | None = None
    last_transient_error: str | None = None
    while True:
        result = client.poll_login(
            session.qrcode,
            base_url=poll_base,
            verify_code=verify_code,
        )
        diagnostics = getattr(client, "last_login_diagnostics", {})
        transient_error = diagnostics.get("transient_error")
        if result.status != last_status or transient_error != last_transient_error:
            suffix = f" transient_error={transient_error}" if transient_error else ""
            print(f"[login] status={result.status}{suffix}", flush=True)
            last_status = result.status
            last_transient_error = transient_error
        if result.status in {"wait", "scaned"}:
            if result.status == "scaned":
                print("已扫码，等待确认……")
            time.sleep(1)
            continue
        if result.status == "need_verifycode":
            verify_code = input("请输入手机微信显示的数字：").strip()
            continue
        if result.status == "verify_code_blocked":
            print("配对码多次错误，请重新执行 python -m steerwx login。", file=sys.stderr)
            return 2
        if result.status == "scaned_but_redirect":
            if result.redirect_host:
                poll_base = f"https://{result.redirect_host}"
                print(f"[login] IDC redirect -> {result.redirect_host}", flush=True)
            else:
                print("[login] warning: scaned_but_redirect 缺少 redirect_host，继续使用当前 host。", file=sys.stderr)
            continue
        if result.status == "binded_redirect":
            if existing:
                print("已连接过此 ClawBot；继续使用本机现有凭据，无需重复绑定。")
                return 0
            print("服务端报告 ClawBot 已绑定，但本机没有可复用凭据。", file=sys.stderr)
            return 3
        if result.status == "expired":
            print("二维码已过期，请重新执行 python -m steerwx login。", file=sys.stderr)
            return 2
        if result.status != "confirmed":
            print(f"未知登录状态: {result.status}", file=sys.stderr)
            return 2
        if not result.bot_token or not result.account_id:
            print("登录确认但缺少 bot_token/account_id。", file=sys.stderr)
            return 2
        credentials = WeixinCredentials(
            account_id=result.account_id,
            base_url=result.base_url or poll_base,
            user_id=result.user_id,
        )
        store.save(credentials, result.bot_token)
        print(f"登录成功。account_id={credentials.account_id}")
        return 0


def _echo() -> int:
    store = CredentialStore()
    loaded = store.load()
    if not loaded:
        print("尚未登录，请先执行 python -m steerwx login。", file=sys.stderr)
        return 2
    credentials, token = loaded
    client = WeixinClient()
    cursor = ""
    started_ms = int(time.time() * 1000)
    print("M0 echo 已启动：请在微信 ClawBot 中发送 hello。")
    try:
        client.notify_start(token, credentials.base_url)
        while True:
            try:
                data = client.get_updates(token, credentials.base_url, cursor)
            except ILinkStaleTokenError as exc:
                print(f"M0 echo FAIL: iLink bot token stale ({exc}). 请重新执行 python -m steerwx login。", file=sys.stderr)
                return 2
            cursor = data.get("get_updates_buf") or cursor
            for message in data.get("msgs") or []:
                if int(message.get("create_time_ms") or 0) < started_ms - 5000:
                    continue
                sender = message.get("from_user_id")
                if not credentials.user_id or sender != credentials.user_id:
                    continue
                text = extract_text(message)
                context = message.get("context_token")
                if text and text.strip().lower() == "hello" and sender and context:
                    client_id = safe_send_text(
                        client,
                        token,
                        credentials.base_url,
                        sender,
                        context,
                        "world",
                        purpose="m0_echo",
                        outbound_kind="REPLY",
                    )
                    if client_id is not None:
                        print("M0 API ACCEPTED: received hello; reply API accepted, delivery unconfirmed.")
                        return 0
                    return 2
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            client.notify_stop(token, credentials.base_url)
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="steerwx")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check first-run SteerWX readiness")
    sub.add_parser("migrate-data", help="Copy legacy ClawBridge data to SteerWX without deleting it")
    sub.add_parser("login", help="Bind WeChat ClawBot with QR login")
    sub.add_parser("echo", help="M0: reply world to a new hello message")
    sub.add_parser("run", help="Run the WeChat bridge service")
    notify = sub.add_parser("work-notify", help="Send a proactive Work notification")
    notify.add_argument("status", choices=["complete", "failed", "need_input"])
    notify.add_argument("--summary", required=True)
    chat_browser = sub.add_parser("chat-browser", help="M3-A ChatGPT browser diagnostics")
    chat_sub = chat_browser.add_subparsers(dest="chat_browser_command", required=True)
    chat_sub.add_parser("setup", help="Open the dedicated Chrome profile for manual login")
    doctor = chat_sub.add_parser("doctor", help="Check ChatGPT browser readiness")
    doctor.add_argument("--send", action="store_true", help="Send the M3-A acceptance prompt")
    doctor.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the diagnostic browser open for manual inspection",
    )
    chat_local = sub.add_parser("chat-local", help="M3-C local conversation session")
    chat_local.add_argument(
        "--show-context", action="store_true", help="Print selected local context"
    )
    chat_local.add_argument("message", help="Message, status, reset, or use")
    chat_local.add_argument("project", nargs="?", help="Configured project name for use")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "doctor":
        return run_doctor()
    if args.command == "migrate-data":
        try:
            old, new = migrate_data()
        except (OSError, RuntimeError) as exc:
            print(f"Data migration stopped: {exc}", file=sys.stderr)
            return 2
        print(f"Copied runtime data from {old} to {new}. Original data was retained.")
        return 0
    if args.command == "login":
        return _login()
    if args.command == "echo":
        return _echo()
    if args.command == "run":
        return run_bridge()
    if args.command == "work-notify":
        send_work_notification(args.status, args.summary)
        print("Work notification sent.")
        return 0
    if args.command == "chat-browser":
        return _chat_browser(
            args.chat_browser_command == "setup",
            getattr(args, "send", False),
            getattr(args, "keep_open", False),
        )
    if args.command == "chat-local":
        return _chat_local(
            args.message,
            project=args.project,
            show_context=args.show_context,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
