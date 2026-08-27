# AGENTS.md

## Project purpose

ClawBridge is a lightweight bridge between WeChat ClawBot and local AI workspaces. It is not an agent framework.

## Required reading

Before implementation, read `README.md`, `docs/ARCHITECTURE.md`, and `docs/ROADMAP.md`.

## Current constraints

- Do not add QClaw or OpenClaw as runtime dependencies.
- Keep Weixin/iLink transport isolated under `channels/`.
- Implement milestones in order: M0 transport, M1 Work Observer, M2 Codex CLI, M3 ChatGPT conversation bridge.
- Prefer explicit callbacks and stable local artifacts over GUI scraping.
- Do not invent undocumented OpenAI or Tencent interfaces; verify before implementation.
- Keep credentials and session data outside Git.
- Default remote execution to least privilege.
- Keep PoCs small and independently testable.

## Open-source discipline

Avoid machine-specific paths, personal data, secrets, and assumptions that only work on one developer PC.
