"""Unit tests for streaming tool call argument accumulation."""

from types import SimpleNamespace


def _make_function(name=None, arguments=None):
    return SimpleNamespace(name=name, arguments=arguments)


def _make_tool_call(index, name=None, arguments=None):
    return SimpleNamespace(index=index, function=_make_function(name=name, arguments=arguments))


def _accumulate(full_tool_calls: dict, tc) -> None:
    """Mirror llm_manager.py:_chat_with_tools_stream accumulation logic."""
    if tc.index not in full_tool_calls:
        full_tool_calls[tc.index] = tc
    elif tc.function and tc.function.arguments:
        if full_tool_calls[tc.index].function.arguments is None:
            full_tool_calls[tc.index].function.arguments = ""
        full_tool_calls[tc.index].function.arguments += tc.function.arguments


def test_first_chunk_none_arguments_then_string_does_not_raise():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="get_weather", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='{"location":'))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='"Beijing"}'))

    assert full_tool_calls[0].function.arguments == '{"location":"Beijing"}'


def test_first_chunk_none_arguments_single_follow_up():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments="{}"))

    assert full_tool_calls[0].function.arguments == "{}"


def test_first_chunk_with_arguments_accumulates_correctly():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments='{"k":'))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='"v"}'))

    assert full_tool_calls[0].function.arguments == '{"k":"v"}'


def test_multiple_tool_call_indices_accumulated_independently():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="tool_a", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='{"x":1}'))
    _accumulate(full_tool_calls, _make_tool_call(1, name="tool_b", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(1, arguments='{"y":'))
    _accumulate(full_tool_calls, _make_tool_call(1, arguments="2}"))

    assert full_tool_calls[0].function.arguments == '{"x":1}'
    assert full_tool_calls[1].function.arguments == '{"y":2}'


def test_chunk_with_empty_string_arguments_is_not_accumulated():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments=""))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments="{}"))

    assert full_tool_calls[0].function.arguments == "{}"
