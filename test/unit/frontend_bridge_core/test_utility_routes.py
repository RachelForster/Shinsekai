from __future__ import annotations

from frontend_bridge_core.routes.utility_routes import UTILITY_ROUTES


def _contracts() -> set[tuple[str, str]]:
    return {
        (method, route.pattern) for route in UTILITY_ROUTES for method in route.methods
    }


def test_utility_route_contracts_remain_stable() -> None:
    assert _contracts() == {
        ("GET", "/api/logs"),
        ("GET", "/api/logs/default"),
        ("POST", "/api/files/browse"),
        ("POST", "/api/logs/diagnostic-bundle"),
        ("POST", "/api/logs/read"),
        ("POST", "/api/media/thumbnails"),
    }
