"""Local pre-scanner — scans repos and builds proposals without Claude API calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable

from .knowledge.plugin_index import PluginKnowledgeBase
from .knowledge.signal_map import (
    SIGNAL_MAP,
    get_always_recommend_plugins,
    get_blocked_plugins,
)
from .models import (
    CatalogEntityProposal,
    ComponentType,
    Confidence,
    DetectedSignal,
    PluginProposal,
    RepoProfile,
)
from .tools.github import (
    get_file_content,
    get_repo_info,
    get_repo_languages,
    get_repo_tree,
    parse_repo_url,
)


@dataclass
class ScanResult:
    profiles: list[RepoProfile] = field(default_factory=list)
    plugin_proposals: list[PluginProposal] = field(default_factory=list)
    entity_proposals: list[CatalogEntityProposal] = field(default_factory=list)


def _glob_match(filepath: str, pattern: str) -> bool:
    """Match a filepath against a glob pattern, supporting ** for recursive dirs."""
    if "**" in pattern:
        prefix, _, suffix = pattern.partition("**")
        suffix = suffix.lstrip("/")
        if prefix and not filepath.startswith(prefix):
            return False
        remainder = filepath[len(prefix):]
        if not suffix:
            return True
        parts = remainder.split("/")
        for i in range(len(parts)):
            if fnmatch("/".join(parts[i:]), suffix):
                return True
        return False
    return fnmatch(filepath, pattern)


def detect_signals(file_tree: list[str]) -> list[DetectedSignal]:
    """Match file tree against SIGNAL_MAP patterns."""
    signals: list[DetectedSignal] = []
    seen_techs: set[str] = set()

    for pattern in SIGNAL_MAP:
        if pattern.technology in seen_techs:
            continue

        evidence: list[str] = []
        for filepath in file_tree:
            for glob in pattern.file_patterns:
                if _glob_match(filepath, glob):
                    evidence.append(filepath)
                    if len(evidence) >= 5:
                        break
            if len(evidence) >= 5:
                break

        if evidence:
            seen_techs.add(pattern.technology)
            signals.append(DetectedSignal(
                technology=pattern.technology,
                evidence=evidence,
                confidence=pattern.confidence,
            ))

    return signals


def _infer_component_type_from_signals(profile: RepoProfile) -> ComponentType:
    """Infer component type from detected signals and languages."""
    signal_techs = {s.technology for s in profile.signals}
    langs = profile.languages

    if "helm" in signal_techs:
        return ComponentType.RESOURCE
    if "kubernetes" in signal_techs or "tekton" in signal_techs:
        return ComponentType.SERVICE
    if "docker" in signal_techs:
        return ComponentType.SERVICE

    top_lang = max(langs, key=langs.get) if langs else ""
    if top_lang in ("TypeScript", "JavaScript", "CSS", "HTML"):
        return ComponentType.WEBSITE

    if any(s in signal_techs for s in ("github-actions", "jenkins", "argocd")):
        return ComponentType.SERVICE

    if top_lang in ("Go", "Java", "Python", "Rust", "C#"):
        return ComponentType.LIBRARY

    return ComponentType.SERVICE


def scan_repo(
    url: str,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> RepoProfile:
    """Scan a single repo — fetches tree, languages, info in parallel."""
    owner, repo = parse_repo_url(url)

    if on_event:
        on_event("scan_start", {"owner": owner, "repo": repo})

    info: dict[str, Any] = {}
    tree: list[str] = []
    languages: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_info = pool.submit(get_repo_info, owner, repo)
        fut_tree = pool.submit(get_repo_tree, owner, repo)
        fut_langs = pool.submit(get_repo_languages, owner, repo)

        try:
            info = fut_info.result(timeout=30)
            if on_event:
                on_event("scan_info", {
                    "owner": owner, "repo": repo,
                    "description": info.get("description", ""),
                    "topics": info.get("topics", []),
                })
        except Exception:
            info = {}

        try:
            tree = fut_tree.result(timeout=30)
            if on_event:
                on_event("scan_tree", {"owner": owner, "repo": repo, "count": len(tree)})
        except Exception:
            tree = []

        try:
            languages = fut_langs.result(timeout=30)
            if on_event:
                on_event("scan_languages", {"owner": owner, "repo": repo, "languages": languages})
        except Exception:
            languages = {}

    signals = detect_signals(tree)
    if on_event:
        on_event("scan_signals", {
            "owner": owner, "repo": repo,
            "signals": [s.technology for s in signals],
        })

    has_catalog_info = "catalog-info.yaml" in tree
    existing_catalog_info = None
    if has_catalog_info:
        try:
            content = get_file_content(owner, repo, "catalog-info.yaml")
            import yaml
            existing_catalog_info = yaml.safe_load(content)
        except Exception:
            pass

    readme_content = ""
    if "README.md" in tree:
        try:
            readme_content = get_file_content(owner, repo, "README.md")
        except Exception:
            pass

    profile = RepoProfile(
        url=url,
        owner=owner,
        repo=repo,
        default_branch=info.get("default_branch", "main"),
        languages=languages,
        signals=signals,
        has_catalog_info=has_catalog_info,
        existing_catalog_info=existing_catalog_info,
    )

    if on_event:
        on_event("scan_complete", {"owner": owner, "repo": repo})

    return profile


def build_proposals(
    profiles: list[RepoProfile],
    kb: PluginKnowledgeBase,
    owner: str = "group:default/rhdh-team",
) -> tuple[list[PluginProposal], list[CatalogEntityProposal]]:
    """Build plugin and entity proposals from scan results."""
    blocked = get_blocked_plugins()
    always = get_always_recommend_plugins()

    plugin_names: set[str] = set()
    plugin_proposals: list[PluginProposal] = []

    for entry in always:
        name = entry["plugin"]
        if name in blocked or name in plugin_names:
            continue
        details = kb.get_plugin_config_details(name)
        if not details:
            continue
        plugin_names.add(name)
        plugin_proposals.append(_details_to_proposal(
            details, entry["reason"], Confidence.HIGH,
        ))

    for profile in profiles:
        for signal in profile.signals:
            for pattern in SIGNAL_MAP:
                if pattern.technology != signal.technology:
                    continue
                for plugin_name in pattern.plugins:
                    if plugin_name in blocked or plugin_name in plugin_names:
                        continue
                    details = kb.get_plugin_config_details(plugin_name)
                    if not details:
                        continue
                    plugin_names.add(plugin_name)

                    evidence_str = ", ".join(signal.evidence[:3])
                    reason = (
                        f"Detected {signal.technology} signals in "
                        f"{profile.owner}/{profile.repo}: {evidence_str}"
                    )
                    plugin_proposals.append(_details_to_proposal(
                        details, reason, signal.confidence,
                    ))

    entity_proposals: list[CatalogEntityProposal] = []
    for profile in profiles:
        comp_type = _infer_component_type_from_signals(profile)
        top_lang = max(profile.languages, key=profile.languages.get) if profile.languages else ""
        tags = [top_lang.lower()] if top_lang else []
        for signal in profile.signals:
            if signal.technology not in ("catalog-info", "github-pull-requests", "github-insights", "security-insights"):
                tags.append(signal.technology)
        tags = tags[:6]

        entity_proposals.append(CatalogEntityProposal(
            name=profile.repo,
            component_type=comp_type,
            description=f"{profile.owner}/{profile.repo}",
            source_repo=profile.url,
            owner=owner,
            annotations={
                "github.com/project-slug": f"{profile.owner}/{profile.repo}",
                "backstage.io/source-location": f"file:./configs/catalog-entities/{profile.repo}-component.yaml",
                "backstage.io/techdocs-ref": f"dir:./{profile.repo}-docs/",
            },
            links=[{"url": profile.url, "title": "Source Code", "icon": "github"}],
            tags=tags,
        ))

    return plugin_proposals, entity_proposals


def _details_to_proposal(
    details: dict[str, Any],
    reason: str,
    confidence: Confidence,
) -> PluginProposal:
    packages = [p["name"] for p in details.get("packages", [])]
    package_refs = {p["name"]: p["ref"] for p in details.get("packages", []) if p.get("ref")}
    plugin_config: dict[str, Any] = {}
    for p in details.get("packages", []):
        if p.get("plugin_config"):
            plugin_config.update(p["plugin_config"])

    return PluginProposal(
        plugin=details["plugin"],
        title=details.get("title", details["plugin"]),
        packages=packages,
        package_refs=package_refs,
        reason=reason,
        plugin_config=plugin_config,
        required_env_vars=details.get("required_env_vars", []),
        confidence=confidence,
        category="",
        tier=details.get("tier", 2),
    )


def pre_scan_all(
    urls: list[str],
    kb: PluginKnowledgeBase,
    owner: str = "group:default/rhdh-team",
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> ScanResult:
    """Scan all repos in parallel, build proposals locally."""
    profiles: list[RepoProfile] = []

    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        futures = {
            pool.submit(scan_repo, url, on_event): url
            for url in urls
        }
        for future in as_completed(futures):
            try:
                profile = future.result(timeout=60)
                profiles.append(profile)
            except Exception as e:
                url = futures[future]
                if on_event:
                    on_event("scan_error", {"url": url, "error": str(e)})

    plugin_proposals, entity_proposals = build_proposals(profiles, kb, owner)

    return ScanResult(
        profiles=profiles,
        plugin_proposals=plugin_proposals,
        entity_proposals=entity_proposals,
    )
