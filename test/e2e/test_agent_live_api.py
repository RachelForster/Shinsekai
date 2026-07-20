"""真机 E2E：真实 LLM API + 真实 macOS 工具 + 真实 TTS 探测。

跑通「主对话 → agent_task → loop thread / interact thread」的完整链路，
把全轨迹（主对话每一轮、channel 事件流、执行线程每次工具调用、交互线程每句播报、
TTS 层探测结果）落盘成 markdown：``logs/agent_live_trajectory.md``——
**无论成败都会写**，失败时它就是排障现场。

花真实 API 费用、在本机真实执行工具，所以默认整套跑测试时跳过；显式运行：

    SHINSEKAI_LIVE=1 runtime/bin/python3 -m pytest test/e2e/test_agent_live_api.py -s
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from queue import Empty, Queue

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SHINSEKAI_LIVE") != "1",
    reason="真机测试：花真实 API 费用、在本机执行真实工具；用 SHINSEKAI_LIVE=1 显式运行",
)

import llm.tools.macos_tools  # noqa: F401  注册 macOS 工具组
import llm.tools.agent_tools  # noqa: F401  注册 agent_task
from sdk.tool_registry import apply_registered_tools
from llm.tools.tool_manager import ToolManager
from config.config_manager import ConfigManager
from core.runtime.app_runtime import AppRuntime, set_app_runtime
from core.agent.agent_loop import _LLMBackend, get_session

# 可用 SHINSEKAI_LIVE_TASK 换任务（例：上网自搜），默认查音量。
TASK = os.environ.get("SHINSEKAI_LIVE_TASK", "帮我看看我现在的系统音量是多少？")
TRAJECTORY_MD = Path("logs/agent_live_trajectory.md")
AGENT_DEADLINE = 300  # 秒：搜索类任务一步 = 一次慢 LLM + 一次网络抓取，放宽
DENIAL_WORDS = ("做不了", "无法", "没法", "做不到", "没有权限", "不能帮你")

# 主对话用真实角色卡（对齐 main.py 的加载方式）——角色自己的表达、对话级输出是必检项。
CHARACTER_CARD = Path("data/character_templates/七海.txt")


def _parse_dialog(content: str) -> list[dict]:
    """解析角色卡规定的对话级输出：{"dialog": [{character_name, sprite, speech, ...}]}。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    data = json.loads(text)
    dialog = data["dialog"]
    assert isinstance(dialog, list) and dialog, f"dialog 数组为空：{content[:200]}"
    for d in dialog:
        assert d.get("character_name") and d.get("sprite") and d.get("speech"), \
            f"对话级字段缺失（character_name/sprite/speech）：{d}"
    return dialog


def _now() -> str:
    return time.strftime("%H:%M:%S")


class Trajectory:
    """按时间序收集全链路事件，最后渲染成 markdown。"""

    def __init__(self):
        self.events: list[tuple[str, str, str]] = []  # (ts, 分类, 内容)
        self._lock = threading.Lock()

    def add(self, kind: str, text: str) -> None:
        with self._lock:
            self.events.append((_now(), kind, text))

    def render(self, verdicts: list[str]) -> str:
        lines = [
            "# Agent 真机 E2E 全轨迹",
            "",
            f"*{time.strftime('%Y-%m-%d %H:%M:%S')} · 任务：「{TASK}」·"
            " 真实 LLM API + 真实 macOS 工具 + 真实 TTS 探测*",
            "",
            "## 结论",
            "",
            *[f"- {v}" for v in verdicts],
            "",
            "## 全事件流（时间序）",
            "",
        ]
        for ts, kind, text in self.events:
            body = text if "\n" not in text else "\n\n  ```\n  " + text.replace("\n", "\n  ") + "\n  ```\n"
            lines.append(f"- `{ts}` **[{kind}]** {body}")
        lines.append("")
        return "\n".join(lines)


def test_agent_full_trajectory_live():
    tm = ToolManager()
    apply_registered_tools(tm)
    traj = Trajectory()

    # ── 最小应用运行时：让 get_session()/agent_task 走真实入口 ────────────
    rt = AppRuntime(
        config=ConfigManager(),
        ui_update_manager=None, llm_manager=None, tts_manager=None, t2i_manager=None,
        bgm_list=[], user_input_queue=Queue(), tts_queue=Queue(), audio_path_queue=Queue(),
        text_processor=None, opencc=None,
    )
    set_app_runtime(rt)

    # 先拿会话，把探针装好（channel 事件、执行线程工具调用、交互线程播报）。
    session = get_session()
    assert session is not None

    orig_put = session.channel.put
    reports: list = []
    def traced_put(item):
        if item is not None:
            reports.append(item)
            traj.add("channel", f"kind={item.kind} tool={item.tool or '-'} "
                                f"rounds={item.rounds} dur={item.duration:.0f}s "
                                f"text={item.text[:160] or '-'}")
        return orig_put(item)
    session.channel.put = traced_put

    tool_calls_made: list[str] = []
    def traced_run_tool(name, args):
        traj.add("loop→工具", f"{name}({args[:300]})")
        result = tm.execute(name, args)
        traj.add("工具→loop", f"{name} → {result[:300]}")
        tool_calls_made.append(name)
        return result
    session.run_tool = traced_run_tool

    spoken: list[str] = []
    stop_watch = threading.Event()
    def watch_tts():
        while not stop_watch.is_set():
            try:
                m = rt.tts_queue.get(timeout=0.5)
            except Empty:
                continue
            spoken.append(m.text)
            traj.add("interact→TTS", f"{m.name}：「{m.text}」")
    threading.Thread(target=watch_tts, daemon=True).start()

    verdicts: list[str] = []
    try:
        # ── 主对话第 1 轮：真实 API + 真实角色卡，挂 default 组工具（对齐 llm_manager）──
        backend = _LLMBackend()
        default_defs = tm.get_definitions(groups="default")
        from llm.tools.agent_tools import with_agent_capability
        card = with_agent_capability(CHARACTER_CARD.read_text(encoding="utf-8"))  # 对齐 main.py
        traj.add("主对话", f"用户：「{TASK}」（角色卡：{CHARACTER_CARD.name}，{len(card)} 字；"
                          f"挂载工具：{[d['function']['name'] for d in default_defs]}）")
        msgs = [{"role": "system", "content": card}, {"role": "user", "content": TASK}]

        out1 = backend.complete(msgs, tools=default_defs)
        assert out1 is not None, "主对话第 1 轮 API 断点"
        traj.add("主对话·第1轮", f"content={out1.content or '-'} tool_calls={[c.name for c in out1.calls]}")
        agent_calls = [c for c in out1.calls if c.name == "agent_task"]
        assert agent_calls, f"主 LLM 没有调用 agent_task（说明工具描述还不够硬）：{out1.content}"
        call = agent_calls[0]

        # ── 真实派发：走注册的 agent_task（内部 get_session().submit）──────
        dispatch_result = tm.execute("agent_task", call.arguments)
        traj.add("agent_task 返回", dispatch_result)

        # ── 主对话第 2 轮：把工具结果喂回去，拿角色的口头答复 ─────────────
        msgs.append({
            "role": "assistant", "content": out1.content,
            "tool_calls": [{"id": call.id, "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments}}],
        })
        msgs.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": dispatch_result})
        out2 = backend.complete(msgs, tools=default_defs)
        assert out2 is not None, "主对话第 2 轮 API 断点"
        assert not out2.calls, f"第 2 轮又发起了工具调用而不是回话：{[c.name for c in out2.calls]}"
        # 对话级输出必检：必须是角色卡规定的 dialog JSON，台词、立绘一样不能少。
        dialog = _parse_dialog(out2.content)
        speeches = [d["speech"] for d in dialog]
        for d in dialog:
            traj.add("主对话·台词", f"{d['character_name']}（sprite {d['sprite']}）：「{d['speech']}」")
        denial = [w for w in DENIAL_WORDS for s in speeches if w in s]
        assert not denial, f"角色台词仍在说自己做不了：命中 {denial}，台词={speeches}"

        # ── 等后台双线程跑完：channel 出现终态（done/say），播报安定 ────────
        start = time.time()
        def terminal_seen():
            return any(k == "channel" and ("kind=done" in t or "kind=say" in t)
                       for _, k, t in list(traj.events))
        last_beat = 0
        while time.time() - start < AGENT_DEADLINE and not terminal_seen():
            if not session.loop_thread.is_alive():
                traj.add("异常", "执行线程已死亡（未捕获异常）")
                break
            elapsed = int(time.time() - start)
            if elapsed - last_beat >= 15:
                last_beat = elapsed
                print(f"[wait {elapsed}s] events={len(traj.events)} spoken={len(spoken)} "
                      f"loop_alive={session.loop_thread.is_alive()}", flush=True)
            time.sleep(1)
        if terminal_seen():
            settle_from, settle_at = len(spoken), time.time()
            while time.time() - start < AGENT_DEADLINE:
                if len(spoken) != settle_from:
                    settle_from, settle_at = len(spoken), time.time()
                elif time.time() - settle_at > 20:  # done 后交互线程还有一次收尾 LLM 调用
                    break
                time.sleep(1)

        assert terminal_seen(), (
            f"{int(time.time() - start)} 秒内执行线程没有走到 done/say 终态"
            f"（loop_alive={session.loop_thread.is_alive()}，已捕获 {len(traj.events)} 条事件）"
        )
        assert tool_calls_made, "执行线程没有执行任何 macOS 工具"
        assert spoken, "交互线程一句话都没送进 TTS 队列"

        # 「简单乐观的返回次序」必检：request → tool_output* → done/say，一条不乱。
        kinds = [r.kind for r in reports]
        assert kinds[0] == "request", f"channel 首事件不是 request：{kinds}"
        assert kinds[-1] in ("done", "say"), f"channel 末事件不是终态：{kinds}"
        assert all(x == "tool_output" for x in kinds[1:-1]), f"channel 次序乱了：{kinds}"

        # 轮次预算必检：检索类 3 轮、动手类 5 轮——终态元数据不得超过硬预算。
        terminal = reports[-1]
        assert terminal.rounds <= 5, (
            f"执行线程烧了 {terminal.rounds} 轮（{terminal.duration:.0f} 秒），超出预算"
        )

        # ── TTS 层真机探测：真实云端合成一次，记录成败（余额不足也如实记录）─
        try:
            from plugins.cloud_tts.adapter import CloudTTSAdapter
            probe = Path("cache/audio/e2e_probe.wav.part")
            probe.unlink(missing_ok=True)
            result = CloudTTSAdapter().generate_speech("嗯。", file_path=str(probe))
            size = probe.stat().st_size if probe.is_file() else 0
            double = probe.with_suffix(".wav")  # e2e_probe.wav.wav 旧病灶
            tts_verdict = f"TTS 合成成功：{result}（{size} 字节，路径原样、无 .wav.wav：{not double.exists()}）"
            probe.unlink(missing_ok=True)
        except Exception as e:
            tts_verdict = f"TTS 合成失败：{e}"
        traj.add("TTS 真机探测", tts_verdict)

        verdicts = [
            f"主 LLM 第 1 轮就调用了 `agent_task`（task=「{json.loads(call.arguments).get('task', '')}」）✅",
            f"角色卡对话级输出合规（dialog JSON，{len(dialog)} 条台词带立绘），台词无「做不了」类措辞 ✅：{['「%s」' % s for s in speeches]}",
            f"返回次序符合「简单乐观」模型（request → tool_output×{len(kinds) - 2} → {kinds[-1]}）✅",
            f"轮次预算内：{terminal.rounds} 轮 / {terminal.duration:.0f} 秒（检索≤3，动手≤5）✅",
            f"执行线程真实执行了 {len(tool_calls_made)} 次 macOS 工具：{tool_calls_made} ✅",
            f"交互线程送出 {len(spoken)} 句播报 ✅：{['「%s」' % t for t in spoken]}",
            tts_verdict,
        ]
    finally:
        stop_watch.set()
        TRAJECTORY_MD.parent.mkdir(exist_ok=True)
        TRAJECTORY_MD.write_text(
            traj.render(verdicts or ["❌ 测试中途失败——以下为已捕获的全部现场事件"]), encoding="utf-8"
        )
        print(f"\n轨迹已写入 {TRAJECTORY_MD}" +
              ("\n" + "\n".join(f"  - {v}" for v in verdicts) if verdicts else "（失败现场）"))
