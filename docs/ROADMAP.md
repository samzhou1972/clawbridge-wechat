# Roadmap

## M0 — Standalone WeChat transport PoC

Status: PASS

- Bind/login without installing QClaw or OpenClaw.
- Receive one text message from the existing WeChat ClawBot.
- Reply to the same conversation.
- Store credentials locally and safely.

Exit: `WeChat → SteerWX → WeChat` works reliably.

## M1 — Work Observer

Status: PASS

- `/work status`: current activity and last observed action.
- `/work last`: latest observed Work activity.
- `/work result`: latest explicit or verified result.
- `/work watch`: one proactive notification when a whole task first reaches COMPLETE.

Exit: useful Work progress/result visibility while away from the PC.

## M2 — Codex CLI Read-only Analysis

Status: PASS

- `/codex <project> <task>` invokes `codex exec --sandbox read-only` for a configured project.
- Capture exit status and final analysis output.
- Return a bounded result to WeChat; no project mutation is available.

## M3 — Conversation Core

Status: PASS

- M3-A Browser Driver: PASS. Runtime automation remains Playwright.
- M3-B Conversation Session: PASS.
- M3-C Project Context: PASS.
- M3-D WeChat E2E: PASS. Supervised tests covered real ChatGPT round-trip, conversation continuity, repeated execution-boundary rejection, and bounded single-message delivery.

M3 never executes project changes. `/codex` remains the explicit read-only analysis boundary.
M3 COMPLETE: YES.

Known external issue: during acceptance, one previously bound WeChat account exhibited an iLink-specific QR rebind and outbound client-delivery anomaly while inbound and online-state signaling still worked. A different account on the same SteerWX host completed QR binding, echo, `/work`, and `/chat` E2E successfully. This external account/binding anomaly does not block M0 or M3 acceptance.
