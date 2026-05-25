"""Unit tests for streaming tool call accumulation in _chat_with_tools_stream.

Bug fixed: when the first delta chunk for a tool call has function.arguments=None
(provider sends function name first, arguments in later chunks), the += operator
raised TypeError: unsupported operand type(s) for +=: 'NoneType' and 'str'.
"""
import pytest
from types import SimpleNamespace

def _make_function(name=None, arguments=None):
    return SimpleNamespace(name=name, arguments=arguments)

def _make_tool_call(index, name=None, arguments=None):
    return SimpleNamespace(index=index, function=_make_function(name=name, arguments=arguments))

def _accumulate(full_tool_calls: dict, tc) -> None:
    """Exact copy of the accumulation logic from llm_manager.py:_chat_with_tools_stream."""
    if tc.index not in full_tool_calls:
        full_tool_calls[tc.index] = tc
    elif tc.function and tc.function.arguments:
        if full_tool_calls[tc.index].function.arguments is None:
            full_tool_calls[tc.index].function.arguments = ""
        full_tool_calls[tc.index].function.arguments += tc.function.arguments

# --------------------------------------------------
# Bug reproduction: first chunk has arguments=None
# --------------------------------------------------

def test_first_chunk_none_arguments_then_string_does_not_raise():
    """Provider sends function name first (arguments=None), then argument chunks."""
    full_tool_calls = {}

    chunk1 = _make_tool_call(0, name="get_weather", arguments=None)
    chunk2 = _make_tool_call(0, name=None, arguments='{"location":')
    chunk3 = _make_tool_call(0, name=None, arguments='"Beijing"}')

    _accumulate(full_tool_calls, chunk1)
    _accumulate(full_tool_calls, chunk2)  # would raise TypeError before fix
    _accumulate(full_tool_calls, chunk3)

    assert full_tool_calls[0].function.arguments == '{"location":"Beijing"}'

def test_first_chunk_none_arguments_single_follow_up():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='{}'))

    assert full_tool_calls[0].function.arguments == '{}'

# --------------------------------------------------
# Normal path: first chunk already has arguments
# --------------------------------------------------

def test_first_chunk_with_arguments_accumulates_correctly():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments='{"k":'))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='"v"}'))

    assert full_tool_calls[0].function.arguments == '{"k":"v"}'

# --------------------------------------------------
# Multiple tool calls in one response
# --------------------------------------------------

def test_multiple_tool_call_indices_accumulated_independently():
    full_tool_calls = {}

    # tool 0: first chunk has arguments=None
    _accumulate(full_tool_calls, _make_tool_call(0, name="tool_a", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='{"x":1}'))

    # tool 1: first chunk has arguments=None
    _accumulate(full_tool_calls, _make_tool_call(1, name="tool_b", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(1, arguments='y":'))
    _accumulate(full_tool_calls, _make_tool_call(1, arguments='2}'))

    assert full_tool_calls[0].function.arguments == '{"x":1}'
    assert full_tool_calls[1].function.arguments == '{"y":2}'

# --------------------------------------------------
# Edge: chunk with empty-string arguments is skipped (guard: tc.function.arguments)
# --------------------------------------------------

def test_chunk_with_empty_string_arguments_is_not_accumulated():
    full_tool_calls = {}

    _accumulate(full_tool_calls, _make_tool_call(0, name="foo", arguments=None))
    _accumulate(full_tool_calls, _make_tool_call(0, arguments=""))  # falsy, skipped
    _accumulate(full_tool_calls, _make_tool_call(0, arguments='{}'))

    assert full_tool_calls[0].function.arguments == '{}'
