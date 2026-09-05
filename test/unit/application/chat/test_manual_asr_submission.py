from types import SimpleNamespace

import pytest

from application.chat.commands import ChatCommandDispatcher
from test.unit.application.chat.test_wire_streaming_session import _live_wiring
from test.unit.adapters.test_streaming_asr_controller import _wait_until


@pytest.mark.parametrize("mode", ["engine_final", "silence_fallback", "already_deferred"])
@pytest.mark.parametrize("edited", [False, True])
def test_manual_voice_draft_is_submitted_only_once(mode, edited):
    wiring, service, queue = _live_wiring(continuous=True)
    controller = wiring._create_streaming_asr()
    controller._silence_submit_seconds = 300
    service.begin_turn()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("blue umbrella 731", True)
        utterance_id = controller._utterance_id
        timer = controller._silence_timer
        if mode == "already_deferred":
            adapter.callback("blue umbrella 731", False)
        dispatcher = SimpleNamespace(
            runtime_asr=controller,
            bindings=SimpleNamespace(submit_text=wiring.submit_runtime_text),
        )
        manual_text = "edited blue umbrella 731" if edited else "blue umbrella 731"
        ChatCommandDispatcher._send_message(dispatcher, {
            "text": manual_text, "asrUtteranceId": utterance_id,
        })
        assert queue.get_nowait() == manual_text
        manual_turn = service.begin_turn()
        if mode == "engine_final":
            adapter.callback("corrected blue umbrella 731", False)
        elif mode == "silence_fallback":
            timer.function(*timer.args, **timer.kwargs)
        service.mark_generation_complete(manual_turn)
        service.finish_turn(manual_turn)
        assert queue.empty()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("new sentence", True)
        controller._adapter.callback("new sentence", False)
        assert queue.get_nowait() == "new sentence"
        assert queue.empty()
    finally:
        service.close()
        controller.close()


def test_manual_replacement_of_deferred_draft_preserves_newer_utterance():
    wiring, service, queue = _live_wiring(continuous=True)
    controller = wiring._create_streaming_asr()
    service.begin_turn()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("first", True)
        old_id = controller._utterance_id
        adapter.callback("first", False)
        adapter.callback("second", True)
        new_id = controller._utterance_id
        dispatcher = SimpleNamespace(runtime_asr=controller, bindings=SimpleNamespace(submit_text=wiring.submit_runtime_text))
        ChatCommandDispatcher._send_message(dispatcher, {"text": "edited first", "asrUtteranceId": old_id})
        assert controller._utterance_id == new_id
        assert controller._adapter is adapter
        assert queue.get_nowait() == "edited first"
        turn = service.begin_turn()
        adapter.callback("second", False)
        service.mark_generation_complete(turn)
        service.finish_turn(turn)
        assert queue.get_nowait() == "second"
        assert queue.empty()
    finally:
        service.close()
        controller.close()


def test_rejected_manual_submission_does_not_retire_active_speech():
    wiring, service, queue = _live_wiring(continuous=True)
    controller = wiring._create_streaming_asr()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("keep speech", True)
        old_id, timer = controller._utterance_id, controller._silence_timer
        dispatcher = SimpleNamespace(runtime_asr=controller, bindings=SimpleNamespace(submit_text=lambda *args, **kwargs: False))
        ChatCommandDispatcher._send_message(dispatcher, {"text": "keep speech", "asrUtteranceId": old_id})
        assert controller._utterance_id == old_id
        assert controller._silence_timer is timer
        adapter.callback("keep speech", False)
        assert queue.get_nowait() == "keep speech"
    finally:
        service.close()
        controller.close()
