# Agentic RHDH Local — Implementation Plan

## Context

RHDH onboarding is painful: users must manually discover plugins, write pluginConfig YAML, create catalog entities, and configure app-config — all before seeing value. This system flips the model: users provide their repo URLs and the system automatically proposes the right plugins, catalog entities, and configuration. A multi-agent architecture handles scanning, recommendation, and config writing, with resilience built into every step.

This is a proof-of-concept built on [RHDH Local](https://github.com/redhat-developer/rhdh-local) and the [Anthropic Managed Agents SDK](https://docs.anthropic.com/en/docs/agents-and-tools/managed-agents).

---

## Architecture

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

### Agent Runtime: Anthropic Managed Agents SDK

**Why Managed Agents over raw API calls:**
- Agents are server-side objects with persistent identity — create once, reuse across sessions
- Coordinator pattern handles agent-to-agent handoffs natively
- Each agent runs in its own session thread with isolated conversation history
- Built-in `agent_toolset_20260401` provides bash, file ops, web search out of the box
- Custom tools for domain-specific operations (YAML writes, health checks)
- Streaming events for real-time CLI progress updates
- Session persistence (30 days) — can resume interrupted onboarding

**SDK:** `anthropic` Python SDK with `client.beta.agents`
**Model:** `claude-sonnet-4-6` (fast, capable, cost-effective for tool-heavy agents)

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Clean SDK support, strong YAML/JSON tooling, fast iteration |
| Agent Runtime | Anthropic Managed Agents SDK | Server-side agents, coordinator pattern, streaming, persistence |
| Model | `claude-sonnet-4-6` | Fast output, strong tool use, cost-effective for multi-agent |
| CLI Framework | Rich + Typer | Interactive TUI with tables, progress, prompts |
| Data Models | Pydantic v2 | Typed, validated, serializable |
| Plugin Data | Extracted catalog index (JSON/YAML) | Authoritative, version-matched, no vector DB |
| HTTP Client | httpx | Modern Python HTTP with async support |
| Container Runtime | Podman/Docker (auto-detected) | For RHDH health checks and restarts |
| GitHub Auth | `gh` CLI fallback to `GITHUB_TOKEN` | Zero config for most users |

---

## Data Sources (No Vector DB)

The catalog index image (`quay.io/rhdh/plugin-catalog-index:1.9`) contains everything we need as structured data:

- **`index.json`** — Every plugin's OCI reference, version, base64-encoded package metadata
- **`dynamic-plugins.default.yaml`** — Complete pluginConfig blocks for all ~84 plugins (mount points, routes, env vars, etc.)
- **`catalog-entities/extensions/plugins/*.yaml`** — Plugin definitions with categories, tags, descriptions
- **`catalog-entities/extensions/packages/*.yaml`** — Package definitions with `appConfigExamples` containing exact config needed
- **`catalog-entities/extensions/collections/*.yaml`** — Curated groupings (recommended, featured, cicd, openshift, redhat)

At startup, the CLI extracts this image via podman/docker and builds a structured `PluginKnowledgeBase` (in-memory JSON). No embedding, no similarity search — deterministic matching against repo signals.

---

## Project Structure

```
agentic-rhdh-local/
├── agentic/                        # Multi-agent onboarding system
│   ├── __init__.py                 # Package init + version
│   ├── __main__.py                 # CLI entry point (Typer app)
│   ├── models.py                   # Pydantic data models
│   ├── agents/                     # Agent definitions & orchestration
│   │   ├── __init__.py
│   │   ├── prompts.py              # System prompts for all 5 agents
│   │   ├── tools.py                # Custom tool JSON Schema definitions
│   │   ├── setup.py                # Agent creation via Managed Agents API
│   │   └── session.py              # Session lifecycle, event streaming, tool dispatch
│   ├── knowledge/                  # Plugin knowledge base
│   │   ├── __init__.py
│   │   ├── extractor.py            # Extracts catalog index image (podman/docker)
│   │   ├── plugin_index.py         # PluginKnowledgeBase — structured plugin lookup
│   │   └── signal_map.py           # File patterns → technology → plugin mapping
│   ├── tools/                      # Local tool implementations
│   │   ├── __init__.py
│   │   ├── github.py               # GitHub API (gh CLI / GITHUB_TOKEN fallback)
│   │   ├── yaml_writer.py          # Atomic YAML writes with backup + validation
│   │   ├── compose.py              # Podman/Docker compose operations
│   │   └── health_check.py         # RHDH health check + log-based error diagnosis
│   └── ui/                         # CLI interface
│       ├── __init__.py
│       └── app.py                  # Rich TUI — input, progress, proposals, review
├── pyproject.toml                  # Python project config + dependencies
├── compose.yaml                    # RHDH Local container orchestration
├── configs/                        # RHDH configuration (agents write overrides here)
│   ├── dynamic-plugins/
│   │   ├── dynamic-plugins.yaml    # Default plugin config
│   │   └── dynamic-plugins.override.yaml  # Agent writes here
│   ├── catalog-entities/
│   │   ├── users.yaml              # Default user entity
│   │   └── components.override.yaml       # Agent writes here
│   └── app-config/
│       ├── app-config.yaml         # Main RHDH config
│       └── app-config.local.yaml   # Agent writes here
├── plan.md                         # This file
└── ...                             # RHDH Local base files (scripts, docs, etc.)
```

**19 Python source files, ~2,150 lines of code.**

---

## Agent Details

### 1. Repo Scanner Agent

**Input:** List of GitHub repo URLs
**Output:** `RepoProfile` per repo (structured JSON)

**Signals detected (16 patterns):**

| Signal | File Patterns | Plugin |
|--------|--------------|--------|
| GitHub Actions | `.github/workflows/*.yml` | github-actions |
| Tekton | `tekton/`, `.tekton/`, `apiVersion: tekton.dev/` | tekton |
| Jenkins | `Jenkinsfile` | jenkins |
| Azure DevOps | `azure-pipelines.yml` | azure-devops |
| ArgoCD | `argocd/`, `argoproj.io/` | argocd |
| Kubernetes | `k8s/`, `deploy/`, `manifests/`, `apiVersion: apps/v1` | kubernetes, topology |
| Helm | `Chart.yaml` | kubernetes |
| Docker | `Dockerfile`, `Containerfile` | topology |
| Quay | `quay.io/` references | quay |
| TechDocs | `mkdocs.yml`, `docs/` | techdocs |
| OpenAPI | `openapi.yaml`, `swagger.json` | api-docs |
| SonarQube | `sonar-project.properties` | sonarqube |
| GitHub PRs | `.github/` (low confidence) | github-pull-requests |
| Backstage | `catalog-info.yaml` | Direct import |
| Ansible | `ansible/`, `playbooks/`, `roles/` | ansible-plugin |
| 3scale | `3scale` references | 3scale |

**Custom tools:**
- `scan_repo_tree(owner, repo)` — Full file tree via GitHub API
- `read_repo_file(owner, repo, path)` — Read specific file content
- `get_repo_languages(owner, repo)` — Language breakdown
- `get_repo_info(owner, repo)` — Default branch, description, topics

### 2. Plugin Recommender Agent

**Input:** `RepoProfile[]` + plugin knowledge base (injected into system prompt)
**Output:** `PluginProposal[]`

**Logic:**
1. For each detected signal, look up matching plugins in the knowledge base
2. Resolve plugin pairs (frontend + backend packages)
3. Pull complete `pluginConfig` from `dynamic-plugins.default.yaml`
4. Identify required env vars (`${VAR_NAME}` in config)
5. Check for conflicts (e.g., don't enable both roadie-argocd and redhat-argocd)
6. Rank by confidence

### 3. Catalog Entity Generator Agent

**Input:** `RepoProfile[]` from scanner
**Output:** `CatalogEntityProposal[]`

**Type inference rules:**
- `Dockerfile` + backend language → `service`
- `package.json` with React/Angular/Vue → `website`
- Library code only → `library`
- Helm charts, Terraform, infra → `resource`

**Annotations added:**
- `github.com/project-slug` (always)
- `backstage.io/techdocs-ref` (if TechDocs detected)
- `backstage.io/kubernetes-id` (if Kubernetes detected)

### 4. Config Writer Agent (with Resilience)

**Files it modifies (override only):**
- `configs/dynamic-plugins/dynamic-plugins.override.yaml` — enables plugins with pluginConfig
- `configs/catalog-entities/components.override.yaml` — adds component entities
- `configs/app-config/app-config.local.yaml` — adds catalog locations

**Custom tools:**
- `write_yaml(path, content)` — Atomic write with backup + validation
- `restart_rhdh()` — Compose restart
- `check_rhdh_health(wait, max_wait)` — HTTP health check with polling
- `diagnose_plugin_errors(lines)` — Parse container logs for errors
- `read_container_logs(service, lines)` — Raw log access

**Resilience loop:**
```
Write config → Restart RHDH → Health check → Check logs
                                                 │
                    ┌────────────────────────────┘
                    ▼
               Error found?
                ├── Missing env var → add placeholder, retry
                ├── Bad config → fix YAML, retry
                ├── OCI pull failed → try alt version, retry
                └── Max retries (3) → disable plugin, report
```

### 5. Coordinator Agent

Orchestrates the full pipeline:
1. **Scan Phase** — Send repos to Scanner (parallel per repo)
2. **Analysis Phase** — Send profiles to Recommender + Entity Generator (parallel)
3. **Proposal Phase** — Collect and return proposals to user
4. **Apply Phase** — After approval, send to Config Writer
5. **Verify** — Ensure Config Writer reports success or specific failures

---

## CLI Flow

```
agentic-rhdh
  │
  ├── Show banner
  ├── Collect repo URLs (interactive prompt, validated)
  ├── Extract catalog index image → build PluginKnowledgeBase (84 plugins)
  ├── Create Managed Agents (idempotent, cached in ~/.cache/agentic-rhdh/)
  ├── Create session → send repos to coordinator
  ├── Stream events → show scan progress in real-time
  ├── Parse agent responses → PluginProposal[] + CatalogEntityProposal[]
  ├── Display proposals in Rich tables
  ├── Prompt: [a] Accept all  [e] Edit selections  [r] Reject all
  ├── Send approved proposals to coordinator → Config Writer applies
  └── Show completion: plugins enabled, entities added, required env vars
```

---

## Implementation Phases & Status

### Phase 1: Foundation — COMPLETE ✓

- [x] Python project scaffold (`pyproject.toml`, package structure)
- [x] Pydantic data models (`models.py`)
  - `RepoProfile`, `DetectedSignal`, `PluginProposal`, `CatalogEntityProposal`
  - `PluginInfo`, `PluginPackage`, `AgentIDs`, `OnboardingState`
- [x] Catalog index extractor (`knowledge/extractor.py`)
  - Pulls `quay.io/rhdh/plugin-catalog-index:1.9` via podman/docker
  - Extracts and parses `index.json`, `dynamic-plugins.default.yaml`, plugin/package YAMLs
- [x] Plugin knowledge base (`knowledge/plugin_index.py`)
  - `PluginKnowledgeBase.build()` — loads 84 plugins with packages, configs, OCI refs
  - Lookup by name, search by text, filter by category
  - `to_agent_context()` — serializes to text for agent system prompts
- [x] Signal-to-plugin mapping (`knowledge/signal_map.py`)
  - 16 technology patterns with file globs, content patterns, confidence levels
  - Maps each signal to plugin names, categories, required env vars

### Phase 2: Agents — COMPLETE ✓

- [x] System prompts for all 5 agents (`agents/prompts.py`)
  - Scanner, Recommender, Entity Generator, Config Writer, Coordinator
- [x] Custom tool JSON Schema definitions (`agents/tools.py`)
  - 9 custom tools: scan_repo_tree, read_repo_file, get_repo_languages, get_repo_info, write_yaml, restart_rhdh, check_rhdh_health, diagnose_plugin_errors, read_container_logs
- [x] Agent creation via Managed Agents API (`agents/setup.py`)
  - Creates 4 specialists + 1 coordinator with `multiagent.type = "coordinator"`
  - Idempotent — caches agent IDs in `~/.cache/agentic-rhdh/agent_ids.json`
  - Validates cached agents still exist before reuse
- [x] Session management (`agents/session.py`)
  - Creates environment + session
  - Sends user messages, streams events
  - Dispatches custom tool calls to local handlers
  - Collects agent messages for proposal parsing

### Phase 3: Tool Implementations — COMPLETE ✓

- [x] GitHub API tools (`tools/github.py`)
  - `parse_repo_url()`, `get_repo_tree()`, `get_repo_languages()`, `get_file_content()`
  - Uses `gh` CLI when available, falls back to `GITHUB_TOKEN` + httpx
  - `match_file_patterns()` — glob matching against file trees
- [x] Atomic YAML writer (`tools/yaml_writer.py`)
  - `write_yaml()` — temp file → validate → rename (atomic)
  - Backup existing files before overwrite
  - `merge_yaml_file()`, `append_to_yaml_list()` for incremental updates
- [x] Compose operations (`tools/compose.py`)
  - Auto-detects podman compose / docker compose / docker-compose
  - `restart_rhdh()`, `run_install_plugins()`, `get_container_logs()`, `is_running()`
- [x] Health check (`tools/health_check.py`)
  - `check_rhdh_health()` — single HTTP check on localhost:7007/healthcheck
  - `wait_for_healthy()` — poll with configurable timeout
  - `diagnose_plugin_errors()` — regex patterns against container logs
  - `check_health_with_diagnosis()` — combined check + log diagnosis

### Phase 4: CLI UI — COMPLETE ✓

- [x] Rich TUI (`ui/app.py`)
  - `show_banner()` — styled double-border panel
  - `collect_repos()` — interactive multi-URL input with validation
  - `show_scan_progress()` — streaming event handler for real-time progress
  - `show_plugin_proposals()` / `show_entity_proposals()` — Rich tables
  - `prompt_review()` — accept all / edit / reject with toggle UI
  - `show_apply_progress()` — step-by-step apply status
  - `show_completion()` — final summary with required env vars
  - `parse_proposals_from_messages()` — extracts JSON from agent responses
- [x] CLI entry point (`__main__.py`)
  - Typer app with `--project-dir` option
  - `agentic-rhdh` console script

### Phase 5: Resilience + Polish — TODO

- [ ] **Integration testing with real repos**
  - Test full pipeline against known GitHub repos
  - Verify generated YAML is valid and matches expected plugins
  - Test with repos that have multiple technology signals

- [ ] **Error recovery testing**
  - Deliberately misconfigure a plugin, verify agent detects and fixes
  - Test missing env var scenario → agent adds placeholder
  - Test OCI pull failure → agent tries alternative version
  - Test max retries → agent disables plugin and reports clearly

- [ ] **Edge cases**
  - Empty repos, private repos, very large repos
  - Repos with existing `catalog-info.yaml` (should import, not regenerate)
  - Multiple repos with conflicting plugin versions
  - No container runtime available (graceful error)

- [ ] **Unit tests**
  - Signal detection accuracy: known file trees → expected `DetectedSignal[]`
  - Plugin knowledge base: verify all 84 plugins load with correct packages
  - YAML writer: atomic write, backup creation, merge behavior
  - GitHub URL parsing: various URL formats

- [ ] **Polish**
  - Update plan.md TypeScript references (this update)
  - Improve proposal parsing robustness (handle partial JSON, nested responses)
  - Add `--verbose` flag for debug output
  - Add `--dry-run` flag to show proposals without applying

---

## Key Design Decisions

1. **Anthropic Managed Agents** — Server-side agents with coordinator pattern. Production-grade, built-in tool execution, streaming events, session persistence. No custom orchestration code needed.

2. **No vector DB** — The plugin catalog is small (~84 plugins), structured, and version-matched. A JSON index with deterministic matching is more reliable than semantic search for config generation.

3. **Catalog index as source of truth** — `dynamic-plugins.default.yaml` already has every plugin's complete config. The agents don't guess or hallucinate config blocks — they use the exact config from the authoritative source.

4. **Override files only** — Agents never modify default configs. Everything goes through the established override system (`dynamic-plugins.override.yaml`, `app-config.local.yaml`, etc.).

5. **Custom tools execute locally** — Agent reasons about what to do; CLI executes it locally. This keeps sensitive operations (file writes, compose commands) under user's control while leveraging agent intelligence for decisions.

6. **Batch + restart** — Enable all approved plugins at once, then restart RHDH once. Only fall back to per-plugin restarts if batch fails.

7. **Python over TypeScript** — Cleaner Anthropic SDK support, less tooling friction (no tsc compilation issues), stronger YAML/JSON ecosystem, faster iteration for a POC.

---

## Verification Plan

1. **Unit tests**: Signal detection accuracy against known repo file trees
2. **Integration test**: Full flow with a sample GitHub repo → verify generated override YAML is valid
3. **E2E test**: Run the CLI, add a repo with known technologies, accept proposals, verify RHDH starts with plugins active at `localhost:7007`
4. **Resilience test**: Deliberately misconfigure a plugin, verify the agent detects the error, fixes it, and retries
