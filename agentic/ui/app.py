"""Main CLI application — Rich-based interactive TUI for RHDH onboarding."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich import box

from ..agents.client import create_client
from ..agents.prompts import build_unified_system
from ..agents.session import run_agent_loop
from ..agents.tools import ALL_TOOLS
from ..knowledge import PluginKnowledgeBase, extract_catalog_index
from ..models import CatalogEntityProposal, OnboardingState, PluginProposal

console = Console()


def show_banner() -> None:
    banner = Text()
    banner.append("Agentic RHDH Local", style="bold cyan")
    banner.append(" — Smart Onboarding", style="dim")
    console.print(Panel(banner, box=box.DOUBLE, padding=(1, 2)))


def collect_repos() -> list[str]:
    """Prompt user to enter GitHub repo URLs."""
    console.print("\n[bold]Add your team's repositories:[/bold]")
    console.print("[dim]Enter GitHub URLs one per line. Press Enter on empty line to finish.[/dim]\n")

    repos: list[str] = []
    while True:
        try:
            url = Prompt.ask("  [cyan]>[/cyan]", default="").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not url:
            if repos:
                break
            console.print("  [yellow]Add at least one repository[/yellow]")
            continue

        if not _validate_repo_url(url):
            console.print(f"  [red]Invalid GitHub URL: {url}[/red]")
            continue

        repos.append(url)
        console.print(f"  [green]✓[/green] {url}")

    return repos


def _validate_repo_url(url: str) -> bool:
    return bool(re.match(r"https?://github\.com/[\w.-]+/[\w.-]+/?$", url))


def _on_event(event_type: str, event_data: dict[str, Any]) -> None:
    """Handle events from the agent loop for progress display."""
    if event_type == "tool_use":
        tool = event_data.get("tool", "")
        tool_input = event_data.get("input", {})
        if tool == "scan_repo_tree":
            console.print(f"  [dim]├── Scanning {tool_input.get('owner', '')}/{tool_input.get('repo', '')}...[/dim]")
        elif tool == "read_repo_file":
            console.print(f"  [dim]│   Reading {tool_input.get('path', '')}...[/dim]")
        elif tool == "get_repo_languages":
            console.print(f"  [dim]│   Checking languages...[/dim]")
        elif tool == "write_yaml":
            console.print(f"  [dim]├── Writing {tool_input.get('path', '')}...[/dim]")
        elif tool == "restart_rhdh":
            console.print(f"  [dim]├── Restarting RHDH...[/dim]")
        elif tool == "check_rhdh_health":
            console.print(f"  [dim]├── Checking health...[/dim]")
        elif tool == "diagnose_plugin_errors":
            console.print(f"  [dim]├── Diagnosing errors...[/dim]")
    elif event_type == "tool_result":
        tool = event_data.get("tool", "")
        result = event_data.get("result", {})
        if tool == "scan_repo_tree":
            console.print(f"  [dim]│   Found {result.get('count', 0)} files[/dim]")
        elif tool == "check_rhdh_health":
            if result.get("healthy"):
                console.print(f"  [green]├── Health check passed ✓[/green]")
            else:
                console.print(f"  [yellow]├── Health check: {result.get('message', 'unhealthy')}[/yellow]")
        elif tool == "write_yaml":
            if result.get("success"):
                console.print(f"  [green]│   ✓[/green]")


def show_plugin_proposals(proposals: list[PluginProposal]) -> None:
    """Display proposed plugins in a table."""
    if not proposals:
        console.print("\n[yellow]No plugins to propose.[/yellow]")
        return

    console.print(f"\n[bold]Proposed Plugins ({len(proposals)}):[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("#", style="dim", width=3)
    table.add_column("Plugin", style="bold")
    table.add_column("Confidence", width=10)
    table.add_column("Category", width=14)
    table.add_column("Reason")

    for i, p in enumerate(proposals, 1):
        conf_style = {"high": "green", "medium": "yellow", "low": "red"}.get(p.confidence.value, "white")
        marker = "✓" if p.accepted else "○"
        table.add_row(
            f"[{'green' if p.accepted else 'dim'}]{marker}[/]",
            p.title or p.plugin,
            f"[{conf_style}]{p.confidence.value}[/]",
            p.category,
            p.reason,
        )

    console.print(table)


def show_entity_proposals(proposals: list[CatalogEntityProposal]) -> None:
    """Display proposed catalog entities in a table."""
    if not proposals:
        return

    console.print(f"\n[bold]Proposed Catalog Entities ({len(proposals)}):[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("Entity", style="bold")
    table.add_column("Type", width=10)
    table.add_column("Source Repo")

    for p in proposals:
        table.add_row(p.name, p.component_type.value, p.source_repo)

    console.print(table)


def prompt_review(
    plugin_proposals: list[PluginProposal],
    entity_proposals: list[CatalogEntityProposal],
) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Let user accept, edit, or reject proposals."""
    console.print()
    choice = Prompt.ask(
        "[bold]  [a] Accept all  [e] Edit selections  [r] Reject all[/bold]",
        choices=["a", "e", "r"],
        default="a",
    )

    if choice == "r":
        for p in plugin_proposals:
            p.accepted = False
        for e in entity_proposals:
            e.accepted = False
        return plugin_proposals, entity_proposals

    if choice == "a":
        return plugin_proposals, entity_proposals

    console.print("\n[dim]Toggle plugins (enter numbers to toggle, 'done' to finish):[/dim]")
    while True:
        for i, p in enumerate(plugin_proposals, 1):
            marker = "[green]✓[/green]" if p.accepted else "[dim]○[/dim]"
            console.print(f"  {marker} {i}. {p.title or p.plugin}")

        inp = Prompt.ask("  Toggle #", default="done").strip()
        if inp.lower() == "done":
            break
        try:
            idx = int(inp) - 1
            if 0 <= idx < len(plugin_proposals):
                plugin_proposals[idx].accepted = not plugin_proposals[idx].accepted
        except ValueError:
            continue

    return plugin_proposals, entity_proposals


def show_completion(
    plugin_count: int,
    entity_count: int,
    env_vars: list[str],
    base_url: str = "http://localhost:7007",
) -> None:
    """Show final completion summary."""
    console.print()
    console.print(Panel(
        f"[bold green]RHDH is ready at {base_url}[/bold green]\n"
        f"{plugin_count} plugins enabled, {entity_count} catalog entities added",
        box=box.ROUNDED,
    ))

    if env_vars:
        console.print("\n[yellow]Required: Set these env vars in .env for full functionality:[/yellow]")
        for var in sorted(set(env_vars)):
            console.print(f"  [dim]- {var}[/dim]")


def parse_proposals_from_response(content: list[dict[str, Any]]) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Extract structured proposals from agent response content blocks."""
    plugin_proposals: list[PluginProposal] = []
    entity_proposals: list[CatalogEntityProposal] = []

    for block in content:
        if block.get("type") != "text":
            continue
        text = block.get("text", "")

        json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if not json_blocks:
            json_blocks = re.findall(r"(\[[\s\S]*?\])", text)

        for jblock in json_blocks:
            try:
                data = json.loads(jblock)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if "plugin" in item and ("packages" in item or "plugin_config" in item):
                        plugin_proposals.append(PluginProposal(**item))
                    elif "component_type" in item or ("source_repo" in item and "name" in item):
                        entity_proposals.append(CatalogEntityProposal(**item))
            except (json.JSONDecodeError, Exception):
                continue

    return plugin_proposals, entity_proposals


def run_app(project_root: Path | None = None) -> None:
    """Main application entry point."""
    if project_root is None:
        project_root = Path.cwd()

    show_banner()

    # Step 1: Collect repos
    repos = collect_repos()
    if not repos:
        console.print("[yellow]No repositories added. Exiting.[/yellow]")
        return

    state = OnboardingState(repos=repos)

    # Step 2: Extract knowledge base
    with console.status("[bold]Preparing plugin knowledge base..."):
        try:
            extract_dir = extract_catalog_index()
            kb = PluginKnowledgeBase.build(extract_dir)
            console.print(f"[green]✓[/green] Loaded {len(kb.plugins)} plugins from catalog index")
        except Exception as e:
            console.print(f"[red]Failed to load knowledge base: {e}[/red]")
            return

    # Step 3: Create client
    try:
        client = create_client()
        console.print("[green]✓[/green] Claude client ready")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return

    # Step 4: Build system prompt with knowledge context
    knowledge_context = kb.to_agent_context()
    system_prompt = build_unified_system(knowledge_context)

    # Step 5: Scan + Propose
    console.print("\n[bold]Scanning repositories...[/bold]")
    repo_list = "\n".join(f"- {url}" for url in repos)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Scan these repositories and propose plugins and catalog entities:\n{repo_list}"},
    ]

    try:
        response_content = run_agent_loop(
            client=client,
            system=system_prompt,
            tools=ALL_TOOLS,
            messages=messages,
            project_root=project_root,
            on_event=_on_event,
        )
    except Exception as e:
        console.print(f"\n[red]Agent failed: {e}[/red]")
        return

    # Step 6: Parse and display proposals
    plugin_proposals, entity_proposals = parse_proposals_from_response(response_content)

    if not plugin_proposals and not entity_proposals:
        console.print("\n[yellow]Agent didn't return structured proposals. Raw output:[/yellow]")
        for block in response_content:
            if block.get("type") == "text":
                console.print(f"  {block.get('text', '')[:500]}")
        return

    show_plugin_proposals(plugin_proposals)
    show_entity_proposals(entity_proposals)

    # Step 7: Review
    plugin_proposals, entity_proposals = prompt_review(plugin_proposals, entity_proposals)

    accepted_plugins = [p for p in plugin_proposals if p.accepted]
    accepted_entities = [e for e in entity_proposals if e.accepted]

    if not accepted_plugins and not accepted_entities:
        console.print("[yellow]Nothing to apply. Exiting.[/yellow]")
        return

    # Step 8: Apply
    console.print("\n[bold]Applying configuration...[/bold]")
    apply_msg = (
        "Apply these approved proposals. Write the config files, restart RHDH, and verify health.\n\n"
        f"Plugins:\n```json\n{json.dumps([p.model_dump() for p in accepted_plugins], indent=2, default=str)}\n```\n\n"
        f"Entities:\n```json\n{json.dumps([e.model_dump() for e in accepted_entities], indent=2, default=str)}\n```"
    )
    messages.append({"role": "user", "content": apply_msg})

    try:
        run_agent_loop(
            client=client,
            system=system_prompt,
            tools=ALL_TOOLS,
            messages=messages,
            project_root=project_root,
            on_event=_on_event,
        )
    except Exception as e:
        console.print(f"\n[red]Apply phase failed: {e}[/red]")
        return

    # Step 9: Report
    all_env_vars = []
    for p in accepted_plugins:
        all_env_vars.extend(p.required_env_vars)

    show_completion(
        plugin_count=len(accepted_plugins),
        entity_count=len(accepted_entities),
        env_vars=all_env_vars,
    )
