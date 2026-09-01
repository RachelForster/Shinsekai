from pathlib import Path

from config.repository.mcp_config import (
    default_mcp_config,
    read_mcp_config,
    write_mcp_config,
)


def test_mcp_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "mcp.yaml"
    config = {
        "enabled": False,
        "default_call_timeout": 42,
        "servers": [
            {
                "transport": "stdio",
                "command": "example",
            }
        ],
    }

    write_mcp_config(config, path)

    assert read_mcp_config(path) == {
        "enabled": False,
        "default_call_timeout": 42.0,
        "servers": config["servers"],
    }


def test_missing_mcp_config_returns_fresh_defaults(
    tmp_path: Path,
) -> None:
    first = read_mcp_config(tmp_path / "missing.yaml")
    first["servers"].append({"transport": "sse"})

    assert read_mcp_config(tmp_path / "missing.yaml") == default_mcp_config()
