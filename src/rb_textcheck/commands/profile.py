from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services

app = output.group("Quality profiles (quality.yml).")


@app.command("validate")
@output.guard
def validate(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Quality profile file (quality.yml)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Validate a quality profile against the bundled JSON Schema and compile its regexes.

    Follows `extends` (each base is validated too; a cycle is an error). Any
    unknown key, at any level, is an error. Both kinds validate: article
    (check/fix) and meta (antagor seo-meta). Exit 0: valid — prints kind and
    fingerprint (first 8 hex of sha1 of the profile and its bases). Exit 2:
    INVALID_PROFILE with the path to the key and what is wrong.

    Example: {cli} profile validate content-logistics.quality.yml --json
    """
    output.emit_success(
        ctx,
        services.validate_profile(path),
        render_human=lambda d: output.human.echo(f"{d['profile']}: ok, kind {d['kind']} ({d['fingerprint']})"),
    )
