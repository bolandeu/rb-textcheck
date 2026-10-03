from __future__ import annotations

import sys
from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def fix(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Text file to fix, or '-' for stdin."),
    profile: Path | None = typer.Option(
        None, "--profile", help="Quality profile (quality.yml) with a `fixes` section. Without fixes: text unchanged."
    ),
    text_format: str | None = typer.Option(
        None, "--format", help="html or md. Default: md for .md/.markdown files, html otherwise (and for stdin)."
    ),
    then_check: bool = typer.Option(
        False, "--check", help="Run check on the fixed text and exit with its code (0 gate passed, 1 failed)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Apply the profile's mechanical replacements (fixes) and print the fixed text.

    Deterministic, no LLM: what to replace with what is in the profile, in
    its order. Only the text a reader sees changes — HTML text nodes (tags,
    attributes and block order stay byte for byte), md outside code; code,
    pre, script, style, md code, link targets and bare URLs are never touched.
    Default output: the fixed text on stdout, a summary on stderr. --json:
    {ok, text, applied[{name, count, addresses}], unchanged}; with --check
    also check's {issues, humanizer, gate_failed} and its exit code.
    Exit 2: bad arguments or profile (INVALID_PROFILE) — no text is printed.

    Example: {cli} fix article.html --profile typography.quality.yml --check --json
    """
    text = sys.stdin.read() if source == "-" else services.read_text(Path(source))
    payload, problem = services.run_fix(text, profile, services.text_format(source, text_format), then_check=then_check)
    if not ctx.obj.get("json"):
        output.human.write_text(payload["text"])  # the text is the data: printed even with --quiet
    output.emit_report(ctx, payload, render_human=output.human.render_fix, problem=problem)
