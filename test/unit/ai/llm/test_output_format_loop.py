from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.llm_manager import LLMManager
from ai.vision.message_content import normalize_openai_messages
from core.chat_history.identity import CHAT_OUTPUT_FORMAT
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID
from test.mocks import MockLLMAdapter

VALID_XML = '<say char="Alice" sprite="01" motion="shake">Hello!</say>'
VALID_JSON = '{"dialog":[{"character_name":"Alice","sprite":"01","speech":"Hello!"}]}'


def test_llm_manager_sets_response_format_and_stamps_output_format() -> None:
    xml_adapter = MockLLMAdapter(responses=[VALID_XML])
    manager = LLMManager(
        adapter=xml_adapter,
        user_template="System",
        output_format=XML_DIALOG_FORMAT_ID,
    )

    reply = manager.chat(
        "hi",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )

    assert reply == VALID_XML
    assert xml_adapter.call_history[0]["kwargs"].get("response_format") == {
        "type": "text"
    }
    assistant_msgs = [m for m in manager.messages if m.get("role") == "assistant"]
    assert assistant_msgs[-1][CHAT_OUTPUT_FORMAT] == XML_DIALOG_FORMAT_ID

    json_adapter = MockLLMAdapter(responses=[VALID_JSON])
    json_manager = LLMManager(
        adapter=json_adapter,
        user_template="System",
        output_format=DEFAULT_DIALOG_FORMAT_ID,
    )
    json_manager.chat(
        "hi",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )
    assert json_adapter.call_history[0]["kwargs"].get("response_format") == {
        "type": "json_object"
    }


def test_repair_dialog_output_uses_xml_prompt_for_xml_format() -> None:
    adapter = MockLLMAdapter(responses=["plain unformatted text", VALID_XML])

    repaired = repair_dialog_output(
        adapter,
        "broken reply",
        [{"role": "system", "content": "S"}, {"role": "user", "content": "hi"}],
        {},
        cancelled=lambda: False,
        event_logger=MagicMock(),
        locale="en",
        output_format_id=XML_DIALOG_FORMAT_ID,
    )

    assert repaired == VALID_XML
    prompts = [m["content"] for m in adapter.call_history[-1]["messages"] if m["role"] == "user"]
    assert any("<say" in text for text in prompts)


def test_switching_output_format_converts_history_non_destructively() -> None:
    adapter = MockLLMAdapter(responses=[VALID_JSON, VALID_XML])
    manager = LLMManager(
        adapter=adapter,
        user_template="System",
        output_format=DEFAULT_DIALOG_FORMAT_ID,
    )

    manager.chat(
        "turn 1",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )
    persisted_first = next(m for m in manager.messages if m.get("role") == "assistant")
    assert persisted_first["content"] == VALID_JSON
    assert persisted_first[CHAT_OUTPUT_FORMAT] == DEFAULT_DIALOG_FORMAT_ID

    manager.output_format = XML_DIALOG_FORMAT_ID
    manager.chat(
        "turn 2",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )

    # Outbound messages sent to adapter must convert legacy JSON turn to XML...
    outbound = adapter.call_history[1]["messages"]
    outbound_first_assistant = next(m for m in outbound if m.get("role") == "assistant")
    assert "<say" in outbound_first_assistant["content"]
    sanitized_wire = normalize_openai_messages(outbound)
    sanitized_assistant = next(m for m in sanitized_wire if m.get("role") == "assistant")
    assert CHAT_OUTPUT_FORMAT not in sanitized_assistant

    # ...while persisted in-memory history keeps original turn untouched.
    assert persisted_first["content"] == VALID_JSON
    assert persisted_first[CHAT_OUTPUT_FORMAT] == DEFAULT_DIALOG_FORMAT_ID
