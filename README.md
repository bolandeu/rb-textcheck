# textcheck

Deterministic text quality checks by a quality profile (no network, no LLM)

## Development

```bash
uv sync
uv run textcheck --help
uv run scripts/release.py --check   # the full gate (what releases and CI run)
scripts/install_hooks.sh  # once per clone: git uses the versioned hooks in .githooks/
uv run pytest --snapshot-update  # after changing a command's help; review tests/snapshots/help/
```

`pytest` fails below the coverage floor in `pyproject.toml`; `ruff` includes
the security (`S`) rules; the gate also scans `uv.lock` for known
vulnerabilities when `osv-scanner` is installed (`brew install osv-scanner`),
and says it skipped the scan otherwise. CI is optional and only repeats
`release.py --check`.

## Release

The version is the git tag (`vX.Y.Z`) — `pyproject.toml` has no `version =`.
Each change adds a changelog fragment instead of editing `CHANGELOG.md`:

```bash
uv run towncrier create +<slug>.<type>.md -c "What changed, for a human reader."
uv run scripts/release.py patch   # or minor / major (SemVer; at 0.x: patch = fix/feature, minor = breaking)
# then the root tools agent pushes it (git push --follow-tags) after your yes
```

`release.py` refuses off `main`, on a dirty tree or behind the remote, runs
the full gate (the same as `--check`; any failing step aborts the release), assembles `CHANGELOG.md` from `changelog.d/`, commits
`Release vX.Y.Z` and tags it; pushing goes through the root tools agent.

## Install

**On this machine, from a local checkout:**

```bash
uv tool install .
```

**On any other machine (any OS), once this repo is pushed to GitHub — no
PyPI publish needed:**

```bash
uv tool install "rb-textcheck @ git+https://github.com/bolandeu/textcheck.git@vX.Y.Z"
```

Replace `vX.Y.Z` with the latest release tag (a tag cut by
`scripts/release.py`; never install a branch). This is also how an AI agent
bootstraps this CLI on a fresh machine/sandbox where it isn't installed
yet — see `src/rb_textcheck/data/SKILL.md`.

**Private repo?** The command above is unchanged — `uv` runs git under the
hood, so it authenticates the same way `git clone` does. On a machine
where the install is refused with an auth error, do one of these once:

```bash
gh auth login          # interactive login also sets up git's credential helper
gh auth setup-git      # only needed if gh was logged in with --with-token / in CI
```

or use the SSH form instead of HTTPS:

```bash
uv tool install "rb-textcheck @ git+ssh://git@github.com/bolandeu/textcheck.git@vX.Y.Z"
```

**Update** an installed copy to the latest commit:

```bash
uv tool upgrade rb-textcheck
```

After install, the command `textcheck` is available globally, on
macOS, Linux and Windows alike (see `architecture.md` in the cli-generator
plugin for why: no shelling out, no hardcoded POSIX paths).

To pick up later architecture changes from the `cli-generator` template
itself, run `copier update` in this repo (requires this repo and the
template to both be git repos; see the `cli-generator` plugin's README).

## Architecture

This project follows a fixed CLI architecture:

- `src/rb_textcheck/commands/` — argument parsing only, no business logic.
- `src/rb_textcheck/core/` — services, models, errors: the real logic.
- `src/rb_textcheck/providers/` — external APIs/integrations.
- `src/rb_textcheck/credentials/` — secrets via the OS keychain (`keyring`)
  and environment variables. Secrets never live in `.rb_textcheck/config.toml`.
- `src/rb_textcheck/output/` — human (`rich`) and `--json` rendering.

Run `textcheck doctor` to check environment/config/auth readiness, and
`textcheck --help` for the full command surface. Every command supports
`--json` for machine/agent consumption; errors are structured (`error.code`,
fixed exit codes, `error.action` telling you what to do next) and go to
stderr in human mode, so stdout is always safe to pipe.

A project can require a minimum CLI version in its `.rb_textcheck/config.toml`
(`[cli] min_version = "..."`); an older install refuses with exit 6 and
`uv tool upgrade rb-textcheck` fixes it.

See `src/rb_textcheck/data/SKILL.md` for the agent-facing usage guide
bundled with this package — install it into an AI tool with
`textcheck skill install`, or get it as plain text with
`textcheck --ai` (works even without file access).
