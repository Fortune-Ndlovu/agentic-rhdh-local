"""Tool-use loop — runs the agent via Messages API with local tool dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import anthropic

from ..tools.compose import get_container_logs, restart_rhdh
from ..tools.github import get_file_content, get_repo_info, get_repo_languages, get_repo_tree
from ..tools.health_check import check_rhdh_health, diagnose_plugin_errors, wait_for_healthy
from ..tools.yaml_writer import merge_yaml_file, read_yaml, write_text_file, write_yaml

if TYPE_CHECKING:
    from ..knowledge.plugin_index import PluginKnowledgeBase

MODEL = "claude-sonnet-4-6"


def run_agent_loop(
    client: anthropic.Anthropic,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    project_root: Path,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    max_turns: int = 25,
    knowledge_base: PluginKnowledgeBase | None = None,
) -> list[dict[str, Any]]:
    """Run the Messages API tool-use loop with streaming until the agent finishes.

    Appends to `messages` in place (maintains conversation history across calls).
    Returns the content blocks from the final assistant response.
    """
    assistant_content: list[dict[str, Any]] = []

    for turn in range(max_turns):
        if on_event:
            on_event("turn_start", {"turn": turn})

        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=system,
            tools=tools,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text") and on_event:
                        on_event("text_delta", {"text": event.delta.text})

            response = stream.get_final_message()

        assistant_content = _serialize_content(response.content)
        messages.append({"role": "assistant", "content": assistant_content})

        if on_event:
            for block in response.content:
                if hasattr(block, "text"):
                    on_event("text_done", {"text": block.text})

        if response.stop_reason == "end_turn":
            return assistant_content

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if on_event:
                        on_event("tool_start", {"tool": block.name, "input": block.input})

                    result = dispatch_tool(block.name, block.input, project_root, knowledge_base)

                    if on_event:
                        on_event("tool_end", {"tool": block.name, "result": result})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return assistant_content


def dispatch_tool(
    name: str,
    tool_input: dict[str, Any],
    project_root: Path,
    knowledge_base: PluginKnowledgeBase | None = None,
) -> dict[str, Any]:
    """Execute a tool locally and return the result."""
    try:
        if name == "lookup_plugin_config":
            if not knowledge_base:
                return {"error": "Knowledge base not available"}
            details = knowledge_base.get_plugin_config_details(tool_input["plugin_name"])
            if not details:
                return {"error": f"Plugin '{tool_input['plugin_name']}' not found in knowledge base"}
            return details

        elif name == "scan_repo_tree":
            tree = get_repo_tree(tool_input["owner"], tool_input["repo"])
            return {"files": tree, "count": len(tree)}

        elif name == "read_repo_file":
            content = get_file_content(tool_input["owner"], tool_input["repo"], tool_input["path"])
            return {"content": content}

        elif name == "get_repo_languages":
            langs = get_repo_languages(tool_input["owner"], tool_input["repo"])
            return {"languages": langs}

        elif name == "get_repo_info":
            info = get_repo_info(tool_input["owner"], tool_input["repo"])
            return {
                "default_branch": info.get("default_branch", "main"),
                "description": info.get("description", ""),
                "language": info.get("language", ""),
                "topics": info.get("topics", []),
            }

        elif name == "read_yaml":
            path = project_root / tool_input["path"]
            if not path.exists():
                return {"exists": False, "content": None}
            data = read_yaml(path)
            return {"exists": True, "content": data}

        elif name == "write_yaml":
            path = project_root / tool_input["path"]
            write_yaml(path, tool_input["content"])
            return {"success": True, "path": str(path)}

        elif name == "merge_yaml":
            path = project_root / tool_input["path"]
            merge_yaml_file(path, tool_input["content"])
            return {"success": True, "path": str(path)}

        elif name == "write_file":
            path = project_root / tool_input["path"]
            write_text_file(path, tool_input["content"])
            return {"success": True, "path": str(path)}

        elif name == "restart_rhdh":
            success, output = restart_rhdh(project_root)
            return {"success": success, "output": output}

        elif name == "check_rhdh_health":
            if tool_input.get("wait", False):
                result = wait_for_healthy(max_wait=tool_input.get("max_wait", 120))
            else:
                result = check_rhdh_health()
            return {
                "healthy": result.healthy,
                "status_code": result.status_code,
                "message": result.message,
            }

        elif name == "diagnose_plugin_errors":
            errors = diagnose_plugin_errors(project_root, lines=tool_input.get("lines", 200))
            return {"errors": errors, "count": len(errors)}

        elif name == "read_container_logs":
            logs = get_container_logs(
                project_root,
                service=tool_input.get("service", "rhdh"),
                lines=tool_input.get("lines", 100),
            )
            return {"logs": logs}

        else:
            return {"error": f"Unknown tool: {name}"}

    except Exception as e:
        return {"error": str(e)}


def _serialize_content(content: list[Any]) -> list[dict[str, Any]]:
    """Convert SDK content blocks to JSON-serializable dicts for message history."""
    serialized = []
    for block in content:
        if block.type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return serialized
