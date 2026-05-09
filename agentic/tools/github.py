"""GitHub API tools for repo scanning — uses `gh` CLI with GITHUB_TOKEN fallback."""

from __future__ import annotations

import json
import os
import subprocess
from fnmatch import fnmatch
from typing import Any

import httpx


def _gh_available() -> bool:
    try:
        subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _api_headers() -> dict[str, str]:
    token = _github_token()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_api(endpoint: str) -> Any:
    """Call GitHub API via `gh` CLI or direct HTTP."""
    if _gh_available():
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    url = f"https://api.github.com/{endpoint.lstrip('/')}"
    resp = httpx.get(url, headers=_api_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL."""
    url = url.rstrip("/")
    if url.startswith("git@"):
        path = url.split(":")[-1]
    else:
        path = "/".join(url.split("/")[-2:])
    path = path.removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse owner/repo from: {url}")
    return parts[-2], parts[-1]


def get_repo_info(owner: str, repo: str) -> dict[str, Any]:
    """Get basic repo info (default branch, description, etc.)."""
    return _gh_api(f"repos/{owner}/{repo}")


def get_repo_tree(owner: str, repo: str, branch: str = "main") -> list[str]:
    """Get the full file tree of a repo (paths only)."""
    try:
        data = _gh_api(f"repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
        return [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]
    except (httpx.HTTPStatusError, subprocess.CalledProcessError):
        data = _gh_api(f"repos/{owner}/{repo}/git/trees/master?recursive=1")
        return [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]


def get_repo_languages(owner: str, repo: str) -> dict[str, float]:
    """Get language breakdown (language -> bytes)."""
    data = _gh_api(f"repos/{owner}/{repo}/languages")
    total = sum(data.values()) if data else 1
    return {lang: round(bytes_ / total * 100, 1) for lang, bytes_ in data.items()}


def get_file_content(owner: str, repo: str, path: str) -> str:
    """Read a single file's content from a repo."""
    if _gh_available():
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/contents/{path}", "--jq", ".content"],
            capture_output=True, text=True, check=True,
        )
        import base64
        return base64.b64decode(result.stdout.strip()).decode("utf-8", errors="replace")

    data = _gh_api(f"repos/{owner}/{repo}/contents/{path}")
    if isinstance(data, dict) and data.get("encoding") == "base64":
        import base64
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return ""


def match_file_patterns(file_tree: list[str], patterns: list[str]) -> list[str]:
    """Find files in the tree matching any of the given glob patterns."""
    matches = []
    for filepath in file_tree:
        for pattern in patterns:
            if fnmatch(filepath, pattern):
                matches.append(filepath)
                break
    return matches
