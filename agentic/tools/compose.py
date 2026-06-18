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
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a compose command (up, down, restart, logs, etc.)."""
    compose = detect_compose_command(project_root)
    args = [*compose, command]
    if extra_args:
        args.extend(extra_args)
    if service:
        args.append(service)

    kwargs: dict = dict(
        capture_output=True, text=True, timeout=timeout,
    )
    if project_root:
        kwargs["cwd"] = str(project_root)

    return subprocess.run(args, **kwargs)


COMPOSE_VOLUME_VARS = [
    "VERTEX_AI_CREDENTIALS_PATH",
]


def _lightspeed_enabled(project_root: Path) -> bool:
    return (project_root / "developer-lightspeed" / "compose.yaml").exists()


def _restart_services(project_root: Path) -> list[str]:
    """Services to restart after config changes (lightspeed shares rhdh's network)."""
    services = ["rhdh"]
    if _lightspeed_enabled(project_root) and is_running(project_root, "lightspeed-core"):
        services.append("lightspeed-core")
    return services


def ensure_dotenv_compose_vars(project_root: Path) -> None:
    """Copy volume-mount variables from default.env to .env so compose can resolve them.

    Compose only reads .env (not env_file entries like default.env) for variable
    substitution in volume mounts. Without this, mounts using ${VAR:-fallback}
    silently fall back to placeholder files.
    """
    default_env = project_root / "default.env"
    dot_env = project_root / ".env"

    if not default_env.exists():
        return

    source_vars: dict[str, str] = {}
    for line in default_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in COMPOSE_VOLUME_VARS and value.strip():
            source_vars[key] = value.strip()

    if not source_vars:
        return

    existing: dict[str, str] = {}
    existing_lines: list[str] = []
    if dot_env.exists():
        existing_lines = dot_env.read_text().splitlines()
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                existing[k.strip()] = stripped

    new_lines: list[str] = []
    for key, value in source_vars.items():
        if key not in existing:
            new_lines.append(f"{key}={value}")

    if new_lines:
        content = "\n".join(existing_lines + new_lines) + "\n"
        dot_env.write_text(content)


def run_install_plugins(project_root: Path) -> tuple[bool, str]:
    """Re-run the install-dynamic-plugins init container and wait for completion."""
    compose = detect_compose_command(project_root)
    # Foreground, no deps: only reinstall plugins — do not start/stop rhdh or lightspeed.
    result = subprocess.run(
        [
            *compose,
            "up",
            "--no-deps",
            "--force-recreate",
            "--abort-on-container-exit",
            "install-dynamic-plugins",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(project_root),
    )
    success = result.returncode == 0
    output = result.stdout + result.stderr
    return success, output


def _full_stack_restart(project_root: Path) -> tuple[bool, str]:
    """Tear down and recreate the entire compose stack (cold start / recovery)."""
    compose = detect_compose_command(project_root)
    down = subprocess.run(
        [*compose, "down"],
        capture_output=True, text=True, timeout=60,
        cwd=str(project_root),
    )
    up = subprocess.run(
        [*compose, "up", "-d"],
        capture_output=True, text=True, timeout=300,
        cwd=str(project_root),
    )
    success = up.returncode == 0
    output = down.stdout + down.stderr + up.stdout + up.stderr
    return success, output


def _fast_restart(
    project_root: Path,
    *,
    reinstall_plugins: bool,
) -> tuple[bool, str]:
    """Restart only what changed — skip full stack teardown."""
    compose = detect_compose_command(project_root)
    output_parts: list[str] = []

    if reinstall_plugins:
        ok, out = run_install_plugins(project_root)
        output_parts.append(out)
        if not ok:
            return False, "".join(output_parts)

    services = _restart_services(project_root)
    result = subprocess.run(
        [*compose, "restart", *services],
        capture_output=True, text=True, timeout=120,
        cwd=str(project_root),
    )
    output_parts.append(result.stdout + result.stderr)

    # compose restart may warn on shared-network sidecars; running rhdh is what matters.
    success = result.returncode == 0 or is_running(project_root, "rhdh")
    return success, "".join(output_parts)


def restart_rhdh(
    project_root: Path,
    *,
    reinstall_plugins: bool = True,
    full: bool = False,
) -> tuple[bool, str]:
    """Apply config changes by restarting RHDH.

    Fast path (default when rhdh is already running):
      1. Optionally re-run install-dynamic-plugins (when plugin override changed)
      2. compose restart rhdh [+ lightspeed-core]

    Full path (cold start or explicit recovery):
      compose down && compose up -d — recreates every service including rag-init.
    """
    if full or not is_running(project_root, "rhdh"):
        return _full_stack_restart(project_root)
    return _fast_restart(project_root, reinstall_plugins=reinstall_plugins)


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
