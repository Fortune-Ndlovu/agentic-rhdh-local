"""Structured plugin knowledge base built from extracted catalog data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..models import PluginInfo, PluginPackage, PluginRole
from .signal_map import get_always_recommend_plugins, get_blocked_plugins
from .extractor import (
    DEFAULT_EXTRACT_DIR,
    load_dynamic_plugins_default,
    load_package_yamls,
    load_plugin_yamls,
)


class PluginKnowledgeBase:
    """In-memory lookup for all RHDH plugins, packages, and configs."""

    def __init__(self) -> None:
        self.plugins: dict[str, PluginInfo] = {}
        self._package_to_plugin: dict[str, str] = {}

    @classmethod
    def build(cls, extract_dir: Path = DEFAULT_EXTRACT_DIR) -> PluginKnowledgeBase:
        kb = cls()
        plugin_yamls = load_plugin_yamls(extract_dir)
        package_yamls = load_package_yamls(extract_dir)
        dpdy_entries = load_dynamic_plugins_default(extract_dir)

        dpdy_by_package = _index_dpdy(dpdy_entries)

        for name, pdata in plugin_yamls.items():
            spec = pdata.get("spec", {})
            meta = pdata.get("metadata", {})

            info = PluginInfo(
                name=name,
                title=meta.get("title", name),
                description=(meta.get("description", "") or "").split("\n")[0],
                categories=spec.get("categories", []),
                tags=meta.get("tags", []),
            )

            pkg_refs = spec.get("packages", [])
            for pkg_ref in pkg_refs:
                pkg_name = pkg_ref if isinstance(pkg_ref, str) else pkg_ref.get("name", "")
                if not pkg_name:
                    continue

                pkg_yaml = package_yamls.get(pkg_name, {})
                pkg_spec = pkg_yaml.get("spec", {})

                role_str = pkg_spec.get("backstage", {}).get("role", "frontend-plugin")
                role = PluginRole.BACKEND if "backend" in role_str else PluginRole.FRONTEND

                oci_ref = pkg_spec.get("dynamicArtifact", "")
                if not oci_ref:
                    oci_ref = dpdy_by_package.get(pkg_name, {}).get("oci_ref", "")

                plugin_config = dpdy_by_package.get(pkg_name, {}).get("pluginConfig", {})
                if not plugin_config:
                    examples = pkg_spec.get("appConfigExamples", [])
                    if examples:
                        content = examples[0].get("content", {})
                        if isinstance(content, dict):
                            plugin_config = content
                        elif isinstance(content, str):
                            try:
                                parsed = yaml.safe_load(content)
                                plugin_config = parsed if isinstance(parsed, dict) else {}
                            except yaml.YAMLError:
                                plugin_config = {}

                pkg = PluginPackage(
                    name=pkg_name,
                    package_name=pkg_spec.get("packageName", f"@unknown/{pkg_name}"),
                    role=role,
                    oci_ref=oci_ref,
                    version=pkg_spec.get("version", ""),
                    plugin_config=plugin_config,
                )
                info.packages.append(pkg)
                kb._package_to_plugin[pkg_name] = name

                examples = pkg_spec.get("appConfigExamples", [])
                for ex in examples:
                    info.app_config_examples.append(ex.get("content", {}))

            kb.plugins[name] = info

        return kb

    def get(self, name: str) -> PluginInfo | None:
        return self.plugins.get(name)

    def search(self, query: str) -> list[PluginInfo]:
        q = query.lower()
        results = []
        for info in self.plugins.values():
            if (
                q in info.name.lower()
                or q in info.title.lower()
                or any(q in c.lower() for c in info.categories)
                or any(q in t.lower() for t in info.tags)
            ):
                results.append(info)
        return results

    def by_category(self, category: str) -> list[PluginInfo]:
        cat = category.lower()
        return [p for p in self.plugins.values() if any(cat in c.lower() for c in p.categories)]

    def get_full_config_for_plugin(self, name: str) -> dict[str, Any]:
        """Get merged pluginConfig + appConfigExamples for a plugin."""
        info = self.get(name)
        if not info:
            return {}
        merged: dict[str, Any] = {}
        for pkg in info.packages:
            if pkg.plugin_config:
                _deep_merge(merged, pkg.plugin_config)
        return merged

    def get_plugin_config_details(self, name: str) -> dict[str, Any] | None:
        """Get full config details for a plugin — used by lookup_plugin_config tool."""
        info = self.get(name)
        if not info:
            results = self.search(name)
            if results:
                info = results[0]
            else:
                return None

        env_vars = self._get_env_vars_for_plugin(info)
        tier = self._classify_tier(info, env_vars)

        packages = []
        for pkg in info.packages:
            packages.append({
                "name": pkg.name,
                "role": pkg.role.value,
                "ref": pkg.oci_ref,
                "plugin_config": pkg.plugin_config,
            })

        return {
            "plugin": info.name,
            "title": info.title,
            "packages": packages,
            "required_env_vars": sorted(env_vars),
            "tier": tier,
            "app_config_examples": info.app_config_examples,
        }

    def get_oci_refs_for_plugin(self, name: str) -> list[str]:
        info = self.get(name)
        if not info:
            return []
        return [pkg.oci_ref for pkg in info.packages if pkg.oci_ref]

    def to_agent_context(self) -> str:
        """Serialize the knowledge base into a text block for agent system prompts."""
        blocked = get_blocked_plugins()
        always = get_always_recommend_plugins()

        lines = ["# Available RHDH Plugins\n"]

        lines.append("## BLOCKED — never recommend these plugins")
        for name in sorted(blocked):
            lines.append(f"- {name}")
        lines.append("")

        lines.append("## ALWAYS INCLUDE — recommend on every onboarding")
        for entry in always:
            lines.append(f"- {entry['plugin']}: {entry['reason']}")
        lines.append("")

        for info in sorted(self.plugins.values(), key=lambda p: p.name):
            if info.name in blocked:
                continue
            cats = ", ".join(info.categories) if info.categories else "uncategorized"
            env_vars = self._get_env_vars_for_plugin(info)
            tier = self._classify_tier(info, env_vars)
            lines.append(f"## {info.title} ({info.name}) [Tier {tier}]")
            lines.append(f"Categories: {cats}")
            lines.append("Packages:")
            for pkg in info.packages:
                ref_label = "[bundled]" if pkg.oci_ref.startswith("./") else "[remote]"
                lines.append(f"  - {pkg.name} [{pkg.role.value}] {ref_label}")
                lines.append(f"    ref: {pkg.oci_ref}")
            if env_vars:
                lines.append(f"Required env vars: {', '.join(sorted(env_vars))}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _get_env_vars_for_plugin(info: PluginInfo) -> set[str]:
        env_vars: set[str] = set()
        for pkg in info.packages:
            config_str = str(pkg.plugin_config)
            env_vars.update(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", config_str))
        return env_vars

    @staticmethod
    def _classify_tier(info: PluginInfo, env_vars: set[str]) -> int:
        has_bundled = any(p.oci_ref.startswith("./") for p in info.packages)
        if not env_vars and has_bundled:
            return 1
        if env_vars <= {"GITHUB_TOKEN"}:
            return 2
        return 3


def _index_dpdy(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index dynamic-plugins.default.yaml entries by inferred package name."""
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        package = entry.get("package", "")
        pkg_name = _extract_package_name(package)
        if pkg_name:
            result[pkg_name] = {
                "oci_ref": package,
                "disabled": entry.get("disabled", True),
                "pluginConfig": entry.get("pluginConfig", {}),
            }
    return result


def _extract_package_name(package_ref: str) -> str:
    """Extract the package name from an OCI ref or local path.

    Examples:
      oci://ghcr.io/.../backstage-community-plugin-github-actions:tag → backstage-community-plugin-github-actions
      ./dynamic-plugins/dist/backstage-community-plugin-github-actions → backstage-community-plugin-github-actions
    """
    if "!" in package_ref:
        return package_ref.split("!")[-1]
    name = package_ref.split("/")[-1]
    name = re.sub(r"[@:].*$", "", name)
    if name.endswith("-dynamic"):
        name = name[:-8]
    return name


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
