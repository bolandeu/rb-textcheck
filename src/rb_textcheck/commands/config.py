from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..core.models import ProjectConfig

app = output.group("Manage project configuration.")


@app.command("list")
@output.guard
def list_config(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """List all configuration values.

    Example: {cli} config list --json
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    config = services.load_config(root)
    data = config.model_dump()
    output.emit_success(ctx, data, render_human=lambda d: output.human.key_values("Config", d))


@app.command("get")
@output.guard
def get_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Dotted config key, e.g. cli.min_version (see `config list`)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Get a single configuration value.

    Example: {cli} config get cli.min_version
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    value: object = services.load_config(root).model_dump()
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise InvalidArguments(f"Unknown config key '{key}'.")
        value = value[part]
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"{d['key']} = {d['value']}")
    )


@app.command("set")
@output.guard
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Dotted config key, e.g. cli.min_version (see `config list`)."),
    value: str = typer.Argument(..., help="New value (stored as a string)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Set a single, non-secret configuration value.

    Example: {cli} config set cli.min_version 0.2.0
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    data = services.load_config(root).model_dump()
    parts = key.split(".")
    target = data
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise InvalidArguments(f"Unknown config key '{key}'.")
        target = target[part]
    if not isinstance(target, dict) or parts[-1] not in target:
        raise InvalidArguments(f"Unknown config key '{key}'.")
    target[parts[-1]] = value
    services.save_config(root, ProjectConfig.model_validate(data))
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"Set {d['key']} = {d['value']}")
    )
