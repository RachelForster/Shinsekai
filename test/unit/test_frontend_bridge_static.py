from core.plugins.github_bundle_update import publish_frontend_dist_release
from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.static import _frontend_dist_fallback_roots, _frontend_dist_root


def test_frontend_dist_root_uses_published_release_pointer(tmp_path):
    raw_dist = tmp_path / "frontend" / "dist"
    raw_dist.mkdir(parents=True)
    (raw_dist / "index.html").write_text("old frontend", encoding="utf-8")
    source = tmp_path / "source-dist"
    source.mkdir()
    (source / "index.html").write_text("new frontend", encoding="utf-8")

    publish_frontend_dist_release(tmp_path, source, release_id="v2")
    state = BridgeState(None, None, None, None, frontend_dist_dir=str(raw_dist))

    assert _frontend_dist_root(state) == (tmp_path / "frontend" / ".dist-releases" / "v2").resolve()
    assert raw_dist.resolve() in _frontend_dist_fallback_roots(state)
