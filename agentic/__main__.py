"""CLI entry point for agentic-rhdh-local."""

from pathlib import Path

import typer

from .ui.app import run_app

app = typer.Typer(
    name="agentic-rhdh",
    help="Multi-agent CLI for automated RHDH onboarding",
    no_args_is_help=False,
)


@app.command()
def main(
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--project-dir", "-p",
        help="Path to the agentic-rhdh-local project directory",
    ),
) -> None:
    """Scan repos, propose plugins and catalog entities, configure RHDH automatically."""
    run_app(project_root=project_dir)


if __name__ == "__main__":
    app()
