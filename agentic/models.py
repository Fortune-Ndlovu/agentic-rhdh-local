"""Shared data models for the agentic RHDH onboarding system."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PluginRole(str, Enum):
    FRONTEND = "frontend-plugin"
    BACKEND = "backend-plugin"


class ComponentType(str, Enum):
    SERVICE = "service"
    WEBSITE = "website"
    LIBRARY = "library"
    RESOURCE = "resource"


class Lifecycle(str, Enum):
    PRODUCTION = "production"
    EXPERIMENTAL = "experimental"
    DEVELOPMENT = "development"
    DEPRECATED = "deprecated"


# --- Repo scanning ---


class DetectedSignal(BaseModel):
    """A technology signal detected in a repository."""

    technology: str  # e.g. "github-actions", "kubernetes", "tekton"
    evidence: list[str]  # file paths or patterns that triggered detection
    confidence: Confidence = Confidence.HIGH


class RepoProfile(BaseModel):
    """Result of scanning a single repository."""

    url: str
    owner: str
    repo: str
    default_branch: str = "main"
    languages: dict[str, float] = Field(default_factory=dict)
    signals: list[DetectedSignal] = Field(default_factory=list)
    has_catalog_info: bool = False
    existing_catalog_info: dict[str, Any] | None = None


# --- Plugin knowledge ---


class PluginPackage(BaseModel):
    """A single plugin package from the catalog index."""

    name: str  # e.g. "backstage-community-plugin-github-actions"
    package_name: str  # e.g. "@backstage-community/plugin-github-actions"
    role: PluginRole
    oci_ref: str  # full OCI reference from dynamic-plugins.default.yaml
    version: str = ""
    plugin_config: dict[str, Any] = Field(default_factory=dict)


class PluginInfo(BaseModel):
    """A logical plugin (may have frontend + backend packages)."""

    name: str  # e.g. "github-actions"
    title: str = ""
    description: str = ""
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    packages: list[PluginPackage] = Field(default_factory=list)
    app_config_examples: list[dict[str, Any]] = Field(default_factory=list)


# --- Proposals ---


class PluginProposal(BaseModel):
    """A proposed plugin to enable for the user."""

    plugin: str  # e.g. "github-actions"
    title: str = ""
    packages: list[str] = Field(default_factory=list)
    package_refs: dict[str, str] = Field(default_factory=dict)  # name -> full ref
    reason: str = ""
    plugin_config: dict[str, Any] = Field(default_factory=dict)
    required_env_vars: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.HIGH
    category: str = ""
    tier: int = 2
    accepted: bool = True


class CatalogEntityProposal(BaseModel):
    """A proposed catalog entity to register."""

    name: str
    kind: str = "Component"
    component_type: ComponentType = ComponentType.SERVICE
    description: str = ""
    source_repo: str = ""
    owner: str = "user:default/guest"
    lifecycle: Lifecycle = Lifecycle.PRODUCTION
    system: str = ""
    annotations: dict[str, str] = Field(default_factory=dict)
    links: list[dict[str, str]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    accepted: bool = True

    def to_yaml_dict(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "type": self.component_type.value,
            "lifecycle": self.lifecycle.value,
            "owner": self.owner,
        }
        if self.system:
            spec["system"] = self.system
        metadata: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "annotations": self.annotations,
        }
        if self.links:
            metadata["links"] = self.links
        if self.tags:
            metadata["tags"] = self.tags
        return {
            "apiVersion": "backstage.io/v1alpha1",
            "kind": self.kind,
            "metadata": metadata,
            "spec": spec,
        }


# --- Session state ---


class OnboardingState(BaseModel):
    """Overall state of an onboarding session."""

    repos: list[str] = Field(default_factory=list)
    profiles: list[RepoProfile] = Field(default_factory=list)
    plugin_proposals: list[PluginProposal] = Field(default_factory=list)
    entity_proposals: list[CatalogEntityProposal] = Field(default_factory=list)
    phase: str = "input"  # input -> scanning -> proposals -> applying -> done
    errors: list[str] = Field(default_factory=list)
