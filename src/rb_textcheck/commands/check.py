from __future__ import annotations

import sys
from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def check(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Text file to check, or '-' for stdin."),
    profile: Path | None = typer.Option(
        None, "--profile", help="Quality profile (quality.yml). Without it: built-in defaults only."
    ),
    text_format: str | None = typer.Option(
        None, "--format", help="html or md. Default: md for .md/.markdown files, html otherwise (and for stdin)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Check a text against a quality profile: findings, humanizer verdict, gate.

    Deterministic, no network and no LLM. Every finding has rule, message,
    excerpt, gate, unit, address and action; `textcheck rules` lists the rules.
    Exit 0: the gate passed (findings with gate=false are for information).
    Exit 1: findings with gate=true — the report is still emitted (ok=false,
    error QUALITY_GATE_FAILED). Exit 2: bad arguments or profile.

    Example: {cli} check article.html --profile content-logistics.quality.yml --json
    """
    text = sys.stdin.read() if source == "-" else services.read_text(Path(source))
    result, problem = services.run_check(text, profile, services.text_format(source, text_format))
    output.emit_report(ctx, result, render_human=output.human.render_check, problem=problem)
