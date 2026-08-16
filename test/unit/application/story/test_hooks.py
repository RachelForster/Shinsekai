from __future__ import annotations

from types import SimpleNamespace

from sdk.hooks import BeforeChatContext, PluginHookDispatcher

from application.story.coordinator import refresh_story_chat_prompt
from application.story.hooks import (
    StoryChatHooks,
    StoryChatPrompt,
    install_story_hooks,
    read_story_chat_prompt,
    write_story_chat_prompt,
)


def _context(messages: list[dict[str, str]]) -> BeforeChatContext:
    return BeforeChatContext(
        messages=list(messages),
        tools=None,
        generation_kwargs={},
        stream=False,
    )


def test_before_chat_splices_scene_into_user_without_changing_history() -> None:
    original = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "你好"},
    ]
    hooks = StoryChatHooks(
        prompt_loader=lambda: StoryChatPrompt(
            user="## 现在场景\n旧校舍门口\n\n## 已达成场景上下文\n尚无已达成的场景记录。",
            system="## 回复格式\ndialog JSON",
        )
    )
    context = _context(original)

    hooks.before_chat(context)

    assert context.messages[0]["role"] == "system"
    assert context.messages[0]["content"] == "S"
    assert "## 回复格式" not in context.messages[0]["content"]
    assert context.messages[-1]["role"] == "user"
    assert context.messages[-1]["content"].startswith("## 现在场景")
    assert "旧校舍门口" in context.messages[-1]["content"]
    assert "[用户消息]\n你好" in context.messages[-1]["content"]
    assert context.messages[-1]["content"].endswith("你好")
    assert "[Shinsekai story scene context]" not in context.messages[-1]["content"]
    assert "## 回复格式" not in context.messages[-1]["content"]
    assert original == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "你好"},
    ]


def test_before_chat_injects_on_opening_turn_without_user_message() -> None:
    hooks = StoryChatHooks(prompt_loader=lambda: "## 现在场景\n旧校舍门口")
    context = _context([{"role": "system", "content": "S"}])

    hooks.before_chat(context)

    assert len(context.messages) == 2
    assert context.messages[-1]["role"] == "user"
    assert context.messages[-1]["content"] == "## 现在场景\n旧校舍门口"
    assert context.messages[0]["content"] == "S"


def test_before_chat_skips_tool_followup_rounds() -> None:
    hooks = StoryChatHooks(prompt_loader=lambda: "场景")
    context = _context(
        [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        ]
    )

    hooks.before_chat(context)

    assert len(context.messages) == 3
    assert context.messages[1]["content"] == "你好"


def test_before_chat_skips_when_prompt_is_empty() -> None:
    hooks = StoryChatHooks(prompt_loader=lambda: "  ")
    context = _context(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "你好"}]
    )

    hooks.before_chat(context)

    assert context.messages == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "你好"},
    ]


def test_install_story_hooks_reads_cached_prompt(tmp_path) -> None:
    history = tmp_path / "session.json"
    write_story_chat_prompt(history, "## 现在场景\n旧校舍门口")
    dispatcher = PluginHookDispatcher()
    install_story_hooks(dispatcher, history_path=history)
    context = _context(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "你好"}]
    )

    dispatcher.dispatch_before_chat(context)

    assert context.messages[-1]["role"] == "user"
    assert "旧校舍门口" in context.messages[-1]["content"]
    assert "[用户消息]\n你好" in context.messages[-1]["content"]
    assert context.messages[-1]["content"].endswith("你好")
    assert read_story_chat_prompt(history).user == "## 现在场景\n旧校舍门口"


def test_refresh_story_chat_prompt_writes_sidecar(tmp_path) -> None:
    history = tmp_path / "session.json"

    class _Service:
        def prepare_llm_turn(self, text: str, *, command_id: str, message_id: str):
            return SimpleNamespace(
                appendix="",
                user_context=f"scene:{text or 'idle'}",
                system_prompt="## 回复格式\ndialog JSON",
            )

    refresh_story_chat_prompt(
        SimpleNamespace(
            story_session=SimpleNamespace(owner_history_path=str(history)),
            story_scene_service=_Service(),
            chat_session={},
        )
    )

    cached = read_story_chat_prompt(history)
    assert cached.user == "scene:idle"
    assert cached.system == "## 回复格式\ndialog JSON"


def test_apply_system_writes_into_the_leading_system_message() -> None:
    manager = SimpleNamespace(
        user_template="角色设定",
        llm_adapter=SimpleNamespace(set_user_template=lambda _value: None),
        messages=[{"role": "system", "content": "角色设定"}],
    )
    hooks = StoryChatHooks(
        prompt_loader=lambda: StoryChatPrompt(
            user="## 现在场景\n旧校舍门口",
            system="## 回复格式\ndialog JSON",
        ),
        llm_manager=manager,
    )

    hooks.apply_system()

    assert manager.messages[0]["content"].startswith("角色设定")
    assert "## 回复格式" in manager.messages[0]["content"]
    assert "## 现在场景" not in manager.messages[0]["content"]
    assert "## 回复格式" in manager.user_template
