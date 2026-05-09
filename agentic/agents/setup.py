"""Create and manage Anthropic Managed Agents for the RHDH onboarding pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic

from ..models import AgentIDs
from .prompts import (
    CONFIG_WRITER_SYSTEM,
    COORDINATOR_SYSTEM,
    ENTITY_GENERATOR_SYSTEM,
    RECOMMENDER_SYSTEM,
    SCANNER_SYSTEM,
)
from .tools import (
    CONFIG_WRITER_TOOLS,
    ENTITY_GENERATOR_TOOLS,
    RECOMMENDER_TOOLS,
    SCANNER_TOOLS,
)

AGENT_IDS_FILE = Path.home() / ".cache" / "agentic-rhdh" / "agent_ids.json"
MODEL = "claude-sonnet-4-6"


def _build_tools(custom_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine built-in agent toolset with custom tools."""
    tools: list[dict[str, Any]] = [{"type": "agent_toolset_20260401"}]
    tools.extend(custom_tools)
    return tools


def create_agents(client: anthropic.Anthropic, knowledge_context: str = "") -> AgentIDs:
    """Create all specialist agents and the coordinator. Idempotent — reuses cached IDs."""
    cached = _load_cached_ids()
    if cached and _agents_exist(client, cached):
        return cached

    recommender_system = RECOMMENDER_SYSTEM
    if knowledge_context:
        recommender_system += f"\n\n## Available Plugins\n\n{knowledge_context}"

    scanner = client.beta.agents.create(
        model=MODEL,
        name="Repo Scanner",
        description="Analyzes GitHub repositories to detect technologies, frameworks, and CI/CD tooling",
        system=SCANNER_SYSTEM,
        tools=_build_tools(SCANNER_TOOLS),
    )

    recommender = client.beta.agents.create(
        model=MODEL,
        name="Plugin Recommender",
        description="Maps detected technologies to RHDH plugins with full configuration",
        system=recommender_system,
        tools=_build_tools(RECOMMENDER_TOOLS),
    )

    entity_gen = client.beta.agents.create(
        model=MODEL,
        name="Entity Generator",
        description="Generates Backstage catalog entity YAML from repository analysis",
        system=ENTITY_GENERATOR_SYSTEM,
        tools=_build_tools(ENTITY_GENERATOR_TOOLS),
    )

    config_writer = client.beta.agents.create(
        model=MODEL,
        name="Config Writer",
        description="Writes RHDH configuration files and ensures plugins are properly installed",
        system=CONFIG_WRITER_SYSTEM,
        tools=_build_tools(CONFIG_WRITER_TOOLS),
    )

    coordinator = client.beta.agents.create(
        model=MODEL,
        name="RHDH Onboarding Orchestrator",
        description="Coordinates the full RHDH onboarding pipeline",
        system=COORDINATOR_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": scanner.id},
                {"type": "agent", "id": recommender.id},
                {"type": "agent", "id": entity_gen.id},
                {"type": "agent", "id": config_writer.id},
            ],
        },
    )

    ids = AgentIDs(
        scanner=scanner.id,
        recommender=recommender.id,
        entity_generator=entity_gen.id,
        config_writer=config_writer.id,
        coordinator=coordinator.id,
    )
    _save_cached_ids(ids)
    return ids


def _agents_exist(client: anthropic.Anthropic, ids: AgentIDs) -> bool:
    """Check if all cached agent IDs still exist."""
    for agent_id in [ids.scanner, ids.recommender, ids.entity_generator, ids.config_writer, ids.coordinator]:
        if not agent_id:
            return False
        try:
            client.beta.agents.retrieve(agent_id)
        except anthropic.NotFoundError:
            return False
    return True


def _load_cached_ids() -> AgentIDs | None:
    if not AGENT_IDS_FILE.exists():
        return None
    try:
        data = json.loads(AGENT_IDS_FILE.read_text())
        return AgentIDs(**data)
    except (json.JSONDecodeError, KeyError):
        return None


def _save_cached_ids(ids: AgentIDs) -> None:
    AGENT_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_IDS_FILE.write_text(ids.model_dump_json(indent=2))
