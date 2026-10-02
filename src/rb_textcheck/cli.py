from __future__ import annotations

from importlib import resources

import typer

from . import output
from .commands import auth, describe, doctor, init, run, skill, status
from .commands import config as config_cmd
from .core.version import DEV_VERSION, cli_name, installed_version, package_summary

_PACKAGE_NAME = __name__.split(".")[0]

# A bare `<cli>` is the discovery entry point for humans and agents alike:
# name + version + description, then every command with the first line of
# its docstring. No `no_args_is_help` (that exits 2) — main_options() below
# prints this and exits 0. Shell completion stays enabled.
app = typer.Typer(
    help=f"{cli_name()} {installed_version() or DEV_VERSION} — {package_summary() or 'project-aware automation CLI'}"
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(auth.app, name="auth")  # `auth status` in every CLI; login/logout only with credentials
app.add_typer(skill.app, name="skill")

app.command(name="init")(init.init)
app.command(name="status")(status.status)
app.command(name="doctor")(doctor.doctor)
app.command(name="run")(run.run)
app.command(name="describe")(describe.describe)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(installed_version() or DEV_VERSION)
    raise typer.Exit()


def _ai_callback(value: bool) -> None:
    """Print the bundled agent skill doc to stdout.

    For agents that can execute this CLI but cannot read files from disk
    (e.g. a sandboxed shell with no access to a SKILL.md on the filesystem),
    this is the fallback way to get full usage guidance.
    """
    if not value:
        return
    content = resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text()
    typer.echo(content)
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_options(
    ctx: typer.Context,
    project: str = typer.Option(None, "--project", help="Path to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-essential output."),
    verbose: bool = typer.Option(False, "--verbose", help="Emit extra diagnostic output."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Never prompt; fail instead."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show the version and exit."
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        callback=_ai_callback,
        is_eager=True,
        help="Print AI-oriented usage documentation (the bundled skill doc) and exit.",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["json"] = json_output
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["non_interactive"] = non_interactive
    ctx.obj["dry_run"] = dry_run
    output.configure_logging(verbose)
    output.help_if_no_command(ctx)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
