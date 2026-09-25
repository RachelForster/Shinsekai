from types import SimpleNamespace
from threading import Lock
from unittest.mock import Mock

import pytest

from application.chat import runtime_process
from frontend_bridge_core.routes.reminder_routes import _presenter
from test.unit.frontend_bridge_core.test_chat_runtime_mode import _ConfigManager


@pytest.mark.parametrize(
    "saved,session,running,disabled",
    [(False, False, False, False), (True, False, False, True),
     (False, True, True, True), (False, True, False, False),
     (False, False, True, False), (True, True, True, True),
     (True, False, True, False)],
)
def test_reminder_policy_covers_saved_setting_and_running_session(
    monkeypatch, tmp_path, saved, session, running, disabled,
):
    state = SimpleNamespace(
        config_manager=_ConfigManager(),
        chat_session={"characterSpeechDisabled": session},
        chat_stream=None,
        reminder_presenter=None,
        project_root_dir=tmp_path,
        task_lock=Lock(),
    )
    state.config_manager.config.system_config.asr_continuous_during_reply_experimental_enabled = saved
    monkeypatch.setattr(runtime_process, "_chat_process_running", lambda: running)
    assert runtime_process._chat_snapshot(state)["characterSpeechDisabled"] is disabled
    presenter = _presenter(SimpleNamespace(state=state))
    assert presenter._speech_disabled() is disabled
    if disabled:
        presenter._synthesize = Mock()
        assert presenter.speech({}) == {"audio_path": None}
        presenter._synthesize.assert_not_called()
    # The retained presenter observes future saved/runtime settings too.
    monkeypatch.setattr(runtime_process, "_chat_process_running", lambda: False)
    state.config_manager.config.system_config.asr_continuous_during_reply_experimental_enabled = False
    assert presenter._speech_disabled() is False
    presenter.close()
