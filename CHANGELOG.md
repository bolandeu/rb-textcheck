# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

Don't edit this file between releases: each change adds a fragment to
`changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "..."`, type
one of added/changed/deprecated/removed/fixed/security), and
`scripts/release.py` assembles them into a new section below the marker.

<!-- towncrier release notes start -->

## [0.2.0] - 2026-10-03

### Added

- Profile: `kind: article | meta` (meta = antagor seo-meta profile, validated only; check/fix refuse it with INVALID_PROFILE), `extends` (base by name or path; child overrides keys, forbid and fixes are concatenated base-first; a cycle is INVALID_PROFILE), `headings.required` (mandatory <h2>: exact title or {name, regex}; missing → a gate finding of rule headings). `profile validate --json` reports `kind`.
- textcheck fix <file|-> [--profile] [--format html|md] [--json] [--check]: mechanical replacements from the profile's new `fixes` section ({name, from, to, regex, where: text|headings|paragraphs|lists, fixes_rule}), in profile order, text nodes only (code/pre/script/style, md code, link targets, bare URLs and attributes untouched); --json {ok, text, applied[{name, count, addresses}], unchanged}; --check runs check on the result and returns its code. Library: rb_textcheck.fix(text, profile, format).

### Changed

- Breaking: unknown keys inside profile sections (and in forbid items) are now INVALID_PROFILE, with the path to the key (length/min_char); a profile that antagor accepted with a typo inside a section is refused.

### Removed

- Breaking: the built-in forbid rule «ставка НДС 20%» is no longer in the code — put it into the profile (example: vectors/profiles/vat-22.quality.yml); without it a profile no longer flags a 20% VAT rate.


## [0.1.0] - 2026-10-02

### Added

- textcheck check <file|-> [--profile quality.yml] [--format html|md] [--json]: deterministic text checks ported from antagor (quality_checks, humanizer_lint by Serge Shima, MIT); exit 0 gate passed, 1 gate failed (QUALITY_GATE_FAILED with the full report), 2 bad arguments or profile (INVALID_PROFILE). textcheck profile validate (bundled JSON Schema), textcheck rules. Library: rb_textcheck.check(text, profile, format).

### Removed

- The template's placeholder `run` command: `check` is the tool's operation.
