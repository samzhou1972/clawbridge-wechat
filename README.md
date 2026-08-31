# ClawBridge for WeChat

**English** | [简体中文](README.zh-CN.md)

**Control local ChatGPT Work and Codex from WeChat - without exposing your development PC to the public Internet.**

ClawBridge is a lightweight, local-first bridge that turns WeChat ClawBot into a remote control and conversation channel for AI development running on your PC.

From your phone, you can:

- check local ChatGPT Work status and results;
- continue discussing the current project with ChatGPT;
- add lightweight local project, Git, and Work context when needed;
- explicitly trigger read-only Codex analysis for a configured local repository;
- receive brief completion notifications without exposing your full development environment to the public Internet.

Detailed work, full reports, logs, source code, and runtime state stay on the PC.

> **Status: Alpha / Early Stage**  
> The complete first-time setup flow is currently verified on Windows only. ClawBridge is still experimental and is not production-ready infrastructure. Tencent iLink / WeChat ClawBot is an external dependency whose account, session, binding, rate-limit, and delivery behavior may change independently of ClawBridge.

ClawBridge is an independent open-source project and is not affiliated with, authorized by, or endorsed by Tencent, WeChat, or OpenAI.

---

## See it in action

Ask about the local project directly from WeChat:

<p align="center">
  <img src="docs/images/clawbridge-wechat-chat-overview.jpg" alt="ClawBridge WeChat /chat demo" width="430">
</p>

For example:

```text
/chat What problem does this project solve?
```

ClawBridge keeps the conversation tied to the current project context instead of treating every WeChat message as a completely unrelated request.

---

## What can ClawBridge do?

```text
WeChat ClawBot
      ↕
  ClawBridge
      ├─ /work  → local ChatGPT Work status
      ├─ /chat  → ChatGPT Web + project context
      └─ /codex → local Codex CLI (read-only analysis)
                    ↓
                local projects
```

The command boundary is deliberate:

- **`/work` observes** local Work facts, status, and results.
- **`/chat` discusses** the project with ChatGPT and may prepare a Codex handoff.
- **`/codex` explicitly analyzes** a configured local project with Codex in a read-only sandbox.

A `/chat` message that asks to modify code, run tests, commit, or deploy **does not automatically perform those actions**.

ClawBridge is intentionally not a general-purpose agent framework. It does not provide model routing, RAG, long-term memory, or workflow orchestration, and it does not depend on QClaw or OpenClaw.

---

## Capabilities

| Capability | Purpose | Requirement |
|---|---|---|
| `/work` | Observe local ChatGPT Work facts, status, and results | Accessible local Work state |
| `/chat` | Discuss and analyze the current project with ChatGPT | Chrome with ChatGPT Web signed in |
| `/codex` | Explicitly start local read-only Codex analysis | Configured project + working Codex CLI |
| Git Context | Add on-demand, read-only Git facts to `/chat` | Git repository + Git CLI |
| WeChat transport | Send commands and receive results from WeChat | WeChat + Tencent iLink / WeChat ClawBot |

---

## Requirements

The complete first-time setup is currently verified on **Windows**. Linux and macOS are not yet accepted platforms.

Prepare only the dependencies required by the capabilities you plan to use:

- Python 3.11 or later;
- Google Chrome, for the dedicated ChatGPT Web profile;
- a ChatGPT Web account, only for `/chat` — ClawBridge **does not use the OpenAI API**;
- WeChat and Tencent iLink / WeChat ClawBot, for WeChat transport;
- Codex CLI, with its own authentication/configuration complete, only for `/codex`;
- Git CLI and a Git repository, only for Git Context;
- one or more local project directories;
- locally accessible ChatGPT Work state, only for Work Observer.

Cloning the repository and running `python -m clawbridge run` does not automatically enable every capability. For example, `/work` does not require ChatGPT Browser, while `/chat` does.

---

# First-time setup

## 1. Install ClawBridge

```powershell
git clone https://github.com/samzhou1972/clawbridge-wechat.git
cd clawbridge-wechat
python -m pip install -e .
```

Confirm the CLI is available:

```powershell
python -m clawbridge --help
```

---

## 2. Configure local projects

Runtime configuration is stored at:

```text
%LOCALAPPDATA%\ClawBridge\config.toml
```

Copy `config.example.toml` to that location, then explicitly configure every project ClawBridge may use:

```toml
[projects.clawbridge]
root = "C:\\path\\to\\clawbridge"
```

Here:

- `clawbridge` is the logical project name;
- `root` is the real local directory.

`[projects.<name>].root` is the sole project-path authority for `/chat` context, Git Context, Work matching, and `/codex`.

From WeChat:

```text
/chat use clawbridge
```

selects that configured project.

ClawBridge does not scan the disk to guess your projects. Do not commit personal runtime configuration, credentials, or browser profiles to Git.

---

## 3. Bind WeChat ClawBot

ClawBridge uses Tencent iLink / WeChat ClawBot as its transport layer rather than a normal WeChat Web API.

Start the binding flow:

```powershell
python -m clawbridge login
```

The terminal requests and displays a binding QR code. Then:

1. scan it with WeChat on your phone;
2. if WeChat displays a numeric verification code, enter it in the terminal;
3. finish the ClawBot binding flow;
4. keep the resulting credentials in local runtime state only.

---

## 4. Verify WeChat transport

Run the minimal transport smoke test:

```powershell
python -m clawbridge echo
```

Then send this to WeChat ClawBot:

```text
hello
```

Expected reply:

```text
world
```

This verifies only:

```text
WeChat ↔ Tencent iLink ↔ ClawBridge
```

Complete this step before diagnosing ChatGPT, Work, or Codex.

> API acceptance does not prove that the WeChat client actually received the message. See [External service limitations](#external-service-limitations).

---

## 5. Prepare the ChatGPT browser session

ClawBridge uses a dedicated Chrome profile:

```text
%LOCALAPPDATA%\ClawBridge\browser\chrome-profile
```

Run the one-time login setup:

```powershell
python -m clawbridge chat-browser setup
```

This launches normal system Chrome with the dedicated profile.

In the opened browser:

1. manually sign in to `chatgpt.com`;
2. confirm ChatGPT works;
3. close that Chrome window.

The authenticated session remains in the dedicated profile.

ClawBridge never asks for, collects, or stores your ChatGPT password.

> Being signed in to your everyday Chrome or Edge does not mean the ClawBridge profile is signed in. ClawBridge does not use your daily Edge profile or a browser extension.

---

## 6. Verify ChatGPT Browser

After closing the login browser, run:

```powershell
python -m clawbridge chat-browser doctor
```

A ready environment reports `PASS` for the browser and ChatGPT readiness checks.

Then run the end-to-end browser check:

```powershell
python -m clawbridge chat-browser doctor --send
```

On success:

```text
CLAWBRIDGE_BROWSER_OK
```

For first-time setup, use the doctor command before diagnosing `/chat` itself.

---

## 7. Prepare Codex CLI (optional)

If you want to use `/codex`, install and authenticate Codex CLI separately.

ClawBridge explicitly runs configured projects in a read-only sandbox:

```text
codex exec --sandbox read-only
```

ClawBridge does not provide a Codex/OpenAI account and does not silently route ordinary `/chat` messages into Codex execution.

---

## 8. Start ClawBridge

```powershell
python -m clawbridge run
```

This starts the long-running bridge process.

If the PowerShell window stops, ClawBridge stops too. If WeChat no longer receives replies, first confirm that the bridge process is still running.

---

## Quick setup checklist

For a first installation using all current capabilities:

1. clone and install ClawBridge;
2. create `%LOCALAPPDATA%\ClawBridge\config.toml` and configure at least one project;
3. run `python -m clawbridge login`;
4. run `python -m clawbridge echo`, send `hello` in WeChat, and expect `world`;
5. run `python -m clawbridge chat-browser setup` and sign in to ChatGPT;
6. close that Chrome window;
7. run `python -m clawbridge chat-browser doctor`;
8. run `python -m clawbridge chat-browser doctor --send`;
9. confirm Codex CLI if you plan to use `/codex`;
10. run `python -m clawbridge run`;
11. try `/work status`, `/chat status`, and `/chat use clawbridge` from WeChat.

---

# WeChat commands

| Command | Meaning |
|---|---|
| `/work status` | Show the latest Work status |
| `/work last` | Show the latest Work activity |
| `/work result` | Show the latest Work result |
| `/work watch` | Enable one brief notification when a whole task first reaches `COMPLETE` |
| `/work unwatch` | Disable Work completion notifications |
| `/codex <project> <task>` | Explicitly start read-only Codex analysis for a configured project |
| `/chat use <project>` | Bind the configured project to the default ChatGPT session |
| `/chat <message>` | Discuss or analyze with ChatGPT; it does not execute code changes |
| `/chat status` | Show local chat-session status |
| `/chat reset` | Reset ChatGPT thread/history while keeping the project binding |

---

# A longer conversation example

A `/chat` conversation can continue across messages and keep the selected project context:

<p align="center">
  <img src="docs/images/clawbridge-wechat-chat-details.jpg" alt="ClawBridge longer WeChat conversation example" width="430">
</p>

The intended workflow is simple:

**discuss with `/chat`, observe with `/work`, and explicitly use `/codex` only when local analysis is actually needed.**

---

# WeChat outbound policy

WeChat is treated as a **control, short-summary, and completion-reminder channel**, not a long-log channel.

Current policy:

- a business response normally sends at most one WeChat message;
- the outbound hard cap is 1000 Unicode characters;
- automatic multipart / numbered-message chunking is disabled;
- `/chat` asks ChatGPT for a short summary by default;
- a Codex handoff of 1000 characters or fewer is provided in full;
- a Codex handoff over 1000 characters is neither truncated nor split; ClawBridge sends a notice to continue on the PC;
- full reports, logs, tracebacks, test output, and detailed development work stay on the PC;
- a proactive Work notification is sent only when a whole task first reaches `COMPLETE`, and remains intentionally brief.

---

# Runtime data and credentials

Local runtime state lives under:

```text
%LOCALAPPDATA%\ClawBridge
```

It may contain:

- `config.toml`;
- `chat\session.json`;
- the dedicated Chrome profile;
- WeChat / iLink account metadata;
- route/runtime state.

ChatGPT login data stays in the dedicated Chrome profile. The iLink token is stored through the local credential store / OS keyring.

**Never commit tokens, credentials, profiles, session state, or personal runtime configuration to Git.**

---

# External service limitations

Tencent iLink / WeChat ClawBot is an external transport service. Tencent controls availability, rate limits, message volume/frequency, session and context validity, binding state, and actual client delivery behavior. These may change independently of ClawBridge.

In particular:

- Tencent does not publish a stable fixed rate-limit threshold for this use case, so do not rely on a permanent “N messages per minute” rule;
- short bursts or frequent outbound messages may be limited, which is why ClawBridge uses short messages and low-frequency proactive notifications;
- `sendmessage ret=0` or similar API acceptance only means that the server accepted the request — it does not guarantee delivery to the WeChat client;
- ClawBridge records such calls as `ACCEPTED_UNCONFIRMED` and does not densely auto-retry delivery that has not been confirmed;
- supervised real WeChat E2E delivery has been verified, but account-specific binding or client-delivery anomalies may still occur independently of ClawBridge.

---

# Architecture

```text
WeChat ClawBot
      ↕
ClawBridge Core
      ├─ M1 Work Observer
      ├─ M2 Codex Executor
      └─ M3 Conversation Core
             └─ ChatGPT Browser Driver
```

## M3-A: ChatGPT Browser

Runtime browser automation uses Playwright with the same dedicated profile used during manual Chrome login.

It waits for a new assistant response, stable non-empty text, and the corresponding completion signals.

## M3-B: Local conversation session

The default session stores its canonical ChatGPT `/c/...` URL and up to 24 recent audit messages at:

```text
%LOCALAPPDATA%\ClawBridge\chat\session.json
```

Later runs reopen that exact thread.

ClawBridge does not search the ChatGPT sidebar, inject artificial history, or silently replace an unavailable thread with another one.

## M3-C: Lightweight project context

Project context is demand-driven and read-only.

It may summarize:

- Work state;
- Git branch;
- working tree clean/dirty state;
- changed-file count;
- last local commit.

It does **not** perform:

- `git fetch` / `pull`;
- checkout;
- commit;
- source-code search;
- project execution.

## M3-D: WeChat conversation bridge

Only one `/chat` request drives the default browser session at a time.

Control commands do not start the browser.

The complete assistant response remains local; WeChat receives only the bounded result defined by the outbound policy.

---

# Current development status

Current acceptance state:

- M0 — WeChat / iLink Transport: automated acceptance passed;
- M1 — Work Observer: automated acceptance passed;
- M2 — Codex Executor: automated acceptance passed;
- M3-A / B / C / D: automated acceptance passed;
- M0 and M3-D: supervised real WeChat E2E verification completed.

This is still an early-stage project. In particular, the WeChat transport depends on Tencent iLink / ClawBot, so the status above should not be interpreted as a production SLA.

---

# Why ClawBridge exists

ClawBridge solves a very specific problem:

> Once development work increasingly depends on ChatGPT, Codex, and local AI tools, how can you leave the computer and still know what is happening, continue the discussion, and explicitly trigger local analysis when needed?

The answer here is not another full remote IDE, and it is not exposing the development machine directly to the public Internet.

WeChat is already on the phone.

ClawBridge therefore uses it as a lightweight entry point:

**use `/chat` to discuss, `/work` to observe, and `/codex` only when local analysis is explicitly required.**

The project intentionally stays small and opinionated. If that workflow matches your needs, use it as-is. If not, fork it and adapt the bridge to your own local AI setup.

---

# Contributing

Issues, bug reports, documentation improvements, and pull requests are welcome.

Before contributing, please read:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

---

# License

ClawBridge is released under the [MIT License](LICENSE).

If ClawBridge is useful to you, a ⭐ Star helps other developers with the same problem discover the project.
