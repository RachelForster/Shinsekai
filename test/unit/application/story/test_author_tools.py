from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from ai.llm.template.core import TextSection
from ai.llm.template.story import (
    build_story_author_system_section,
    build_story_author_user_section,
)
from application.story import generation
from ai.tools.random_tools import random_tool_definitions
from application.random_requests import RandomRequestExecutor
from application.story.author_tool_loop import (
    AuthorToolLoopError,
    MAX_AUTHOR_ROUNDS,
    run_author_tool_loop,
)
from application.story.generation import (
    ConfigStoryAuthorModel,
    StoryGenerationCancelled,
    StoryGenerationError,
)
from test.unit.application.story.test_generation import (
    enabled_flags,
    service_at,
    stage_artifacts,
)


def call_reply(name="random_assign", arguments=None, *, provider="openai"):
    args = (
        arguments
        if arguments is not None
        else {
            "requestId": "roles",
            "participants": ["A", "B"],
            "labels": {"wolf": 1, "villager": 1},
        }
    )
    if provider == "claude":
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id="call-1", name=name, input=args)
            ]
        )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    reasoning_content="Need a real random result.",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                            "extra_content": {
                                "google": {"thought_signature": "signed"}
                            },
                        }
                    ],
                )
            )
        ]
    )


@pytest.mark.parametrize("stage", ["foundation", "repair"])
def test_author_renders_shared_sections_with_committed_decisions(monkeypatch, stage):
    executor = RandomRequestExecutor(scope="test")
    executor.execute("shuffle", "roles", {"items": ["A", "B"]})
    request = {"stage": stage, "synopsis": 'literal {braces} and "quotes"'}
    original = deepcopy(request)
    contexts = []

    def system_section(**kwargs):
        section = build_story_author_system_section(**kwargs)
        return replace(
            section,
            children=section.children
            + (TextSection(id="extension", text="EXTENSION"),),
        )

    def user_section():
        section = build_story_author_user_section()
        leaf = section.children[0]

        def render(context):
            contexts.append(context)
            return leaf.render(context)

        return replace(section, children=(TextSection(id="request", text=render),))

    def chat(messages, **kwargs):
        assert messages[0]["content"].endswith("EXTENSION")
        assert "resolvedRandomRequests" in messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        assert payload == {
            **request,
            "resolvedRandomRequests": executor.resolved_requests(),
        }
        return {"artifact": {"ok": True}}

    monkeypatch.setattr(generation, "build_story_author_system_section", system_section)
    monkeypatch.setattr(generation, "build_story_author_user_section", user_section)
    model = ConfigStoryAuthorModel(enabled_flags(), SimpleNamespace())
    model._llm_manager = lambda: SimpleNamespace(llm_adapter=SimpleNamespace(chat=chat))
    assert model.complete_with_tools(request, executor=executor) == {
        "artifact": {"ok": True}
    }
    assert len(contexts) == 1
    assert request == original


@pytest.mark.parametrize("provider", ["openai", "claude"])
def test_author_executes_scoped_tools_and_echoes_results_before_final_json(provider):
    requests = []

    def chat(messages, stream=False, **kwargs):
        requests.append(deepcopy(messages))
        assert {item["function"]["name"] for item in kwargs["tools"]} == {
            "random_sample",
            "random_shuffle",
            "random_roll_dice",
            "random_assign",
        }
        assert "response_format" not in kwargs
        if len(requests) == 1:
            return call_reply(provider=provider)
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]
        result = json.loads(messages[-1]["content"])
        assert result["ok"]
        assert sorted(result["result"]["assignments"].values()) == ["villager", "wolf"]
        if provider == "openai":
            assert messages[-2]["reasoning_content"] == "Need a real random result."
            assert (
                messages[-2]["tool_calls"][0]["extra_content"]["google"][
                    "thought_signature"
                ]
                == "signed"
            )
        return '{"artifact":{"ok":true}}'

    messages = [
        {"role": "system", "content": "author"},
        {"role": "user", "content": "Generate"},
    ]
    original = deepcopy(messages)
    final = run_author_tool_loop(
        SimpleNamespace(chat=chat),
        messages,
        executor=RandomRequestExecutor(scope="test"),
    )
    assert json.loads(final)["artifact"]["ok"]
    assert messages == original


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_file", {"requestId": "bad"}),
        (
            "random_assign",
            {"requestId": "roles", "participants": ["A"], "labels": {"wolf": 2}},
        ),
        ("random_shuffle", {"items": ["A"]}),
    ],
)
def test_invalid_calls_return_feedback_for_model_correction(name, args):
    calls = []

    def chat(messages, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return call_reply(name, args)
        assert json.loads(messages[-1]["content"])["ok"] is False
        return {"artifact": {"fixed": True}}

    result = run_author_tool_loop(
        SimpleNamespace(chat=chat), [], executor=RandomRequestExecutor(scope="test")
    )
    assert result == {"artifact": {"fixed": True}}


def test_loop_is_bounded_and_disables_tools_on_final_request():
    calls = []

    def chat(messages, **kwargs):
        calls.append(kwargs)
        return call_reply()

    with pytest.raises(AuthorToolLoopError):
        run_author_tool_loop(
            SimpleNamespace(chat=chat),
            [],
            executor=RandomRequestExecutor(scope="test"),
            native_json=True,
        )
    assert len(calls) == MAX_AUTHOR_ROUNDS
    assert calls[-1] == {"stream": False, "response_format": {"type": "json_object"}}


def test_cancel_after_model_reply_prevents_tool_execution():
    cancelled = False
    saved = []
    executor = RandomRequestExecutor(scope="test", save=saved.append)

    def chat(*args, **kwargs):
        nonlocal cancelled
        cancelled = True
        return call_reply()

    def check_cancel():
        if cancelled:
            raise StoryGenerationCancelled()

    with pytest.raises(StoryGenerationCancelled):
        run_author_tool_loop(
            SimpleNamespace(chat=chat), [], executor=executor, before_call=check_cancel
        )
    assert len(saved) == 1  # No random decision was committed.


def test_generation_persists_random_choices_and_counts_each_model_request(tmp_path):
    artifacts = stage_artifacts()
    model = ConfigStoryAuthorModel(enabled_flags(), SimpleNamespace())
    requests = []

    def chat(messages, **kwargs):
        request = json.loads(messages[1]["content"])
        requests.append(request["stage"])
        if request["stage"] == "foundation" and messages[-1]["role"] != "tool":
            return call_reply()
        return {"artifact": artifacts[request["stage"]]}

    model._manager = SimpleNamespace(llm_adapter=SimpleNamespace(chat=chat))
    model._llm_manager = lambda: model._manager
    service, repository = service_at(tmp_path, model)
    task = service.create("Random story", task_id="random-story")
    result = service.run(task["id"])
    assert result["validation"]["valid"]
    assert result["cost"]["requests"] == len(requests) == 4
    path = repository.task_directory(task["id"]) / "random-requests.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "roles" in saved["requests"]
    restored = repository.random_request_executor(task["id"])
    record = saved["requests"]["roles"]
    assert (
        restored.execute("assign", "roles", record["request"]["arguments"])
        == record["result"]
    )


def test_tool_definitions_are_fresh_and_array_object_parameters_are_typed():
    first = random_tool_definitions()
    first[0]["function"]["parameters"]["properties"]["items"]["type"] = "broken"
    definitions = random_tool_definitions()
    assert (
        definitions[0]["function"]["parameters"]["properties"]["items"]["type"]
        == "array"
    )
    assert (
        definitions[-1]["function"]["parameters"]["properties"]["labels"]["type"]
        == "object"
    )


def test_restart_injects_committed_decisions_after_invalid_final_json(tmp_path):
    artifacts = stage_artifacts()
    model = ConfigStoryAuthorModel(enabled_flags(), SimpleNamespace())
    attempts = []

    def chat(messages, **kwargs):
        request = json.loads(messages[1]["content"])
        attempts.append(request)
        if len(attempts) == 1:
            return call_reply()
        if len(attempts) == 2:
            return "broken JSON"
        assert "roles" in request["resolvedRandomRequests"]
        assert "seed" not in request["resolvedRandomRequests"]
        return {"artifact": artifacts[request["stage"]]}

    model._llm_manager = lambda: SimpleNamespace(llm_adapter=SimpleNamespace(chat=chat))
    service, repository = service_at(tmp_path, model)
    task = service.create("Random story", task_id="restart-story")
    with pytest.raises(StoryGenerationError, match="invalid JSON"):
        service.run(task["id"])
    original = repository.random_request_executor(task["id"]).resolved_requests()
    # Recreate both the service and repository as a process restart would.
    restarted, restored_repository = service_at(tmp_path, model)
    result = restarted.run(task["id"])
    assert result["validation"]["valid"]
    assert result["cost"]["requests"] == 5
    assert (
        restored_repository.random_request_executor(task["id"]).resolved_requests()
        == original
    )


def test_malformed_json_tool_arguments_are_correctable():
    count = 0

    def chat(messages, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            response = call_reply()
            response.choices[0].message.tool_calls[0]["function"]["arguments"] = "{"
            return response
        assert not json.loads(messages[-1]["content"])["ok"]
        return {"artifact": {}}

    assert run_author_tool_loop(
        SimpleNamespace(chat=chat), [], executor=RandomRequestExecutor(scope="test")
    ) == {"artifact": {}}


def test_oversized_tool_batch_is_rejected_before_any_execution():
    response = call_reply()
    response.choices[0].message.tool_calls *= 25
    executor = RandomRequestExecutor(scope="test")
    with pytest.raises(AuthorToolLoopError):
        run_author_tool_loop(
            SimpleNamespace(chat=lambda *args, **kwargs: response),
            [],
            executor=executor,
        )
    assert executor.resolved_requests() == {}
