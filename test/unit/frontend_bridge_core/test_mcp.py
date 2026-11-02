from pathlib import Path

from frontend_bridge_core import mcp


def test_open_mcp_config_file_uses_transport_adapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "mcp.yaml"
    opened: list[str] = []
    monkeypatch.setattr(mcp, "ensure_mcp_config_file", lambda: path)
    monkeypatch.setattr(
        mcp.webbrowser,
        "open",
        lambda uri: opened.append(uri),
    )

    result = mcp._open_mcp_config_file()

    assert result == {"path": path.as_posix()}
    assert opened == [path.resolve().as_uri()]
