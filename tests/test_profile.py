"""Профиль quality.yml: формат как в antagor, JSON Schema — в инструменте."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import jsonschema
import pytest
import yaml

import rb_textcheck
from rb_textcheck.core.profile import PIPELINE_FORBID, ProfileError, load_profile

VECTORS = Path(__file__).resolve().parents[1] / "vectors"
VALID = sorted((VECTORS / "profiles").glob("*.quality.yml"))
INVALID = sorted((VECTORS / "profiles-invalid").glob("*.quality.yml"))


def _schema() -> dict:
    return json.loads(resources.files("rb_textcheck.data").joinpath("quality-profile.schema.json").read_text())


def test_samples_exist() -> None:
    assert len(VALID) >= 4
    assert len(INVALID) >= 7


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_sample_profile_loads(path: Path) -> None:
    profile = load_profile(path)
    assert profile.path == path


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_sample_profile_matches_bundled_schema(path: Path) -> None:
    jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")), _schema())


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_profile_is_an_error(path: Path) -> None:
    """Битый профиль не откатывается молча на дефолты — проверка стала бы мягче, чем думает пользователь."""
    with pytest.raises(ProfileError):
        load_profile(path)


def test_default_profile_has_no_domain_rules() -> None:
    """antagor test_default_profile_has_no_domain_rules: на дефолтах только запреты пайплайна."""
    profile = load_profile(None)
    assert profile.length_bounds() == (None, None)
    assert profile.cliches == []
    assert [r.name for r in profile.forbid] == [r["name"] for r in PIPELINE_FORBID]


def test_merge_is_per_key() -> None:
    """Профиль с одним `length` не обнуляет остальные настройки секции и humanizer."""
    profile = load_profile({"length": {"min_chars": 100}, "humanizer": {"max_warnings": 3}})
    assert profile.length["tolerance"] == 0.1
    assert profile.humanizer["error_is_gate"] is True
    assert profile.humanizer["max_warnings"] == 3


def test_missing_profile_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "nope.quality.yml")


def test_fingerprint() -> None:
    assert load_profile(None).fingerprint == "defaults"
    assert len(load_profile(VALID[0]).fingerprint) == 8


def test_check_accepts_profile_forms() -> None:
    """check() берёт профиль путём, словарём, готовым QualityProfile или None."""
    text = "<p>Обычный абзац текста.</p>"
    for spec in (None, VALID[0], str(VALID[0]), {"length": {}}, load_profile(None)):
        assert rb_textcheck.check(text, spec, "html").as_dict()["issues"] is not None


def test_check_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        rb_textcheck.check("текст", None, "docx")


# --- T78 B ----------------------------------------------------------------------


def test_meta_profile_loads_as_meta() -> None:
    profile = load_profile(VECTORS / "profiles" / "seo-meta.quality.yml")
    assert profile.kind == "meta"


def test_check_refuses_meta_profile() -> None:
    with pytest.raises(ProfileError, match="kind"):
        rb_textcheck.check("<p>т</p>", VECTORS / "profiles" / "seo-meta.quality.yml", "html")


def test_unknown_inner_key_names_its_path(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match=r"humanizer/max_warning\b"):
        load_profile({"humanizer": {"max_warning": 3}})


def test_extends_child_overrides_and_lists_merge() -> None:
    profile = load_profile(VECTORS / "profiles" / "article-required.quality.yml")
    assert [r.name for r in profile.forbid] == [r["name"] for r in PIPELINE_FORBID] + ["ставка НДС 20%", "бетон"]
    assert profile.headings["h2_min"] == 2
    assert profile.headings["forbid_colon"] is True


def test_extends_fingerprint_covers_the_base(tmp_path: Path) -> None:
    (tmp_path / "base.quality.yml").write_text("forbid:\n  - name: a\n    regex: a\n", encoding="utf-8")
    child = tmp_path / "child.quality.yml"
    child.write_text("extends: base\n", encoding="utf-8")
    before = load_profile(child).fingerprint
    (tmp_path / "base.quality.yml").write_text("forbid:\n  - name: b\n    regex: b\n", encoding="utf-8")
    assert load_profile(child).fingerprint != before


def test_extends_from_dict_resolves_against_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(VECTORS / "profiles")
    assert [r.name for r in load_profile({"extends": "vat-22"}).forbid][-1] == "ставка НДС 20%"


def test_vat_rule_is_not_in_code() -> None:
    assert "ставка НДС 20%" not in [r["name"] for r in PIPELINE_FORBID]


def test_profile_validate_meta_ok() -> None:
    from typer.testing import CliRunner

    from rb_textcheck.cli import app

    result = CliRunner().invoke(
        app, ["profile", "validate", str(VECTORS / "profiles" / "seo-meta.quality.yml"), "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["kind"] == "meta"


def test_schema_fixes_rule_ids_match_rules() -> None:
    """fixes_rule в схеме перечисляет id правил - тот же список, что `textcheck rules`."""
    pattern = _schema()["$defs"]["article"]["properties"]["fixes"]["items"]["properties"]["fixes_rule"]["pattern"]
    ids = pattern.removeprefix("^(").split(")")[0].split("|")
    assert ids == [r["id"] for r in rb_textcheck.rules()]
