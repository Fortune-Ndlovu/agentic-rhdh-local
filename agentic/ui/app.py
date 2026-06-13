"""Main CLI application — Rich-based interactive TUI for RHDH onboarding."""

from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich import box

import yaml

from ..agents.client import create_client
from ..agents.prompts import build_unified_system
from ..agents.session import MODEL, run_agent_loop
from ..agents.tools import ALL_TOOLS
from ..knowledge import PluginKnowledgeBase, extract_catalog_index
from ..models import CatalogEntityProposal, OnboardingState, PluginProposal
from ..scanner import pre_scan_all
from .progress import AgentProgressDisplay

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


_progress: AgentProgressDisplay | None = None


def _on_event(event_type: str, event_data: dict[str, Any]) -> None:
    """Delegate agent loop events to the progress display."""
    if _progress is None:
        return

    if event_type == "turn_start":
        _progress.on_turn_start(event_data.get("turn", 0))
    elif event_type == "text_delta":
        _progress.on_text_delta(event_data.get("text", ""))
    elif event_type == "text_done":
        _progress.on_text_done(event_data.get("text", ""))
    elif event_type == "tool_start":
        _progress.on_tool_start(event_data.get("tool", ""), event_data.get("input", {}))
    elif event_type == "tool_end":
        _progress.on_tool_end(event_data.get("tool", ""), event_data.get("result", {}))


def show_plugin_proposals(proposals: list[PluginProposal]) -> None:
    """Display proposed plugins in a table."""
    if not proposals:
        console.print("\n[yellow]No plugins to propose.[/yellow]")
        return

    console.print(f"\n[bold]Proposed Plugins ({len(proposals)}):[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("#", style="bold cyan", width=3)
    table.add_column("Plugin", style="bold")
    table.add_column("Category", width=14)
    table.add_column("Reason")

    for i, p in enumerate(proposals, 1):
        table.add_row(
            str(i),
            p.title or p.plugin,
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
    client: Any = None,
) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Review proposals with natural language support.

    Accepts simple inputs (parsed locally) and natural language (local
    keyword matching first, Haiku fallback for ambiguous input).
    """
    console.print()
    console.print("[dim]  Options: all, none, pick by row number (e.g. 1,4,5), or natural language (e.g. \"remove notifications\")[/dim]")
    user_input = Prompt.ask(
        "[bold]  Which plugins?[/bold]",
        default="all",
    )

    _apply_review_input(user_input, plugin_proposals, client)
    return plugin_proposals, entity_proposals


def _fuzzy_match_plugin(query: str, proposals: list[PluginProposal]) -> list[int]:
    """Match a user query fragment against plugin names/titles, returning 1-indexed matches."""
    q = query.strip().lower()
    matches = []
    for i, p in enumerate(proposals, 1):
        name = (p.title or p.plugin).lower()
        plugin_id = p.plugin.lower()
        if q in name or q in plugin_id or name in q or plugin_id in q:
            matches.append(i)
    return matches


def _try_local_nl_parse(user_input: str, proposals: list[PluginProposal]) -> bool:
    """Try to interpret natural language locally. Returns True if handled."""
    normalized = user_input.strip().lower()

    # "remove X" / "drop X" / "without X" / "no X"
    remove_match = re.match(r"(?:remove|drop|without|no|disable|exclude)\s+(.+)", normalized)
    if remove_match:
        to_remove: set[int] = set()
        for fragment in re.split(r"[,&]+|\band\b", remove_match.group(1)):
            to_remove.update(_fuzzy_match_plugin(fragment, proposals))
        if to_remove:
            for i, p in enumerate(proposals, 1):
                if i in to_remove:
                    p.accepted = False
            return True

    # "only X" / "just X" / "keep X"
    only_match = re.match(r"(?:only|just|keep)\s+(.+)", normalized)
    if only_match:
        to_keep: set[int] = set()
        for fragment in re.split(r"[,&]+|\band\b", only_match.group(1)):
            to_keep.update(_fuzzy_match_plugin(fragment, proposals))
        if to_keep:
            for i, p in enumerate(proposals, 1):
                p.accepted = i in to_keep
            return True

    # "everything except X" / "all except X" / "all but X"
    except_match = re.match(r"(?:everything|all)\s+(?:except|but|without)\s+(.+)", normalized)
    if except_match:
        to_exclude: set[int] = set()
        for fragment in re.split(r"[,&]+|\band\b", except_match.group(1)):
            to_exclude.update(_fuzzy_match_plugin(fragment, proposals))
        if to_exclude:
            for i, p in enumerate(proposals, 1):
                p.accepted = i not in to_exclude
            return True

    return False


def _apply_review_input(
    user_input: str, proposals: list[PluginProposal], client: Any,
) -> None:
    normalized = user_input.strip().lower()

    # Fast path: simple inputs
    if normalized in ("all", "a", "yes", "y", ""):
        return
    if normalized in ("none", "r", "reject", "no", "n"):
        for p in proposals:
            p.accepted = False
        return

    # Number selection: "1,3,5" or "1 3 5"
    nums = re.findall(r"\d+", normalized)
    if nums and all(c in "0123456789, " for c in normalized):
        selected = {int(n) for n in nums}
        for i, p in enumerate(proposals, 1):
            p.accepted = i in selected
        return

    # Local NL parsing (remove X, only X, everything except X)
    if _try_local_nl_parse(user_input, proposals):
        return

    # Haiku fallback for genuinely ambiguous input
    if client is None:
        console.print("[yellow]Couldn't parse that — keeping all plugins.[/yellow]")
        return

    plugin_list = "\n".join(f"{i}. {p.title or p.plugin}" for i, p in enumerate(proposals, 1))
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system="You interpret plugin selection intent. Given a list of plugins and user input, return a JSON array of plugin numbers (1-indexed) to KEEP enabled. Only return the JSON array, nothing else.",
            messages=[{
                "role": "user",
                "content": f"Plugins:\n{plugin_list}\n\nUser said: \"{user_input}\"\n\nReturn JSON array of numbers to keep:",
            }],
        )
        text = response.content[0].text.strip()
        keep_nums = set(json.loads(text))
        for i, p in enumerate(proposals, 1):
            p.accepted = i in keep_nums
    except Exception:
        console.print("[yellow]Couldn't parse that — keeping all plugins.[/yellow]")


def _generate_onboarding_doc(
    plugins: list[PluginProposal],
    entities: list[CatalogEntityProposal],
    env_vars: list[str],
    project_root: Path,
    base_url: str = "http://localhost:7007",
) -> Path:
    """Generate ONBOARDING.md summarising what was configured."""
    today = datetime.date.today().isoformat()
    lines = [
        "# RHDH Onboarding Summary",
        "",
        f"Generated by `agentic-rhdh` on {today}",
        "",
    ]

    # Plugins table
    lines.append(f"## Enabled Plugins ({len(plugins)})")
    lines.append("")
    lines.append("| # | Plugin | Category | Config File |")
    lines.append("|---|--------|----------|-------------|")
    for i, p in enumerate(plugins, 1):
        lines.append(
            f"| {i} | {p.title or p.plugin} | {p.category} "
            f"| `configs/dynamic-plugins/dynamic-plugins.override.yaml` |"
        )
    lines.append("")

    # Entities table
    if entities:
        lines.append(f"## Catalog Entities ({len(entities)})")
        lines.append("")
        lines.append("| Entity | Type | Entity File | TechDocs |")
        lines.append("|--------|------|-------------|----------|")
        for e in entities:
            entity_file = f"`configs/catalog-entities/{e.name}-component.yaml`"
            docs_dir = f"`configs/catalog-entities/{e.name}-docs/`"
            lines.append(
                f"| {e.name} | {e.component_type.value} | {entity_file} | {docs_dir} |"
            )
        lines.append("")

    # Config files reference
    lines.append("## Configuration Files")
    lines.append("")
    lines.append("- **Plugin overrides**: `configs/dynamic-plugins/dynamic-plugins.override.yaml`")
    lines.append("- **Entity registry**: `configs/catalog-entities/components.override.yaml`")
    lines.append("- **App config**: `configs/app-config/app-config.local.yaml`")
    lines.append("")

    # Next steps
    lines.append("## What To Do Next")
    lines.append("")
    lines.append(f"1. Open RHDH at [{base_url}]({base_url})")
    lines.append("2. Go to **Catalog** to see your registered entities")
    lines.append("3. Click any entity and explore the **Overview**, **CI**, and **Docs** tabs to see enabled plugins in action")
    if env_vars:
        var_list = ", ".join(f"`{v}`" for v in sorted(set(env_vars)))
        lines.append(f"4. Set these environment variables in `.env` for full functionality: {var_list}")
    lines.append("")

    # Adding more plugins
    lines.append("## Adding More Plugins")
    lines.append("")
    lines.append("RHDH has 80+ dynamic plugins available beyond what was auto-configured above.")
    lines.append("")
    lines.append("**Browse available plugins:**")
    lines.append("- [RHDH Dynamic Plugins Catalog](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html/dynamic_plugins_reference/index)")
    lines.append("- Run `agentic-rhdh` again with additional repos to detect more plugin opportunities")
    lines.append("")
    lines.append("**How plugins are configured:**")
    lines.append("")
    lines.append("Each plugin is an entry in `configs/dynamic-plugins/dynamic-plugins.override.yaml`:")
    lines.append("")
    lines.append("```yaml")
    lines.append("plugins:")
    lines.append("  - package: <oci-ref or ./dynamic-plugins/dist/package-name>")
    lines.append("    disabled: false")
    lines.append("    pluginConfig:")
    lines.append("      # plugin-specific configuration")
    lines.append("```")
    lines.append("")
    lines.append("Plugins that need external services (Kubernetes, ArgoCD, SonarQube, Jira) also require:")
    lines.append("- Credentials in `.env` (e.g. `K8S_CLUSTER_URL`, `ARGOCD_AUTH_TOKEN`)")
    lines.append("- Connection config in `configs/app-config/app-config.local.yaml`")
    lines.append("")
    lines.append("After adding a plugin, restart RHDH with `docker compose restart`.")
    lines.append("")

    # Reset
    lines.append("## Reset")
    lines.append("")
    lines.append("Run `agentic-rhdh reset` to remove all generated configuration and return RHDH to its baseline state.")
    lines.append("")

    doc_path = project_root / "ONBOARDING.md"
    doc_path.write_text("\n".join(lines))
    return doc_path


def show_completion(
    plugin_count: int,
    entity_count: int,
    env_vars: list[str],
    base_url: str = "http://localhost:7007",
    doc_path: Path | None = None,
) -> None:
    """Show final completion summary."""
    console.print()
    summary = (
        f"[bold green]RHDH is ready at {base_url}[/bold green]\n"
        f"{plugin_count} plugins enabled, {entity_count} catalog entities added"
    )
    if doc_path:
        summary += f"\n\nOnboarding summary saved to [bold]{doc_path.name}[/bold]"
    console.print(Panel(summary, box=box.ROUNDED))

    if env_vars:
        console.print("\n[yellow]Required: Set these env vars in .env for full functionality:[/yellow]")
        for var in sorted(set(env_vars)):
            console.print(f"  [dim]- {var}[/dim]")


def _detect_catalog_owner(project_root: Path) -> str:
    """Read users.yaml to find the real user entity for component ownership."""
    users_file = project_root / "configs" / "catalog-entities" / "users.yaml"
    if not users_file.exists():
        return "group:default/rhdh-team"

    try:
        with open(users_file) as f:
            docs = list(yaml.safe_load_all(f))
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "User":
                name = doc.get("metadata", {}).get("name", "")
                if name and name != "user":
                    return f"user:default/{name}"
    except Exception:
        pass
    return "group:default/rhdh-team"


def _github_integration_configured(project_root: Path) -> bool:
    """Check if GitHub integration is already in app-config.local.yaml."""
    local_cfg = project_root / "configs" / "app-config" / "app-config.local.yaml"
    if not local_cfg.exists():
        return False
    try:
        with open(local_cfg) as f:
            data = yaml.safe_load(f)
        return bool(
            isinstance(data, dict)
            and data.get("integrations", {}).get("github")
        )
    except Exception:
        return False


_VALID_COMPONENT_TYPES = {"service", "website", "library", "resource"}
_VALID_LIFECYCLES = {"production", "experimental", "development", "deprecated"}
_VALID_CONFIDENCES = {"high", "medium", "low"}

_PLUGIN_FIELDS = {f.alias or name for name, f in PluginProposal.model_fields.items()}
_ENTITY_FIELDS = {f.alias or name for name, f in CatalogEntityProposal.model_fields.items()}


def _parse_plugin_proposal(item: dict[str, Any]) -> PluginProposal:
    if item.get("confidence") not in _VALID_CONFIDENCES:
        item["confidence"] = "medium"
    if "tier" in item:
        try:
            item["tier"] = int(item["tier"])
        except (ValueError, TypeError):
            item["tier"] = 2
    filtered = {k: v for k, v in item.items() if k in _PLUGIN_FIELDS}
    return PluginProposal(**filtered)


def _parse_entity_proposal(item: dict[str, Any]) -> CatalogEntityProposal:
    if item.get("component_type") not in _VALID_COMPONENT_TYPES:
        item["component_type"] = "service"
    if item.get("lifecycle") not in _VALID_LIFECYCLES:
        item["lifecycle"] = "production"
    filtered = {k: v for k, v in item.items() if k in _ENTITY_FIELDS}
    return CatalogEntityProposal(**filtered)


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
            json_blocks = _extract_json_arrays(text)

        for raw_block in json_blocks:
            jblock = re.sub(r"^[^\[{]*", "", raw_block.strip(), count=1)
            try:
                data = json.loads(jblock)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if "plugin" in item and ("packages" in item or "plugin_config" in item):
                        plugin_proposals.append(_parse_plugin_proposal(item))
                    elif "component_type" in item or ("source_repo" in item and "name" in item):
                        entity_proposals.append(_parse_entity_proposal(item))
            except (json.JSONDecodeError, ValueError, Exception):
                continue

    return plugin_proposals, entity_proposals


def _extract_json_arrays(text: str) -> list[str]:
    """Extract top-level JSON arrays from text using bracket balancing."""
    results = []
    i = 0
    while i < len(text):
        if text[i] == "[":
            depth = 0
            start = i
            in_string = False
            escape = False
            while i < len(text):
                ch = text[i]
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start : i + 1]
                            try:
                                json.loads(candidate)
                                results.append(candidate)
                            except json.JSONDecodeError:
                                pass
                            break
                i += 1
        i += 1
    return results


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

    # Step 4: Build system prompt with knowledge context + owner identity
    knowledge_context = kb.to_agent_context()
    owner = _detect_catalog_owner(project_root)
    system_prompt = build_unified_system(knowledge_context, owner=owner)

    # Step 5: Pre-scan repos locally (parallel, no Claude API calls)
    global _progress
    _progress = AgentProgressDisplay(console)
    _progress.specialist = "Pre-Scanner"
    _progress.specialist_icon = "⚡"
    _progress.phase = "scan"
    _progress.start()

    def _prescan_event(event_type: str, event_data: dict[str, Any]) -> None:
        if _progress:
            _progress.on_prescan_event(event_type, event_data)

    try:
        scan_result = pre_scan_all(repos, kb, owner=owner, on_event=_prescan_event)
    except Exception as e:
        _progress.stop()
        _progress = None
        console.print(f"\n[red]Pre-scan failed: {e}[/red]")
        return

    plugin_proposals = scan_result.plugin_proposals
    entity_proposals = scan_result.entity_proposals

    if not plugin_proposals and not entity_proposals:
        _progress.stop()
        _progress = None
        console.print("\n[yellow]No plugins or entities detected.[/yellow]")
        return

    # Step 5b: Enrich proposals with AI-generated reasons (single Claude call)
    _progress._transition("Recommender Agent", "\U0001f9e0", "recommend")

    profiles_json = json.dumps(
        [p.model_dump() for p in scan_result.profiles], indent=2, default=str,
    )
    plugins_json = json.dumps(
        [p.model_dump() for p in plugin_proposals], indent=2, default=str,
    )
    entities_json = json.dumps(
        [e.model_dump() for e in entity_proposals], indent=2, default=str,
    )

    enrich_msg = (
        "I've pre-scanned the repositories and built initial proposals. "
        "Please enrich each proposal with a detailed, contextual reason explaining WHY "
        "this plugin/entity is valuable for this specific repo — not generic descriptions. "
        "Also improve entity descriptions based on what the repo actually does.\n\n"
        "Return the enriched proposals as two JSON blocks (PLUGIN_PROPOSALS and ENTITY_PROPOSALS) "
        "with the same structure but better `reason` and `description` fields.\n\n"
        f"Repo Profiles:\n```json\n{profiles_json}\n```\n\n"
        f"Plugin Proposals:\n```json\n{plugins_json}\n```\n\n"
        f"Entity Proposals:\n```json\n{entities_json}\n```"
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": enrich_msg},
    ]

    try:
        response_content = run_agent_loop(
            client=client,
            system=system_prompt,
            tools=[],
            messages=messages,
            project_root=project_root,
            on_event=_on_event,
            max_turns=1,
        )
    except Exception as e:
        _progress.stop()
        _progress = None
        console.print(f"\n[yellow]Enrichment failed, using basic proposals: {e}[/yellow]")
        show_plugin_proposals(plugin_proposals)
        show_entity_proposals(entity_proposals)
        plugin_proposals, entity_proposals = prompt_review(plugin_proposals, entity_proposals, client)
        # fall through to apply phase below
        accepted_plugins = [p for p in plugin_proposals if p.accepted]
        accepted_entities = [e for e in entity_proposals if e.accepted]
        if not accepted_plugins and not accepted_entities:
            console.print("[yellow]Nothing to apply. Exiting.[/yellow]")
            return
        _save_baseline(project_root)
        # jump to apply phase handled below
        response_content = []

    _progress.stop()
    _progress = None

    enriched_plugins, enriched_entities = parse_proposals_from_response(response_content)
    if enriched_plugins:
        plugin_proposals = enriched_plugins
    if enriched_entities:
        entity_proposals = enriched_entities

    show_plugin_proposals(plugin_proposals)
    show_entity_proposals(entity_proposals)

    # Step 7: Review
    plugin_proposals, entity_proposals = prompt_review(plugin_proposals, entity_proposals, client)

    accepted_plugins = [p for p in plugin_proposals if p.accepted]
    accepted_entities = [e for e in entity_proposals if e.accepted]

    if not accepted_plugins and not accepted_entities:
        console.print("[yellow]Nothing to apply. Exiting.[/yellow]")
        return

    # Snapshot baseline app-config before the agent modifies it
    _save_baseline(project_root)

    # Step 8: Apply
    _progress = AgentProgressDisplay(console)
    _progress.phase = "apply"
    _progress.specialist = "Config Writer Agent"
    _progress.specialist_icon = "✍️"
    _progress.start()

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
            knowledge_base=kb,
        )
    except Exception as e:
        _progress.stop()
        _progress = None
        console.print(f"\n[red]Apply phase failed: {e}[/red]")
        return

    _progress.stop()
    _progress = None

    # Step 9: Report
    all_env_vars = []
    for p in accepted_plugins:
        all_env_vars.extend(p.required_env_vars)

    if _github_integration_configured(project_root):
        all_env_vars = [v for v in all_env_vars if v != "GITHUB_TOKEN"]

    doc_path = _generate_onboarding_doc(
        plugins=accepted_plugins,
        entities=accepted_entities,
        env_vars=all_env_vars,
        project_root=project_root,
    )

    show_completion(
        plugin_count=len(accepted_plugins),
        entity_count=len(accepted_entities),
        env_vars=all_env_vars,
        doc_path=doc_path,
    )


_BASELINE_SUFFIX = ".baseline"


def _save_baseline(project_root: Path) -> None:
    """Snapshot app-config.local.yaml before the agent modifies it.

    Only saves if a baseline doesn't already exist, preserving the true
    pre-onboarding state across multiple agent runs.
    """
    local_cfg = project_root / "configs" / "app-config" / "app-config.local.yaml"
    baseline = local_cfg.with_suffix(local_cfg.suffix + _BASELINE_SUFFIX)
    if local_cfg.exists() and not baseline.exists():
        shutil.copy2(local_cfg, baseline)


def _discover_generated_files(project_root: Path) -> dict[str, list[Path]]:
    """Find all agent-generated files that reset should remove."""
    catalog_dir = project_root / "configs" / "catalog-entities"
    plugins_dir = project_root / "configs" / "dynamic-plugins"

    result: dict[str, list[Path]] = {
        "entities": [],
        "techdocs": [],
        "overrides": [],
        "backups": [],
    }

    if catalog_dir.exists():
        for f in catalog_dir.glob("*-component.yaml"):
            result["entities"].append(f)
        for d in catalog_dir.iterdir():
            if d.is_dir() and d.name.endswith("-docs"):
                result["techdocs"].append(d)
        comp_override = catalog_dir / "components.override.yaml"
        if comp_override.exists():
            result["overrides"].append(comp_override)

    plugin_override = plugins_dir / "dynamic-plugins.override.yaml"
    if plugin_override.exists():
        result["overrides"].append(plugin_override)

    for bak in project_root.joinpath("configs").rglob("*.bak"):
        result["backups"].append(bak)

    onboarding_doc = project_root / "ONBOARDING.md"
    if onboarding_doc.exists():
        result["overrides"].append(onboarding_doc)

    return result


def run_reset(project_root: Path | None = None, *, skip_confirm: bool = False) -> None:
    """Reset RHDH to the baseline state by removing all agent-generated files."""
    if project_root is None:
        project_root = Path.cwd()

    console.print(Panel(
        Text("Agentic RHDH Local — Reset to Baseline", style="bold cyan"),
        box=box.DOUBLE,
        padding=(1, 2),
    ))

    generated = _discover_generated_files(project_root)
    total = sum(len(v) for v in generated.values())

    local_cfg = project_root / "configs" / "app-config" / "app-config.local.yaml"
    baseline = local_cfg.with_suffix(local_cfg.suffix + _BASELINE_SUFFIX)
    has_baseline = baseline.exists()

    if total == 0 and not has_baseline:
        console.print("\n[green]Already at baseline — nothing to reset.[/green]")
        return

    # Show what will be removed
    console.print("\n[bold]The following will be removed:[/bold]")
    for entity in generated["entities"]:
        console.print(f"  [red]✕[/red] {entity.relative_to(project_root)}")
    for docs_dir in generated["techdocs"]:
        console.print(f"  [red]✕[/red] {docs_dir.relative_to(project_root)}/")
    for override in generated["overrides"]:
        console.print(f"  [red]✕[/red] {override.relative_to(project_root)}")
    for bak in generated["backups"]:
        console.print(f"  [dim]✕ {bak.relative_to(project_root)}[/dim]")
    if has_baseline:
        console.print(f"  [yellow]↺[/yellow] configs/app-config/app-config.local.yaml [dim](restore baseline)[/dim]")

    if not skip_confirm:
        console.print()
        confirm = Prompt.ask(
            "[bold]Reset to baseline?[/bold]",
            choices=["y", "n"],
            default="n",
        )
        if confirm != "y":
            console.print("[dim]Reset cancelled.[/dim]")
            return

    # Delete generated files
    console.print()
    removed = 0
    for entity in generated["entities"]:
        entity.unlink()
        removed += 1
    for docs_dir in generated["techdocs"]:
        shutil.rmtree(docs_dir)
        removed += 1
    for override in generated["overrides"]:
        override.unlink()
        removed += 1
    for bak in generated["backups"]:
        bak.unlink()
        removed += 1

    # Restore app-config baseline
    if has_baseline:
        shutil.copy2(baseline, local_cfg)
        baseline.unlink()
        console.print("[green]✓[/green] Restored app-config.local.yaml to baseline")

    console.print(f"[green]✓[/green] Removed {removed} generated files")

    # Restart RHDH
    from ..tools.compose import ensure_dotenv_compose_vars, restart_rhdh, is_running

    ensure_dotenv_compose_vars(project_root)
    if is_running(project_root):
        console.print("[dim]Restarting RHDH...[/dim]")
        success, output = restart_rhdh(project_root)
        if not success:
            console.print(f"[red]Restart failed: {output}[/red]")
            return

        from ..tools.health_check import wait_for_healthy

        console.print("[dim]Waiting for RHDH to become healthy...[/dim]")
        result = wait_for_healthy()
        if result.healthy:
            console.print("[green]✓[/green] RHDH is healthy")
        else:
            console.print(f"[yellow]RHDH health check: {result.message}[/yellow]")

    console.print(Panel(
        "[bold green]Reset complete — RHDH is back to baseline[/bold green]",
        box=box.ROUNDED,
    ))
