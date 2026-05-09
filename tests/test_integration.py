"""Integration test — exercises scan+propose phase against a real GitHub repo via Vertex AI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentic.agents.client import create_client
from agentic.agents.prompts import build_unified_system
from agentic.agents.session import run_agent_loop
from agentic.agents.tools import ALL_TOOLS
from agentic.knowledge import PluginKnowledgeBase, extract_catalog_index
from agentic.ui.app import parse_proposals_from_response

TEST_REPO = "https://github.com/redhat-developer/rhdh-local"


def main() -> None:
    project_root = Path(__file__).parent.parent

    # 1. Knowledge base
    print("=== Step 1: Knowledge base ===")
    extract_dir = extract_catalog_index()
    kb = PluginKnowledgeBase.build(extract_dir)
    print(f"  Loaded {len(kb.plugins)} plugins")

    # 2. Client
    print("\n=== Step 2: Client ===")
    client = create_client()
    print(f"  Client type: {type(client).__name__}")

    # 3. System prompt
    print("\n=== Step 3: System prompt ===")
    knowledge_context = kb.to_agent_context()
    system_prompt = build_unified_system(knowledge_context)
    print(f"  System prompt: {len(system_prompt)} chars")

    # 4. Scan + Propose
    print("\n=== Step 4: Scan + Propose ===")
    messages: list[dict] = [
        {"role": "user", "content": f"Scan these repositories and propose plugins and catalog entities:\n- {TEST_REPO}"},
    ]

    def on_event(event_type: str, event_data: dict) -> None:
        if event_type == "tool_use":
            print(f"  [tool] {event_data.get('tool', '')}({json.dumps(event_data.get('input', {}), default=str)[:80]})")
        elif event_type == "tool_result":
            tool = event_data.get("tool", "")
            result = event_data.get("result", {})
            if tool == "scan_repo_tree":
                print(f"  [result] {result.get('count', 0)} files found")
            elif tool == "get_repo_languages":
                print(f"  [result] languages: {result.get('languages', {})}")
        elif event_type == "agent_text":
            text = event_data.get("text", "")
            if text.strip():
                preview = text.strip()[:120]
                print(f"  [agent] {preview}...")

    try:
        response_content = run_agent_loop(
            client=client,
            system=system_prompt,
            tools=ALL_TOOLS,
            messages=messages,
            project_root=project_root,
            on_event=on_event,
        )
    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return

    # 5. Parse proposals
    print("\n=== Step 5: Parse proposals ===")
    plugin_proposals, entity_proposals = parse_proposals_from_response(response_content)
    print(f"  Plugin proposals: {len(plugin_proposals)}")
    for p in plugin_proposals:
        print(f"    - {p.plugin} ({p.confidence.value}) — {p.reason[:60]}")
    print(f"  Entity proposals: {len(entity_proposals)}")
    for e in entity_proposals:
        print(f"    - {e.name} ({e.component_type.value}) — {e.source_repo}")

    # 6. Show raw response if no proposals parsed
    if not plugin_proposals and not entity_proposals:
        print("\n  WARNING: No proposals parsed. Raw agent response:")
        for block in response_content:
            if block.get("type") == "text":
                print(f"  {block.get('text', '')[:500]}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
