# Agentic RHDH Local — Implementation Plan

## Context

RHDH onboarding is painful: users must manually discover plugins, write pluginConfig YAML, create catalog entities, and configure app-config — all before seeing value. This system flips the model: users provide their repo URLs and the system automatically proposes the right plugins, catalog entities, and configuration. A multi-agent architecture handles scanning, recommendation, and config writing, with resilience built into every step.

This is a proof-of-concept built on [RHDH Local](https://github.com/redhat-developer/rhdh-local) and the [Anthropic Claude API via Google Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude).

---

## Architecture

A single unified agent with 4 specialist capabilities, driven by a tool-use loop:

```
┌─────────────────────────────────────────────────────┐
│                  CLI (Rich TUI)                      │
│   User adds repos → sees proposals → approves       │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│          Unified RHDH Onboarding Agent               │
│   Claude via Messages API + tool-use loop            │
│                                                      │
│   Capabilities:                                      │
│   ├── Repo Scanner — scan_repo_tree, read_repo_file │
│   ├── Plugin Recommender — knowledge base context    │
│   ├── Entity Generator — type inference rules        │
│   └── Config Writer — write_yaml, restart, health    │
└────────────────────────┬────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Local Tool Dispatch │
              │  (Python handlers)   │
              └─────────────────────┘
```

### Agent Runtime: Messages API with Tool-Use Loops

**Why Messages API over Managed Agents SDK:**
- Works with Google Vertex AI (Red Hat's Claude access is via Vertex, not direct Anthropic API)
- The `anthropic` Python SDK supports both backends identically via `AnthropicVertex`
- Each "agent" is a system prompt + tool set — no server-side state to manage
- Tool-use loop in Python gives explicit control over orchestration and resilience
- Simpler debugging: you can see every message and tool call
- No dependency on beta APIs that could change

**Client:** `AnthropicVertex(region, project_id)` auto-detected from env vars, falls back to `Anthropic()` if `ANTHROPIC_API_KEY` is set
**Model:** `claude-sonnet-4-6`

### How the Tool-Use Loop Works

```
User message → client.messages.create(system, tools, messages)
                         │
                         ▼
                  stop_reason?
                  ├── "end_turn" → done, extract text response
                  └── "tool_use" → for each tool_use block:
                                     dispatch locally (GitHub API, YAML write, etc.)
                                     collect tool_results
                                     append to messages
                                     loop back to messages.create()
```

The agent calls tools as needed — scanning repos, reading files, writing configs — and the Python loop handles execution. Max 25 turns per phase to prevent runaway loops.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Clean SDK support, strong YAML/JSON tooling, fast iteration |
| AI Backend | Google Vertex AI (Claude) | Red Hat's provisioned access to Claude models |
| SDK | `anthropic` with `AnthropicVertex` | Same Messages API for both Vertex and direct Anthropic |
| Model | `claude-sonnet-4-6` | Fast output, strong tool use, cost-effective |
| CLI Framework | Rich + Typer | Interactive TUI with tables, progress, prompts |
| Data Models | Pydantic v2 | Typed, validated, serializable |
| Plugin Data | Extracted catalog index (JSON/YAML) | Authoritative, version-matched, no vector DB |
| HTTP Client | httpx | Modern Python HTTP |
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
│   ├── agents/                     # Agent orchestration
│   │   ├── __init__.py
│   │   ├── client.py               # Client factory (Vertex AI / direct Anthropic)
│   │   ├── prompts.py              # System prompts (specialist + unified)
│   │   ├── tools.py                # Tool definitions (Messages API format)
│   │   └── session.py              # Tool-use loop + local tool dispatch
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

---

## Agent Capabilities

The unified agent has all 4 specialist capabilities built into one system prompt:

### Repo Scanner

Scans GitHub repos via custom tools, detects 16 technology signals:

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

**Tools:** `scan_repo_tree`, `read_repo_file`, `get_repo_languages`, `get_repo_info`

### Plugin Recommender

Maps detected signals to RHDH plugins using the knowledge base (injected into system prompt). Resolves frontend+backend package pairs, pulls complete pluginConfig, identifies required env vars, checks for conflicts.

**Tools:** None (uses knowledge base context in system prompt)

### Catalog Entity Generator

Creates Backstage Component entities with inferred type, lifecycle, and annotations.

**Tools:** None (generative from scan results)

### Config Writer (with Resilience)

Writes override YAML files, restarts RHDH, verifies health, diagnoses errors, retries.

**Tools:** `write_yaml`, `restart_rhdh`, `check_rhdh_health`, `diagnose_plugin_errors`, `read_container_logs`

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

---

## CLI Flow

```
agentic-rhdh
  │
  ├── Show banner
  ├── Collect repo URLs (interactive prompt, validated)
  ├── Extract catalog index image → build PluginKnowledgeBase (84 plugins)
  ├── Create Claude client (Vertex AI or direct Anthropic, auto-detected)
  ├── Build unified system prompt with knowledge base context
  ├── SCAN+PROPOSE PHASE: run_agent_loop() with repo URLs
  │   └── Agent calls scan_repo_tree, read_repo_file, etc. via tool-use loop
  │       Then recommends plugins + generates entities
  │       Returns structured JSON proposals
  ├── Parse agent response → PluginProposal[] + CatalogEntityProposal[]
  ├── Display proposals in Rich tables
  ├── Prompt: [a] Accept all  [e] Edit selections  [r] Reject all
  ├── APPLY PHASE: run_agent_loop() with approved proposals
  │   └── Agent calls write_yaml, restart_rhdh, check_rhdh_health
  │       Follows resilience loop for error recovery
  └── Show completion: plugins enabled, entities added, required env vars
```

---

## Implementation Phases & Status

### Phase 1: Foundation — COMPLETE ✓

- [x] Python project scaffold (`pyproject.toml`, package structure)
- [x] Pydantic data models (`models.py`)
  - `RepoProfile`, `DetectedSignal`, `PluginProposal`, `CatalogEntityProposal`
  - `PluginInfo`, `PluginPackage`, `OnboardingState`
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

### Phase 2: Agents — COMPLETE ✓ (originally Managed Agents, now refactoring)

- [x] System prompts for specialist roles (`agents/prompts.py`)
  - Scanner, Recommender, Entity Generator, Config Writer, Coordinator
- [x] Custom tool JSON Schema definitions (`agents/tools.py`)
  - 9 custom tools: scan_repo_tree, read_repo_file, get_repo_languages, get_repo_info, write_yaml, restart_rhdh, check_rhdh_health, diagnose_plugin_errors, read_container_logs

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
  - `show_banner()`, `collect_repos()`, `show_plugin_proposals()`, `show_entity_proposals()`
  - `prompt_review()`, `show_apply_progress()`, `show_completion()`
  - `parse_proposals_from_messages()` — extracts JSON from agent responses
- [x] CLI entry point (`__main__.py`)
  - Typer app with `--project-dir` option
  - `agentic-rhdh` console script

### Phase 4.5: Vertex AI Refactor — COMPLETE ✓

The original implementation used Anthropic Managed Agents SDK (`client.beta.agents`), which requires a direct Anthropic API key. Red Hat provides Claude via Google Vertex AI, so we refactored to use the standard Messages API with tool-use loops.

- [x] **Created `agents/client.py`** — Client factory that auto-detects Vertex AI (`CLAUDE_CODE_USE_VERTEX=1`) or direct Anthropic (`ANTHROPIC_API_KEY`)
- [x] **Updated `agents/tools.py`** — Removed `"type": "custom"` (Messages API format), added `ALL_TOOLS` flat list
- [x] **Added unified prompt to `agents/prompts.py`** — `UNIFIED_SYSTEM` combining all 4 specialist roles + workflow. `build_unified_system()` appends knowledge base context
- [x] **Rewrote `agents/session.py`** — `run_agent_loop()` calls `client.messages.create()` in a loop, `dispatch_tool()` handles 9 tools locally. Removed SessionContext, create_session, send_user_message
- [x] **Deleted `agents/setup.py`** — No more server-side agent creation or caching
- [x] **Updated `models.py`** — Removed `AgentIDs`
- [x] **Rewrote `ui/app.py`** — Uses `create_client()` + `run_agent_loop()`. Two-phase flow: scan+propose, then apply
- [x] **Updated `agents/__init__.py`** — New exports: `create_client`, `run_agent_loop`, `ALL_TOOLS`

**Verified:** `AnthropicVertex` client creates successfully with user's GCP credentials. All 9 tools, imports, and CLI entry point work.

### Phase 5: Resilience + Polish — TODO

- [ ] Integration testing with real repos
- [ ] Error recovery testing (deliberate misconfigs)
- [ ] Edge cases (empty repos, private repos, existing catalog-info.yaml)
- [ ] Unit tests (signal detection, knowledge base, YAML writer, URL parsing)
- [ ] Polish (--verbose flag, --dry-run flag, improved proposal parsing)

---

## Key Design Decisions

1. **Messages API over Managed Agents** — Managed Agents is Anthropic-only. Messages API works identically on Vertex AI and direct Anthropic. Same model, same tools, same results — just a different client constructor.

2. **Unified agent over multi-agent** — One system prompt with all 4 capabilities is simpler than coordinating separate agents. The model handles role-switching internally. Tool-use loop gives Python-level control over orchestration.

3. **No vector DB** — The plugin catalog is small (~84 plugins), structured, and version-matched. A JSON index with deterministic matching is more reliable than semantic search for config generation.

4. **Catalog index as source of truth** — `dynamic-plugins.default.yaml` already has every plugin's complete config. The agent doesn't guess or hallucinate config blocks — it uses the exact config from the authoritative source.

5. **Override files only** — Agent never modifies default configs. Everything goes through the established override system (`dynamic-plugins.override.yaml`, `app-config.local.yaml`, etc.).

6. **Custom tools execute locally** — Agent reasons about what to do; CLI executes it locally. This keeps sensitive operations (file writes, compose commands) under user control.

7. **Python over TypeScript** — Cleaner Anthropic SDK support, less tooling friction, stronger YAML/JSON ecosystem, faster iteration for a POC.

---

## Verification Plan

1. **Imports clean**: `python3 -c "from agentic.agents import create_client, run_agent_loop"`
2. **CLI runs**: `agentic-rhdh --help`
3. **Integration test**: Full flow with a sample GitHub repo → verify generated override YAML is valid
4. **E2E test**: Run the CLI, add a repo with known technologies, accept proposals, verify RHDH starts with plugins active at `localhost:7007`
5. **Resilience test**: Deliberately misconfigure a plugin, verify the agent detects the error, fixes it, and retries
