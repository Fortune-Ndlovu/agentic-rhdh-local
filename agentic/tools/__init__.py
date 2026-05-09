"""Local tool implementations — executed by the CLI, results sent back to agents."""

from .compose import (
    compose_run,
    detect_compose_command,
    get_container_logs,
    is_running,
    restart_rhdh,
    run_install_plugins,
)
from .github import (
    get_file_content,
    get_repo_info,
    get_repo_languages,
    get_repo_tree,
    match_file_patterns,
    parse_repo_url,
)
from .health_check import (
    HealthResult,
    check_health_with_diagnosis,
    check_rhdh_health,
    diagnose_plugin_errors,
    wait_for_healthy,
)
from .yaml_writer import (
    append_to_yaml_list,
    merge_yaml_file,
    read_yaml,
    write_yaml,
)

__all__ = [
    "compose_run",
    "detect_compose_command",
    "get_container_logs",
    "is_running",
    "restart_rhdh",
    "run_install_plugins",
    "get_file_content",
    "get_repo_info",
    "get_repo_languages",
    "get_repo_tree",
    "match_file_patterns",
    "parse_repo_url",
    "HealthResult",
    "check_health_with_diagnosis",
    "check_rhdh_health",
    "diagnose_plugin_errors",
    "wait_for_healthy",
    "append_to_yaml_list",
    "merge_yaml_file",
    "read_yaml",
    "write_yaml",
]
