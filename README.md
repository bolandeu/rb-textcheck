# textcheck

Deterministic text quality checks by a quality profile (no network, no LLM)

Перенос детерминированного слоя проверок antagor (`utils/quality_checks.py`,
`humanizer_lint.py`, `quality_profile.py`, `text_blocks.py`, коммит `9a5e4d8`)
в отдельный инструмент: без сети, без LLM.

```bash
textcheck check article.html --profile content-logistics.quality.yml --json
cat article.md | textcheck check - --format md --json
textcheck fix article.html --profile typography.quality.yml > fixed.html
textcheck fix article.html --profile typography.quality.yml --check --json
textcheck profile validate content-logistics.quality.yml
textcheck rules --json
```

`check --json` → `{ok, issues[{rule, message, excerpt, gate, unit, address, action}],
humanizer{score, verdict} | null, gate_failed}`. Коды выхода: `0` — гейт пройден
(находки с `gate: false` — к сведению), `1` — есть находки с `gate: true`
(отчёт выдаётся целиком, плюс `error.code = QUALITY_GATE_FAILED`), `2` —
аргументы или профиль (`INVALID_ARGUMENTS`, `INVALID_PROFILE`).

`fix` — механические автозамены из секции профиля `fixes` (`{name, from, to,
regex, where, fixes_rule}`), по порядку, только в тексте (теги, атрибуты, код,
адреса ссылок и голые URL не трогаются). По умолчанию — исправленный текст в
stdout; `--json` → `{ok, text, applied[{name, count, addresses}], unchanged}`;
`--check` — плюс отчёт `check` по результату и его код выхода.

Библиотечно:

```python
import rb_textcheck

result = rb_textcheck.check(text, "content-logistics.quality.yml", "html")  # профиль: путь | dict | None
result.gate_failed, result.as_dict()
fixed = rb_textcheck.fix(text, "typography.quality.yml", "html")  # .text, .applied, .unchanged
```

Профиль `quality.yml` — формат antagor `prompts/*.quality.yml`: `kind: article`
(по умолчанию; секции `length`, `headings` (+ `required`), `tags`, `cliches`,
`forbid`, `fixes`, `humanizer`, `language`, `grounding`, `judge_model`,
`generation` — последние три textcheck не применяет) или `kind: meta` (профиль
seo-meta, только валидация). `extends: <имя|путь>` — наследование. Неизвестный
ключ на любом уровне — ошибка. JSON Schema —
`src/rb_textcheck/data/quality-profile.schema.json`.

Поведение закреплено корпусом `vectors/` (формат — `vectors/README.md`).

`core/humanizer_lint.py` — копия `lint.py` скилла humanizer-ru, автор Serge Shima,
MIT: `src/rb_textcheck/data/LICENSE-humanizer-ru.txt`.

## Development

```bash
uv sync
uv run textcheck --help
uv run pytest --snapshot-update  # after changing a command's help; review tests/snapshots/help/
```

The gate is the `rb-release check` step of `.gitea/workflows/ci.yml`: run that command before a commit. The version
is the git tag; a release goes through Antagor (`antagor publish`), which writes `CHANGELOG.md`.

## Install

```bash
uv tool install --index gitea=https://homeserver.tailee01ab.ts.net:3000/api/packages/bolandeu/pypi/simple rb-textcheck
```

An AI agent bootstraps the CLI the same way on a fresh machine — see `src/rb_textcheck/data/SKILL.md`.

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
