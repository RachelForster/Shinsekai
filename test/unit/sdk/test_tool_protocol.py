from inspect import signature
from typing import get_type_hints

from ai.tools.tool_manager import ToolManager as HostToolManager
from sdk.tool_protocol import ToolManager as SDKToolManager


def test_sdk_execute_protocol_matches_host_json_contract() -> None:
    sdk_execute = SDKToolManager.execute
    host_execute = HostToolManager.execute

    assert tuple(signature(sdk_execute).parameters) == (
        "self",
        "name",
        "arguments_json",
    )
    assert tuple(signature(host_execute).parameters) == (
        "self",
        "name",
        "arguments_json",
    )
    assert (
        get_type_hints(sdk_execute)
        == get_type_hints(host_execute)
        == {
            "name": str,
            "arguments_json": str,
            "return": str,
        }
    )
