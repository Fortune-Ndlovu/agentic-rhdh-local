"""RHDH health check with retry and log-based error diagnosis."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from .compose import get_container_logs

RHDH_BASE_URL = "http://localhost:7007"


@dataclass
class HealthResult:
    healthy: bool
    status_code: int = 0
    message: str = ""
    plugin_errors: list[str] | None = None


def check_rhdh_health(
    base_url: str = RHDH_BASE_URL,
    timeout: float = 10,
) -> HealthResult:
    """Single HTTP health check against RHDH."""
    try:
        resp = httpx.get(f"{base_url}/healthcheck", timeout=timeout, follow_redirects=True)
        if resp.status_code == 200:
            return HealthResult(healthy=True, status_code=200, message="OK")
        return HealthResult(
            healthy=False,
            status_code=resp.status_code,
            message=f"HTTP {resp.status_code}",
        )
    except httpx.ConnectError:
        return HealthResult(healthy=False, message="Connection refused — RHDH not running")
    except httpx.TimeoutException:
        return HealthResult(healthy=False, message="Timeout — RHDH not responding")
    except Exception as e:
        return HealthResult(healthy=False, message=str(e))


def wait_for_healthy(
    base_url: str = RHDH_BASE_URL,
    max_wait: int = 120,
    interval: int = 5,
    on_poll: Callable[[int, int, HealthResult], None] | None = None,
) -> HealthResult:
    """Poll RHDH until healthy or timeout.

    on_poll receives (attempt, elapsed_seconds, last_result) each iteration.
    """
    start = time.time()
    last_result = HealthResult(healthy=False, message="Never checked")
    attempt = 0

    while time.time() - start < max_wait:
        attempt += 1
        last_result = check_rhdh_health(base_url)
        elapsed = int(time.time() - start)
        if on_poll:
            on_poll(attempt, elapsed, last_result)
        if last_result.healthy:
            return last_result
        time.sleep(interval)

    last_result.message = f"Timed out after {max_wait}s: {last_result.message}"
    return last_result


def diagnose_plugin_errors(
    project_root: Path,
    lines: int = 200,
) -> list[str]:
    """Parse RHDH container logs for plugin-related errors."""
    logs = get_container_logs(project_root, "rhdh", lines)
    errors = []

    error_patterns = [
        r"(?i)error.*plugin.*(\S+)",
        r"(?i)failed to load.*dynamic plugin",
        r"(?i)cannot find module",
        r"(?i)ENOENT.*dynamic-plugins",
        r"(?i)missing required.*env",
        r"(?i)plugin.*disabled.*error",
    ]

    for line in logs.split("\n"):
        for pattern in error_patterns:
            if re.search(pattern, line):
                errors.append(line.strip())
                break

    return errors


def check_health_with_diagnosis(
    project_root: Path,
    base_url: str = RHDH_BASE_URL,
) -> HealthResult:
    """Combined health check + log diagnosis."""
    result = check_rhdh_health(base_url)
    if not result.healthy:
        result.plugin_errors = diagnose_plugin_errors(project_root)
    return result
