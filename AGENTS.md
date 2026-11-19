# AGENTS.md

Pointers for agents. Antagor shows the changing state (statuses, branches, tasks): `antagor board`.

- What the project is, and the domain glossary: `CONTEXT.md`. Take terms only from there.
- Decisions and why: `docs/adr/` (format: `docs/adr/README.md`).
- Code rules for review: `CODING_STANDARDS.md`.
- Antagor keeps the tasks and epics: `.agents/antagor/`.
- How to write to the Human and to agents (ASD-STE100): the skill `antagor-method`, section «How to write to the Human and to agents».
- The package Standard: https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md (sections by name, for example «Install»).
- The gate before a commit: `gate check`, on this machine — the command is `[publish] gate_command` in `.agents/antagor/antagor.toml` (Standard, CI). It is the only gate: no workflow runs it.

## Package specifics

### Corpus contract (`vectors/`)

- `vectors/cases/*.yaml` is the behaviour contract (`tests/test_vectors.py`):
  a check change that moves a finding changes a case, with the reason in
  `source` or a comment — never adjust a case just to make the code pass.
- Profiles are data of the `prompts` component; the format (and
  `data/quality-profile.schema.json`) changes only through the user via dev —
  send a proposal, don't change it here.
- `core/humanizer_lint.py` is a third-party copy (MIT, Serge Shima): keep
  rules in sync by porting diffs, keep the attribution and the license file.

### Tests

- A test is not edited to fit the code. An existing test changes only when the requirement did; the gate's
  `existing tests` step lists every changed or removed one, and each goes into the report with its reason.
- Consumer contracts (`tests/contracts/<consumer>/textcheck.yaml`) are never edited to pass; the offline data their
  `run` cases need is `tests/contracts/fixtures.yaml` and `tests/contracts/data/`.
- Mutation testing now and then, outside the gate: `uv run --group mutation mutmut run`.

## Architect only

A worker does not need this section: Antagor cuts it from the worker's brief.
