from __future__ import annotations

from unittest.mock import Mock

from application.chat.history_state import revert_chat_history
from application.chat.presentation import StreamingHistoryPresenter


def test_revert_replays_previous_dialog_instead_of_adjacent_options() -> None:
    previous_dialog = (
        "<p><b style='color:#84C2D5;'>Mio</b>：We should take the quiet road.</p>"
    )
    options = "<p><b>选项</b>：Take the quiet road / Stay here</p>"
    selected_user_turn = "<p><b>你</b>：Take the quiet road</p>"
    latest_dialog = (
        "<p><b style='color:#84C2D5;'>Mio</b>：Then let us leave now.</p>"
    )
    history = [previous_dialog, options, selected_user_turn, latest_dialog]
    llm_manager = Mock()
    llm_manager.get_messages.return_value = [
        {"role": "assistant", "content": "previous"},
        {"role": "user", "content": "Take the quiet road"},
        {"role": "assistant", "content": "latest"},
    ]
    ui_updates = Mock()
    presenter = StreamingHistoryPresenter(ui_updates)

    revert_chat_history(
        0,
        llm_manager=llm_manager,
        hist=history,
        window=presenter,
    )

    assert history == [previous_dialog, options]
    ui_updates.post_dialog_html.assert_called_once_with(
        previous_dialog,
        append_history=False,
        speaker="Mio",
        color="#84C2D5",
        is_system=False,
    )
    ui_updates.post_options.assert_not_called()
    llm_manager.set_messages.assert_called_once_with(
        [{"role": "assistant", "content": "previous"}]
    )
