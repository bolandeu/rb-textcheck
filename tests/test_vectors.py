"""Корпус-контракт vectors/: каждый случай через rb_textcheck.check, сравнение целиком.

Формат случая и происхождение ожиданий — vectors/README.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import rb_textcheck

VECTORS = Path(__file__).resolve().parents[1] / "vectors"


def _cases() -> list:
    params = []
    for path in sorted((VECTORS / "cases").glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")):
            params.append(pytest.param(case, id=f"{path.stem}:{case['id']}"))
    return params


CASES = _cases()


def _profile(spec):
    if isinstance(spec, str):
        return VECTORS / spec
    return spec


def test_corpus_is_not_empty() -> None:
    assert len(CASES) >= 60


def test_case_ids_are_unique() -> None:
    ids = [p.id for p in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES)
def test_vector(case: dict) -> None:
    result = rb_textcheck.check(case["text"], _profile(case.get("profile")), case["format"]).as_dict()
    scope = case.get("rules")
    issues = [i for i in result["issues"] if not scope or i["rule"] in scope]
    expect = case["expect"]

    assert issues == expect["issues"]
    assert result["gate_failed"] is expect["gate_failed"]
    assert result["humanizer"] == expect["humanizer"]


def test_every_rule_is_covered_by_the_corpus() -> None:
    """Каждое правило из `textcheck rules` встречается в ожиданиях корпуса хотя бы раз."""
    seen = {i["rule"] for p in CASES for i in p.values[0]["expect"]["issues"]}
    assert {r["id"] for r in rb_textcheck.rules()} == seen


# --- fix (T78 A) ------------------------------------------------------------------


def _fix_cases() -> list:
    path = VECTORS / "fix" / "cases.yaml"
    return [pytest.param(c, id=f"fix:{c['id']}") for c in yaml.safe_load(path.read_text(encoding="utf-8"))]


FIX_CASES = _fix_cases()


def test_fix_corpus_is_not_empty() -> None:
    assert len(FIX_CASES) >= 15


@pytest.mark.parametrize("case", FIX_CASES)
def test_fix_vector(case: dict) -> None:
    result = rb_textcheck.fix(case["text"], _profile(case.get("profile")), case["format"]).as_dict()
    expect = case["expect"]

    assert result["text"] == expect["text"]
    assert result["unchanged"] is expect["unchanged"]
    assert [(a["name"], a["count"]) for a in result["applied"]] == [(a["name"], a["count"]) for a in expect["applied"]]
    for got, want in zip(result["applied"], expect["applied"], strict=True):
        assert len(got["addresses"]) == len(want["addresses"])
        for address, expected in zip(got["addresses"], want["addresses"], strict=True):
            assert expected.items() <= address.items()


# --- invalid profiles: what the refusal names (T78 B) --------------------------------


INVALID_EXPECT = yaml.safe_load((VECTORS / "profiles-invalid" / "expect.yaml").read_text(encoding="utf-8"))


def test_every_invalid_profile_has_an_expectation() -> None:
    files = {p.name for p in (VECTORS / "profiles-invalid").glob("*.quality.yml")}
    assert files == set(INVALID_EXPECT)


@pytest.mark.parametrize("name", sorted(INVALID_EXPECT))
def test_invalid_profile_message(name: str) -> None:
    with pytest.raises(rb_textcheck.ProfileError) as error:
        rb_textcheck.load_profile(VECTORS / "profiles-invalid" / name)
    assert INVALID_EXPECT[name] in str(error.value)
