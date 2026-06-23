"""Deterministic config writer — generates all RHDH configs from approved proposals.

Replaces the multi-turn Claude agent loop for config writing. All YAML is
computed in Python and written atomically via yaml_writer, eliminating
3-8 API round trips per apply phase.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..models import CatalogEntityProposal, PluginProposal
from .github import get_file_content, parse_repo_url
from .yaml_writer import merge_yaml_file, write_text_file, write_yaml

DYNAMIC_PLUGINS_INCLUDES = [
    "dynamic-plugins.default.yaml",
    "/dynamic-plugins-root/dynamic-plugins.extensions.yaml",
    "/opt/app-root/src/configs/dynamic-plugins/dynamic-plugins.lightspeed.yaml",
]

DISABLED_KUBERNETES_PLUGINS = [
    {
        "package": "./dynamic-plugins/dist/backstage-plugin-kubernetes-backend-dynamic",
        "disabled": True,
    },
    {
        "package": "./dynamic-plugins/dist/backstage-plugin-kubernetes",
        "disabled": True,
    },
]

DISABLED_ORCHESTRATOR_PLUGINS = [
    {
        "package": "oci://registry.access.redhat.com/rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend-module-loki:{{inherit}}",
        "disabled": True,
    },
    {
        "package": "oci://registry.access.redhat.com/rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-backend:{{inherit}}",
        "disabled": True,
    },
    {
        "package": "oci://registry.access.redhat.com/rhdh/red-hat-developer-hub-backstage-plugin-orchestrator-form-widgets:{{inherit}}",
        "disabled": True,
    },
    {
        "package": "oci://registry.access.redhat.com/rhdh/red-hat-developer-hub-backstage-plugin-orchestrator:{{inherit}}",
        "disabled": True,
    },
    {
        "package": "oci://registry.access.redhat.com/rhdh/red-hat-developer-hub-backstage-plugin-scaffolder-backend-module-orchestrator:{{inherit}}",
        "disabled": True,
    },
]


def _read_existing_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    from .yaml_writer import read_yaml
    try:
        return read_yaml(path)
    except Exception:
        return None


def _existing_plugin_packages(existing: dict[str, Any] | None) -> set[str]:
    """Extract package names already in the override file."""
    if not existing or "plugins" not in existing:
        return set()
    packages = set()
    for entry in existing.get("plugins", []):
        pkg = entry.get("package", "")
        packages.add(_normalize_package_ref(pkg))
    return packages


def _normalize_package_ref(ref: str) -> str:
    """Extract the package name from a full ref for dedup comparison."""
    ref = ref.strip()
    if ref.startswith("./dynamic-plugins/dist/"):
        return ref.split("/")[-1]
    if "oci://" in ref:
        name = ref.split("/")[-1]
        return name.split(":")[0].split("@")[0]
    return ref


def write_dynamic_plugins_override(
    project_root: Path,
    plugins: list[PluginProposal],
) -> Path:
    """Write configs/dynamic-plugins/dynamic-plugins.override.yaml.

    Preserves existing plugins, appends new ones, always includes the
    required disabled entries and includes chain.
    """
    override_path = project_root / "configs" / "dynamic-plugins" / "dynamic-plugins.override.yaml"
    existing = _read_existing_yaml(override_path)
    existing_packages = _existing_plugin_packages(existing)

    existing_plugins = []
    if existing and "plugins" in existing:
        existing_plugins = list(existing["plugins"])

    if not existing_plugins:
        existing_plugins = list(DISABLED_KUBERNETES_PLUGINS + DISABLED_ORCHESTRATOR_PLUGINS)

    new_entries = []
    for proposal in plugins:
        for pkg_name, pkg_ref in proposal.package_refs.items():
            if _normalize_package_ref(pkg_ref) in existing_packages:
                continue
            entry: dict[str, Any] = {
                "package": pkg_ref,
                "disabled": False,
            }
            pkg_config = proposal.plugin_config.get(pkg_name)
            if pkg_config:
                entry["pluginConfig"] = pkg_config
            new_entries.append(entry)

    data = {
        "includes": list(DYNAMIC_PLUGINS_INCLUDES),
        "plugins": existing_plugins + new_entries,
    }

    return write_yaml(override_path, data)


def write_entity_yaml(
    project_root: Path,
    entity: CatalogEntityProposal,
) -> Path:
    """Write configs/catalog-entities/<name>-component.yaml."""
    entity_path = project_root / "configs" / "catalog-entities" / f"{entity.name}-component.yaml"
    data = entity.to_yaml_dict()
    return write_yaml(entity_path, data)


def write_techdocs(
    project_root: Path,
    entity: CatalogEntityProposal,
) -> tuple[Path, Path]:
    """Write mkdocs.yml + docs/index.md for one entity.

    Fetches README.md from GitHub to populate the docs content.
    """
    docs_dir = project_root / "configs" / "catalog-entities" / f"{entity.name}-docs"
    mkdocs_path = docs_dir / "mkdocs.yml"
    index_path = docs_dir / "docs" / "index.md"

    title = entity.name.replace("-", " ").title()

    mkdocs_data = {
        "site_name": title,
        "plugins": ["techdocs-core"],
        "nav": [{"Home": "index.md"}],
    }
    write_yaml(mkdocs_path, mkdocs_data)

    readme_content = ""
    if entity.source_repo:
        try:
            owner, repo = parse_repo_url(entity.source_repo)
            readme_content = get_file_content(owner, repo, "README.md")
        except Exception:
            pass

    if not readme_content:
        readme_content = f"# {title}\n\n{entity.description or 'Documentation coming soon.'}\n"

    write_text_file(index_path, readme_content)
    return mkdocs_path, index_path


def write_components_override(
    project_root: Path,
    entities: list[CatalogEntityProposal],
) -> Path:
    """Write configs/catalog-entities/components.override.yaml.

    Preserves existing targets, appends new ones, removes stale targets
    whose YAML files no longer exist.
    """
    override_path = project_root / "configs" / "catalog-entities" / "components.override.yaml"
    catalog_dir = project_root / "configs" / "catalog-entities"
    existing = _read_existing_yaml(override_path)

    existing_targets: list[str] = []
    if existing and "spec" in existing:
        existing_targets = list(existing.get("spec", {}).get("targets", []))

    live_targets = []
    for t in existing_targets:
        target_path = catalog_dir / t.lstrip("./")
        if target_path.exists():
            live_targets.append(t)

    target_set = set(live_targets)
    for entity in entities:
        target = f"./{entity.name}-component.yaml"
        if target not in target_set:
            live_targets.append(target)
            target_set.add(target)

    data = {
        "apiVersion": "backstage.io/v1alpha1",
        "kind": "Location",
        "metadata": {
            "name": "rhdh-onboarded-components",
            "description": "Auto-generated catalog entities for onboarded repositories",
        },
        "spec": {
            "targets": live_targets,
        },
    }
    return write_yaml(override_path, data)


def write_app_config(
    project_root: Path,
    plugins: list[PluginProposal],
) -> Path | None:
    """Merge plugin-specific app-config into configs/app-config/app-config.local.yaml.

    Only writes sections that are needed (techdocs, GitHub integration).
    Never writes catalog.locations.
    """
    app_config_path = project_root / "configs" / "app-config" / "app-config.local.yaml"

    updates: dict[str, Any] = {}

    has_techdocs = any(p.plugin == "techdocs" for p in plugins)
    if has_techdocs:
        updates["techdocs"] = {
            "builder": "local",
            "generator": {"runIn": "local"},
            "publisher": {"type": "local"},
        }

    has_github_plugins = any(p.tier <= 2 and "GITHUB_TOKEN" in p.required_env_vars for p in plugins)
    if has_github_plugins:
        existing = _read_existing_yaml(app_config_path) or {}
        if not existing.get("integrations", {}).get("github"):
            updates["integrations"] = {
                "github": [
                    {"host": "github.com", "token": "${GITHUB_TOKEN}"},
                ],
            }

    if not updates:
        return None

    return merge_yaml_file(app_config_path, updates)


def apply_configs(
    project_root: Path,
    plugins: list[PluginProposal],
    entities: list[CatalogEntityProposal],
    on_event: Any | None = None,
) -> dict[str, Any]:
    """Write all config files deterministically and return a summary.

    This replaces the multi-turn Claude agent loop for config writing.
    File writes that don't depend on each other run in parallel.
    """
    written_files: list[str] = []
    plugins_changed = False
    errors: list[str] = []

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        if on_event:
            on_event(event_type, data)

    # Phase 1: Write dynamic-plugins override
    if plugins:
        _emit("tool_start", {"tool": "write_yaml", "input": {"path": "configs/dynamic-plugins/dynamic-plugins.override.yaml"}})
        try:
            path = write_dynamic_plugins_override(project_root, plugins)
            written_files.append(str(path.relative_to(project_root)))
            plugins_changed = True
            _emit("tool_end", {"tool": "write_yaml", "result": {"success": True, "path": str(path)}})
        except Exception as e:
            errors.append(f"dynamic-plugins.override.yaml: {e}")
            _emit("tool_end", {"tool": "write_yaml", "result": {"error": str(e)}})

    # Phase 2: Write entity YAMLs + TechDocs in parallel
    if entities:
        def _write_entity(entity: CatalogEntityProposal) -> list[str]:
            paths = []
            _emit("tool_start", {"tool": "write_yaml", "input": {"path": f"configs/catalog-entities/{entity.name}-component.yaml"}})
            p = write_entity_yaml(project_root, entity)
            paths.append(str(p.relative_to(project_root)))
            _emit("tool_end", {"tool": "write_yaml", "result": {"success": True, "path": str(p)}})

            _emit("tool_start", {"tool": "write_techdocs", "input": {"entity": entity.name}})
            mkdocs, index = write_techdocs(project_root, entity)
            paths.append(str(mkdocs.relative_to(project_root)))
            paths.append(str(index.relative_to(project_root)))
            _emit("tool_end", {"tool": "write_techdocs", "result": {"success": True, "entity": entity.name}})
            return paths

        with ThreadPoolExecutor(max_workers=min(len(entities), 4)) as pool:
            futures = {pool.submit(_write_entity, e): e for e in entities}
            for future in as_completed(futures):
                entity = futures[future]
                try:
                    paths = future.result()
                    written_files.extend(paths)
                except Exception as e:
                    errors.append(f"{entity.name}: {e}")

        # Phase 3: Write components.override.yaml (after entity files exist)
        _emit("tool_start", {"tool": "write_yaml", "input": {"path": "configs/catalog-entities/components.override.yaml"}})
        try:
            path = write_components_override(project_root, entities)
            written_files.append(str(path.relative_to(project_root)))
            _emit("tool_end", {"tool": "write_yaml", "result": {"success": True, "path": str(path)}})
        except Exception as e:
            errors.append(f"components.override.yaml: {e}")
            _emit("tool_end", {"tool": "write_yaml", "result": {"error": str(e)}})

    # Phase 4: Write app-config
    if plugins:
        _emit("tool_start", {"tool": "merge_yaml", "input": {"path": "configs/app-config/app-config.local.yaml"}})
        try:
            path = write_app_config(project_root, plugins)
            if path:
                written_files.append(str(path.relative_to(project_root)))
            _emit("tool_end", {"tool": "merge_yaml", "result": {"success": True}})
        except Exception as e:
            errors.append(f"app-config.local.yaml: {e}")
            _emit("tool_end", {"tool": "merge_yaml", "result": {"error": str(e)}})

    return {
        "written_files": written_files,
        "plugins_changed": plugins_changed,
        "errors": errors,
    }
