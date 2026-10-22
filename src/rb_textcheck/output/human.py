"""Human-readable output (messages, key-value lists, the doctor report), kept apart from the JSON output."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markup import escape

# Data goes to stdout; errors and diagnostics go to stderr, so
# `<cli> status > out.txt` never captures an "Error: ..." line as data.
console = Console()
err_console = Console(stderr=True)


def echo(message: str) -> None:
    """Print plain text. Escaped: rich would otherwise treat `[...]` in data as markup and drop it."""
    console.print(escape(message))


def echo_markup(message: str) -> None:
    """Print rich markup (`[green]✓[/green]`); escape() any data you put inside it."""
    console.print(message)


def key_values(title: str, pairs: dict) -> None:
    console.print(f"[bold]{escape(title)}[/bold]")
    for key, value in pairs.items():
        console.print(f"  {escape(str(key))}: {escape(str(value))}")


def render_doctor(checks: list[dict]) -> None:
    for check in checks:
        mark = "[green]✓[/green]" if check["ok"] else "[red]✗[/red]"
        detail = f" ({check['detail']})" if check.get("detail") else ""
        console.print(f"{mark} {escape(check['name'] + detail)}")


def render_check(report: dict) -> None:
    """`check`: one line per finding (blocking ones marked), then humanizer and the gate."""
    for issue in report["issues"]:
        mark = "[red]✗[/red]" if issue["gate"] else "[yellow]•[/yellow]"
        where = f" [dim]block {issue['address']['block']}[/dim]" if issue["address"] else ""
        excerpt = f": «{escape(issue['excerpt'])}»" if issue["excerpt"] else ""
        console.print(f"{mark} [bold]{escape(issue['rule'])}[/bold]{where} {escape(issue['message'])}{excerpt}")
    humanizer = report["humanizer"]
    if humanizer is not None:
        console.print(f"humanizer: {humanizer['verdict']} (score {humanizer['score']})")
    console.print("[red]gate failed[/red]" if report["gate_failed"] else "[green]gate passed[/green]")


def render_rules(data: dict) -> None:
    for rule in data["rules"]:
        console.print(
            f"[bold]{escape(rule['id'])}[/bold] [dim]({', '.join(rule['formats'])})[/dim] {escape(rule['description'])}"
        )


def write_text(text: str) -> None:
    """Text as data, byte for byte: no rich markup, no added newline."""
    sys.stdout.write(text)
    sys.stdout.flush()


def render_fix(report: dict) -> None:
    """`fix` summary on stderr (the text itself is written by the command): replacements, check report."""
    applied = ", ".join(f"{a['name']} ×{a['count']}" for a in report["applied"]) or "no replacements"
    err_console.print(f"fix: {escape(applied)}")
    if "issues" in report:
        for issue in report["issues"]:
            mark = "✗" if issue["gate"] else "•"
            err_console.print(f"{mark} {escape(issue['rule'])}: {escape(issue['message'])}")
        err_console.print("gate failed" if report["gate_failed"] else "gate passed")
