# Security

ClawBridge is local-first. Treat inbound messages as untrusted, keep credentials outside Git, and do not expose the bridge to the public Internet by default.

## Security model

- Commands require an explicitly bound WeChat user identity; an unavailable binding or sender mismatch is rejected.
- `/work` observes local state, `/chat` discusses and analyzes, and `/codex` explicitly invokes Codex in `read-only` sandbox mode.
- Runtime credentials, browser profiles, session data, routes, and diagnostics belong outside the repository.
- The project follows least privilege and does not provide a writable remote execution route in v0.1.0.

## Vulnerability reporting

Use GitHub Private Vulnerability Reporting when it is enabled for this repository. Until then, contact the maintainer privately through the GitHub profile rather than opening a public issue. Do not disclose suspected credentials or vulnerabilities in public issues.
