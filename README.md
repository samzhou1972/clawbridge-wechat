# ClawBridge

ClawBridge is a lightweight local-first bridge for using WeChat ClawBot as a remote control and conversation channel for local AI workspaces. It uses WeChat for control, short summaries, and completion reminders; detailed work, full reports, and logs stay on the PC.

ClawBridge is an independent open-source project and is not affiliated with or endorsed by Tencent, WeChat, or OpenAI.

> Status: M0 (WeChat/iLink transport), M1 (Work Observer), M2 (Codex Executor), and M3-A/B/C/D have passed automated acceptance. Supervised real WeChat E2E has also passed for M0 and M3-D. ClawBridge remains an early-stage project and is not production ready; Tencent iLink is an external dependency whose account, session, binding, and delivery behavior can change independently of ClawBridge.

## What ClawBridge Does

| Capability | Purpose | Requirement |
| --- | --- | --- |
| `/work` | Observe local ChatGPT Work facts, status, and results | Accessible local Work state |
| `/chat` | Discuss, analyze, and prepare a Codex handoff | Chrome with ChatGPT Web signed in |
| `/codex` | Explicitly start local Codex analysis | Configured project and working Codex CLI |
| Git Context | Add on-demand, read-only Git facts to `/chat` | Git repository and Git CLI |
| WeChat transport | Use these commands from WeChat | WeChat plus Tencent iLink / ClawBot binding |

The command boundary is deliberate: `/work` observes, `/chat` discusses, and `/codex <project> <task>` explicitly starts local Codex analysis in a read-only sandbox. A `/chat` message that asks to modify code, run tests, commit, or deploy never performs those actions automatically.

ClawBridge is not an agent framework. It does not provide model routing, RAG, memory, or workflow orchestration, and does not depend on QClaw or OpenClaw.

## Requirements

The first-time setup is currently verified on Windows; Linux and macOS are not yet accepted platforms. Prepare only the dependencies for the capabilities you need:

- Python 3.11 or later.
- Google Chrome, for the dedicated ChatGPT Web profile.
- A ChatGPT Web account (only for `/chat`). ClawBridge does not use the OpenAI API.
- WeChat and Tencent iLink / WeChat ClawBot (for WeChat transport).
- Codex CLI, with its own required authentication/configuration complete (only for `/codex`).
- Git CLI and a Git repository (only for Git Context).
- A local project directory. Projects must be explicitly configured; ClawBridge does not scan the disk to guess them.
- Locally accessible ChatGPT Work state (only for Work Observer).

Cloning the repository and running `python -m clawbridge run` does not automatically enable every capability. For example, `/work` does not require ChatGPT Browser, while `/chat` does.

## First-time Setup

### 1. Install ClawBridge

Clone the repository, create your preferred Python environment, then install the project and its declared dependencies:

```powershell
python -m pip install -e .
```

Confirm the available commands without starting the bridge:

```powershell
python -m clawbridge --help
```

### 2. Configure projects

Runtime configuration is stored at:

```text
%LOCALAPPDATA%\ClawBridge\config.toml
```

Copy [`config.example.toml`](config.example.toml) to `%LOCALAPPDATA%\ClawBridge\config.toml`, then add every project that you want to select by name:

```toml
[projects.clawbridge]
root = "C:\\path\\to\\clawbridge"
```

`clawbridge` is a logical project name and `root` is the actual local directory. `[projects.<name>].root` is the sole authority for `/chat` context, Git context, Work matching, and `/codex`; `/chat use clawbridge` selects this name. The real configuration schema also supports optional `[paths]`, `[codex]`, and `[chat]` sections; do not invent fields or commit personal runtime configuration. Do not place `CLAWBRIDGE_HOME` or the browser profile inside the repository.

### 3. Bind WeChat ClawBot

ClawBridge uses Tencent iLink / WeChat ClawBot as transport, not a normal WeChat Web API. Begin the binding flow:

```powershell
python -m clawbridge login
```

The terminal requests and displays a binding QR code. Then:

1. Scan it with WeChat on your phone.
2. If WeChat shows a numeric verification code, enter it in the terminal.
3. Finish the ClawBot binding flow.
4. Keep the credentials in local runtime state only; never add them to Git.

### 4. Verify WeChat transport

Run the M0 smoke test:

```powershell
python -m clawbridge echo
```

Send `hello` to the WeChat ClawBot. The expected reply is `world`. This verifies **WeChat ↔ Tencent iLink ↔ ClawBridge** only; complete it before diagnosing ChatGPT, Work, or Codex.

API acceptance of the echo does not prove the WeChat client received it; see [External Service Limitations](#external-service-limitations).

### 5. Prepare the ChatGPT browser session

ClawBridge uses this dedicated Chrome profile:

```text
%LOCALAPPDATA%\ClawBridge\browser\chrome-profile
```

Start the one-time login setup:

```powershell
python -m clawbridge chat-browser setup
```

This launches normal system Chrome with that profile. In the opened window, manually sign in at `chatgpt.com`, confirm ChatGPT works, then close Chrome. The session remains in the dedicated profile. ClawBridge never asks for, collects, or stores your ChatGPT password.

Being signed in to your everyday Chrome or Edge does **not** mean this separate profile is signed in. ClawBridge does not use a browser extension, your daily Edge profile, or any other automation profile.

### 6. Verify ChatGPT Browser

After closing the login browser:

```powershell
python -m clawbridge chat-browser doctor
```

A ready environment reports `PASS` for Chrome executable, profile directory, browser launch, ChatGPT reachability, ChatGPT session, page readiness, and composer. Run this end-to-end check afterwards:

```powershell
python -m clawbridge chat-browser doctor --send
```

On success it returns `CLAWBRIDGE_BROWSER_OK`. Do not make `/chat` the first browser diagnostic.

### 7. Confirm Codex only if you need read-only analysis

`/codex` is the explicit local read-only Codex analysis route. It runs `codex exec --sandbox read-only` for a configured project. Install and authenticate Codex CLI separately before using it. ClawBridge supplies neither a Codex/OpenAI account nor an implicit route from `/chat` to `/codex`.

### 8. Start ClawBridge

Start the long-running bridge process:

```powershell
python -m clawbridge run
```

The bridge stops when this PowerShell window stops. If WeChat does not receive a response, first confirm that this process is still running.

## Quick Start

For a first installation that uses all current capabilities:

1. Clone and install ClawBridge and its Python dependencies.
2. Create `%LOCALAPPDATA%\ClawBridge\config.toml` and configure a project.
3. Run `python -m clawbridge login`.
4. Run `python -m clawbridge echo`; send `hello` in WeChat and expect `world`.
5. Run `python -m clawbridge chat-browser setup` and sign in to ChatGPT in the dedicated Chrome window.
6. Close that Chrome window.
7. Run `python -m clawbridge chat-browser doctor`.
8. Run `python -m clawbridge chat-browser doctor --send`.
9. Confirm Codex CLI if you plan to use `/codex`.
10. Run `python -m clawbridge run`.
11. In WeChat, try `/work status`, `/chat status`, and `/chat use clawbridge`.

## WeChat Commands

| Command | Meaning |
| --- | --- |
| `/work status` | Show the latest Work status. |
| `/work last` | Show the latest Work activity. |
| `/work result` | Show the latest Work result. |
| `/work watch` | Enable one brief notification when a whole task first reaches `COMPLETE`. |
| `/work unwatch` | Disable Work completion notifications. |
| `/codex <project> <task>` | Explicitly start read-only Codex analysis for a configured project. |
| `/chat use <project>` | Bind the configured project to the default ChatGPT session. |
| `/chat <message>` | Discuss or analyze with ChatGPT; it does not execute. |
| `/chat status` | Show local chat-session status. |
| `/chat reset` | Reset ChatGPT thread/history while keeping the project binding. |

## WeChat Outbound Policy

WeChat is a control, short-summary, and completion-reminder channel—not a long-log channel.

- A business response normally sends at most one WeChat message.
- The outbound hard cap is **1000 Unicode characters**.
- Automatic multipart/numbered-message chunking is disabled.
- `/chat` asks ChatGPT for a short summary by default.
- A Codex handoff of 1000 characters or fewer is provided in full.
- A Codex handoff over 1000 characters is neither truncated nor split; ClawBridge sends a fixed notice to continue on the PC.
- Full reports, logs, tracebacks, test output, and detailed development work belong on the PC, where the complete ChatGPT reply remains local audit state.
- A Work proactive notification is sent only when a whole development task first reaches `COMPLETE`; it stays extremely short, identifying the task and `状态：完成`. Use `/work result` for details.

## Runtime Data and Credentials

Local runtime state lives under:

```text
%LOCALAPPDATA%\ClawBridge
```

This includes `config.toml`, the local chat session at `chat\session.json`, the dedicated browser profile, WeChat/iLink account metadata, and route/runtime state. ChatGPT login data stays in the dedicated Chrome profile; the iLink token is stored through the local credential store/OS keyring. Never commit tokens, credentials, profiles, session state, or personal configuration.

## External Service Limitations

Tencent iLink / WeChat ClawBot is an external transport service. Tencent controls availability, rate limits, message volume/frequency, session and context validity, and actual client delivery behavior. These can change independently of ClawBridge.

- Tencent does not publish a stable fixed rate-limit threshold for this use; do not rely on a “N messages per minute” rule.
- Short bursts or frequent outbound messages may be limited, which is why ClawBridge uses short messages and low-frequency proactive notifications.
- `sendmessage ret=0` or other API acceptance means only that the API accepted a request. It does **not** guarantee delivery to the WeChat client.
- ClawBridge records such calls as `ACCEPTED_UNCONFIRMED` and does not densely auto-retry delivery that has not been confirmed.
- Supervised real WeChat E2E delivery has been verified. Account-specific iLink binding or client-delivery anomalies can still occur independently of ClawBridge; treat `ret=0` or other API acceptance as delivery-unconfirmed unless the WeChat client actually receives the message.

## Architecture and Advanced Usage

```text
WeChat ClawBot
      ↕
ClawBridge core
      ├─ M1 Work Observer
      ├─ M2 Codex Executor
      └─ M3 Conversation Core
            └─ ChatGPT Browser Driver
```

### M3-A: ChatGPT browser setup

Runtime browser automation uses Playwright with the same dedicated profile used during manual Chrome login. It waits for a new assistant response, stable non-empty text, and completion UI signals within the configured reply deadline.

### M3-B: Local conversation session

The `default` session stores its canonical ChatGPT `/c/...` URL and up to 24 recent audit messages in `%LOCALAPPDATA%\ClawBridge\chat\session.json`. Later runs reopen that exact thread; ClawBridge does not search the sidebar, inject history, or silently replace an unavailable thread.

### M3-C: Lightweight project context

Project context is demand-driven and read-only. It can summarize Work and limited Git facts (branch, clean/dirty state, changed-file count, and last local commit), but never fetches, pulls, checks out, commits, searches source, or executes a project.

### M3-D: WeChat conversation bridge

Only one `/chat` request drives the default browser session at a time. Control commands do not start the browser. The full assistant response remains local; WeChat receives the bounded result described in the outbound policy above.
