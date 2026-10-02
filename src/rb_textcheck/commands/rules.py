from __future__ import annotations

import typer

from .. import output
from .. import rules as all_rules


@output.guard
def rules(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
) -> None:
    """List the check rules: id (the `rule` of a finding), formats, description.

    Example: {cli} rules --json
    """
    output.emit_success(ctx, {"rules": all_rules()}, render_human=output.human.render_rules)
