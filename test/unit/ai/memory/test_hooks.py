from __future__ import annotations

from ai.memory.hooks import MemoryAutoHooks, install_memory_hooks
from ai.memory.queue import MemoryWriteQueue
from core.runtime.shutdown import shutdown_chat_runtime
from sdk.chat_init import ChatInitService, InitChatContext
from sdk.hooks import BeforeChatContext, MessageAddedContext
from sdk.hooks import PluginHookDispatcher, clear_shutdown_hooks
from test.mocks import MockLLMAdapter


def _before_chat_context(content="hello"):
    return BeforeChatContext(
        messages=[{"role": "system", "content": "S"}, {"role": "user", "content": content}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )


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


def test_before_chat_ignores_memory_search_failure(tmp_path):
    def search(_query, character_name=None, limit=5):
        raise RuntimeError("search unavailable")

    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        search_func=search,
    )
    context = _before_chat_context()
    original_messages = list(context.messages)

    hooks.before_chat(context)

    assert context.messages == original_messages


def test_before_chat_ignores_unavailable_or_empty_memory_search_results(tmp_path):
    results = [
        {"status": "loading", "message": "still loading"},
        {"error": "forbidden"},
        {"memories": []},
        {"memories": "not a list"},
    ]

    for index, result in enumerate(results):
        hooks = MemoryAutoHooks(
            llm_adapter=MockLLMAdapter(),
            character_names=["Mika"],
            queue=MemoryWriteQueue(path=tmp_path / f"queue-{index}.json", remember_func=lambda *_args: {"ok": True}),
            search_func=lambda *_args, _result=result, **_kwargs: _result,
        )
        context = _before_chat_context()
        original_messages = list(context.messages)

        hooks.before_chat(context)

        assert context.messages == original_messages


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


def test_periodic_extraction_normalizes_assistant_dialog_json_before_prompting(tmp_path):
    adapter = MockLLMAdapter(responses=["[]"])
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        extract_interval_turns=1,
    )

    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "记住雨天"}, messages=[]))
    hooks.message_added(
        MessageAddedContext(
            role="assistant",
            message={
                "role": "assistant",
                "content": '{"dialog":[{"character_name":"Mika","speech":"我会记住。"}]}',
            },
            messages=[],
        )
    )
    hooks.wait_for_idle()

    prompt = adapter.call_history[0]["messages"][-1]["content"]
    assert "user: 记住雨天" in prompt
    assert "Mika: 我会记住。" in prompt
    assert '"dialog"' not in prompt


def test_periodic_extraction_skips_assistant_tool_call_messages(tmp_path):
    saved = []
    adapter = MockLLMAdapter(responses=['[{"character_name":"Mika","memory":"should not save"}]'])
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mika"],
        queue=MemoryWriteQueue(
            path=tmp_path / "queue.json",
            remember_func=lambda content, character_name=None: saved.append((character_name, content)) or {"ok": True},
        ),
        extract_interval_turns=1,
    )

    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "hello"}, messages=[]))
    hooks.message_added(
        MessageAddedContext(
            role="assistant",
            message={
                "role": "assistant",
                "content": "tool result",
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
            messages=[],
        )
    )
    hooks.wait_for_idle()

    assert adapter.call_history == []
    assert saved == []
    assert len(hooks.queue) == 0


def test_shutdown_extracts_tail_messages_below_interval(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    adapter = MockLLMAdapter(
        responses=['[{"character_name":"Mika","memory":"User likes concise answers.","confidence":0.9}]']
    )
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember),
        extract_interval_turns=5,
    )

    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "Please be concise."}, messages=[]))
    hooks.message_added(
        MessageAddedContext(role="assistant", message={"role": "assistant", "content": "Got it."}, messages=[])
    )

    assert saved == []
    hooks.shutdown()

    assert saved == [("Mika", "User likes concise answers.")]
    assert len(adapter.call_history) == 1
    assert len(hooks.queue) == 0


def test_shutdown_does_not_reextract_already_extracted_turn(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    adapter = MockLLMAdapter(
        responses=['[{"character_name":"Mika","memory":"Already saved at interval.","confidence":0.9}]']
    )
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember),
        extract_interval_turns=1,
    )

    hooks.message_added(MessageAddedContext(role="user", message={"role": "user", "content": "Remember this."}, messages=[]))
    hooks.message_added(
        MessageAddedContext(role="assistant", message={"role": "assistant", "content": "Saved soon."}, messages=[])
    )
    hooks.wait_for_idle()
    hooks.shutdown()

    assert saved == [("Mika", "Already saved at interval.")]
    assert len(adapter.call_history) == 1
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


def test_install_memory_hooks_registers_shutdown_flush(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    clear_shutdown_hooks()
    try:
        queue = MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember)
        queue.enqueue("关闭时写入", character_name="Mika")
        dispatcher = PluginHookDispatcher()

        hooks = install_memory_hooks(
            dispatcher,
            llm_adapter=MockLLMAdapter(),
            character_names=["Mika"],
            queue=queue,
        )

        assert hooks is not None
        shutdown_chat_runtime()
        assert saved == [("Mika", "关闭时写入")]
        assert len(queue) == 0
    finally:
        clear_shutdown_hooks()


def test_memory_init_hook_starts_bridge_loading_once_and_forwards_progress(tmp_path):
    calls = []
    responses = iter(
        [
            {
                "status": "loading",
                "task": {
                    "phase": "download",
                    "progress": 0.25,
                    "message": "Downloading embedding model",
                    "logs": ["download started"],
                },
            },
            {
                "status": "loading",
                "task": {
                    "phase": "reload",
                    "progress": 0.8,
                    "message": "Loading cached model",
                    "logs": ["download started", "model cached"],
                },
            },
            {"status": "ready", "task": {"phase": "completed", "progress": 1.0}},
        ]
    )

    def status(**kwargs):
        calls.append(kwargs)
        return next(responses)

    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        memory_status_func=status,
        sleep_func=lambda _seconds: None,
        monotonic_func=lambda: 0.0,
    )
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    events = []

    failures = dispatcher.dispatch_init_chat(
        InitChatContext(service=ChatInitService(events.append), memory_enabled=True)
    )

    assert failures == ()
    assert calls == [
        {"start_loading": True, "monitor_ready": False},
        {"start_loading": False, "monitor_ready": False},
        {"start_loading": False, "monitor_ready": False},
    ]
    assert any(event["task"]["message"] == "Downloading embedding model" for event in events)
    assert any(event["task"]["phase"] == "memory.reload" for event in events)
    assert events[-1]["task"]["progress"] == 1.0
    assert events[-1]["task"]["logs"] == ["download started", "model cached"]


def test_memory_init_missing_dependency_is_nonfatal_and_does_not_install(tmp_path):
    status_calls = []
    continued = []

    def missing_status(**kwargs):
        status_calls.append(kwargs)
        return {
            "status": "missing_dependency",
            "moduleName": "mem0",
            "packageName": "mem0ai",
        }

    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        memory_status_func=missing_status,
        sleep_func=lambda _seconds: None,
    )
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    dispatcher.register_init_chat(lambda _context: continued.append(True), label="after-memory")

    failures = dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService(), memory_enabled=True))

    assert status_calls == [{"start_loading": True, "monitor_ready": False}]
    assert continued == [True]
    assert [failure.label for failure in failures] == ["memory"]
    assert "dependency" in str(failures[0].error).lower()


def test_memory_init_hook_skips_service_when_memory_is_disabled(tmp_path):
    hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        queue=MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=lambda *_args: {"ok": True}),
        memory_status_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled memory must not call the service")
        ),
    )
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    service = ChatInitService()

    assert dispatcher.dispatch_init_chat(
        InitChatContext(service=service, memory_enabled=False)
    ) == ()
    assert service.snapshot()["progress"] == 1.0
