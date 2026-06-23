# Agentic RHDH Local — Technical Specification

> **Status:** Proof-of-concept (not production software)  
> **Version:** 0.1 (DevConf 2026 demo)  
> **Repository:** [github.com/Fortune-Ndlovu/agentic-rhdh-local](https://github.com/Fortune-Ndlovu/agentic-rhdh-local)

---

## 1. Executive overview

**Agentic RHDH Local** (`agentic-rhdh`) is a Python CLI that automates first-day onboarding for [Red Hat Developer Hub](https://developers.redhat.com/rhdh) (RHDH) when running on top of [RHDH Local](https://github.com/redhat-developer/rhdh-local).

A platform engineer or developer provides **GitHub repository URLs**. The system:

1. Scans those repositories for technology signals (CI, docs, Kubernetes, quality tooling, etc.).
2. Maps signals to **RHDH dynamic plugins** using a grounded plugin catalog (~84 plugins).
3. Proposes **Backstage catalog entities** and **TechDocs** scaffolding.
4. Lets the user **review and approve** proposals.
5. Writes **override-layer configuration only** (never replaces RHDH defaults).
6. Restarts RHDH Local and verifies health.

The agent is built on the **Anthropic Messages API** with a **tool-use loop** (Claude Sonnet 4.6 via direct API or Vertex AI). It runs **alongside** RHDH Local and **Developer Lightspeed** — it configures the portal; Lightspeed helps users once the portal is running.

---

## 2. Problem statement

Standing up a useful RHDH instance requires non-trivial platform knowledge:

| Task | Pain point |
|------|------------|
| Plugin selection | 80+ dynamic plugins; wrong choice wastes time or breaks startup |
| `pluginConfig` YAML | Exact OCI refs, mount points, and env vars are easy to get wrong |
| Catalog entities | Correct annotations (`source-location`, `techdocs-ref`, `project-slug`) are subtle |
| TechDocs | `mkdocs.yml`, local `dir:` refs, and README ingestion must align |
| Safe layering | Overrides must **include** defaults — a bare override replaces tech-radar, FAB, Lightspeed, etc. |
| Restart/debug | Plugin installer failures require log archaeology |

Users expect **immediate, tailored value** when onboarding to a new platform — not a generic empty portal and a week of YAML trial-and-error.

---

## 3. Design goals

| Goal | How it is achieved |
|------|---------------------|
| **Grounded recommendations** | Plugin catalog extracted from official RHDH catalog index OCI image |
| **Fast, cheap scanning** | Local pre-scan via GitHub API + signal map (no LLM for selection) |
| **Human control** | Explicit approval before any config is written |
| **Non-destructive** | Writes only to override files; `agentic-rhdh reset` restores baseline |
| **Self-healing apply** | Write → restart → health check → log diagnosis → retry (prompt-guided) |
| **Coexistence with Lightspeed** | Never rewrites Lightspeed plugin entries; inherits via `includes:` chain |

---

## 4. System architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         User (terminal TUI)                              │
│                    agentic-rhdh  /  agentic-rhdh reset                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────┐
│  agentic/ui/app.py          Orchestrator & Rich progress display       │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ scanner.py    │       │ knowledge/      │       │ agents/         │
│ signal_map    │       │ plugin_index    │       │ session.py      │
│ (local)       │       │ extractor       │       │ prompts.py      │
└───────┬───────┘       └────────┬────────┘       │ client.py       │
        │                        │                └────────┬────────┘
        │                        │                         │
        └────────────────────────┼─────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Anthropic Messages API │
                    │  (Claude Sonnet 4.6)    │
                    │  Vertex AI or direct    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  tools/                 │
                    │  github, yaml_writer,   │
                    │  compose, health_check  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  RHDH Local (Podman)    │
                    │  configs/ override layer│
                    │  + Developer Lightspeed │
                    └─────────────────────────┘
```

### 4.1 Source layout

```text
agentic/
├── __main__.py           Typer CLI entry point
├── models.py             Pydantic models (RepoProfile, PluginProposal, …)
├── scanner.py            Local pre-scan & proposal builder
├── ui/
│   ├── app.py            Main pipeline & user interaction
│   └── progress.py       Rich TUI for tool/scan events
├── knowledge/
│   ├── extractor.py      Pull & parse RHDh plugin catalog index image
│   ├── plugin_index.py   Searchable in-memory plugin KB
│   └── signal_map.py     File-pattern → plugin mapping
├── agents/
│   ├── client.py         Anthropic / Vertex client factory
│   ├── session.py        Tool-use loop & dispatch_tool()
│   ├── prompts.py        UNIFIED_SYSTEM prompt & policies
│   └── tools.py          Tool JSON schemas for Messages API
└── tools/
    ├── github.py         GitHub REST API
    ├── yaml_writer.py    Atomic YAML I/O with backups
    ├── compose.py        Podman/Docker compose restart
    └── health_check.py   /healthcheck polling & log diagnosis
```

---

## 5. End-to-end pipeline

### Phase 0 — Prerequisites

- RHDH Local running (`podman compose up -d`), optionally with Lightspeed overlay.
- Claude auth: `ANTHROPIC_API_KEY` **or** `CLAUDE_CODE_USE_VERTEX=1` + `ANTHROPIC_VERTEX_PROJECT_ID`.
- GitHub auth: `gh auth login` or `GITHUB_TOKEN` for repo scanning and Tier 2 plugins.

### Phase 1 — Input

User enters one or more GitHub URLs via the Rich TUI (`collect_repos()`).

### Phase 2 — Knowledge base bootstrap

1. Pull/extract `quay.io/rhdh/plugin-catalog-index:1.9` (cached under `/tmp/rhdh-catalog-extract`).
2. Parse plugin YAMLs, package YAMLs, and `dynamic-plugins.default.yaml` entries.
3. Build `PluginKnowledgeBase` (~84 plugins) with OCI refs, `pluginConfig`, env var requirements, and tier classification.

This KB is serialized into the **system prompt** (`kb.to_agent_context()`) so the LLM knows blocked plugins, always-include plugins, and the full catalog.

### Phase 3 — Local pre-scan (no LLM)

For each repo, **in parallel**:

| Step | Source | Output |
|------|--------|--------|
| Repo metadata | GitHub API | description, default branch, topics |
| File tree | GitHub API | all paths |
| Languages | GitHub API | language percentages |
| Signal detection | `signal_map.py` | technologies + evidence paths |
| Catalog check | GitHub API | existing `catalog-info.yaml` if present |

`build_proposals()` then:

- Adds **always-include** plugins (`adoption-insights`, `notifications`).
- Maps each detected signal to plugins via `SIGNAL_MAP`.
- Skips **blocked** plugins (e.g. `github-issues`, `kubernetes` when env not configured).
- Looks up exact package refs from KB (`get_plugin_config_details`).
- Generates **CatalogEntityProposal** per repo (type inferred from signals/languages).

### Phase 4 — AI enrichment (LLM, no tools)

A **single** `run_agent_loop()` call with `tools=[]` and `max_turns=1`:

- Input: pre-built `RepoProfile`, `PluginProposal`, and `CatalogEntityProposal` JSON.
- Task: rewrite `reason` and `description` fields to be repo-specific and contextual.
- Output: parsed `PLUGIN_PROPOSALS` / `ENTITY_PROPOSALS` JSON blocks.

**Why separate from apply?** Cheaper, safer, and keeps plugin *selection* deterministic while LLM adds *explanation* quality.

### Phase 5 — Human review

User selects `all`, `none`, row numbers, or natural-language adjustments (`prompt_review()`). Nothing is written until approval.

### Phase 6 — Baseline snapshot

`app-config.local.yaml` copied to `.baseline` so `agentic-rhdh reset` can restore.

### Phase 7 — Apply (LLM + full tools)

Second `run_agent_loop()` with `tools=ALL_TOOLS` and shared `messages` history:

1. Read existing override files (`read_yaml`).
2. Write/merge config (see §8).
3. `restart_rhdh` (fast path: plugin reinstall + `compose restart rhdh`).
4. `check_rhdh_health(wait=true)`.
5. `diagnose_plugin_errors()` if needed; retry per resilience protocol.

### Phase 8 — Report

Generates `ONBOARDING.md` with enabled plugins, entities, config paths, and required env vars.

---

## 6. Plugin recommendation system

Recommendation is a **hybrid pipeline** — not pure LLM guessing.

```text
GitHub file tree
      │
      ▼
┌─────────────────┐
│  SIGNAL_MAP     │  Pattern match (.github/workflows → github-actions)
│  (deterministic)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  BLOCKED filter │  github-issues, kubernetes (no cluster creds), …
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ALWAYS INCLUDE │  adoption-insights, notifications
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Plugin KB      │  Exact OCI ref, pluginConfig, tier, env vars
│  lookup         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Claude enrich  │  Contextual reasons, Tier 3 surfacing in prose
└────────┬────────┘
         │
         ▼
   User approval
```

### 6.1 Signal map

Defined in `agentic/knowledge/signal_map.py`. Each `SignalPattern` maps:

- **technology** — e.g. `github-actions`, `techdocs`, `helm`
- **file_patterns** — glob matches against repo tree
- **plugins** — one or more plugin names in the KB
- **confidence** — `high` | `medium` | `low`
- **required_env_vars** — surfaced in proposals

Examples:

| Signal | Evidence | Plugin(s) |
|--------|----------|-----------|
| `github-actions` | `.github/workflows/*.yml` | `github-actions` |
| `techdocs` | `mkdocs.yml`, `docs/**/*.md` | `techdocs` |
| `helm` | `Chart.yaml` | `kubernetes` (Tier 3) |
| `sonarqube` | `.sonarcloud.properties` | `sonarqube` (Tier 3) |

### 6.2 Plugin tiers

Classified in `PluginKnowledgeBase._classify_tier()`:

| Tier | Criteria | Auto-include? |
|------|----------|---------------|
| **1** | Bundled in RHDH image, no env vars | Yes, when signal matches |
| **2** | Needs `GITHUB_TOKEN` only | Yes, for GitHub repos with matching signals |
| **3** | External services (K8s, SonarQube, ArgoCD, …) | **No** — mentioned in enrichment text; user must supply creds |

Tier 3 plugins are **surfaced with context** (e.g. “both repos have `.sonarcloud.properties`”) but not written to override unless the user explicitly enables them later.

### 6.3 Always-include and blocked lists

**Always include** (every onboarding):

- `adoption-insights` — platform usage metrics
- `notifications` — in-app notifications

**Blocked** (never recommend):

- `github-issues` — runtime crash with `file:` source-location entities
- `kubernetes` / `kubernetes-backend` — startup failure when cluster env vars unset

**Lightspeed** is never proposed — it is pre-wired via `configs/dynamic-plugins/dynamic-plugins.lightspeed.yaml` in the `includes:` chain.

### 6.4 Contextual weighting (LLM enrichment)

The system prompt instructs Claude to weigh **primary vs incidental** signals:

- 11 GitHub Actions workflows → high-value `github-actions`
- Dockerfile only used for CI → low-value `topology` (often flagged for review/skip)
- Helm chart repo → entity type `resource`, not live workload topology

This mirrors human platform-engineering judgment without letting the LLM invent package refs.

---

## 7. AI techniques

### 7.1 Tool-use agent loop (Anthropic Messages API)

Implemented in `agentic/agents/session.py`:

```text
repeat up to max_turns (25):
  stream Claude response (system + tools + messages)
  if stop_reason == end_turn → done
  if stop_reason == tool_use:
    dispatch_tool() locally
    append tool_result to messages
    continue
```

Claude decides **which** tools to call and **when**; Python executes them and returns JSON results. This is Anthropic’s recommended pattern for **effective agents** — the model plans; code acts.

### 7.2 Two-speed LLM usage

| Call | Tools | Turns | Role |
|------|-------|-------|------|
| Enrich | `[]` | 1 | Natural language only — polish proposals |
| Apply | `ALL_TOOLS` | up to 25 | Write files, restart, verify |

Separating **reasoning/display** from **side-effecting actions** reduces cost, latency, and accidental writes.

### 7.3 Prompt engineering (`prompts.py`)

`UNIFIED_SYSTEM` is a large, structured system prompt containing:

- Role and goal (“layer on top of defaults”)
- SCAN+PROPOSE and APPLY workflows
- Plugin selection policy (tiers, blocked, always-include)
- Catalog entity rules (annotations, TechDocs, `file:` vs `url:`)
- Critical safety rules (never write `catalog.locations` to app-config)
- Resilience protocol (restart → health → diagnose → retry)

Appended at runtime: full plugin catalog text from `kb.to_agent_context()`.

### 7.4 Prompt caching

System prompt is sent with Anthropic **ephemeral cache** hint:

```python
system_with_cache = [
    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
]
```

Reduces token cost on multi-turn apply loops where the large catalog + rules are reused.

### 7.5 Streaming

`client.messages.stream()` delivers token deltas for UI feedback (`text_delta` → progress display). Agent logic waits for `get_final_message()` before tool dispatch — streaming is UX, not control flow.

### 7.6 Parallel tool execution

When Claude returns multiple `tool_use` blocks in one turn, `ThreadPoolExecutor` runs them concurrently (e.g. parallel GitHub reads during apply).

### 7.7 Grounding / RAG analogue

| Lightspeed | Agentic RHDH |
|------------|----------------|
| FAISS vector DB of RHDH product docs | Plugin catalog index OCI image |
| `file_search` tool at chat time | `lookup_plugin_config` + pre-loaded catalog in system prompt |
| Prevents hallucinated doc URLs | Prevents hallucinated OCI refs and `pluginConfig` |

Both systems **retrieve authoritative data** instead of trusting the LLM to invent infrastructure details.

### 7.8 Human-in-the-loop

Mandatory approval gate before apply. Aligns with Anthropic guidance: agents with **irreversible or infrastructure side effects** should require explicit user consent.

### 7.9 Verify-after-act

Apply phase always attempts:

1. `restart_rhdh`
2. `check_rhdh_health(wait=true)`
3. `diagnose_plugin_errors`

Prompt instructs: if health OK despite restart warning, **do not** retry the whole apply loop.

---

## 8. Configuration model (override layer)

The agent **only writes override files**:

| File | Purpose |
|------|---------|
| `configs/dynamic-plugins/dynamic-plugins.override.yaml` | Plugin packages + `includes:` chain |
| `configs/catalog-entities/components.override.yaml` | Location entity listing component YAML targets |
| `configs/catalog-entities/<name>-component.yaml` | Per-repo catalog entities |
| `configs/catalog-entities/<name>-docs/` | TechDocs (`mkdocs.yml`, `docs/index.md` from README) |
| `configs/app-config/app-config.local.yaml` | Merged plugin-specific app config (GitHub integration, etc.) |

### 8.1 Critical `includes:` chain

Override **must** start with:

```yaml
includes:
  - dynamic-plugins.default.yaml
  - dynamic-plugins.lightspeed.yaml
```

Without this, the override **replaces** all default plugins (tech-radar, quay, FAB, extensions, Lightspeed, scaffolder-github).

### 8.2 Catalog location safety

The agent must **never** write `catalog.locations` to `app-config.local.yaml` — Backstage array merge would destroy default locations. Entities are registered via `components.override.yaml` targets instead.

### 8.3 TechDocs local resolution

Entities use:

- `backstage.io/source-location: file:./configs/catalog-entities/<name>-component.yaml`
- `backstage.io/techdocs-ref: dir:./<name>-docs/`

Using `url:` source-location breaks local `dir:` TechDocs resolution.

---

## 9. Tool reference

| Tool | Phase | Description |
|------|-------|-------------|
| `scan_repo_tree` | Scan/Apply | Full GitHub file tree |
| `read_repo_file` | Apply | Fetch README, catalog-info, etc. |
| `get_repo_languages` | Scan/Apply | Language breakdown |
| `get_repo_info` | Scan/Apply | Description, branch, topics |
| `lookup_plugin_config` | Apply | KB lookup: refs, config, tier, env vars |
| `read_yaml` | Apply | Read local config before merge |
| `write_yaml` | Apply | Atomic full-file YAML write + backup |
| `merge_yaml` | Apply | Deep-merge into app-config.local.yaml |
| `write_file` | Apply | Markdown, mkdocs, etc. |
| `restart_rhdh` | Apply | Fast plugin reinstall + compose restart |
| `check_rhdh_health` | Apply | HTTP GET `/healthcheck` |
| `diagnose_plugin_errors` | Apply | Regex scan of rhdh logs |
| `read_container_logs` | Apply | Raw compose logs |

---

## 10. Relationship to Developer Lightspeed

Both systems use the **same agentic architecture pattern** at different layers:

```text
┌────────────────────────────────────────────────────────────────┐
│                    Shared agentic pattern                       │
├────────────────────────────────────────────────────────────────┤
│  Profile / system prompt   │  rhdh-profile.py  │  prompts.py   │
│  Knowledge grounding       │  FAISS RAG docs   │  Plugin KB    │
│  Orchestrator              │  Lightspeed Core  │  session.py   │
│  Tool loop                 │  Llama Stack      │  dispatch_tool│
│  LLM provider              │  Vertex (Gemini)  │  Claude       │
│  User surface              │  /lightspeed UI   │  agentic TUI  │
└────────────────────────────────────────────────────────────────┘
```

| Dimension | Developer Lightspeed | Agentic RHDH |
|-----------|---------------------|--------------|
| **When** | After RHDH is running | Before / during first useful config |
| **Job** | Answer questions, cite docs, optional MCP | Configure plugins + catalog from repos |
| **Memory** | SQLite conversation cache | Stateless CLI; `messages` list per run |
| **Side effects** | None on disk (chat only) | Writes YAML, restarts containers |
| **Config wiring** | `lightspeed-stack.yaml` → `config.yaml` + `rhdh-profile.py` | `prompts.py` + `tools/` + `configs/` |

**Together:** Agentic RHDH gets you to a **personalized portal**; Lightspeed helps you **use** that portal afterward (including RHDH documentation via RAG).

The agent explicitly **preserves** Lightspeed configuration — it never duplicates Lightspeed entries in `dynamic-plugins.override.yaml`.

---

## 11. Alignment with Anthropic “Building Effective Agents” practices

This PoC intentionally follows patterns recommended by Anthropic for production-grade agents:

| Practice | Implementation in Agentic RHDH |
|----------|-------------------------------|
| **Clear system instructions** | Large `UNIFIED_SYSTEM` with explicit policies and anti-patterns |
| **Tools with precise schemas** | JSON Schema in `agents/tools.py`; one function per capability |
| **Let the model plan, code executes** | `dispatch_tool()` — no YAML generation in Python without LLM intent |
| **Ground responses in retrieved data** | Plugin KB from official catalog index; `lookup_plugin_config` |
| **Minimize model responsibility** | Pre-scan selects plugins deterministically; LLM enriches reasons |
| **Human approval for destructive ops** | Review gate before apply |
| **Verify outcomes** | Health check + log diagnosis after restart |
| **Prompt caching** | Ephemeral cache on system prompt for multi-turn apply |
| **Parallel independent tools** | ThreadPoolExecutor for multi-tool turns |
| **Fail gracefully** | Resilience protocol; reset command; baseline snapshots |
| **Keep agents focused** | Single domain: RHDH Local onboarding — not a general coding agent |

Reference: [Anthropic — Building effective agents](https://docs.anthropic.com/en/docs/build-with-claude/agentic-systems)

---

## 12. Runtime dependencies

| Component | Purpose |
|-----------|---------|
| Python 3.11+ | CLI runtime |
| `anthropic` SDK | Messages API + streaming |
| `typer` / `rich` | CLI & TUI |
| `httpx` | GitHub API, health checks |
| `pyyaml` | Config I/O |
| Podman or Docker | RHDH Local compose |
| RHDH Local | Target platform |
| GitHub token | Repo scan + Tier 2 plugins |
| Claude (Vertex or API) | Enrichment + apply agent |

---

## 13. Limitations (current PoC)

- **GitHub only** — no GitLab/Bitbucket scanning.
- **Pre-scan is pattern-based** — does not deeply analyze file contents except `catalog-info.yaml`.
- **Tier 3 plugins** are surfaced but not auto-configured (credentials required).
- **Single-machine** — no multi-tenant or remote RHDH cluster support.
- **Enrichment parsing** relies on JSON blocks in Claude’s text response.
- **Not production-hardened** — no authz, audit log, or encrypted secret storage for generated configs.
- **Proof-of-concept** — built on RHDH Local (dev/test only).

---

## 14. Future roadmap

### 14.1 Near term

| Item | Description |
|------|-------------|
| **Credential wizard** | Interactive prompts for Tier 3 env vars (SonarQube, K8s) during apply |
| **Smarter content analysis** | Read workflow YAML, `catalog-info.yaml`, and Dockerfiles for richer signals |
| **GitLab / Gitea support** | Extend `tools/github.py` to a generic Git provider interface |
| **Lightspeed handoff** | Post-onboarding message in Lightspeed context (“your portal was configured with …”) |
| **CI integration** | GitHub Action / GitLab CI job that runs scan+propose on PR |
| **Spec-driven tests** | Golden-file tests for signal_map → expected proposals |

### 14.2 Medium term

| Item | Description |
|------|-------------|
| **In-portal onboarding UI** | Backstage plugin wrapping the same agent loop (not only CLI) |
| **Software Template generation** | Scaffold golden-path templates from detected repo patterns |
| **System entity auto-wiring** | Detect multi-repo systems and create `System`/`Domain` groupings |
| **Plugin conflict matrix** | Automated detection of incompatible plugins beyond current blocklist |
| **Observability** | OpenTelemetry traces for tool calls, token usage, restart latency |
| **Session persistence** | Save/resume onboarding sessions; team-shared proposals |

### 14.3 Long term

| Item | Description |
|------|-------------|
| **Production RHDH operator flow** | Generate `AppConfig` / CRD patches for cluster-deployed RHDH (not only Local) |
| **Continuous reconciliation** | Re-scan repos on schedule; propose drift fixes |
| **Multi-agent specialization** | Optional split agents (Scanner, Recommender, Writer) with coordinator — currently unified for simplicity |
| **Evaluation harness** | Benchmark proposal quality against human platform-engineer labels |
| **Enterprise policy engine** | Org-wide allow/deny lists for plugins; compliance tags |

---

## 15. Commands

```bash
# Run onboarding
agentic-rhdh

# Use a different project directory
agentic-rhdh --project-dir /path/to/agentic-rhdh-local

# Reset all agent-generated config
agentic-rhdh reset
agentic-rhdh reset --yes
```

---

## 16. Related documentation

- [README.md](../README.md) — quick start
- [ONBOARDING.md](../ONBOARDING.md) — per-run summary (generated)
- [developer-lightspeed/README.md](../developer-lightspeed/README.md) — Lightspeed setup
- [RHDH Dynamic Plugins Reference](https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.9/html/dynamic_plugins_reference/index)

---

## 17. Glossary

| Term | Meaning |
|------|---------|
| **Dynamic plugin** | RHDH plugin installed via OCI or bundled path at runtime |
| **Override layer** | User config that extends (via `includes:`) rather than replaces defaults |
| **Signal** | Detected technology indicator from repo file patterns |
| **Tier** | Plugin complexity class (1=bundled, 2=GitHub token, 3=external services) |
| **Tool-use loop** | Agent pattern: LLM requests tools → runtime executes → results fed back |
| **Pre-scan** | Local, deterministic repo analysis before any Claude call |

---

*Document generated for the Agentic RHDH Local project. For corrections or extensions, update this file alongside code changes in `agentic/`.*
