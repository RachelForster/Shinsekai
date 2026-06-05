from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.static import _frontend_dist_root


def test_frontend_dist_root_returns_none_without_configured_dist():
    state = BridgeState(None, None, None, None)

    assert _frontend_dist_root(state) is None


def test_frontend_dist_root_resolves_configured_dist(tmp_path):
    raw_dist = tmp_path / "frontend" / "dist"
    state = BridgeState(None, None, None, None, frontend_dist_dir=str(raw_dist))

    assert _frontend_dist_root(state) == raw_dist.resolve()
