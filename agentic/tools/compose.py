"""Docker/Podman compose operations for RHDH container management."""

from __future__ import annotations

import subprocess
from pathlib import Path


def detect_compose_command(project_root: Path | None = None) -> list[str]:
    """Detect whether to use 'podman compose' or 'docker compose'.

    Automatically includes the developer-lightspeed compose overlay
    when it exists in the project root.
    """
    for cmd in (["podman", "compose"], ["docker", "compose"], ["docker-compose"]):
        try:
            subprocess.run([*cmd, "version"], capture_output=True, check=True)
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    else:
        raise RuntimeError("No compose command found. Install podman-compose or docker-compose.")

    if project_root:
        lightspeed_compose = project_root / "developer-lightspeed" / "compose.yaml"
        if lightspeed_compose.exists():
            return [*cmd, "-f", "compose.yaml", "-f", str(lightspeed_compose.relative_to(project_root))]

    return cmd


def compose_run(
    command: str,
    project_root: Path | None = None,
    *,
    service: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a compose command (up, down, restart, logs, etc.)."""
    compose = detect_compose_command(project_root)
    args = [*compose, command]
    if service:
        args.append(service)

    kwargs: dict = dict(
        capture_output=True, text=True, timeout=timeout,
    )
    if project_root:
        kwargs["cwd"] = str(project_root)

    return subprocess.run(args, **kwargs)


def restart_rhdh(project_root: Path) -> tuple[bool, str]:
    """Restart RHDH by cycling containers so the plugin installer re-runs."""
    compose = detect_compose_command(project_root)
    down = subprocess.run(
        [*compose, "down"],
        capture_output=True, text=True, timeout=60,
        cwd=str(project_root),
    )
    up = subprocess.run(
        [*compose, "up", "-d"],
        capture_output=True, text=True, timeout=180,
        cwd=str(project_root),
    )
    success = up.returncode == 0
    output = down.stdout + down.stderr + up.stdout + up.stderr
    return success, output


def run_install_plugins(project_root: Path) -> tuple[bool, str]:
    """Run the install-dynamic-plugins init container."""
    compose_run("stop", project_root, service="install-dynamic-plugins")
    result = compose_run("up", project_root, service="install-dynamic-plugins", timeout=180)
    success = result.returncode == 0
    output = result.stdout + result.stderr
    return success, output


def get_container_logs(
    project_root: Path,
    service: str = "rhdh",
    lines: int = 100,
) -> str:
    """Get recent container logs."""
    compose = detect_compose_command(project_root)
    result = subprocess.run(
        [*compose, "logs", "--tail", str(lines), service],
        capture_output=True, text=True, timeout=30,
        cwd=str(project_root),
    )
    return result.stdout + result.stderr


def is_running(project_root: Path, service: str = "rhdh") -> bool:
    """Check if a compose service is running."""
    compose = detect_compose_command(project_root)
    result = subprocess.run(
        [*compose, "ps", "--status=running", service],
        capture_output=True, text=True, timeout=15,
        cwd=str(project_root),
    )
    return service in result.stdout
