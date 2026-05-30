# Plan: Professional Two-Phase Onboarding UX

## Context & Current State

The agentic-rhdh-local CLI (`agentic-rhdh`) automates RHDH onboarding by scanning GitHub repos, recommending plugins, generating catalog entities, and configuring RHDH. The current committed state (commit `e3dcd8f`) includes:

- **`agentic-rhdh`** (default) — scan repos, propose plugins, apply config
- **`agentic-rhdh reset`** — remove all agent-generated files, restore baseline
- **Owner detection** — reads `users.yaml` to set component owner to the signed-in user (e.g., `user:default/fortune-ndlovu`)
- **GITHUB_TOKEN suppression** — hides the env var reminder when GitHub integration is already configured
- **github-issues blocked in prompts** — `NEVER recommend github-issues` line in the prompt (but not enforced in signal map or KB)

### Problems with the current flow

1. **Narrow plugin recommendations** — only ever recommends TechDocs + GitHub plugins (3-4 total). 84 plugins available, 25 are Tier 1 (zero-config).
2. **Missing OOB plugins** — `adoption-insights`, `notifications`, `github-insights`, `security-insights` all work out of the box but are never recommended.
3. **github-issues still sneaks through** — prompt-only block isn't reliable; needs enforcement in signal map + KB context.
4. **Tier 3 plugins ignored** — plugins needing credentials (Kubernetes, Topology, Tekton, ArgoCD, SonarQube, Jira) are mentioned as footnotes but never offered for enablement.
5. **Rigid review UX** — `[a/e/r]` menu with number toggling. User can't say "remove TechDocs" or "only keep GitHub Actions."

### Goal

A professional, agentic onboarding experience:
- **Phase 1**: OOB plugins proposed in table, reviewed via natural language or simple commands
- **Phase 2**: Detected infrastructure plugins offered interactively with guided credential collection
- **Phase 3** (deferred): `agentic-rhdh enable <plugin>` for later enablement

---

## Architecture Overview

```
agentic-rhdh
  │
  ├── Phase 1: OOB Plugin Onboarding
  │   ├── Scan repos (agent)
  │   ├── Propose OOB plugins (agent + always-recommend list)
  │   ├── Show proposal table (Rich TUI)
  │   ├── Natural language review (Claude Haiku for NL, local parse for simple)
  │   ├── Apply approved plugins (agent)
  │   └── Create catalog entities (agent)
  │
  └── Phase 2: Guided Tier 3 Enablement
      ├── Detect Tier 3 opportunities from scan signals
      ├── Show opportunities with required credentials
      ├── User selects which to enable
      ├── Prompt for credentials (masked input)
      ├── Write credentials to .env
      ├── Enable each plugin (agent writes config, restarts, verifies)
      └── Loop until user says "skip"
```

---

## Phase 1: OOB Plugins with Natural Language Review

### 1.1 Expand plugin recommendations

**`agentic/knowledge/signal_map.py`** — add new signals and control lists:

```python
# New GitHub signal-driven plugins (alongside existing github-pull-requests)
SignalPattern(
    technology="github-insights",
    file_patterns=[".github/**/*"],
    plugins=["github-insights"],
    confidence=Confidence.LOW,
    category="Source Control",
    required_env_vars=["GITHUB_TOKEN"],
),
SignalPattern(
    technology="security-insights",
    file_patterns=[".github/**/*"],
    plugins=["security-insights"],
    confidence=Confidence.LOW,
    category="Security",
    required_env_vars=["GITHUB_TOKEN"],
),

# Control lists
BLOCKED_PLUGINS: set[str] = {
    "github-issues",  # crashes with file: source-location entities
}

ALWAYS_RECOMMEND_PLUGINS: list[dict[str, str]] = [
    {"plugin": "adoption-insights", "reason": "Platform usage metrics dashboard"},
    {"plugin": "notifications", "reason": "In-app notification system for catalog changes and CI events"},
]
```

Export functions: `get_blocked_plugins()`, `get_always_recommend_plugins()`

**`agentic/knowledge/plugin_index.py`** — update `to_agent_context()`:

```python
def to_agent_context(self) -> str:
    blocked = get_blocked_plugins()
    always = get_always_recommend_plugins()
    
    lines = ["# Available RHDH Plugins\n"]
    
    # BLOCKED section — agent sees this first
    lines.append("## BLOCKED — never recommend these plugins")
    for name in sorted(blocked):
        lines.append(f"- {name}")
    
    # ALWAYS INCLUDE section
    lines.append("## ALWAYS INCLUDE — recommend on every onboarding")
    for entry in always:
        lines.append(f"- {entry['plugin']}: {entry['reason']}")
    
    # Rest of plugin listing, excluding blocked
    for info in sorted(self.plugins.values(), key=lambda p: p.name):
        if info.name in blocked:
            continue
        # ... existing format ...
```

**`agentic/agents/prompts.py`** — rewrite Plugin Selection Policy:

```
## Plugin Selection Policy

### Blocked Plugins — NEVER recommend these
- **github-issues** — incompatible with file: source-location entities, crashes at runtime

### Always-Include Plugins (every onboarding)
These Tier 1 plugins enhance every RHDH instance. ALWAYS include them:
- **adoption-insights** — Platform usage metrics dashboard
- **notifications** — In-app notification system

### Signal-Driven Plugins

**Tier 1 [bundled, zero-config]**: Include if matching signal detected.
Examples: techdocs

**Tier 2 [needs GITHUB_TOKEN only]**: Include for any GitHub repo.
- github-actions (when .github/workflows/ exists)
- github-pull-requests
- github-insights — repo languages, contributors, activity
- security-insights — Dependabot alerts, security advisories

### Tier 3 [advanced] — Surface with context, don't auto-include
(unchanged from current)
```

### 1.2 Natural language review

**`agentic/ui/app.py`** — replace `prompt_review()`:

The new review accepts:
- **Simple inputs** (parsed locally, no API call): `all`, `none`, `a`, `r`, `1,3,5`, `y`, `n`
- **Natural language** (parsed via Claude Haiku): `remove TechDocs`, `only keep GitHub Actions and PRs`, `everything except notifications`

```python
def prompt_review_natural(
    plugin_proposals: list[PluginProposal],
    entity_proposals: list[CatalogEntityProposal],
    client: Any,
) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Review proposals with natural language support."""
    console.print()
    user_input = Prompt.ask(
        "[bold]  Which plugins? (all / none / 1,3,5 / or describe what you want)[/bold]",
        default="all",
    )
    
    _apply_review_input(user_input, plugin_proposals, client)
    return plugin_proposals, entity_proposals


def _apply_review_input(user_input: str, proposals: list[PluginProposal], client: Any) -> None:
    normalized = user_input.strip().lower()
    
    # Fast path: simple inputs
    if normalized in ("all", "a", "yes", "y", ""):
        return  # keep all accepted
    if normalized in ("none", "r", "reject", "no", "n"):
        for p in proposals:
            p.accepted = False
        return
    
    # Number selection: "1,3,5" or "1 3 5"
    nums = re.findall(r'\d+', normalized)
    if nums and all(c in '0123456789, ' for c in normalized):
        selected = {int(n) for n in nums}
        for i, p in enumerate(proposals, 1):
            p.accepted = i in selected
        return
    
    # Natural language: ask Claude Haiku to interpret
    plugin_list = "\n".join(f"{i}. {p.title or p.plugin}" for i, p in enumerate(proposals, 1))
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system="You interpret plugin selection intent. Given a list of plugins and user input, return a JSON array of plugin numbers (1-indexed) to KEEP enabled. Only return the JSON array, nothing else.",
        messages=[{
            "role": "user",
            "content": f"Plugins:\n{plugin_list}\n\nUser said: \"{user_input}\"\n\nReturn JSON array of numbers to keep:",
        }],
    )
    
    try:
        text = response.content[0].text.strip()
        keep_nums = set(json.loads(text))
        for i, p in enumerate(proposals, 1):
            p.accepted = i in keep_nums
    except (json.JSONDecodeError, IndexError, KeyError):
        console.print("[yellow]Couldn't parse that — keeping all plugins.[/yellow]")
```

**Important**: The `client` parameter is the same Anthropic client used for the main agent loop. Claude Haiku is used for the review parse (fast, cheap) — not the full agent.

### 1.3 Update run_app() flow

The existing `run_app()` flow stays mostly the same, but:
- Step 7 (Review): call `prompt_review_natural()` instead of `prompt_review()`, passing `client`
- Step 9 (Report): `_github_integration_configured()` check already suppresses GITHUB_TOKEN

---

## Phase 2: Guided Tier 3 Credential Flow

### 2.1 Data model

**`agentic/models.py`** — add:

```python
@dataclass
class Tier3Opportunity:
    """A detected plugin opportunity that needs credentials to enable."""
    plugin: str               # plugin name in KB
    title: str                # display name
    description: str          # why this was detected
    required_env_vars: list[str]
    detected_signal: str      # technology that triggered detection
    packages: list[dict]      # from KB lookup (name, role, ref, plugin_config)
    group: str = ""           # credential group (e.g., "kubernetes" — shared creds)
```

### 2.2 Detect Tier 3 opportunities from scan

After the scan+propose phase, the agent's response includes Tier 3 mentions (the prompt already tells it to surface them). But we also have the signal map data from the repo scan.

**`agentic/ui/app.py`** — add detection:

```python
def _detect_tier3_opportunities(
    plugin_proposals: list[PluginProposal],
    kb: PluginKnowledgeBase,
) -> list[Tier3Opportunity]:
    """Identify Tier 3 plugins the agent detected signals for but didn't propose."""
    # Get the signal map
    from ..knowledge.signal_map import get_signal_map, get_blocked_plugins
    
    blocked = get_blocked_plugins()
    proposed_plugins = {p.plugin for p in plugin_proposals}
    
    # Tier 3 opportunity definitions — manually curated for quality
    TIER3_DEFS = [
        {
            "plugin": "kubernetes",  # actually kubernetes-backend + kubernetes frontend + topology
            "title": "Kubernetes + Topology",
            "description": "Live pod status, deployment graph, CRD monitoring",
            "required_env_vars": ["K8S_CLUSTER_URL", "K8S_CLUSTER_TOKEN", "K8S_CLUSTER_NAME"],
            "signals": ["kubernetes", "helm", "docker"],
            "group": "kubernetes",
            "extra_plugins": ["topology"],  # enable both
        },
        {
            "plugin": "tekton",
            "title": "Tekton Pipelines",
            "description": "Pipeline run status and logs from OpenShift Pipelines",
            "required_env_vars": ["K8S_CLUSTER_URL", "K8S_CLUSTER_TOKEN", "K8S_CLUSTER_NAME"],
            "signals": ["tekton"],
            "group": "kubernetes",  # shares creds with K8s
        },
        {
            "plugin": "redhat-argocd",
            "title": "ArgoCD",
            "description": "GitOps deployment status and sync state",
            "required_env_vars": ["ARGOCD_INSTANCE1_URL", "ARGOCD_AUTH_TOKEN"],
            "signals": ["argocd"],
            "group": "argocd",
        },
        {
            "plugin": "sonarqube-catalog-cards",
            "title": "SonarQube",
            "description": "Code quality metrics, coverage, and quality gate status",
            "required_env_vars": ["SONARQUBE_URL", "SONARQUBE_TOKEN"],
            "signals": ["sonarqube"],
            "group": "sonarqube",
        },
        {
            "plugin": "jira",
            "title": "Jira",
            "description": "Issue tracking and project status",
            "required_env_vars": ["JIRA_URL", "JIRA_TOKEN"],
            "signals": [],  # detected from README/content, not file patterns
            "group": "jira",
        },
    ]
    
    opportunities = []
    for defn in TIER3_DEFS:
        if defn["plugin"] in blocked or defn["plugin"] in proposed_plugins:
            continue
        
        # Check if any matching signal was detected by the agent
        # (For now, check if the plugin exists in KB — signal detection 
        #  is done by the agent during scan, we'll match on what it mentioned)
        details = kb.get_plugin_config_details(defn["plugin"])
        if not details:
            continue
        
        opportunities.append(Tier3Opportunity(
            plugin=defn["plugin"],
            title=defn["title"],
            description=defn["description"],
            required_env_vars=defn["required_env_vars"],
            detected_signal=", ".join(defn.get("signals", [])),
            packages=details.get("packages", []),
            group=defn.get("group", ""),
        ))
    
    return opportunities
```

### 2.3 Interactive Tier 3 selection and credential flow

**`agentic/ui/app.py`** — add after Phase 1 completion:

```python
def _show_tier3_opportunities(opportunities: list[Tier3Opportunity]) -> None:
    console.print("\n[bold]─── Additional Plugins Detected ───[/bold]")
    console.print("[dim]These plugins need credentials to connect to your infrastructure:[/dim]\n")
    
    for i, opp in enumerate(opportunities, 1):
        console.print(f"  [bold cyan]{i}.[/bold cyan] [bold]{opp.title}[/bold] — {opp.description}")
        env_str = ", ".join(opp.required_env_vars)
        console.print(f"     [dim]Needs: {env_str}[/dim]\n")


def _prompt_tier3_selection(opportunities: list[Tier3Opportunity]) -> list[Tier3Opportunity]:
    choice = Prompt.ask(
        "[bold]  Enable any?[/bold]",
        default="skip",
    ).strip().lower()
    
    if choice in ("skip", "none", "n", ""):
        return []
    if choice in ("all", "a", "yes", "y"):
        return list(opportunities)
    
    # Number selection
    nums = re.findall(r'\d+', choice)
    selected = []
    for n in nums:
        idx = int(n) - 1
        if 0 <= idx < len(opportunities):
            selected.append(opportunities[idx])
    return selected


def _prompt_credentials(opp: Tier3Opportunity, existing_creds: dict[str, str]) -> dict[str, str]:
    """Prompt for required env vars, skipping ones already provided."""
    console.print(f"\n[bold]  Configuring {opp.title}:[/bold]")
    credentials = {}
    for var in opp.required_env_vars:
        if var in existing_creds:
            console.print(f"  [dim]{var}: (using previously entered value)[/dim]")
            credentials[var] = existing_creds[var]
            continue
        
        is_secret = "TOKEN" in var or "SECRET" in var or "PASSWORD" in var or "KEY" in var
        value = Prompt.ask(f"  [cyan]{var}[/cyan]", password=is_secret)
        credentials[var] = value
    return credentials


def _write_env_vars(project_root: Path, credentials: dict[str, str]) -> None:
    """Append credentials to .env file (gitignored)."""
    env_file = project_root / ".env"
    existing = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    
    existing.update(credentials)
    
    lines = [f"{k}={v}" for k, v in sorted(existing.items())]
    env_file.write_text("\n".join(lines) + "\n")
```

### 2.4 Credential sharing between plugins

Kubernetes, Topology, and Tekton share the same K8s credentials. The `group` field on `Tier3Opportunity` tracks this. When the user provides credentials for one plugin in a group, those credentials are reused for other plugins in the same group.

```python
# In run_app(), Phase 2 loop:
collected_creds: dict[str, str] = {}  # accumulates across selections
for opp in selected_opportunities:
    creds = _prompt_credentials(opp, collected_creds)
    collected_creds.update(creds)
    _write_env_vars(project_root, collected_creds)
    _enable_tier3_plugin(client, system_prompt, messages, opp, project_root, kb)
```

### 2.5 Enable Tier 3 plugin via agent

After credentials are written to `.env`, run a focused agent loop to enable the specific plugin:

```python
def _enable_tier3_plugin(
    client, system_prompt, messages, opp, project_root, kb
):
    console.print(f"\n[dim]  Enabling {opp.title}...[/dim]")
    
    enable_msg = (
        f"Enable the {opp.title} plugin ({opp.plugin}). "
        f"The required credentials ({', '.join(opp.required_env_vars)}) are already set in .env. "
        f"Write the plugin config to dynamic-plugins.override.yaml (append to existing plugins), "
        f"update entity annotations if needed, restart RHDH, and verify health."
    )
    
    enable_messages = list(messages)  # copy to avoid polluting Phase 1 history
    enable_messages.append({"role": "user", "content": enable_msg})
    
    run_agent_loop(
        client=client,
        system=system_prompt,
        tools=ALL_TOOLS,
        messages=enable_messages,
        project_root=project_root,
        on_event=_on_event,
        knowledge_base=kb,
    )
```

---

## Phase 3: `agentic-rhdh enable` (deferred — implement after Phase 1+2)

**`agentic/__main__.py`**:
```python
@app.command()
def enable(
    plugin: str = typer.Argument(None, help="Plugin to enable (e.g., 'kubernetes', 'argocd')"),
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", "-p"),
) -> None:
    """Enable a Tier 3 plugin with guided credential setup."""
    run_enable(plugin_name=plugin, project_root=project_dir)
```

Lower priority — the Phase 2 flow covers the interactive case. `enable` is for users who skipped during onboarding and want to come back later.

---

## Files to modify (summary)

| File | Changes |
|------|---------|
| `agentic/knowledge/signal_map.py` | Add github-insights + security-insights signals. Add BLOCKED_PLUGINS set + ALWAYS_RECOMMEND_PLUGINS list with getter functions |
| `agentic/knowledge/plugin_index.py` | Import blocked/always from signal_map. Update `to_agent_context()` with BLOCKED + ALWAYS INCLUDE sections, skip blocked from listing |
| `agentic/agents/prompts.py` | Rewrite Plugin Selection Policy: blocked section, always-include section, expanded Tier 2 list (github-insights, security-insights) |
| `agentic/ui/app.py` | Replace `prompt_review()` with `prompt_review_natural()` (NL support via Haiku). Add Phase 2: `_detect_tier3_opportunities()`, `_show_tier3_opportunities()`, `_prompt_tier3_selection()`, `_prompt_credentials()`, `_write_env_vars()`, `_enable_tier3_plugin()`. Wire Phase 2 into `run_app()` after Phase 1 |
| `agentic/models.py` | Add `Tier3Opportunity` dataclass |
| `agentic/__main__.py` | (Phase 3 only) Add `enable` subcommand |

---

## Verified OOB plugins (Phase 1 proposal set)

These are the plugins that work end-to-end when the agent enables them:

| Plugin | Tier | Type | Trigger |
|--------|------|------|---------|
| techdocs | T1 | bundled FE+BE | docs/ or README exists |
| github-actions | T3 | OCI FE | `.github/workflows/` exists |
| github-pull-requests | T3 | OCI FE | any GitHub repo |
| github-insights | T3 | OCI FE | any GitHub repo |
| security-insights | T3 | OCI FE | any GitHub repo |
| adoption-insights | T1 | bundled FE+BE | always (platform-level) |
| notifications | T1 | bundled FE+BE | always (platform-level) |

**BLOCKED**: github-issues (crashes with `file:` source-location — TypeError: URL constructor)

## Tier 3 plugins (Phase 2 guided enablement)

| Plugin | Signal detection | Credentials | Credential group |
|--------|-----------------|-------------|-----------------|
| Kubernetes + Topology | K8s manifests, CRDs, operator patterns | K8S_CLUSTER_URL, K8S_CLUSTER_TOKEN, K8S_CLUSTER_NAME | kubernetes |
| Tekton | `.tekton/` dirs, `tekton.dev/` API | (shares K8s creds) | kubernetes |
| ArgoCD | `argocd/` dirs, `argoproj.io/` | ARGOCD_INSTANCE1_URL, ARGOCD_AUTH_TOKEN | argocd |
| SonarQube | `sonar-project.properties`, `.sonarcloud.properties` | SONARQUBE_URL, SONARQUBE_TOKEN | sonarqube |
| Jira | JIRA references in README/content | JIRA_URL, JIRA_TOKEN | jira |

---

## Verification checklist

1. `agentic-rhdh reset` — clean baseline
2. `agentic-rhdh` with `rhdh-operator` repo:
   - Proposes 7 OOB plugins (TechDocs, GH Actions, GH PRs, GH Insights, Security Insights, Adoption Insights, Notifications)
   - Natural language review: try `"remove notifications"`, `"only keep TechDocs and GitHub Actions"`, `"all"`, `"1,3,5"`
   - Phase 1 applies, RHDH healthy, no GITHUB_TOKEN reminder
   - Phase 2 shows: Kubernetes+Topology, SonarQube (detected from repo)
   - Select K8s, provide OCP cluster creds, verify pod status shows on entity page
   - Skip SonarQube
3. `agentic-rhdh reset` — verify reset cleans up Phase 2 artifacts too
4. Owner shows as `fortune-ndlovu` not `guest`
5. github-issues never appears in proposals
