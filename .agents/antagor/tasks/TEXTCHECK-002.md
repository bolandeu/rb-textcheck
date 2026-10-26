---
id: TEXTCHECK-002
title: 'Deps: setuptools for GHSA-xmj3-9gf7-h52w'
status: in_progress
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: chore
owns_paths:
- uv.lock
test_paths: []
docs: none
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- osv-scanner scan source --lockfile uv.lock
- uv run pytest
resident: null
tool: null
pr: null
---

osv-scanner flags setuptools 84.0.0 (GHSA-xmj3-9gf7-h52w, fixed in 84.1.0) in uv.lock; setuptools is a transitive dependency (pymorphy3). Run `uv lock --upgrade-package setuptools`, then `uv run pytest`. Only uv.lock changes. No ignores, no osv config. If the fixed version is not reachable (a pin above it), name the package that holds it back and stop.

## Acceptance

- Given uv.lock, When the gate's vulnerability audit runs, Then osv-scanner reports none [check: osv-scanner scan source --lockfile uv.lock]
- Given the updated uv.lock, When the test suite runs, Then the tests pass [check: uv run pytest]

## Out of scope

- No osv-scanner ignores or config.
- No change to pyproject.toml or other dependencies.
