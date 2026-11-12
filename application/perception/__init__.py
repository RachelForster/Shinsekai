"""Application orchestration and chat hooks for real-time game perception."""

from application.perception.coordinator import PerceptionCoordinator
from application.perception.hooks import PerceptionAutoHooks, install_perception_hooks
from application.perception.server_launcher import (
    PerceptionLocalServerManager,
    discover_perception_python,
    get_perception_server_manager,
    shutdown_perception_local_server,
)

__all__ = [
    "PerceptionAutoHooks",
    "PerceptionCoordinator",
    "PerceptionLocalServerManager",
    "discover_perception_python",
    "get_perception_server_manager",
    "install_perception_hooks",
    "shutdown_perception_local_server",
]
