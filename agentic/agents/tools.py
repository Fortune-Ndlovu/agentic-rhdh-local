"""Custom tool definitions for Managed Agents (JSON Schema format)."""

from __future__ import annotations

from typing import Any

SCAN_REPO_TREE_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "scan_repo_tree",
    "description": "Get the full file tree of a GitHub repository. Returns a list of all file paths.",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "GitHub org or user"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    },
}

READ_REPO_FILE_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "read_repo_file",
    "description": "Read a specific file's content from a GitHub repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "GitHub org or user"},
            "repo": {"type": "string", "description": "Repository name"},
            "path": {"type": "string", "description": "File path within the repo"},
        },
        "required": ["owner", "repo", "path"],
    },
}

GET_REPO_LANGUAGES_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "get_repo_languages",
    "description": "Get the language breakdown of a GitHub repository as percentages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "GitHub org or user"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    },
}

GET_REPO_INFO_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "get_repo_info",
    "description": "Get basic repository info (default branch, description, etc.).",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "GitHub org or user"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    },
}

WRITE_YAML_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "write_yaml",
    "description": "Atomically write YAML content to a file. Creates backups, validates YAML, and creates parent directories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write to"},
            "content": {"type": "object", "description": "YAML content as a JSON object"},
        },
        "required": ["path", "content"],
    },
}

RESTART_RHDH_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "restart_rhdh",
    "description": "Restart the RHDH container via docker/podman compose. Returns success status and output.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

CHECK_RHDH_HEALTH_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "check_rhdh_health",
    "description": "Check if RHDH is healthy (HTTP 200 on /healthcheck). Optionally waits up to max_wait seconds.",
    "input_schema": {
        "type": "object",
        "properties": {
            "wait": {"type": "boolean", "description": "If true, poll until healthy or timeout", "default": False},
            "max_wait": {"type": "integer", "description": "Max seconds to wait (default 120)", "default": 120},
        },
    },
}

DIAGNOSE_PLUGIN_ERRORS_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "diagnose_plugin_errors",
    "description": "Parse RHDH container logs for plugin-related errors. Returns a list of error messages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lines": {"type": "integer", "description": "Number of log lines to check (default 200)", "default": 200},
        },
    },
}

READ_CONTAINER_LOGS_TOOL: dict[str, Any] = {
    "type": "custom",
    "name": "read_container_logs",
    "description": "Read recent RHDH container logs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name (default 'rhdh')", "default": "rhdh"},
            "lines": {"type": "integer", "description": "Number of lines (default 100)", "default": 100},
        },
    },
}

SCANNER_TOOLS = [SCAN_REPO_TREE_TOOL, READ_REPO_FILE_TOOL, GET_REPO_LANGUAGES_TOOL, GET_REPO_INFO_TOOL]
RECOMMENDER_TOOLS: list[dict[str, Any]] = []
ENTITY_GENERATOR_TOOLS: list[dict[str, Any]] = []
CONFIG_WRITER_TOOLS = [WRITE_YAML_TOOL, RESTART_RHDH_TOOL, CHECK_RHDH_HEALTH_TOOL, DIAGNOSE_PLUGIN_ERRORS_TOOL, READ_CONTAINER_LOGS_TOOL]
