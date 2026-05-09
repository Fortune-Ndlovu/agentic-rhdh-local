"""Main CLI application — Rich-based interactive TUI for RHDH onboarding."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich import box

from ..agents.session import SessionContext, create_session, run_session_loop, send_user_message
from ..agents.setup import create_agents
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


def show_scan_progress(event_type: str, event_data: dict[str, Any]) -> None:
    """Handle streaming events from the agent session for progress display."""
    if event_type == "session.thread_created":
        agent = event_data.get("agent_name", "Agent")
        console.print(f"  [dim]├── {agent} started[/dim]")
    elif event_type == "agent.message":
        pass
    elif event_type == "agent.tool_use":
        tool = event_data.get("name", "")
        if tool:
            console.print(f"  [dim]│   Using {tool}...[/dim]")
    elif event_type == "agent.custom_tool_use":
        tool = event_data.get("name", "")
        console.print(f"  [dim]│   Running {tool}...[/dim]")
    elif event_type == "session.error":
        error = event_data.get("error", {}).get("message", "Unknown error")
        console.print(f"  [red]│   Error: {error}[/red]")


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

    # Edit mode: let user toggle individual plugins
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


def show_apply_progress(phase: str, detail: str = "", success: bool | None = None) -> None:
    """Show progress during config application."""
    if success is True:
        console.print(f"  [green]├── {phase}... ✓[/green]")
    elif success is False:
        console.print(f"  [red]├── {phase}... ✗[/red]")
        if detail:
            console.print(f"  [red]│   {detail}[/red]")
    else:
        console.print(f"  [dim]├── {phase}...[/dim]")


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


def parse_proposals_from_messages(messages: list[dict[str, Any]]) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Extract structured proposals from agent messages."""
    plugin_proposals: list[PluginProposal] = []
    entity_proposals: list[CatalogEntityProposal] = []

    for msg in messages:
        text = msg.get("text", "") or msg.get("content", "")
        if isinstance(text, list):
            text = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in text)

        json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if not json_blocks:
            json_blocks = re.findall(r"(\[[\s\S]*?\])", text)

        for block in json_blocks:
            try:
                data = json.loads(block)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    if "plugin" in item and "packages" in item:
                        plugin_proposals.append(PluginProposal(**item))
                    elif "component_type" in item or "source_repo" in item:
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

    # Step 3: Create agents
    with console.status("[bold]Setting up AI agents..."):
        try:
            client = anthropic.Anthropic()
            knowledge_context = kb.to_agent_context()
            agent_ids = create_agents(client, knowledge_context)
            console.print("[green]✓[/green] Agents ready (Scanner, Recommender, Entity Generator, Config Writer)")
        except Exception as e:
            console.print(f"[red]Failed to create agents: {e}[/red]")
            return

    # Step 4: Create session and scan
    ctx = SessionContext(
        client=client,
        agent_ids=agent_ids,
        project_root=project_root,
        on_event=show_scan_progress,
    )

    console.print("\n[bold]Scanning repositories...[/bold]")
    try:
        create_session(ctx)
        repo_list = "\n".join(f"- {url}" for url in repos)
        send_user_message(ctx, f"Scan these repositories and propose plugins and catalog entities:\n{repo_list}")
        messages = run_session_loop(ctx)
    except Exception as e:
        console.print(f"\n[red]Agent session failed: {e}[/red]")
        return

    # Step 5: Parse and display proposals
    plugin_proposals, entity_proposals = parse_proposals_from_messages(messages)

    if not plugin_proposals and not entity_proposals:
        console.print("\n[yellow]Agents didn't return structured proposals. Raw output:[/yellow]")
        for msg in messages:
            text = msg.get("text", "")
            if text:
                console.print(f"  {text[:200]}")
        return

    show_plugin_proposals(plugin_proposals)
    show_entity_proposals(entity_proposals)

    # Step 6: Review
    plugin_proposals, entity_proposals = prompt_review(plugin_proposals, entity_proposals)

    accepted_plugins = [p for p in plugin_proposals if p.accepted]
    accepted_entities = [e for e in entity_proposals if e.accepted]

    if not accepted_plugins and not accepted_entities:
        console.print("[yellow]Nothing to apply. Exiting.[/yellow]")
        return

    # Step 7: Apply
    console.print("\n[bold]Applying configuration...[/bold]")
    send_user_message(
        ctx,
        f"Apply these approved proposals:\n\nPlugins:\n{json.dumps([p.model_dump() for p in accepted_plugins], indent=2)}\n\nEntities:\n{json.dumps([e.model_dump() for e in accepted_entities], indent=2)}",
    )
    apply_messages = run_session_loop(ctx)

    # Step 8: Report
    all_env_vars = []
    for p in accepted_plugins:
        all_env_vars.extend(p.required_env_vars)

    show_completion(
        plugin_count=len(accepted_plugins),
        entity_count=len(accepted_entities),
        env_vars=all_env_vars,
    )
