import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest

from application.chat.conversation_library import remember_conversation, list_conversations
from application.chat.share_posts import post_source, post_to_doki


def fixture(tmp_path):
    state = SimpleNamespace(project_root_dir=str(tmp_path), history_dir=str(tmp_path / "history"), template_dir_path=str(tmp_path / "templates"))
    history = tmp_path / "history" / "old-save"
    history.mkdir(parents=True)
    (history / "active.json").write_text(json.dumps([{"role":"system","content":"PRIVATE_SYSTEM_AND_API_CONFIG"}, {"role":"user","content":"用户已经说过的原话"}, {"role":"assistant","content":json.dumps({"dialog":[{"character_name":"A","speech":"关键结局：和好"}]},ensure_ascii=False)}, {"role":"tool","content":"PRIVATE_TOOL_RESULT"}],ensure_ascii=False),encoding="utf-8")
    remember_conversation(state, history, {"characters":["A"],"conversationTitle":"原生存档"})
    return state, list_conversations(state)[0]["id"]


def test_original_save_can_be_shared_without_a_doki_handoff_and_without_private_prompts(tmp_path):
    state, identity = fixture(tmp_path)
    listing = post_source(state, {"action":"list"})
    assert listing["conversations"][0]["id"] == identity
    assert "historyPath" not in listing["conversations"][0]
    result = post_source(state, {"action":"read","conversation_id":identity})
    assert "用户已经说过的原话" in result["text"]
    assert "关键结局：和好" in result["text"]
    assert "PRIVATE_" not in result["text"]
    assert result["timeline"] is None


def test_source_ids_cannot_be_arbitrary_file_paths(tmp_path):
    state, _ = fixture(tmp_path)
    for identity in ["../active.json", "f" * 64]:
        with pytest.raises(ValueError):
            post_source(state, {"action":"read","conversation_id":identity})


def test_native_share_request_uses_actual_root_and_never_provider_config(tmp_path):
    state, identity = fixture(tmp_path)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): return b'{"id":"draft"}'
    with patch("application.chat.share_posts.urllib.request.urlopen", return_value=Response()) as request:
        assert post_to_doki(state, {"action":"request","conversation_id":identity,"recipient_id":"B","root":"wrong-root","api_key":"must-not-forward"})["id"] == "draft"
    body = json.loads(request.call_args.args[0].data)
    assert body == {"root":str(tmp_path.resolve()),"conversation_id":identity,"recipient_id":"B"}
