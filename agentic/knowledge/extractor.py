"""Extract and parse the RHDH plugin catalog index image."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

console = Console()

DEFAULT_CATALOG_IMAGE = "quay.io/rhdh/plugin-catalog-index:1.10"
DEFAULT_EXTRACT_DIR = Path("/tmp/rhdh-catalog-extract")


def detect_container_runtime() -> str:
    for rt in ("podman", "docker"):
        try:
            subprocess.run([rt, "--version"], capture_output=True, check=True)
            return rt
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("Neither podman nor docker found. Install one to continue.")


def extract_catalog_index(
    image: str = DEFAULT_CATALOG_IMAGE,
    dest: Path = DEFAULT_EXTRACT_DIR,
    force: bool = False,
) -> Path:
    """Pull and extract the catalog index image. Returns the extraction directory."""
    if dest.exists() and not force:
        dpdy = dest / "dynamic-plugins.default.yaml"
        if dpdy.exists():
            return dest

    runtime = detect_container_runtime()
    dest.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Pulling {image}...[/dim]")
    subprocess.run([runtime, "pull", image], check=True, capture_output=True)

    container_id = subprocess.run(
        [runtime, "create", image],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    try:
        console.print("[dim]Extracting catalog data...[/dim]")
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
            subprocess.run(
                [runtime, "export", container_id],
                stdout=tmp, check=True,
            )
            tmp_path = tmp.name

        subprocess.run(
            ["tar", "xf", tmp_path, "-C", str(dest)],
            check=True, capture_output=True,
        )
        Path(tmp_path).unlink(missing_ok=True)
    finally:
        subprocess.run([runtime, "rm", container_id], capture_output=True)

    return dest


def load_dynamic_plugins_default(extract_dir: Path) -> list[dict[str, Any]]:
    """Parse dynamic-plugins.default.yaml into a list of plugin entries."""
    dpdy = extract_dir / "dynamic-plugins.default.yaml"
    if not dpdy.exists():
        raise FileNotFoundError(f"{dpdy} not found. Run extract_catalog_index first.")

    with open(dpdy) as f:
        data = yaml.safe_load(f)

    return data.get("plugins", [])


def load_plugin_yamls(extract_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all plugin YAML definitions. Keyed by plugin name."""
    plugins_dir = extract_dir / "catalog-entities" / "extensions" / "plugins"
    result: dict[str, dict[str, Any]] = {}
    if not plugins_dir.exists():
        return result

    for f in plugins_dir.glob("*.yaml"):
        if f.name.startswith("1-") or f.name == "all.yaml":
            continue
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data and data.get("kind") == "Plugin":
                name = data["metadata"]["name"]
                result[name] = data
        except (yaml.YAMLError, KeyError):
            continue
    return result


def load_package_yamls(extract_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all package YAML definitions. Keyed by package name."""
    pkgs_dir = extract_dir / "catalog-entities" / "extensions" / "packages"
    result: dict[str, dict[str, Any]] = {}
    if not pkgs_dir.exists():
        return result

    for f in pkgs_dir.glob("*.yaml"):
        if f.name.startswith("1-"):
            continue
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data and data.get("kind") == "Package":
                name = data["metadata"]["name"]
                result[name] = data
        except (yaml.YAMLError, KeyError):
            continue
    return result


def load_index_json(extract_dir: Path) -> dict[str, Any]:
    """Load the index.json with OCI references and metadata."""
    idx = extract_dir / "index.json"
    if not idx.exists():
        return {}
    with open(idx) as f:
        return json.load(f)
