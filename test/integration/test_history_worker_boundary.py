"""History replacement while a real worker is preparing or awaiting a reply."""

import json
from threading import Event

import pytest

from application.chat.turn_wiring import create_chat_turn_service
from application.runtime.context import set_app_runtime
from application.runtime.workers import LLMWorker
from test.integration.test_workers import (
    _make_runtime_for_workers,
    _wait_for_unfinished_tasks,
)
from test.mocks import MockLLMAdapter


@pytest.mark.parametrize("phase", ["prepare", "reply"])
@pytest.mark.parametrize("mutation", ["clear", "replace"])
@pytest.mark.parametrize("streaming", [False, True])
def test_old_worker_cannot_publish_or_persist_after_history_change(phase, mutation, streaming):
    entered = Event()
    release = Event()

    class BlockedAdapter(MockLLMAdapter):
        def chat(self, messages, stream=False, **kwargs):
            if phase == "reply" and not entered.is_set():
                entered.set()
                assert release.wait(5)
            return super().chat(messages, stream=stream, **kwargs)

    reply = json.dumps({"character_name": "TestChar", "speech": "reply", "sprite": "0"})
    rt = _make_runtime_for_workers(mock_llm_adapter=BlockedAdapter([reply]), is_streaming=streaming)
    rt.config.config.api_config.is_batch_input_enabled = False
    rt.chat_turn_service = create_chat_turn_service(
        config=rt.config, user_input_queue=rt.user_input_queue,
        tts_queue=rt.tts_queue, audio_queue=rt.audio_path_queue,
        llm_manager=rt.llm_manager, ui_worker=None, ui_updates=rt.ui_update_manager,
    )
    set_app_runtime(rt)
    worker = LLMWorker(input_queue=rt.user_input_queue, output_queue=rt.tts_queue)
    original_prepare = worker.chat_vision_service.prepare

    def prepare(*args, **kwargs):
        if phase == "prepare" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original_prepare(*args, **kwargs)

    worker.chat_vision_service.prepare = prepare
    worker.start()
    try:
        rt.chat_turn_service.submit("old voice", defer_until_idle=True, utterance_id="old")
        assert entered.wait(5)
        with rt.chat_turn_service.history_boundary():
            rt.llm_manager.invalidate_history()
            if mutation == "clear":
                rt.llm_manager.clear_messages()
            else:
                rt.llm_manager.set_messages([{"role": "system", "content": "new history"}])
            rt.ui_update_manager.reset_mock()
        expected = list(rt.llm_manager.get_messages())
        release.set()
        assert _wait_for_unfinished_tasks(rt.user_input_queue)
        assert rt.llm_manager.get_messages() == expected
        assert rt.llm_manager._chat_depth == 0
        assert rt.tts_queue.empty()
        rt.ui_update_manager.record_user_message.assert_not_called()
        rt.chat_turn_service.submit("fresh voice", defer_until_idle=True, utterance_id="fresh")
        assert rt.tts_queue.get(timeout=5).text == "reply"
        assert _wait_for_unfinished_tasks(rt.user_input_queue)
        assert any("fresh voice" in str(item.get("content")) for item in rt.llm_manager.get_messages())
    finally:
        release.set()
        worker.stop()
        worker.wait(3000)
        rt.chat_turn_service.close()
