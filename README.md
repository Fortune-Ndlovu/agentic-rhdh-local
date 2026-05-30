# Agentic RHDH Local

> An AI-powered CLI that automates Red Hat Developer Hub onboarding. Instead of manually discovering plugins, writing YAML configs, and creating catalog entities, users provide their GitHub repo URLs and the agent does the rest.

Built on the [Anthropic Messages API](https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview) (tool-use loop) and [RHDH Local](https://github.com/redhat-developer/rhdh-local).

> [!CAUTION]
>
> This is a **proof-of-concept** — not production software.
> It is built on top of RHDH Local, which is itself for development and testing only.

## The Problem

Getting started with RHDH is painful. A platform engineer who wants to onboard their team's repositories must:

1. Figure out which dynamic plugins match their tech stack (GitHub Actions? Tekton? ArgoCD? Kubernetes?)
2. Write the correct `pluginConfig` YAML blocks with mount points, routes, and env vars
3. Create Backstage catalog entities for each repo with the right annotations
4. Configure `app-config` to point at the right catalog locations
5. Install plugins, restart RHDH, debug config errors, repeat

This is error-prone, time-consuming, and requires deep RHDH knowledge before seeing any value.

## The Solution

A single unified agent where the user's only job is to say: **"here are my repos."**

```
$ agentic-rhdh

╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║  Agentic RHDH Local — Smart Onboarding                                     ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

Add your team's repositories:

  > https://github.com/redhat-developer/rhdh-operator   ✓

✓ Loaded 84 plugins from catalog index
✓ Claude client ready

Scanning repositories...
  ├── Scanning redhat-developer/rhdh-operator...
  │   Found 363 files
  │   Checking languages...
  │   Reading README.md...

Proposed Plugins (8):
╭─────┬──────────────────────────┬────────────────┬──────────────────────────────────────────╮
│ #   │ Plugin                   │ Category       │ Reason                                   │
├─────┼──────────────────────────┼────────────────┼──────────────────────────────────────────┤
│ 1   │ TechDocs                 │ Documentation  │ Rich docs/ directory with 10+ files      │
│ 2   │ Adoption Insights        │ Analytics      │ Platform usage metrics dashboard         │
│ 3   │ Notifications            │ Notifications  │ In-app notification system                │
│ 4   │ Lightspeed               │ AI Assistant   │ AI assistant for Developer Hub            │
│ 5   │ GitHub Actions           │ CI/CD          │ 14 workflows — nightly builds, PR tests   │
│ 6   │ GitHub Pull Requests     │ Source Control │ Active PR template + CODEOWNERS           │
│ 7   │ GitHub Insights          │ Source Control │ Language breakdown, contributors, license  │
│ 8   │ Security Insights        │ Security       │ Dependabot alerts, security advisories    │
╰─────┴──────────────────────────┴────────────────┴──────────────────────────────────────────╯

  Options: all, none, pick by row number (e.g. 1,4,5), or natural language (e.g. "remove notifications")
  Which plugins? (all): all

Applying configuration...
  ├── Writing dynamic-plugins.override.yaml... ✓
  ├── Writing catalog entities... ✓
  ├── Restarting RHDH... ✓
  └── Health check passed ✓

╭──────────────────────────────────────────────────────────────────────╮
│ RHDH is ready at http://localhost:7007                              │
│ 8 plugins enabled, 1 catalog entities added                        │
│                                                                    │
│ Onboarding summary saved to ONBOARDING.md                          │
╰──────────────────────────────────────────────────────────────────────╯
```

## Architecture

A unified agent powered by Claude (via Vertex AI or direct API), using a tool-use loop to scan repos, recommend plugins, generate catalog entities, and write config — all in a single conversation turn.

```mermaid
graph TB
    subgraph CLI["CLI (Rich TUI)"]
        Input["User adds repos"]
        Review["Natural language review"]
        Output["Completion + ONBOARDING.md"]
    end

    subgraph Agent["Unified Agent (Claude Sonnet via Vertex AI)"]
        Scan["Scan repos via GitHub API"]
        Recommend["Recommend plugins"]
        Generate["Generate catalog entities"]
        Apply["Write config + restart RHDH"]
    end

    subgraph KB["Knowledge Base"]
        CatalogIndex["Plugin Catalog Index<br/>(84 plugins from OCI image)"]
        SignalMap["Signal Map<br/>(file patterns → plugins)"]
        BlockedAlways["Blocked / Always-Include<br/>control lists"]
    end

    subgraph Tools["Local Tools"]
        GitHub["GitHub API<br/>(gh CLI)"]
        YAML["YAML Writer<br/>(atomic writes)"]
        Compose["Compose<br/>(restart, health)"]
        Health["Health Check<br/>(log diagnosis)"]
    end

    Input --> Scan
    Scan --> GitHub
    Scan --> Recommend
    Recommend --> CatalogIndex
    Recommend --> SignalMap
    Recommend --> BlockedAlways
    Recommend --> Generate
    Generate --> Review
    Review --> Apply
    Apply --> YAML
    Apply --> Compose
    Apply --> Health
    Health --> Output
```

### Onboarding Flow

```mermaid
sequenceDiagram
    actor User
    participant CLI as CLI (Rich TUI)
    participant Agent as Claude Agent
    participant GH as GitHub API
    participant KB as Plugin KB
    participant RHDH as RHDH Container

    User->>CLI: Enter repo URLs
    CLI->>Agent: Scan + Propose

    Agent->>GH: get_repo_info, scan_repo_tree
    GH-->>Agent: File tree, languages, README

    Agent->>KB: lookup_plugin_config (per signal)
    KB-->>Agent: Package refs, pluginConfig

    Agent-->>CLI: Plugin proposals + Entity proposals

    CLI->>User: Show proposals table
    User->>CLI: Natural language selection<br/>("all", "1,3,5", "remove notifications")

    CLI->>Agent: Apply approved proposals
    Agent->>RHDH: write configs, restart, health check
    RHDH-->>Agent: Healthy

    CLI->>User: RHDH ready + ONBOARDING.md
```

### Plugin Selection

```mermaid
graph LR
    subgraph Always["Always Include"]
        AI["Adoption Insights"]
        N["Notifications"]
        LS["Lightspeed"]
    end

    subgraph Signal["Signal-Driven"]
        subgraph T1["Tier 1 (zero-config)"]
            TD["TechDocs"]
        end
        subgraph T2["Tier 2 (GITHUB_TOKEN)"]
            GA["GitHub Actions"]
            GPR["GitHub PRs"]
            GI["GitHub Insights"]
            SI["Security Insights"]
        end
    end

    subgraph Blocked["Blocked"]
        GIS["github-issues<br/>❌ crashes with file: source-location"]
    end

    Always --> Proposed["Proposed to User"]
    T1 --> Proposed
    T2 --> Proposed
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Unified agent** | Single Claude agent handles the full pipeline — no multi-agent coordination overhead |
| **Plugin knowledge base** | 84 plugins indexed from `quay.io/rhdh/plugin-catalog-index:1.9` — real configs, not hallucinated |
| **Signal detection** | File patterns in repos map to plugin recommendations with confidence levels |
| **Always-include plugins** | Adoption Insights, Notifications, and Lightspeed proposed on every onboarding |
| **Blocked plugins** | `github-issues` blocked (crashes with `file:` source-location entities) |
| **Natural language review** | "remove notifications", "only keep GitHub Actions", "1,3,5" — local keyword parsing + Claude fallback |
| **Owner detection** | Reads `users.yaml` to set component owner to the signed-in GitHub user |
| **Onboarding doc** | `ONBOARDING.md` generated with plugin table, config locations, and next steps |
| **Reset** | `agentic-rhdh reset` removes all generated files and restores baseline |
| **Resilient apply** | Config writer retries up to 3 times with log-based error diagnosis |

## Quick Start

### Prerequisites

- Python 3.11+
- [Podman](https://podman.io/docs/installation) v5.4.1+ or [Docker](https://docs.docker.com/engine/) v28.1.0+ with Compose
- Claude API access — either:
  - **Vertex AI**: `CLAUDE_CODE_USE_VERTEX=1` + `ANTHROPIC_VERTEX_PROJECT_ID` (GCP billing)
  - **Direct**: `ANTHROPIC_API_KEY`
- GitHub auth via [`gh` CLI](https://cli.github.com/) (`gh auth login`) or `GITHUB_TOKEN` env var

### Run

```sh
# Clone and start RHDH Local
git clone https://github.com/Fortune-Ndlovu/agentic-rhdh-local.git
cd agentic-rhdh-local
podman compose up -d  # or: docker compose up -d

# Install the agentic CLI
pip install -e .

# Option A: Vertex AI (GCP billing)
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project

# Option B: Direct Anthropic API
export ANTHROPIC_API_KEY=sk-ant-...

# Run the onboarding agent
agentic-rhdh
```

### Commands

```sh
agentic-rhdh                          # Run onboarding
agentic-rhdh reset                    # Remove all generated config, restore baseline
agentic-rhdh --project-dir /path/to   # Use a different project directory
```

## Project Structure

```
agentic-rhdh-local/
├── agentic/                        # AI-powered onboarding system (Python)
│   ├── __main__.py                 # CLI entry point (Typer)
│   ├── models.py                   # Pydantic data models
│   ├── agents/                     # Agent definitions
│   │   ├── client.py               # Client factory (auto-detects Vertex AI or direct API)
│   │   ├── prompts.py              # System prompt with plugin selection policy
│   │   ├── session.py              # Tool-use loop (Messages API)
│   │   └── tools.py                # Tool JSON Schema definitions
│   ├── knowledge/                  # Plugin knowledge base
│   │   ├── extractor.py            # Extracts catalog index image (podman/docker)
│   │   ├── plugin_index.py         # PluginKnowledgeBase — 84 plugins indexed
│   │   └── signal_map.py           # File patterns → plugins, blocked/always-include lists
│   ├── tools/                      # Local tool implementations
│   │   ├── github.py               # GitHub API (gh CLI / GITHUB_TOKEN fallback)
│   │   ├── yaml_writer.py          # Atomic YAML writes with backup
│   │   ├── compose.py              # Podman/Docker compose operations
│   │   └── health_check.py         # RHDH health check + log-based error diagnosis
│   └── ui/                         # CLI interface
│       └── app.py                  # Rich TUI — input, proposals, NL review, onboarding doc
├── pyproject.toml                  # Python project config
├── compose.yaml                    # RHDH Local container orchestration
├── default.env                     # Default env vars (Lightspeed, GitHub auth, DB)
├── configs/                        # RHDH configuration (agent writes overrides here)
│   ├── dynamic-plugins/            # Plugin configs (default + override)
│   ├── catalog-entities/           # Catalog entity YAML + TechDocs
│   └── app-config/                 # App config YAML
├── ONBOARDING.md                   # Generated onboarding summary (after running agent)
└── ...                             # RHDH Local base files (scripts, docs, etc.)
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Clean SDK support, strong YAML/JSON tooling, fast iteration |
| Agent Runtime | Anthropic Messages API (tool-use loop) | Single agent, local tool dispatch, no server-side state |
| Model | Claude Sonnet 4.6 (via Vertex AI or direct) | Strong tool use, cost-effective, auto-detected auth |
| CLI Framework | Rich + Typer | Interactive TUI with tables, progress, prompts |
| Data Models | Pydantic v2 | Typed, validated, serializable |
| Plugin Data | RHDH Catalog Index Image | Authoritative source, version-matched, no vector DB |
| Container Runtime | Podman/Docker (auto-detected) | For RHDH lifecycle management |

## Signals Detected

The agent recognizes these technologies from repo file patterns:

| Signal | File Patterns | Maps To |
|--------|--------------|---------|
| GitHub Actions | `.github/workflows/*.yml` | github-actions plugin |
| GitHub Pull Requests | `.github/**/*` | github-pull-requests plugin |
| GitHub Insights | `.github/**/*` | github-insights plugin |
| Security Insights | `.github/**/*` | security-insights plugin |
| Tekton | `tekton/`, `.tekton/`, `apiVersion: tekton.dev/` | tekton plugin |
| Jenkins | `Jenkinsfile` | jenkins plugin |
| ArgoCD | `argocd/`, `argoproj.io/` | argocd plugin |
| Kubernetes | `k8s/`, `deploy/`, `manifests/`, `apiVersion: apps/v1` | kubernetes + topology plugins |
| Helm | `Chart.yaml` | kubernetes plugin |
| Docker | `Dockerfile`, `Containerfile` | topology plugin |
| TechDocs | `mkdocs.yml`, `docs/` | techdocs plugin |
| OpenAPI | `openapi.yaml`, `swagger.json` | api-docs plugin |
| SonarQube | `sonar-project.properties` | sonarqube plugin |
| Ansible | `ansible/`, `playbooks/`, `roles/` | ansible-plugin |
| Azure DevOps | `azure-pipelines.yml` | azure-devops plugin |
| Existing Backstage | `catalog-info.yaml` | Direct import |

## Config Writer Resilience

The agent doesn't just write files and hope for the best. It follows a resilience loop:

```mermaid
graph TD
    Write["Write config files"] --> Restart["Restart RHDH"]
    Restart --> Health["Health check"]
    Health --> Logs["Check logs for errors"]
    Logs --> Found{"Error found?"}

    Found -->|No| Done["Done ✓"]
    Found -->|Yes| Diagnose{"Diagnose error"}

    Diagnose -->|Missing env var| Fix1["Add placeholder to .env"]
    Diagnose -->|Bad config| Fix2["Fix YAML"]
    Diagnose -->|OCI pull failed| Fix3["Try alternative version"]
    Diagnose -->|Max retries reached| Disable["Disable plugin, report failure"]

    Fix1 --> Retry{"Retry < 3?"}
    Fix2 --> Retry
    Fix3 --> Retry

    Retry -->|Yes| Write
    Retry -->|No| Disable
```

## RHDH Local Commands

> Replace `podman` with `docker` if using Docker.

```sh
# Start RHDH
podman compose up -d

# After plugin config changes
podman compose run install-dynamic-plugins
podman compose stop rhdh && podman compose start rhdh

# Quick restart (config-only changes)
podman compose restart rhdh

# Tear down
podman compose down --volumes
```

Access RHDH at [http://localhost:7007](http://localhost:7007) (login as Guest).

## Additional Guides

1. [Plugins Guide](./docs/rhdh-local-guide/plugins-guide.md) — manual plugin installation
2. [Container Image Guide](docs/rhdh-local-guide/container-image-guide.md) — switching RHDH versions
3. [Simulated Proxy Setup](docs/rhdh-local-guide/corporate-proxy-setup-sim.md) — proxy testing
4. [PostgreSQL Guide](docs/rhdh-local-guide/postgresql-guide.md) — persistent database
5. [Orchestrator Workflow Guide](./orchestrator/README.md) — workflow development
6. [Developer Lightspeed Guide](./developer-lightspeed/README.md) — AI assistance in RHDH

## License

```txt
Copyright Red Hat

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
