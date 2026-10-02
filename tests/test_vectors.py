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
