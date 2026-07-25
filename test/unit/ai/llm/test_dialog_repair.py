from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ai.llm.dialog_repair import repair_dialog_output
from llm.llm_manager import LLMManager
from test.mocks import MockLLMAdapter

VALID_DIALOG = '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"Hi"}]}'


def _repair(adapter, content: str = "plain text answer") -> str:
    return repair_dialog_output(
        adapter,
        content,
        [{"role": "system", "content": "S"}, {"role": "user", "content": "hi"}],
        {"temperature": 0.4},
        cancelled=lambda: False,
        event_logger=MagicMock(),
    )


def test_invalid_final_answer_is_repaired_without_tools() -> None:
    adapter = MockLLMAdapter(responses=[VALID_DIALOG])

    repaired = _repair(adapter, "Hello, this is plain text.")

    assert repaired == VALID_DIALOG
    assert len(adapter.call_history) == 1
    call = adapter.call_history[0]
    assert call["stream"] is False
    assert call["kwargs"]["tools"] is None
    assert call["messages"][-2] == {
        "role": "assistant",
        "content": "Hello, this is plain text.",
    }
    assert call["messages"][-1]["role"] == "user"


def test_invalid_final_answer_retries_with_escalated_instruction() -> None:
    adapter = MockLLMAdapter(responses=["still not json", VALID_DIALOG])

    repaired = _repair(adapter)

    assert repaired == VALID_DIALOG
    assert len(adapter.call_history) == 2
    contents = [message.get("content", "") for message in adapter.call_history[-1]["messages"]]
    assert next(i for i, value in enumerate(contents) if "Reformat" in value) < next(
        i for i, value in enumerate(contents) if "MUST" in value
    )
    assert {"role": "assistant", "content": "still not json"} in adapter.call_history[-1][
        "messages"
    ]
    assert all(call["kwargs"]["tools"] is None for call in adapter.call_history)


def test_invalid_final_answer_gives_up_after_max_attempts() -> None:
    adapter = MockLLMAdapter(responses=["nope", "still nope"])

    result = _repair(adapter)

    assert result == "plain text answer"
    assert len(adapter.call_history) == 2


def test_repair_discards_response_when_cancelled_during_blocking_request() -> None:
    cancelled = False

    class CancellingAdapter(MockLLMAdapter):
        def chat(self, messages, stream=False, **kwargs):
            nonlocal cancelled
            response = super().chat(messages, stream=stream, **kwargs)
            cancelled = True
            return response

    result = repair_dialog_output(
        CancellingAdapter(responses=[VALID_DIALOG]),
        "plain text answer",
        [{"role": "system", "content": "S"}],
        {},
        cancelled=lambda: cancelled,
        event_logger=MagicMock(),
    )

    assert result == "plain text answer"


def test_provider_neutral_response_extraction_supports_content_blocks() -> None:
    class ContentBlockAdapter:
        def chat(self, messages, stream=False, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=VALID_DIALOG)]
            )

    assert _repair(ContentBlockAdapter()) == VALID_DIALOG


def test_manager_does_not_repair_generic_calls_without_dialog_contract() -> None:
    adapter = MockLLMAdapter(responses=["plain text answer", VALID_DIALOG])
    manager = LLMManager(adapter=adapter, user_template="S")

    result = manager.chat("hello", stream=False, include_local_time=False)

    assert result == "plain text answer"
    assert len(adapter.call_history) == 1
    assert "_dialog_output_required" not in adapter.call_history[0]["kwargs"]


def test_manager_repairs_when_dialog_contract_is_explicitly_required() -> None:
    adapter = MockLLMAdapter(responses=["plain text answer", VALID_DIALOG])
    manager = LLMManager(adapter=adapter, user_template="S")

    result = manager.chat(
        "hello",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )

    assert result == VALID_DIALOG
    assert len(adapter.call_history) == 2
    assert "_dialog_output_required" not in adapter.call_history[0]["kwargs"]


def test_manager_does_not_persist_sync_repair_cancelled_in_flight() -> None:
    manager: LLMManager

    class CancellingAdapter(MockLLMAdapter):
        def chat(self, messages, stream=False, **kwargs):
            response = super().chat(messages, stream=stream, **kwargs)
            if len(self.call_history) == 2:
                manager.cancel_current_chat()
            return response

    adapter = CancellingAdapter(responses=["plain text answer", VALID_DIALOG])
    manager = LLMManager(adapter=adapter, user_template="S")

    result = manager.chat(
        "hello",
        stream=False,
        include_local_time=False,
        dialog_output_required=True,
    )

    assert result == ""
    assert [message["role"] for message in manager.messages] == ["system", "user"]


def test_manager_does_not_persist_stream_repair_cancelled_in_flight() -> None:
    manager: LLMManager

    class CancellingAdapter(MockLLMAdapter):
        def chat(self, messages, stream=False, **kwargs):
            response = super().chat(messages, stream=stream, **kwargs)
            if len(self.call_history) == 2:
                manager.cancel_current_chat()
            return response

    adapter = CancellingAdapter(responses=["plain text answer", VALID_DIALOG])
    manager = LLMManager(adapter=adapter, user_template="S")

    chunks = list(
        manager.chat(
            "hello",
            stream=True,
            include_local_time=False,
            dialog_output_required=True,
        )
    )

    assert "".join(chunk for chunk in chunks if isinstance(chunk, str)) == "plain text answer"
    assert [message["role"] for message in manager.messages] == ["system", "user"]
