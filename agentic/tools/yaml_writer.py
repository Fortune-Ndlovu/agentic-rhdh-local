"""Atomic YAML writer with validation and backup."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml


def write_yaml(path: str | Path, data: Any, *, backup: bool = True) -> Path:
    """Atomically write YAML data to a file.

    Writes to a temp file first, validates the YAML round-trips, then moves into place.
    Creates parent dirs and backs up existing files.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        backup_path = path.with_suffix(f"{path.suffix}.bak")
        shutil.copy2(path, backup_path)

    serialized = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    yaml.safe_load(serialized)

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            f.write(serialized)
        import os
        os.chmod(tmp_path, 0o644)
        Path(tmp_path).rename(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return path


def read_yaml(path: str | Path) -> Any:
    """Read and parse a YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def merge_yaml_file(path: str | Path, updates: dict[str, Any]) -> Path:
    """Read existing YAML, deep-merge updates, write back atomically."""
    path = Path(path)
    existing = {}
    if path.exists():
        existing = read_yaml(path) or {}
    _deep_merge(existing, updates)
    return write_yaml(path, existing)


def append_to_yaml_list(path: str | Path, key: str, items: list[Any]) -> Path:
    """Append items to a list inside a YAML file."""
    path = Path(path)
    data = {}
    if path.exists():
        data = read_yaml(path) or {}

    existing_list = data.get(key, [])
    if not isinstance(existing_list, list):
        existing_list = []

    existing_list.extend(items)
    data[key] = existing_list
    return write_yaml(path, data)


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
