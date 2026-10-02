"""CLI: textcheck check | profile validate | rules — JSON и коды выхода (0 гейт пройден, 1 нет, 2 аргументы)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rb_textcheck.cli import app

runner = CliRunner()
VECTORS = Path(__file__).resolve().parents[1] / "vectors"
LOGISTICS = VECTORS / "profiles" / "content-logistics.quality.yml"
CLEAN = "<h2>Раздел</h2><p>Мы подбираем поставщика и готовим документы под конкретную задачу.</p>"
BROKEN = "<h2>Раздел</h2><p>Мы лидер рынка — работаем под ключ.</p>"


def run(*args: str, stdin: str | None = None):
    return runner.invoke(app, list(args), input=stdin)


def run_json(*args: str, stdin: str | None = None) -> tuple[int, dict]:
    result = run(*args, "--json", stdin=stdin)
    assert result.stdout.strip(), result.stderr
    return result.exit_code, json.loads(result.stdout)


def test_check_clean_text_exits_0(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(CLEAN, encoding="utf-8")
    code, data = run_json("check", str(path))
    assert code == 0
    assert data["ok"] is True
    assert data["gate_failed"] is False
    assert set(data) >= {"ok", "issues", "humanizer", "gate_failed"}


def test_check_gate_failure_exits_1_with_full_report(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(BROKEN, encoding="utf-8")
    code, data = run_json("check", str(path), "--profile", str(LOGISTICS))
    assert code == 1
    assert data["ok"] is False
    assert data["gate_failed"] is True
    assert data["error"]["code"] == "QUALITY_GATE_FAILED"
    issue = next(i for i in data["issues"] if i["rule"] == "cliche")
    assert set(issue) == {"rule", "message", "excerpt", "gate", "unit", "address", "action"}
    assert issue["action"] == "rewrite_block"
    assert issue["address"]["block"] == 1
    assert data["humanizer"]["verdict"] in {"clean", "review", "rewrite"}


def test_check_reads_stdin() -> None:
    code, data = run_json("check", "-", "--format", "html", stdin=BROKEN)
    assert code == 1
    assert any(i["rule"] == "humanizer" for i in data["issues"])


def test_check_format_from_extension(tmp_path: Path) -> None:
    """.md читается как markdown: HTML-тег в нём — нарушение формата."""
    path = tmp_path / "a.md"
    path.write_text("Абзац.\n\n<p>Тег.</p>", encoding="utf-8")
    _, data = run_json("check", str(path))
    assert [i["message"] for i in data["issues"] if i["rule"] == "format"] == ["Ждали markdown, а в тексте HTML-теги"]


def test_check_human_output(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(BROKEN, encoding="utf-8")
    result = run("check", str(path))
    assert result.exit_code == 1
    assert "humanizer" in result.stdout


def test_check_missing_file_exits_2(tmp_path: Path) -> None:
    code, data = run_json("check", str(tmp_path / "nope.html"))
    assert code == 2
    assert data["error"]["code"] == "INVALID_ARGUMENTS"


def test_check_broken_profile_exits_2(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(CLEAN, encoding="utf-8")
    bad = VECTORS / "profiles-invalid" / "bad-regex.quality.yml"
    code, data = run_json("check", str(path), "--profile", str(bad))
    assert code == 2
    assert data["error"]["code"] == "INVALID_PROFILE"


def test_check_bad_format_exits_2(tmp_path: Path) -> None:
    path = tmp_path / "a.html"
    path.write_text(CLEAN, encoding="utf-8")
    assert run("check", str(path), "--format", "docx").exit_code == 2


def test_profile_validate_ok() -> None:
    code, data = run_json("profile", "validate", str(LOGISTICS))
    assert code == 0
    assert data["ok"] is True
    assert data["profile"] == str(LOGISTICS)
    assert len(data["fingerprint"]) == 8


def test_profile_validate_invalid_exits_2() -> None:
    for path in sorted((VECTORS / "profiles-invalid").glob("*.quality.yml")):
        code, data = run_json("profile", "validate", str(path))
        assert code == 2, path.name
        assert data["error"]["code"] == "INVALID_PROFILE", path.name


def test_rules_lists_every_rule_with_description() -> None:
    code, data = run_json("rules")
    assert code == 0
    ids = [r["id"] for r in data["rules"]]
    assert ids == [
        "format",
        "tags",
        "markup",
        "length",
        "headings",
        "cliche",
        "forbid",
        "language",
        "corruption",
        "placeholder",
        "self_reference",
        "truncation",
        "humanizer",
    ]
    assert all(r["description"] and r["formats"] for r in data["rules"])


def test_rules_human() -> None:
    result = run("rules")
    assert result.exit_code == 0
    assert "truncation" in result.stdout
