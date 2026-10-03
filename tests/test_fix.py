"""textcheck fix (T78 A): механические автозамены по профилю, без LLM. Сценарии X1-X9."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from typer.testing import CliRunner

import rb_textcheck
from rb_textcheck.cli import app
from rb_textcheck.core.text_blocks import parse_blocks

runner = CliRunner()
VECTORS = Path(__file__).resolve().parents[1] / "vectors"
TYPO = VECTORS / "profiles" / "fix-typography.quality.yml"
DASHES = "".join(f"<p>Абзац {i} — с тире — внутри.</p>" for i in range(15))  # 30 тире в 15 блоках


def _skeleton(html: str) -> list[tuple[str, tuple]]:
    """Разметка без текста: теги, атрибуты и порядок - то, что fix менять не вправе."""
    soup = BeautifulSoup(html, "html.parser")
    return [(tag.name, tuple(sorted((k, str(v)) for k, v in tag.attrs.items()))) for tag in soup.find_all(True)]


def _matches(issue: dict, fixes_rule: str) -> bool:
    """fixes_rule = '<rule id>' или '<rule id>: <текст в сообщении>'."""
    rule, _, detail = fixes_rule.partition(":")
    return issue["rule"] == rule.strip() and detail.strip() in issue["message"]


def run(*args: str, stdin: str | None = None):
    return runner.invoke(app, list(args), input=stdin)


# X1


def test_x1_dashes_replaced_with_addresses_markup_intact() -> None:
    result = rb_textcheck.fix(DASHES, TYPO, "html")
    assert result.text.count("—") == 0
    assert [(a.name, a.count) for a in result.applied] == [("длинное тире", 30)]
    assert [a["block"] for a in result.applied[0].addresses] == list(range(15))
    assert _skeleton(result.text) == _skeleton(DASHES)


def test_x1_addresses_point_at_blocks_of_the_fixed_text() -> None:
    result = rb_textcheck.fix(DASHES, TYPO, "html")
    blocks = parse_blocks(result.text)
    for address in result.applied[0].addresses:
        assert blocks[address["block"]].anchor == address["anchor"]


# X2


def test_x2_check_after_fix_has_no_fixed_rule() -> None:
    profile = rb_textcheck.load_profile(TYPO)
    before = rb_textcheck.check(DASHES, profile, "html").as_dict()["issues"]
    after = rb_textcheck.check(rb_textcheck.fix(DASHES, profile, "html").text, profile, "html").as_dict()["issues"]
    for rule in {f.fixes_rule for f in profile.fixes if f.fixes_rule}:
        assert any(_matches(i, rule) for i in before), rule
        assert not any(_matches(i, rule) for i in after), rule


# X3


@pytest.mark.parametrize("fmt,text", [("html", DASHES), ("md", "Текст — с тире.\n\n- пункт – списка\n")])
def test_x3_fix_is_idempotent(fmt: str, text: str) -> None:
    once = rb_textcheck.fix(text, TYPO, fmt)
    twice = rb_textcheck.fix(once.text, TYPO, fmt)
    assert once.unchanged is False
    assert twice.text == once.text
    assert twice.unchanged is True
    assert twice.applied == []


# X5


@pytest.mark.parametrize("name", ["fix-bad-regex", "fix-empty-from", "fix-bad-group"])
def test_x5_bad_fix_exits_2_without_text(tmp_path: Path, name: str) -> None:
    path = tmp_path / "a.html"
    path.write_text(DASHES, encoding="utf-8")
    profile = str(VECTORS / "profiles-invalid" / f"{name}.quality.yml")
    result = run("fix", str(path), "--profile", profile, "--json")
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "INVALID_PROFILE"
    assert "text" not in data
    human = run("fix", str(path), "--profile", profile)
    assert human.exit_code == 2
    assert human.stdout == ""


# X6


def test_x6_without_fixes_text_is_unchanged_exit_0(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(DASHES, encoding="utf-8")
    result = run("fix", str(path))
    assert result.exit_code == 0
    assert result.stdout == DASHES
    code = run("fix", str(path), "--profile", str(VECTORS / "profiles" / "content-write.quality.yml"), "--json")
    assert code.exit_code == 0
    assert json.loads(code.stdout) == {"ok": True, "text": DASHES, "applied": [], "unchanged": True}


# X8


def test_x8_deterministic() -> None:
    texts = {rb_textcheck.fix(DASHES, TYPO, "html").text for _ in range(5)}
    assert len(texts) == 1


# X9 + CLI shape


def test_x9_check_keeps_other_findings_and_returns_check_code() -> None:
    text = "<h1>Заголовок</h1><p>Мы лидер рынка — работаем под ключ.</p>"
    profile = VECTORS / "profiles" / "fix-child.quality.yml"
    result = run("fix", "-", "--format", "html", "--profile", str(profile), "--check", "--json", stdin=text)
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "QUALITY_GATE_FAILED"
    assert data["text"] == "<h1>Заголовок</h1><p>Мы лидер рынка - работаем под ключ.</p>"
    assert [a["name"] for a in data["applied"]] == ["длинное тире"]
    assert data["gate_failed"] is True
    assert any(i["rule"] == "tags" for i in data["issues"])
    assert not any(_matches(i, "humanizer: 23 длинное тире") for i in data["issues"])


def test_fix_check_passes_with_exit_0() -> None:
    result = run("fix", "-", "--profile", str(TYPO), "--check", "--json", stdin="<p>Обычный текст — без проблем.</p>")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["gate_failed"] is False
    assert set(data) == {"ok", "text", "applied", "unchanged", "issues", "humanizer", "gate_failed"}


def test_fix_human_prints_only_text_to_stdout(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("Текст — с тире.\n", encoding="utf-8")
    result = run("fix", str(path), "--profile", str(TYPO))
    assert result.exit_code == 0
    assert result.stdout == "Текст - с тире.\n"
    assert re.search(r"длинное тире", result.stderr)


def test_fix_human_check_failure(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text("<h1>З</h1><p>Текст — с тире.</p>", encoding="utf-8")
    result = run("fix", str(path), "--profile", str(TYPO), "--check")
    assert result.exit_code == 1
    assert result.stdout == "<h1>З</h1><p>Текст - с тире.</p>"
    assert "tags" in result.stderr


def test_fix_meta_profile_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(DASHES, encoding="utf-8")
    result = run("fix", str(path), "--profile", str(VECTORS / "profiles" / "seo-meta.quality.yml"), "--json")
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_PROFILE"
