---
name: textcheck
description: Conventions for driving the textcheck CLI from an agent — install, JSON output, exit codes, credentials, destructive-command gating. Invoke when a task involves this project's operations.
---

# textcheck

Everything command-specific is in the CLI itself — run `textcheck`
with no arguments for version + command list, `textcheck <command>
--help` for details. This document only covers what `--help` can't tell
you. If you can run the CLI but not read files, `textcheck --ai`
prints this document.

## Install (if `textcheck --version` fails)

```bash
uv tool install rb-textcheck --index https://homeserver.tailee01ab.ts.net:3000/api/packages/bolandeu/pypi/simple
```

From the git tag instead:

```bash
uv tool install "rb-textcheck @ git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/textcheck.git@vX.Y.Z"
```

Replace `vX.Y.Z` with the latest release tag (install from a tag, never a
branch: [the Standard](https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md), Install).

Same command on macOS, Linux and Windows; `uv tool upgrade rb-textcheck`
updates it. Do not run from source unless asked to develop the CLI.

## Conventions

- **`--json` on every command.** Parse stdout; never scrape human output.
  stdout is data only, stderr is diagnostics.
- **Project-aware.** Commands find the project by walking up from the
  current directory, or take `--project PATH`. Not initialized →
  `textcheck init --non-interactive`.
- **`--non-interactive`** on anything that could prompt. It fails with a
  structured error instead of hanging.
- **Destructive commands** are the ones whose `--help` shows `--dry-run`
  and `--confirm`. Always: run with `--dry-run`, show the user, get
  explicit sign-off, then `--confirm --non-interactive`. Never chain
  straight to `--confirm` without a human having seen the dry-run.
- **`doctor --json`** first when something looks off — it reports
  what the CLI needs to run: its version, the project, its config and the external programs.
- **`describe --json`** — the whole CLI as one machine-readable OpenCLI
  document (commands, options, exit codes, env vars, data): the bare
  document, no `{"ok": ...}` envelope.

## Errors

Error envelope: `{"ok": false, "error": {"code", "message", "action"}}`.
Read exit code → `error.code` → `error.action` (the concrete next command).

    0  ok
    1  general (UNEXPECTED = a bug: re-run with --verbose, report; ABORTED = user said no)
    2  invalid arguments
    3  auth required
    4  project not initialized → textcheck init
    5  provider error (network / external service; already retried) → retry later
    6  CLI too old for this project → uv tool upgrade rb-textcheck

Only exit 5 is worth an automatic retry.
