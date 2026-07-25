"""Agent loop / interact thread behavior.

Two threads with fundamentally different purposes, communicating ONLY through a
channel (queue of typed pydantic Reports) — mirroring mvp/commune.py:
- loop thread (`_execute`): only calls tools to fetch info / perform actions,
  streaming typed events into the channel. It carries the DETAILED tool spec
  plus build-time local settings, and never composes the user-facing answer.
- interact thread (`_interact_body` / `_converse`): the conversational voice.
  It carries only a concatenated tool DIGEST in its prompt (nothing callable),
  runs one session per task: ack immediately, consume the channel (with a
  deadlock-guard timeout), narrate progress, close on done/say/timeout.
- each thread holds its OWN LLM backend (future: role-play vs execution models).

Driven synchronously (no real threads, no network) via fake backends and a
preloaded channel.
"""

from __future__ import annotations

import os
import types
from queue import Queue

import pytest

import core.agent.agent_loop as agent_loop
from core.agent.agent_loop import (
    AgentSession,
    Completion,
    Report,
    ToolCall,
    _BREAK_TEXT,
    _LIMIT_TEXT,
    _TIMEOUT_TEXT,
    MAX_STEPS,
)

MACOS_TOOL = {
    "type": "function",
    "function": {"name": "applescript", "description": "执行 AppleScript，驱动系统与应用。"},
}

SILENT = Completion()  # an LLM turn that chooses to say nothing / stop calling tools


def say(text):
    return Completion(content=text)


def call_tool(cid="1", name="applescript", args="{}", **extra):
    return Completion(calls=[ToolCall(id=cid, name=name, arguments=args)], extra=extra)


class FakeBackend:
    """Returns scripted Completions (or None) per complete().

    Records every call so tests can assert per-thread prompt + tool spec.
    """

    def __init__(self, script):
        self.script = list(script)
        self.seen = []  # dicts: {system, messages, tools}

    def complete(self, messages, tools=None):
        self.seen.append(
            {"system": messages[0]["content"], "messages": list(messages), "tools": tools}
        )
        return self.script.pop(0)

    def calls_with(self, system):
        return [c for c in self.seen if c["system"] == system]


def _fake_runtime():
    char = types.SimpleNamespace(name="爱丽丝")
    cfg = types.SimpleNamespace(config=types.SimpleNamespace(characters=[char]))
    return types.SimpleNamespace(tts_queue=Queue(), config=cfg)


def _session(backend, run_tool=None, interact_tools=None, loop_tools=None):
    # 同一个 fake 同时充当两路 backend——脚本按跨线程的调用顺序排布。
    return AgentSession(
        _fake_runtime(),
        loop_backend=backend,
        interact_backend=backend,
        loop_tools=loop_tools if loop_tools is not None else [MACOS_TOOL],
        interact_tools=interact_tools if interact_tools is not None else [],
        run_tool=run_tool or (lambda name, args: '{"ok": true}'),
    )


def _drain(q):
    items = []
    while not q.empty():
        items.append(q.get())
    return items


def _spoken(s):
    return [m.text for m in _drain(s.rt.tts_queue)]


# ── typed channel messages: pydantic, no duck types ──────────────────────


def test_report_rejects_unknown_kind():
    with pytest.raises(Exception):
        Report(kind="bogus")


def test_completion_and_tool_call_are_validated_models():
    c = call_tool(cid="7", args='{"x": 1}', reasoning_content="想了想")
    assert c.calls[0].id == "7"
    assert c.extra == {"reasoning_content": "想了想"}
    with pytest.raises(Exception):
        ToolCall(name="no-id")  # id is required


# ── loop thread ──────────────────────────────────────────────────────────


def test_loop_streams_request_then_raw_tool_output_then_done_into_channel():
    backend = FakeBackend([call_tool(), SILENT])
    s = _session(backend, run_tool=lambda n, a: '{"events": "10:00 会议"}')
    s._execute("查一下我明天的安排")

    reports = _drain(s.channel)
    kinds = [(r.kind, r.tool, r.text) for r in reports]
    assert kinds == [
        ("request", "", "查一下我明天的安排"),
        ("tool_output", "applescript", '{"events": "10:00 会议"}'),
        ("done", "", ""),
    ]


def test_loop_does_not_compose_answer():
    # Even if the model emits prose alongside a final no-tool turn, the loop must
    # NOT ship it as the user-facing answer — it just signals `done`.
    backend = FakeBackend([say("这是模型自己写的最终话，不该被念出来")])
    s = _session(backend)
    s._execute("在吗")

    reports = _drain(s.channel)
    assert len(reports) == 2  # request + done
    assert reports[0].kind == "request"
    assert reports[1].kind == "done"
    assert reports[1].text == ""  # the loop's prose is discarded


def test_tool_result_fed_back_to_loop():
    calls_made = []

    def run_tool(name, args):
        calls_made.append((name, args))
        return '{"result": "会议 10:00"}'

    backend = FakeBackend([call_tool(cid="abc", args='{"script": "x"}'), SILENT])
    s = _session(backend, run_tool=run_tool)
    s._execute("t")

    assert calls_made == [("applescript", '{"script": "x"}')]
    second = backend.seen[1]["messages"]
    # 每轮末尾是 [进度] 预算元数据；工具回执与 assistant 轮次在其前。
    assert second[-1]["role"] == "user" and second[-1]["content"].startswith("[进度] 第 1 轮")
    assert second[-2]["role"] == "tool"
    assert second[-2]["tool_call_id"] == "abc"
    assert second[-2]["content"] == '{"result": "会议 10:00"}'
    assert second[-3]["role"] == "assistant"
    assert second[-3]["tool_calls"][0]["function"]["name"] == "applescript"


def test_loop_api_breakpoint_says_fallback():
    backend = FakeBackend([None])
    s = _session(backend)
    s._execute("t")

    reports = _drain(s.channel)
    # request + a verbatim `say` fallback
    assert [r.kind for r in reports] == ["request", "say"]
    assert reports[-1].text == _BREAK_TEXT


def test_loop_step_limit():
    backend = FakeBackend([call_tool()] * (MAX_STEPS + 5))
    s = _session(backend)
    s._execute("t")

    reports = _drain(s.channel)
    assert reports[-1].kind == "say" and reports[-1].text == _LIMIT_TEXT
    # request + MAX_STEPS tool_output + 1 say
    assert len(reports) == MAX_STEPS + 2
    assert len(backend.seen) == MAX_STEPS


# ── the core split: different prompts, tool specs, and backends ────────────


def test_loop_and_interact_use_different_prompts_and_tool_specs():
    backend = FakeBackend(
        [
            call_tool(),              # loop step 1
            SILENT,                   # loop step 2 → done
            say("我去看看"),           # interact ack
            say("翻了下你日历……"),     # interact voices tool_output
            SILENT,                   # interact done turn: nothing left to add
        ]
    )
    s = _session(backend)
    s._execute("查我明天安排")
    # drive the interact side over the channel the loop filled
    request = s.channel.get()
    assert request.kind == "request"
    s._converse(request.text)

    loop_calls = backend.calls_with(s.loop_prompt)
    interact_calls = backend.calls_with(s.interact_prompt)
    assert loop_calls and interact_calls
    # different prompts
    assert s.loop_prompt != s.interact_prompt
    # different tool specs: loop carries the detailed macOS spec; interact carries none
    assert all(c["tools"] == [MACOS_TOOL] for c in loop_calls)
    assert all(c["tools"] in (None, []) for c in interact_calls)


def test_threads_get_separate_backends_by_default(monkeypatch):
    # 未来两路各配各的模型（角色扮演 / 执行）——默认就得是两个适配器实例。
    created = []

    class StubBackend:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(agent_loop, "_LLMBackend", StubBackend)
    s = AgentSession(_fake_runtime(), loop_tools=[], interact_tools=[], run_tool=lambda n, a: "")

    assert len(created) == 2
    assert s.loop_backend is not s.interact_backend


def test_loop_prompt_carries_build_time_local_settings():
    s = _session(FakeBackend([]))
    assert "macOS" in s.loop_prompt
    assert os.getcwd() in s.loop_prompt
    assert "AppleScript" in s.loop_prompt
    assert "curl" in s.loop_prompt   # 联网能力要写明，搜索类任务才接得住
    assert "macos" in s.loop_prompt  # 工具域
    # 轮次预算：检索 3 轮、动手 5 轮，必须写进系统提示词
    assert "3 轮" in s.loop_prompt and "5 轮" in s.loop_prompt


def test_loop_injects_round_progress_metadata_each_round():
    # 两轮工具：第 2 轮的 LLM 调用必须看到第 1 轮的 [进度]（轮数 + 秒数 + 预算）。
    backend = FakeBackend([call_tool(), call_tool(cid="2"), SILENT])
    s = _session(backend)
    s._execute("t")

    second = backend.seen[1]["messages"]
    progress = [m for m in second if m["role"] == "user" and m["content"].startswith("[进度]")]
    assert len(progress) == 1
    assert "第 1 轮" in progress[0]["content"] and "秒" in progress[0]["content"]
    third = backend.seen[2]["messages"]
    assert sum(m["content"].startswith("[进度]") for m in third if m["role"] == "user") == 2


def test_reports_carry_rounds_and_duration_metadata():
    backend = FakeBackend([call_tool(), SILENT])
    s = _session(backend)
    s._execute("t")

    reports = _drain(s.channel)
    tool_out = next(r for r in reports if r.kind == "tool_output")
    done = next(r for r in reports if r.kind == "done")
    assert tool_out.rounds == 1 and tool_out.duration >= 0
    assert done.rounds == 1 and done.duration >= 0  # 1 轮工具后收口


def test_step_limit_report_carries_full_budget_metadata():
    backend = FakeBackend([call_tool()] * (MAX_STEPS + 5))
    s = _session(backend)
    s._execute("t")

    last = _drain(s.channel)[-1]
    assert last.kind == "say" and last.text == _LIMIT_TEXT
    assert last.rounds == MAX_STEPS


def test_interact_prompt_carries_tool_digest_and_tts_rules():
    s = _session(FakeBackend([]))
    # digest: name + one-line description of the EXECUTOR's tools, as prose
    assert "applescript" in s.interact_prompt
    assert "执行 AppleScript" in s.interact_prompt
    # TTS 硬规矩：每次开口不超过 40 个字；第一轮不许说「我做不了」
    assert "40 个字" in s.interact_prompt
    assert "我做不了" in s.interact_prompt
    # the digest is prose only — the interact side has no callable spec
    assert s.interact_tools == []


# ── interact thread ──────────────────────────────────────────────────────


def test_interact_acks_request_immediately_before_any_tool_output():
    # MVP: the interactive loop responds the moment the query lands — the ack
    # LLM call sees ONLY the human request (it runs parallel to the loop's step 1).
    backend = FakeBackend([say("我去查查"), say("查到了，明天上午有个会")])
    s = _session(backend)
    s.channel.put(Report(kind="done"))
    s._converse("查我明天安排")

    assert _spoken(s)[0] == "我去查查"
    ack_msgs = backend.seen[0]["messages"]
    assert ack_msgs[-1]["content"] == "[人类请求]\n查我明天安排"


def test_interact_sees_request_and_tool_output_then_speaks():
    backend = FakeBackend([SILENT, say("我翻了下你日历，明天上午有个会"), SILENT])
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text='{"events": "10:00 会议"}', tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("查我明天安排")

    # spoke to TTS as the character
    out = _drain(s.rt.tts_queue)
    assert len(out) == 1
    assert out[0].text == "我翻了下你日历，明天上午有个会"
    assert out[0].name == "爱丽丝"
    # the narration LLM call saw BOTH the human request and the tool output
    msgs = backend.seen[1]["messages"]
    joined = "\n".join(m["content"] for m in msgs if isinstance(m.get("content"), str))
    assert "[人类请求]" in joined and "查我明天安排" in joined
    assert "[工具结果] applescript" in joined and "10:00 会议" in joined


def test_interact_done_composes_final_for_pure_conversation():
    # No tools ran → done must answer the request.
    backend = FakeBackend([SILENT, say("明天上午十点有个会")])
    s = _session(backend)
    s.channel.put(Report(kind="done"))
    s._converse("查我明天安排")

    assert _spoken(s) == ["明天上午十点有个会"]
    assert backend.seen[1]["messages"][-1]["content"].startswith("[完成]")


def test_interact_done_turn_always_runs_so_the_answer_is_never_swallowed():
    # The [完成] turn is NEVER structurally suppressed (MVP: done always gets to
    # deliver the result). Dedup lives in the instruction — here the model judges
    # the narration already said it all and outputs empty → exactly one line.
    backend = FakeBackend([SILENT, say("我看了下，音量是 46"), SILENT])
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="46", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("音量多少")

    assert _spoken(s) == ["我看了下，音量是 46"]  # no double-speak
    assert len(backend.seen) == 3  # ack + narration + done turn (always consulted)
    assert backend.seen[2]["messages"][-1]["content"].startswith("[完成]")


def test_interact_done_delivers_result_withheld_by_the_narration():
    # The prompt steers step narration to NOT report the result yet
    # (「别急着把结果报出来」) — so a spoken-but-resultless narration must still
    # get the answer out on done, never a silent close.
    backend = FakeBackend([say("我去查查"), say("我看了下你的音量……"), say("音量是 46")])
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="46", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("音量多少")

    assert _spoken(s) == ["我去查查", "我看了下你的音量……", "音量是 46"]


def test_interact_multi_step_synthesizes_on_done():
    # Two tool outputs → progress narration each + a final synthesis on done.
    backend = FakeBackend(
        [
            SILENT,                          # ack chose silence
            say("我翻了下日历……"),            # tool_output 1
            say("又看了下邮件……"),            # tool_output 2
            say("明天上午有会，下午没事"),      # done synthesis
        ]
    )
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="10:00 会议", tool="applescript"))
    s.channel.put(Report(kind="tool_output", text="无新邮件", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("我明天忙不忙")

    assert _spoken(s) == ["我翻了下日历……", "又看了下邮件……", "明天上午有会，下午没事"]


def test_interact_single_step_silent_narration_still_answers_on_done():
    # The one tool step was voiced as empty (model chose silence) → done must answer.
    backend = FakeBackend([SILENT, SILENT, say("音量是 46")])
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="46", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("音量多少")

    assert _spoken(s) == ["音量是 46"]


def test_interact_say_is_verbatim_no_llm():
    backend = FakeBackend([SILENT])  # consumed by the ack only
    s = _session(backend)
    s.channel.put(Report(kind="say", text=_BREAK_TEXT))
    s._converse("t")

    assert _spoken(s) == [_BREAK_TEXT]
    assert len(backend.seen) == 1  # only the ack; `say` never consults the LLM


def test_interact_api_breakpoint_is_silent_but_session_survives():
    # Every interact-side LLM call breaking → no speech, no crash, session ends
    # normally on done.
    backend = FakeBackend([None, None, None])  # ack, tool_output, done all break
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="x", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("t")

    assert s.rt.tts_queue.empty()


def test_interact_channel_timeout_says_so(monkeypatch):
    # Deadlock guard (MVP's get(timeout=...)): nothing arrives → speak the
    # timeout line and end the session instead of hanging forever.
    monkeypatch.setattr(agent_loop, "CHANNEL_TIMEOUT", 0.01)
    backend = FakeBackend([SILENT])  # the ack
    s = _session(backend)
    s._converse("t")  # channel left empty on purpose

    assert _spoken(s) == [_TIMEOUT_TEXT]


def test_interact_outer_loop_discards_stale_reports_and_only_request_opens_session():
    # Residue from an aborted session (e.g. after a timeout) must not wake the
    # LLM or the TTS — only a fresh `request` opens a conversation.
    backend = FakeBackend([say("我去查查"), say("好了")])
    s = _session(backend)
    s.channel.put(Report(kind="tool_output", text="stale", tool="applescript"))  # discarded
    s.channel.put(Report(kind="done"))                                            # discarded
    s.channel.put(Report(kind="request", text="新任务"))
    s.channel.put(Report(kind="done"))
    s.channel.put(None)  # stop sentinel ends the body
    s._interact_body()

    assert _spoken(s) == ["我去查查", "好了"]
    # both LLM calls belong to the new session
    assert all("新任务" in c["messages"][1]["content"] for c in backend.seen)


def test_stop_sentinel_mid_session_ends_converse_cleanly():
    # stop() puts a None sentinel; arriving mid-session it must end the
    # conversation, not crash the daemon voice thread on `report.kind`.
    backend = FakeBackend([SILENT])  # the ack only
    s = _session(backend)
    s.channel.put(None)
    s._converse("t")

    assert s.rt.tts_queue.empty()
    assert len(backend.seen) == 1  # no done turn after the sentinel


def test_submit_does_not_broadcast_the_loop_thread_does():
    # Deliberate deviation from the MVP's Event dispatch: `request` enters the
    # channel when the loop thread STARTS the task, never at submit — so a
    # queued second task can't interleave its narration into the first one's.
    backend = FakeBackend([])
    s = _session(backend)
    s.submit("任务")

    assert s.channel.empty()
    assert s.tasks.get_nowait() == "任务"


def test_loop_body_serializes_tasks_no_interleaving():
    backend = FakeBackend([SILENT, SILENT])  # both tasks need no tools
    s = _session(backend)
    s.tasks.put("a")
    s.tasks.put("b")
    s.tasks.put(None)
    s._loop_body()

    kinds = [(r.kind, r.text) for r in _drain(s.channel)]
    assert kinds == [("request", "a"), ("done", ""), ("request", "b"), ("done", "")]


def test_interact_configured_tool_spec_reaches_backend():
    sentinel = [{"type": "function", "function": {"name": "emote"}}]
    backend = FakeBackend([SILENT, SILENT])
    s = _session(backend, interact_tools=sentinel)
    s.channel.put(Report(kind="done"))
    s._converse("t")

    assert backend.seen  # ack + done turn both carried the configured spec
    assert all(c["tools"] == sentinel for c in backend.seen)


def test_broken_tts_bridge_does_not_kill_the_session():
    # The UI-bridge guard in _speak is one of the two mandated error handlers:
    # a dead TTS queue must not take the interact thread down with it.
    class BrokenQueue:
        def put(self, item):
            raise RuntimeError("bridge down")

    backend = FakeBackend([say("我去查查"), say("讲两句"), say("好了")])
    s = _session(backend)
    s.rt.tts_queue = BrokenQueue()
    s.channel.put(Report(kind="tool_output", text="x", tool="applescript"))
    s.channel.put(Report(kind="done"))
    s._converse("t")  # must not raise

    assert len(backend.seen) == 3  # the session processed everything regardless


def test_reasoning_content_is_written_back_to_assistant_tool_calls_turn():
    # DeepSeek 思考模式: an assistant turn carrying tool_calls must pass
    # reasoning_content back verbatim, or the endpoint rejects round 2.
    backend = FakeBackend([call_tool(reasoning_content="想了想"), SILENT])
    s = _session(backend)
    s._execute("t")

    assistant = backend.seen[1]["messages"][-3]  # [-1]=[进度] [-2]=tool [-3]=assistant
    assert assistant["role"] == "assistant"
    assert assistant["reasoning_content"] == "想了想"


def test_backend_extracts_reasoning_content_for_writeback():
    from core.agent.agent_loop import _LLMBackend

    b = _LLMBackend.__new__(_LLMBackend)  # bypass __init__ (no network)
    msg = types.SimpleNamespace(content="x", tool_calls=None, reasoning_content="推理")
    b._adapter = types.SimpleNamespace(
        chat=lambda *a, **k: types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
    )

    out = b.complete([{"role": "user", "content": "q"}])
    assert isinstance(out, Completion)
    assert (out.content, out.calls) == ("x", [])
    assert out.extra == {"reasoning_content": "推理"}


def test_backend_treats_malformed_response_as_breakpoint():
    # A malformed HTTP-200 response (e.g. a gateway returning empty choices) is an
    # API breakpoint, not a crash — the parse is inside the guarded boundary so the
    # daemon thread survives and the fallback fires.
    from core.agent.agent_loop import _LLMBackend

    b = _LLMBackend.__new__(_LLMBackend)  # bypass __init__ (no network)

    class BadAdapter:
        def chat(self, *a, **k):
            return types.SimpleNamespace(choices=[])  # choices[0] would IndexError

    b._adapter = BadAdapter()
    assert b.complete([{"role": "user", "content": "x"}]) is None
