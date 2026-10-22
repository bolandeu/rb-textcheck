---
id: TEXTCHECK-001
title: 'Template v1.27.1: README install lines, test fixture, refreshed help/describe
  snapshots, lock'
status: ideas
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: null
worker: claude-code
type: chore
owns_paths:
- README.md
- tests/conftest.py
- tests/snapshots
- uv.lock
test_paths: []
docs:
- README.md
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- uvx --from git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git@v1.27.1#subdirectory=gate
  rb-release check
resident: null
tool: null
pr: null
---

After the copier update to v1.27.1 (commit 65d5d57) the gate still fails (pytest). Apply the Architect's saved patch: git apply /private/tmp/claude-501/-Users-bolandau-Work-tools-textcheck/18cc883a-1094-4365-b843-9a5e006e050c/scratchpad/standard-followup.patch (README install lines, tests/conftest.py contract_data fixture kept next to the template fixtures, uv.lock, help/describe snapshots incl. new skill-list.txt). Then run the gate; it must end with 'release: gate passed'. Report the changed/removed existing tests the gate lists, with reasons (template merge).

## Out of scope

- No behaviour changes; no edits to existing tests beyond snapshots.
