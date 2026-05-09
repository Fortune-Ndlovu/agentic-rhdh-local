"""Session management — create sessions, stream events, dispatch custom tool calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic

from ..models import AgentIDs
from ..tools.compose import get_container_logs, restart_rhdh
from ..tools.github import get_file_content, get_repo_info, get_repo_languages, get_repo_tree
from ..tools.health_check import check_rhdh_health, diagnose_plugin_errors, wait_for_healthy
from ..tools.yaml_writer import write_yaml


@dataclass
class SessionContext:
    """Tracks state for one onboarding session."""

    client: anthropic.Anthropic
    agent_ids: AgentIDs
    session_id: str = ""
    environment_id: str = ""
    project_root: Path = field(default_factory=lambda: Path.cwd())
    on_event: Callable[[str, dict[str, Any]], None] | None = None


def create_session(ctx: SessionContext) -> str:
    """Create an environment and session for the coordinator agent."""
    env = ctx.client.beta.environments.create()
    ctx.environment_id = env.id

    session = ctx.client.beta.sessions.create(
        agent={"type": "agent", "id": ctx.agent_ids.coordinator},
        environment_id=env.id,
    )
    ctx.session_id = session.id
    return session.id


def send_user_message(ctx: SessionContext, message: str) -> None:
    """Send a user message to the session."""
    ctx.client.beta.sessions.events.send(
        session_id=ctx.session_id,
        events=[{
            "type": "user_message",
            "content": [{"type": "text", "text": message}],
        }],
    )


def run_session_loop(ctx: SessionContext) -> list[dict[str, Any]]:
    """Stream session events until the session idles or terminates.

    Returns collected agent messages (the final output).
    """
    collected_messages: list[dict[str, Any]] = []

    while True:
        stream = ctx.client.beta.sessions.events.stream(session_id=ctx.session_id)

        for event in stream:
            event_type = event.type
            event_data = event.model_dump() if hasattr(event, "model_dump") else {}

            if ctx.on_event:
                ctx.on_event(event_type, event_data)

            if event_type == "agent.custom_tool_use":
                result = _handle_custom_tool(ctx, event)
                ctx.client.beta.sessions.events.send(
                    session_id=ctx.session_id,
                    events=[{
                        "type": "user_custom_tool_result",
                        "custom_tool_use_id": event.id,
                        "content": [{"type": "text", "text": json.dumps(result)}],
                    }],
                )

            elif event_type == "agent.message":
                content = event_data.get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        collected_messages.append({
                            "type": "agent_message",
                            "text": block.get("text", ""),
                        })

            elif event_type == "agent.thread_message_received":
                collected_messages.append({
                    "type": "thread_message",
                    "from_agent": event_data.get("from_agent_name", ""),
                    "content": event_data.get("content", ""),
                })

            elif event_type == "session.status_idle":
                stop_reason = event_data.get("stop_reason", {})
                if isinstance(stop_reason, dict) and stop_reason.get("type") == "end_turn":
                    return collected_messages

            elif event_type == "session.status_terminated":
                return collected_messages

            elif event_type == "session.error":
                error_msg = event_data.get("error", {}).get("message", "Unknown error")
                collected_messages.append({"type": "error", "text": error_msg})
                return collected_messages

        break

    return collected_messages


def _handle_custom_tool(ctx: SessionContext, event: Any) -> dict[str, Any]:
    """Dispatch a custom tool call to the appropriate local handler."""
    tool_name = event.name
    tool_input = event.input if isinstance(event.input, dict) else {}

    try:
        if tool_name == "scan_repo_tree":
            tree = get_repo_tree(tool_input["owner"], tool_input["repo"])
            return {"files": tree, "count": len(tree)}

        elif tool_name == "read_repo_file":
            content = get_file_content(tool_input["owner"], tool_input["repo"], tool_input["path"])
            return {"content": content}

        elif tool_name == "get_repo_languages":
            langs = get_repo_languages(tool_input["owner"], tool_input["repo"])
            return {"languages": langs}

        elif tool_name == "get_repo_info":
            info = get_repo_info(tool_input["owner"], tool_input["repo"])
            return {
                "default_branch": info.get("default_branch", "main"),
                "description": info.get("description", ""),
                "language": info.get("language", ""),
                "topics": info.get("topics", []),
            }

        elif tool_name == "write_yaml":
            path = ctx.project_root / tool_input["path"]
            write_yaml(path, tool_input["content"])
            return {"success": True, "path": str(path)}

        elif tool_name == "restart_rhdh":
            success, output = restart_rhdh(ctx.project_root)
            return {"success": success, "output": output}

        elif tool_name == "check_rhdh_health":
            if tool_input.get("wait", False):
                result = wait_for_healthy(max_wait=tool_input.get("max_wait", 120))
            else:
                result = check_rhdh_health()
            return {
                "healthy": result.healthy,
                "status_code": result.status_code,
                "message": result.message,
            }

        elif tool_name == "diagnose_plugin_errors":
            errors = diagnose_plugin_errors(ctx.project_root, lines=tool_input.get("lines", 200))
            return {"errors": errors, "count": len(errors)}

        elif tool_name == "read_container_logs":
            logs = get_container_logs(
                ctx.project_root,
                service=tool_input.get("service", "rhdh"),
                lines=tool_input.get("lines", 100),
            )
            return {"logs": logs}

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"error": str(e)}
