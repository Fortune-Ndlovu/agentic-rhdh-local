"""CLI entry point for agentic-rhdh-local."""

from pathlib import Path

import typer

from .ui.app import run_app, run_reset

app = typer.Typer(
    name="agentic-rhdh",
    help="Multi-agent CLI for automated RHDH onboarding",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--project-dir", "-p",
        help="Path to the agentic-rhdh-local project directory",
    ),
) -> None:
    """Scan repos, propose plugins and catalog entities, configure RHDH automatically."""
    if ctx.invoked_subcommand is None:
        run_app(project_root=project_dir)


@app.command()
def reset(
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--project-dir", "-p",
        help="Path to the agentic-rhdh-local project directory",
    ),
    yes: bool = typer.Option(
        False,
        "--yes", "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Reset RHDH to baseline by removing all agent-generated files."""
    run_reset(project_root=project_dir, skip_confirm=yes)


if __name__ == "__main__":
    app()
