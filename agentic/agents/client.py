"""Client factory — auto-detects Vertex AI or direct Anthropic."""

from __future__ import annotations

import os

import anthropic
from anthropic import AnthropicVertex


def create_client() -> anthropic.Anthropic:
    """Create the right Claude client based on environment variables.

    Vertex AI: CLAUDE_CODE_USE_VERTEX=1 + ANTHROPIC_VERTEX_PROJECT_ID
    Direct:    ANTHROPIC_API_KEY
    """
    if os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
        project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
        region = os.environ.get("CLOUD_ML_REGION", "us-east5")
        if not project_id:
            raise RuntimeError(
                "CLAUDE_CODE_USE_VERTEX=1 but ANTHROPIC_VERTEX_PROJECT_ID is not set. "
                "Set it to your GCP project ID."
            )
        return AnthropicVertex(region=region, project_id=project_id)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic()

    raise RuntimeError(
        "No Claude authentication found. Either:\n"
        "  - Set CLAUDE_CODE_USE_VERTEX=1 + ANTHROPIC_VERTEX_PROJECT_ID (Vertex AI)\n"
        "  - Set ANTHROPIC_API_KEY (direct Anthropic API)"
    )
