from __future__ import annotations

from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
from sdk.hooks import BeforeChatContext, MessageAddedContext
from test.mocks import MockLLMAdapter


def test_before_chat_injects_relevant_memories_without_persisting(tmp_path):
    searched = []

    def search(query, character_name=None, limit=5):
        searched.append((query, character_name, limit))
        return {"memories": [{"memory": "用户喜欢雨天咖啡馆"}]}

    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        search_func=search,
    )
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[本地时间 2026-07-05 12:00:00]\n今天想喝咖啡"},
    ]
    context = BeforeChatContext(messages=list(messages), tools=None, generation_kwargs={}, stream=False)

    hooks.before_chat(context)

    assert searched == [("今天想喝咖啡", "Mika", 5)]
    assert len(context.messages) == 3
    assert "用户喜欢雨天咖啡馆" in context.messages[-1]["content"]
    assert messages == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[本地时间 2026-07-05 12:00:00]\n今天想喝咖啡"},
    ]


def test_periodic_extraction_enqueues_and_flushes_memories(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    adapter = MockLLMAdapter(
        responses=[
            '[{"character_name":"Mika","memory":"用户喜欢把重要决定先写成列表。","confidence":0.9}]'
        ]
    )
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember),
        extract_interval_turns=2,
    )

    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "第一轮"}, messages=[]))
    hooks.message_added(
        MessageAddedContext(role="assistant", message={"role": "assistant", "content": "回应一"}, messages=[])
    )
    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "第二轮"}, messages=[]))
    hooks.message_added(
        MessageAddedContext(role="assistant", message={"role": "assistant", "content": "回应二"}, messages=[])
    )
    hooks.wait_for_idle()

    assert saved == [("Mika", "用户喜欢把重要决定先写成列表。")]
    assert len(hooks.queue) == 0


def test_before_chat_uses_last_assistant_speaker_as_active_character(tmp_path):
    searched = []

    def search(query, character_name=None, limit=5):
        searched.append((query, character_name, limit))
        return {"memories": [{"memory": "Nanami 记得这件事"}]}

    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        character_names=["Mika", "Nanami"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        search_func=search,
    )

    hooks.message_added(
        MessageAddedContext(
            role="assistant",
            message={
                "role": "assistant",
                "content": '{"dialog":[{"character_name":"Mika","speech":"先说。"},{"character_name":"Nanami","speech":"后说。"}]}',
            },
            messages=[],
        )
    )
    context = BeforeChatContext(
        messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "继续刚才的话题"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )

    hooks.before_chat(context)

    assert searched == [("继续刚才的话题", "Nanami", 5)]
    assert "Nanami 记得这件事" in context.messages[-1]["content"]
