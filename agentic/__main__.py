"""CLI entry point for agentic-rhdh-local."""

import shutil
from pathlib import Path

import typer
from rich.console import Console

from .ui.app import run_app

app = typer.Typer(
    name="agentic-rhdh",
    help="Multi-agent CLI for automated RHDH onboarding",
    no_args_is_help=False,
    invoke_without_command=True,
)

console = Console()

KEEP_FILES = {
    "users.yaml",
    "users.override.yaml",
    "users.override.example.yaml",
    "components.override.example.yaml",
    "dynamic-plugins.yaml",
    "dynamic-plugins.override.example.yaml",
    "app-config.yaml",
    "app-config.local.example.yaml",
}


@app.callback()
def main(
    ctx: typer.Context,
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--project-dir", "-p",
        help="Path to the agentic-rhdh-local project directory",
    ),
) -> None:
    """Multi-agent CLI for automated RHDH onboarding."""
    ctx.ensure_object(dict)
    ctx.obj["project_dir"] = project_dir
    if ctx.invoked_subcommand is None:
        run_app(project_root=project_dir)


@app.command()
def reset(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Remove all generated entities, plugin overrides, and backups for a fresh start."""
    project_dir: Path = ctx.obj["project_dir"]
    catalog_dir = project_dir / "configs" / "catalog-entities"
    plugins_dir = project_dir / "configs" / "dynamic-plugins"
    appconfig_dir = project_dir / "configs" / "app-config"

    to_delete: list[Path] = []

    # Catalog entities: *-component.yaml, *-docs/ dirs, components.override.yaml, *.bak
    if catalog_dir.exists():
        for item in catalog_dir.iterdir():
            if item.name in KEEP_FILES:
                continue
            if item.name.endswith("-component.yaml"):
                to_delete.append(item)
            elif item.name.endswith("-docs") and item.is_dir():
                to_delete.append(item)
            elif item.name == "components.override.yaml":
                to_delete.append(item)
            elif item.name.endswith(".bak"):
                to_delete.append(item)

    # Plugin overrides: dynamic-plugins.override.yaml, *.bak
    if plugins_dir.exists():
        for item in plugins_dir.iterdir():
            if item.name in KEEP_FILES:
                continue
            if item.name == "dynamic-plugins.override.yaml":
                to_delete.append(item)
            elif item.name.endswith(".bak"):
                to_delete.append(item)

    # App config: agent-generated app-config.local.yaml, *.bak
    if appconfig_dir.exists():
        for item in appconfig_dir.iterdir():
            if item.name in KEEP_FILES:
                continue
            if item.name == "app-config.local.yaml":
                to_delete.append(item)
            elif item.name.endswith(".bak"):
                to_delete.append(item)

    if not to_delete:
        console.print("[green]Nothing to reset — no generated files found.[/green]")
        raise typer.Exit()

    console.print("[bold]Files to remove:[/bold]")
    for p in sorted(to_delete):
        rel = p.relative_to(project_dir)
        icon = "dir " if p.is_dir() else "file"
        console.print(f"  {icon}  {rel}")

    if not yes:
        typer.confirm(f"\nDelete {len(to_delete)} items?", abort=True)

    for p in to_delete:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    # Restore components.override.yaml as an empty Location entity so the
    # catalog location reference in app-config.yaml doesn't break RHDH
    components_override = catalog_dir / "components.override.yaml"
    if not components_override.exists():
        components_override.write_text(
            "apiVersion: backstage.io/v1alpha1\n"
            "kind: Location\n"
            "metadata:\n"
            "  name: rhdh-onboarded-components\n"
            "  description: Auto-generated catalog entities for onboarded repositories\n"
            "spec:\n"
            "  targets: []\n"
        )

    console.print(f"[green]Removed {len(to_delete)} generated files. Ready for a fresh run.[/green]")


if __name__ == "__main__":
    app()
