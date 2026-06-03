"""Maps repository signals (file patterns) to RHDH plugin recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Confidence


@dataclass
class SignalPattern:
    """A file/content pattern that indicates a technology."""

    technology: str
    file_patterns: list[str]
    content_patterns: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.HIGH
    category: str = ""
    required_env_vars: list[str] = field(default_factory=list)


SIGNAL_MAP: list[SignalPattern] = [
    # CI/CD
    SignalPattern(
        technology="github-actions",
        file_patterns=[".github/workflows/*.yml", ".github/workflows/*.yaml"],
        plugins=["github-actions"],
        category="CI/CD",
        required_env_vars=["GITHUB_TOKEN"],
    ),
    SignalPattern(
        technology="tekton",
        file_patterns=[
            "tekton/**/*.yaml", "tekton/**/*.yml",
            ".tekton/**/*.yaml", ".tekton/**/*.yml",
        ],
        content_patterns=["apiVersion: tekton.dev/"],
        plugins=["tekton"],
        category="CI/CD",
        required_env_vars=["K8S_CLUSTER_URL", "K8S_CLUSTER_TOKEN"],
    ),
    SignalPattern(
        technology="jenkins",
        file_patterns=["Jenkinsfile", "jenkins/**/*"],
        plugins=["jenkins"],
        category="CI/CD",
        required_env_vars=["JENKINS_URL", "JENKINS_USERNAME", "JENKINS_TOKEN"],
    ),
    SignalPattern(
        technology="azure-devops",
        file_patterns=["azure-pipelines.yml", "azure-pipelines.yaml"],
        plugins=["azure-devops"],
        category="CI/CD",
    ),

    # GitOps / Deployment
    SignalPattern(
        technology="argocd",
        file_patterns=[
            "argocd/**/*.yaml", "argo-cd/**/*.yaml",
            "argocd/**/*.yml",
        ],
        content_patterns=["argoproj.io/"],
        plugins=["argocd"],
        category="GitOps",
        required_env_vars=["ARGOCD_INSTANCE1_URL", "ARGOCD_AUTH_TOKEN"],
    ),
    SignalPattern(
        technology="kubernetes",
        file_patterns=[
            "k8s/**/*.yaml", "k8s/**/*.yml",
            "kubernetes/**/*.yaml", "deploy/**/*.yaml",
            "manifests/**/*.yaml", "charts/**/*.yaml",
        ],
        content_patterns=["apiVersion: apps/v1", "kind: Deployment", "kind: Service"],
        plugins=["kubernetes", "topology"],
        category="Kubernetes",
        required_env_vars=["K8S_CLUSTER_URL", "K8S_CLUSTER_TOKEN"],
    ),
    SignalPattern(
        technology="helm",
        file_patterns=["Chart.yaml", "charts/**/Chart.yaml", "helm/**/*.yaml"],
        plugins=["kubernetes"],
        category="Kubernetes",
    ),

    # Container
    SignalPattern(
        technology="docker",
        file_patterns=["Dockerfile", "Containerfile", "docker-compose.yml", "compose.yaml"],
        plugins=["topology"],
        confidence=Confidence.MEDIUM,
        category="Container",
    ),
    SignalPattern(
        technology="quay",
        file_patterns=[],
        content_patterns=["quay.io/"],
        plugins=["quay"],
        confidence=Confidence.MEDIUM,
        category="Container",
        required_env_vars=["QUAY_URL"],
    ),

    # Documentation
    SignalPattern(
        technology="techdocs",
        file_patterns=["mkdocs.yml", "mkdocs.yaml", "docs/**/*.md"],
        plugins=["techdocs"],
        category="Documentation",
    ),

    # API
    SignalPattern(
        technology="openapi",
        file_patterns=[
            "openapi.yaml", "openapi.yml", "openapi.json",
            "swagger.yaml", "swagger.yml", "swagger.json",
            "api/*.yaml", "api/*.json",
        ],
        plugins=["api-docs"],
        confidence=Confidence.MEDIUM,
        category="API",
    ),

    # Quality
    SignalPattern(
        technology="sonarqube",
        file_patterns=["sonar-project.properties", ".sonarcloud.properties"],
        plugins=["sonarqube"],
        category="Quality",
        required_env_vars=["SONARQUBE_URL", "SONARQUBE_TOKEN"],
    ),

    # Source Control
    SignalPattern(
        technology="github-pull-requests",
        file_patterns=[".github/**/*"],
        plugins=["github-pull-requests"],
        confidence=Confidence.LOW,
        category="Source Control",
        required_env_vars=["GITHUB_TOKEN"],
    ),
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

    # Existing Backstage
    SignalPattern(
        technology="catalog-info",
        file_patterns=["catalog-info.yaml", "catalog-info.yml"],
        plugins=[],
        category="Backstage",
    ),

    # Ansible
    SignalPattern(
        technology="ansible",
        file_patterns=[
            "ansible/**/*.yml", "playbooks/**/*.yml",
            "roles/**/*.yml", "ansible.cfg",
        ],
        plugins=["ansible-plugin"],
        confidence=Confidence.MEDIUM,
        category="Automation",
    ),

    # 3scale
    SignalPattern(
        technology="3scale",
        file_patterns=[],
        content_patterns=["3scale"],
        plugins=["3scale"],
        confidence=Confidence.LOW,
        category="API Management",
    ),
]


BLOCKED_PLUGINS: set[str] = {
    "github-issues",  # crashes with file: source-location entities (TypeError: URL constructor)
    "kubernetes",  # requires K8S_CLUSTER_NAME/TOKEN — crashes startup when unset (Tier 3)
    "kubernetes-backend",  # same — disable inherited default via override instead
}

ALWAYS_RECOMMEND_PLUGINS: list[dict[str, str]] = [
    {"plugin": "adoption-insights", "reason": "Platform usage metrics dashboard"},
    {"plugin": "notifications", "reason": "In-app notification system for catalog changes and CI events"},
]


def get_signal_map() -> list[SignalPattern]:
    return SIGNAL_MAP


def get_blocked_plugins() -> set[str]:
    return BLOCKED_PLUGINS


def get_always_recommend_plugins() -> list[dict[str, str]]:
    return ALWAYS_RECOMMEND_PLUGINS


def signals_for_technology(tech: str) -> SignalPattern | None:
    for s in SIGNAL_MAP:
        if s.technology == tech:
            return s
    return None


def technologies_for_plugin(plugin_name: str) -> list[str]:
    return [s.technology for s in SIGNAL_MAP if plugin_name in s.plugins]
