# Agentic RHDH Local

> A proof-of-concept multi-agent system that automates Red Hat Developer Hub onboarding. Instead of manually discovering plugins, writing YAML configs, and creating catalog entities, users provide their GitHub repo URLs and the system does the rest.

Built on [Anthropic Managed Agents SDK](https://docs.anthropic.com/en/docs/agents-and-tools/managed-agents) and [RHDH Local](https://github.com/redhat-developer/rhdh-local).

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

A multi-agent system where the user's only job is to say: **"here are my repos."**

```
$ agentic-rhdh

╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║  Agentic RHDH Local — Smart Onboarding                                     ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

Add your team's repositories:

  > https://github.com/my-org/backend-service    ✓
  > https://github.com/my-org/frontend-app       ✓
  > https://github.com/my-org/infra-configs      ✓

Scanning repositories... (3 agents running in parallel)
  ├── backend-service: Go, Dockerfile, Kubernetes manifests, GitHub Actions
  ├── frontend-app: React, TypeScript, mkdocs.yml, GitHub Actions
  └── infra-configs: Helm charts, ArgoCD configs, Tekton pipelines

Proposed Plugins (7):
╭────┬────────────────────────┬────────────┬────────────┬──────────────────────────────╮
│ #  │ Plugin                 │ Confidence │ Category   │ Reason                       │
├────┼────────────────────────┼────────────┼────────────┼──────────────────────────────┤
│ ✓  │ GitHub Actions         │ high       │ CI/CD      │ Workflows in 2 repos         │
│ ✓  │ Kubernetes             │ high       │ Kubernetes │ K8s manifests in backend     │
│ ✓  │ TechDocs               │ high       │ Docs       │ mkdocs.yml in frontend       │
│ ✓  │ Tekton                 │ high       │ CI/CD      │ Tekton pipelines in infra    │
│ ✓  │ ArgoCD                 │ medium     │ GitOps     │ ArgoCD configs in infra      │
│ ✓  │ Topology               │ medium     │ Container  │ Dockerfiles detected         │
│ ○  │ GitHub Pull Requests   │ low        │ SCM        │ GitHub repos detected        │
╰────┴────────────────────────┴────────────┴────────────┴──────────────────────────────╯

  [a] Accept all  [e] Edit selections  [r] Reject all

  > a

Applying configuration...
  ├── Writing dynamic-plugins.override.yaml... ✓
  ├── Writing catalog entities... ✓
  ├── Restarting RHDH... ✓
  └── Health check passed ✓

RHDH is ready at http://localhost:7007
6 plugins enabled, 3 catalog entities added
```

## Architecture

Four specialist agents coordinated by an orchestrator, all running as Anthropic Managed Agents:

```
┌─────────────────────────────────────────────────────┐
│                  CLI (Rich TUI)                      │
│   User adds repos → sees proposals → approves       │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│      Coordinator Agent (Anthropic Managed Agent)     │
│   Orchestrates specialists, collects proposals,      │
│   presents unified approval, drives apply phase      │
└──┬──────────┬──────────┬──────────┬─────────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
│  Repo  │ │ Plugin   │ │Catalog │ │ Config   │
│Scanner │ │Recommender│ │ Entity │ │ Writer   │
│ Agent  │ │  Agent   │ │ Agent  │ │ Agent    │
└────────┘ └──────────┘ └────────┘ └──────────┘
```

| Agent | What it does |
|-------|-------------|
| **Repo Scanner** | Scans GitHub repos via API — detects technologies (GitHub Actions, Kubernetes, Tekton, ArgoCD, Docker, TechDocs, etc.) from file tree patterns |
| **Plugin Recommender** | Maps detected signals to RHDH plugins using the catalog index knowledge base — includes complete `pluginConfig` from authoritative source |
| **Catalog Entity Generator** | Creates Backstage `Component` entities with inferred type (service/website/library), lifecycle, and annotations |
| **Config Writer** | Writes override YAML files, restarts RHDH, verifies health, diagnoses errors from logs, retries up to 3 times |

### Key Design Decisions

- **Anthropic Managed Agents SDK** — Server-side agents with coordinator pattern, built-in tools, streaming events, session persistence. No custom orchestration needed.
- **No vector DB** — The RHDH plugin catalog (~84 plugins) is small and structured. Deterministic matching against file patterns is more reliable than semantic search.
- **Catalog index as source of truth** — `dynamic-plugins.default.yaml` from `quay.io/rhdh/plugin-catalog-index:1.9` has every plugin's complete config. Agents use real configs, not hallucinated ones.
- **Override files only** — Agents never touch default configs. Everything goes through `dynamic-plugins.override.yaml`, `app-config.local.yaml`, etc.
- **Custom tools execute locally** — Agents decide what to do; the CLI executes locally. File writes, compose commands, and health checks stay under user control.

## Quick Start

### Prerequisites

- Python 3.11+
- [Podman](https://podman.io/docs/installation) v5.4.1+ or [Docker](https://docs.docker.com/engine/) v28.1.0+ with Compose
- An Anthropic API key (`ANTHROPIC_API_KEY`)
- GitHub auth via [`gh` CLI](https://cli.github.com/) (`gh auth login`) or `GITHUB_TOKEN` env var

### Run

```sh
# Clone and start RHDH Local
git clone https://github.com/Fortune-Ndlovu/agentic-rhdh-local.git
cd agentic-rhdh-local
podman compose up -d  # or: docker compose up -d

# Install the agentic CLI
pip install -e .

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run the onboarding agent
agentic-rhdh
```

### Options

```
agentic-rhdh --help
agentic-rhdh --project-dir /path/to/agentic-rhdh-local
```

### Reset

Remove all generated entities, plugin overrides, and backups to start fresh:

```sh
agentic-rhdh reset       # preview and confirm
agentic-rhdh reset -y    # skip confirmation
```

## Project Structure

```
agentic-rhdh-local/
├── agentic/                        # Multi-agent onboarding system (Python)
│   ├── __main__.py                 # CLI entry point (Typer)
│   ├── models.py                   # Pydantic data models
│   ├── agents/                     # Agent definitions & orchestration
│   │   ├── prompts.py              # System prompts for all 5 agents
│   │   ├── tools.py                # Custom tool JSON Schema definitions
│   │   ├── setup.py                # Agent creation via Managed Agents API
│   │   └── session.py              # Session lifecycle, event streaming, tool dispatch
│   ├── knowledge/                  # Plugin knowledge base
│   │   ├── extractor.py            # Extracts catalog index image (podman/docker)
│   │   ├── plugin_index.py         # PluginKnowledgeBase — 84 plugins indexed
│   │   └── signal_map.py           # File patterns → technology → plugin mapping
│   ├── tools/                      # Local tool implementations
│   │   ├── github.py               # GitHub API (gh CLI / GITHUB_TOKEN fallback)
│   │   ├── yaml_writer.py          # Atomic YAML writes with backup
│   │   ├── compose.py              # Podman/Docker compose operations
│   │   └── health_check.py         # RHDH health check + log-based error diagnosis
│   └── ui/                         # CLI interface
│       └── app.py                  # Rich TUI — input, progress, proposals, review
├── pyproject.toml                  # Python project config
├── compose.yaml                    # RHDH Local container orchestration
├── configs/                        # RHDH configuration (agents write overrides here)
│   ├── dynamic-plugins/            # Plugin configs (default + override)
│   ├── catalog-entities/           # Catalog entity YAML
│   └── app-config/                 # App config YAML
├── plan.md                         # Implementation plan and status
└── ...                             # RHDH Local base files (scripts, docs, etc.)
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Clean SDK support, strong YAML/JSON tooling, fast iteration |
| Agent Runtime | Anthropic Managed Agents SDK | Server-side agents, coordinator pattern, streaming, persistence |
| Model | `claude-sonnet-4-6` | Fast, strong tool use, cost-effective for multi-agent workloads |
| CLI Framework | Rich + Typer | Interactive TUI with tables, progress, prompts |
| Data Models | Pydantic v2 | Typed, validated, serializable |
| Plugin Data | RHDH Catalog Index Image | Authoritative source, version-matched, no vector DB |
| HTTP Client | httpx | Async-ready, modern Python HTTP |
| Container Runtime | Podman/Docker (auto-detected) | For RHDH lifecycle management |

## Signals Detected

The scanner agent recognizes these technologies from repo file patterns:

| Signal | File Patterns | Maps To |
|--------|--------------|---------|
| GitHub Actions | `.github/workflows/*.yml` | github-actions plugin |
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

The config writer agent doesn't just write files and hope for the best. It follows a resilience loop:

```
Write config → Restart RHDH → Health check → Check logs for errors
    │                                              │
    │              ┌───────────────────────────────┘
    │              ▼
    │         Error found?
    │          ├── Missing env var → add placeholder to .env, retry
    │          ├── Bad config → fix YAML, retry
    │          ├── OCI pull failed → try alternative version, retry
    │          └── Max retries (3) → disable plugin, report failure
    │
    └── Never silently gives up — always reports what happened
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

## Additional RHDH Local Guides

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
