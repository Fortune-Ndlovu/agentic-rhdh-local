"""Tool definitions for the Messages API (JSON Schema format)."""

from __future__ import annotations

from typing import Any

SCAN_REPO_TREE_TOOL: dict[str, Any] = {
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

READ_YAML_TOOL: dict[str, Any] = {
    "name": "read_yaml",
    "description": "Read and parse a local YAML file relative to the project root. Returns the parsed content as JSON. Use this to check existing config before writing — e.g., read components.override.yaml to see existing entity targets before adding new ones, or read dynamic-plugins.override.yaml to see already-enabled plugins.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
        },
        "required": ["path"],
    },
}

WRITE_YAML_TOOL: dict[str, Any] = {
    "name": "write_yaml",
    "description": "Atomically write YAML content to a file. Creates backups, validates YAML, and creates parent directories. WARNING: this REPLACES the entire file. Use merge_yaml instead when you need to add settings without overwriting existing content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "content": {"type": "object", "description": "YAML content as a JSON object"},
        },
        "required": ["path", "content"],
    },
}

MERGE_YAML_TOOL: dict[str, Any] = {
    "name": "merge_yaml",
    "description": "Deep-merge YAML content into an existing file. Dict keys are merged recursively; arrays at the same key are REPLACED (Backstage merge semantics). Creates the file if it doesn't exist. Use this for app-config.local.yaml to add plugin-specific settings (techdocs, proxy) without overwriting other sections.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "content": {"type": "object", "description": "YAML content to deep-merge into the file"},
        },
        "required": ["path", "content"],
    },
}

RESTART_RHDH_TOOL: dict[str, Any] = {
    "name": "restart_rhdh",
    "description": "Restart the RHDH container via docker/podman compose. Returns success status and output.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

CHECK_RHDH_HEALTH_TOOL: dict[str, Any] = {
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

LOOKUP_PLUGIN_CONFIG_TOOL: dict[str, Any] = {
    "name": "lookup_plugin_config",
    "description": (
        "Look up full configuration details for an RHDH plugin by name. "
        "Returns exact package refs (OCI or bundled paths), pluginConfig, "
        "required env vars, and tier classification. "
        "ALWAYS call this before proposing a plugin to get the correct package ref and config."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plugin_name": {
                "type": "string",
                "description": "Plugin name from the knowledge base (e.g. 'github-actions', 'techdocs', 'topology')",
            },
        },
        "required": ["plugin_name"],
    },
}

WRITE_FILE_TOOL: dict[str, Any] = {
    "name": "write_file",
    "description": "Write arbitrary text content to a file (for markdown, etc.). Creates parent directories and backups. Use write_yaml for YAML files instead.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "content": {"type": "string", "description": "Text content to write"},
        },
        "required": ["path", "content"],
    },
}

SCANNER_TOOLS = [SCAN_REPO_TREE_TOOL, READ_REPO_FILE_TOOL, GET_REPO_LANGUAGES_TOOL, GET_REPO_INFO_TOOL]
CONFIG_WRITER_TOOLS = [READ_YAML_TOOL, WRITE_YAML_TOOL, MERGE_YAML_TOOL, WRITE_FILE_TOOL, RESTART_RHDH_TOOL, CHECK_RHDH_HEALTH_TOOL, DIAGNOSE_PLUGIN_ERRORS_TOOL, READ_CONTAINER_LOGS_TOOL]
KNOWLEDGE_TOOLS = [LOOKUP_PLUGIN_CONFIG_TOOL]

ALL_TOOLS = SCANNER_TOOLS + KNOWLEDGE_TOOLS + CONFIG_WRITER_TOOLS
