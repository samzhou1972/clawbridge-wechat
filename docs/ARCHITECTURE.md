# Architecture

## Core principle

ClawBridge is a bridge, not an agent framework. Each external dependency is isolated behind an adapter.

```text
WeChat ClawBot
      ↕
ClawBridge core
      ├─ M1 Work Observer
      ├─ M2 Codex Read-only Analysis
      └─ M3 Conversation Core
            └─ ChatGPT Browser Driver
```

## Work observation trust order

1. Explicit callback from the running Work task: authoritative completion/failure/needs-input signal.
2. Local session/event observation: activity, last action, active/idle inference.
3. External artifacts: Git, files, reports, tests and logs used to verify real-world results.

## Boundaries

- QClaw and OpenClaw are not runtime dependencies.
- Weixin/iLink protocol code stays isolated under `channels/`.
- Work observation must not depend on fragile GUI scraping for core status.
- M3 Converse means understand → analyze → discuss → decide → prepare a local analysis
  request. It never executes. M2 requires an explicit `/codex` command and stays read-only.
- Browser thread state is transport/runtime state, not authoritative project state.
- M3-A uses a normal Chrome process for manual authentication bootstrap; runtime browser automation remains Playwright. Both use the dedicated persistent ClawBridge profile.
- The ClawBridge Chrome profile is isolated from daily Edge and every other browser automation profile.
- Earlier extension-based experiments are not part of the public runtime architecture.
- M3-D connects WeChat `/chat` to the existing ConversationService; it does not create
  an execution path or duplicate Context routing.
- Credentials remain local and must never be committed.

## M3-B conversation session

The first session implementation supports only `default`. Its authority is a small
JSON artifact under `%LOCALAPPDATA%\ClawBridge\chat\session.json` containing the
session id, canonical browser thread URL, at most 24 recent user/assistant messages,
and timestamps. Writes replace the file atomically only after a complete user and
assistant round trip.

The saved `https://chatgpt.com/c/...` URL is opened directly on later CLI runs. A
missing or inaccessible thread is an explicit failure; ClawBridge does not search the
sidebar, create a replacement, inject history, summarize, or recover automatically.
`recent_messages` is local audit state, not prompt context.

## M3-C project context

The default session may bind one `current_project` logical name. Its root comes only
from `[projects.<name>]` in the local config; the same configured-project resolver is
used by Project Context and `/codex`. Arbitrary message text is never treated as a
filesystem path. Switching projects does not reset or replace the selected
ChatGPT thread. Reset clears thread/history but preserves the binding.

Project Context is lightweight and demand-driven. One centralized deterministic
router selects Work and/or Git from explicit intent keywords. With a bound project,
the outbound prompt separates `[ClawBridge Local Facts]` from `[User Message]`.
The local audit still saves the original user text, never the enriched envelope.

The Work provider reuses the M1 rollout parser and only returns a snapshot whose cwd
matches the selected root. The Git provider runs fixed, read-only argument lists for
local status, branch, and last-commit facts with `shell=False`. Provider failures are
visible in the envelope and CLI warnings but do not inherently abort the conversation.

M3-C does not scan or search source, read project documentation, summarize a project,
execute a task, provide RAG/embedding/vector storage, or create agent memory.

## M3-D WeChat E2E

Exact control commands are handled without opening ChatGPT. Ordinary `/chat` messages
use the shared project binding and deterministic Context envelope, then call the shared
ConversationService. A dedicated process lock and single-worker executor protect the
one default session and browser profile; the independent Codex lock is unchanged.

Outbound answers are character-safe single messages. A bounded process-local inbound
identity set prevents replay when the transport exposes a stable message/event ID.
Successful ChatGPT completion and every other outbound call are never automatically
retried when WeChat delivery fails.

The shared Conversation Mode envelope precedes Local Facts and User Message for both
WeChat and `chat-local`. It is not stored in `recent_messages`. Implementation requests
are answered with a structured Codex handoff for the user to submit explicitly; `/chat`
has no Codex, subprocess, project-mutation, or other side-effect path.

Conversation output has two distinct budgets: a model-side soft request for roughly
800–900 Chinese characters and a universal WeChat transport hard cap of 1000 Unicode
characters. Automatic multi-message chunking is disabled. The full assistant reply
remains in the local session audit; ordinary overflow is bounded only for transport.
A reply containing the fixed `【Codex 执行指令】` marker is a complete execution contract:
when it exceeds 1000 characters it is replaced as a whole by a PC-escalation notice,
never truncated or split.

WeChat is limited to control, short summaries, and one completion notification per Work
task. The PC is authoritative for complete reports, logs, tracebacks, test output, and
detailed development work. Work watch reuses the M1 top-level `task_complete` state and
the persisted route `last_notified` marker; intermediate and failed states do not notify.
iLink diagnostics distinguish `REPLY` from `PROACTIVE` and treat `ret=0` only as
`ACCEPTED_UNCONFIRMED`, because no end-client delivery receipt exists.

Browser completion is a multi-signal decision. The driver tracks the newest assistant
text and requires two seconds of stability, while visible generation and assistant
completion markers act as supporting signals. An apparently stale generation marker
gets only a bounded additional grace period. Timeout diagnostics record response/text
timing, final length, marker visibility, assistant counts, stage, URL, and configured
deadline.
