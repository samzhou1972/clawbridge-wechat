# Changelog

## [0.2.0] - 2026-09-26

### Changed

- Renamed the project from ClawBridge to SteerWX.
- Changed the primary Python package and CLI from `clawbridge` to `steerwx`.
- Changed the default runtime directory to `%LOCALAPPDATA%\SteerWX`.
- Rewrote the product positioning and first-run documentation around SteerWX as a lightweight WeChat companion for ChatGPT and Codex.
- Changed `/chat` so users select a project while SteerWX manages ChatGPT conversations internally.

### Added

- Automatically create a ChatGPT conversation on the first `/chat` message after selecting a project.
- Recover once by creating a new conversation when a saved conversation is explicitly reported as not found or inaccessible.
- Added `migrate-data` to copy legacy ClawBridge runtime data without deleting the original.
- Added regression coverage for the rename migration and `/chat` conversation lifecycle.

### Fixed

- Updated ChatGPT Web page detection for the current page structure.
- Fixed `/chat` failures caused by stale or deleted canonical conversations when their absence can be confirmed.
- Removed the need to manually bind a ChatGPT `/c/...` URL before first use.

### Compatibility

- `python -m clawbridge` and `clawbridge` remain compatibility entry points in v0.2.0.
- Legacy `%LOCALAPPDATA%\ClawBridge` data remains readable and can be copied with `migrate-data`.
- Existing `CLAWBRIDGE_*` overrides and legacy credential/keyring entries remain supported where designed.

### Validation

- 161 automated tests passed.
- `git diff --check` passed.
- Wheel build and clean install were verified.
- Real WeChat send and receive end-to-end tests passed.
- The real `/chat` workflow was verified on the development PC.

## [0.1.1] - 2026-09-21

- Added the non-destructive `clawbridge doctor` command.
- Added first-run checks for local configuration, projects, WeChat binding, Chrome, the ChatGPT browser profile, and Codex CLI.
- Clarified the `/work`, `/chat`, and `/codex` boundaries.
- Improved first-run documentation and the project description.
- 130 automated tests passed.

## [0.1.0] - 2026-08-31

- First public alpha.
- Added WeChat transport through Tencent iLink / WeChat ClawBot.
- Added `/work`, `/chat`, and `/codex` for observing work, discussing projects, and explicitly requesting read-only Codex analysis.
- Added lightweight, read-only Git context.
- Established a local-first Windows workflow that keeps source code, logs, and runtime state on the PC.
