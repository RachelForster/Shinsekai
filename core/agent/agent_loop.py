"""给项目加上「代理」能力：两条职责根本不同的异步线程协作完成一次任务。

术语（贯穿全文件）——两条线程有各自的**提示词**、各自的**工具规格**、各自的
**LLM 适配器**（今后可分别配置模型：一路角色扮演、一路执行），用途根本不同：

- **loop thread（执行线程）**：唯一的一条执行循环，参考 OpenClaw / caiclaw 的
  ``executeToolLoop``。它的职责只有一个：**调用工具**——为对话取回信息，或在用户的
  macOS 上执行动作。它拿到**详细的工具规格**（macOS 工具组）和构建时注入的本机
  环境（系统、工作目录、已装应用）。每执行完一个工具，就把**工具原始结果**写进
  channel；它自己不面向用户组织语言。
- **interact thread（交互线程）**：唯一开口跟用户说话的线程（走既有 TTS/UI 管线，
  与主对话同一条路）。它看得到两样东西——**用户的请求**和执行线程取回的**工具结果**
  ——然后用口语把这些讲给用户听。它不带可调用的工具，只在提示词里拿到一份**工具
  摘要**（名字加一句描述），好知道执行线程有什么本事、从不说「我做不了」。

两条线程之间只靠一条 **channel**（``queue.Queue``）沟通，不走回调——对齐
``mvp/commune.py`` 的 ``progress_channel``。执行线程逐步往 channel 写类型化事件
（``Report``，pydantic 模型）；交互线程一段任务一段会话地消费：任务一开工先应一声
（与执行线程的第一次 LLM 调用并行），随后边听 channel 边同步进度，直到 done / say /
超时收尾。

编码风格刻意极简——除了 API 断点与 UI bridge 两处，别的地方不做错误处理。
"""

from __future__ import annotations

import os
import platform
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from sdk.messages import LLMDialogMessage
from llm.tools.tool_manager import ToolManager
from core.runtime.app_runtime import try_get_app_runtime

tool_manager = ToolManager()

# 一次任务里执行线程最多来回多少轮（硬性兜底；预算规则见 LOOP_PROMPT：检索 3 轮、动手 5 轮）。
MAX_STEPS = 6

# 交互线程读 channel 的兜底超时（秒），防意外死锁——对齐 MVP 的 get(timeout=...)。
# 相邻两条事件的最大间隔 ≈ 一次 LLM 调用 + 一次工具执行，按真实耗时放大。
CHANNEL_TIMEOUT = 120

# ── 提示词模板：两条线程各一段，用途根本不同（每个会话在构建时填充）───────

# 执行线程：只调工具，不说话。详细工具规格随请求的 tools 参数附带；
# 本机环境在会话构建时现取现注入（不为此另设函数或工具）。
LOOP_PROMPT = """你是执行代理的「执行线程」。你唯一的职责，是调用工具——为对话取回信息，或在用户的 macOS 上执行动作。

- 需要信息、或需要动手，就调用工具；每次只做必要的一步，看到结果再决定下一步。
- 需要什么信息，一律用工具现查，别凭记忆直接作答；你输出的正文不会传给用户。
- 不要面向用户组织语言、不要寒暄、也不要复述工具结果——说话是交互线程的事，不归你管。
- 轮次预算（严格）：一般信息检索类任务最多 3 轮；实际动手类任务（操作、写作、编码、改动）最多 5 轮。每轮结束你会收到 [进度]（第几轮、累计秒数）——结果够用就立刻收口，别为覆盖更多来源加轮次。
- 信息取够了、动作做完了，就停止调用工具。

本机环境：
{local_settings}"""

# 交互线程：看着「人类请求 + 工具结果」跟用户对话（TTS）。由本次任务作者手写。
# 它只拿到工具摘要（不能调用）——知道执行线程有什么本事，所以从不说「我做不了」。
INTERACT_PROMPT = """你是执行代理的「交互线程」，负责开口跟用户说话（你说的话会走 TTS 念出来）。

执行线程正拿着这些本事替你办事（你自己不动手，执行也不归你管）：
{tool_digest}

你看得到两样东西：
- [人类请求]：用户想让你办的事。
- [工具结果]：执行线程替你用工具取回的信息、或替你做完的动作。

你的活儿，是把这些用自然的口语讲给用户听，像跟身边的搭档聊天——不是念报告。

- 每次开口不超过 40 个字。
- 刚收到 [人类请求]、还没有任何 [工具结果] 时，用「我去查查」「我这就去弄」这类话应一声；这时候信息还没到手，绝不凭空作答，也绝不说「我做不了」「我没有这个工具」——活儿已经在执行线程手上了。
- 来了 [工具结果]，用一句话顺口同步你「正在做什么」（「我看了下你的音量……」），别急着把结果报出来；一步很琐碎就不吭声，直接留空。
- [完成] 时把最终结果讲清楚。但要是前面已经说到位了，别重复——直接留空。
- 要是压根没查到什么，就自然地随口收个尾，别硬编细节。
- 第一人称、口语、平级；别加开场白，别用「让我」「好的」「接下来我将」这类过场。
- 不用 markdown、列表、表情符号；别提「工具」「函数」「AI」；把技术动作翻成人话。

只输出要说出口的那句话本身。"""

# API 断点 / 步数上限 / channel 超时的兜底话，交互线程照原样念（不再走一次 LLM）。
_BREAK_TEXT = "（跟模型的连接断了，我先停在这。）"
_LIMIT_TEXT = "（步数到上限了，我先停一下。）"
_TIMEOUT_TEXT = "（等了半天没等到下文，我先停在这。）"


class Report(BaseModel):
    """channel 里的一条类型化事件（对齐 MVP 的 {type, data} 消息）。

    ``kind``：
    - ``request``：一次任务开工，携带 [人类请求] 正文——交互线程据此开启一段会话。
    - ``tool_output``：一个工具执行完，携带工具名与**原始结果**（≈ MVP 的 progress）。
    - ``done``：本次任务执行结束，交互线程据此收尾。
    - ``say``：让交互线程照原样念出 ``text`` 并结束会话（≈ MVP 的 error 兜底）。

    两个预算元数据（执行线程逐事件填写）：
    - ``rounds``：本次任务到该事件为止已完成的工具轮数。
    - ``duration``：本次任务到该事件为止的累计秒数。
    """

    kind: Literal["request", "tool_output", "done", "say"]
    text: str = ""
    tool: str = ""
    rounds: int = 0
    duration: float = 0.0


class ToolCall(BaseModel):
    """执行线程的一次工具调用请求（从 LLM 响应归一而来）。"""

    id: str
    name: str
    arguments: str = "{}"


class Completion(BaseModel):
    """一次 LLM 调用的归一化结果。

    ``extra`` 是需要原样写回 assistant 轮次的字段（如 DeepSeek 思考模式要求
    带 tool_calls 的轮次回传 ``reasoning_content``）。
    """

    content: str = ""
    calls: list[ToolCall] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


class _LLMBackend:
    """一次性无状态 LLM 调用，把响应归一成 ``Completion``。

    每条线程各建一个实例（各自的适配器）——今后两路可分别配置模型：
    交互线程走角色扮演模型，执行线程走执行模型。
    """

    def __init__(self) -> None:
        from config.config_manager import ConfigManager
        from llm.llm_manager import LLMAdapterFactory

        cfg = ConfigManager()
        provider, model, base_url, api_key = cfg.get_llm_api_config()
        self._adapter = LLMAdapterFactory.create_adapter(
            **cfg.merged_llm_factory_kwargs(
                provider,
                {"llm_provider": provider, "api_key": api_key, "base_url": base_url, "model": model},
            )
        )

    def complete(self, messages: list[dict], tools: Optional[list] = None) -> Optional[Completion]:
        # 唯一允许的错误处理点之一：API 断点——调不通、或响应残缺（如网关返回空
        # choices），都算断点，一律返回 None，交由上层走兜底。整段解析也在此保护内。
        try:
            resp = self._adapter.chat(
                messages, stream=False, tools=tools or None, response_format={"type": "text"}
            )
            if resp is None:
                return None
            msg = resp.choices[0].message
            return Completion(
                content=msg.content or "",
                calls=[
                    ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
                    for c in (msg.tool_calls or [])
                ],
                extra=(
                    {"reasoning_content": msg.reasoning_content}
                    if getattr(msg, "reasoning_content", None)
                    else {}
                ),
            )
        except Exception:
            return None


def _first_character_name(rt: Any) -> str:
    chars = getattr(rt.config.config, "characters", None) or []
    return chars[0].name if chars else ""


class AgentSession:
    """一次会话：一条 loop thread + 一条 interact thread，靠 channel 异步协作。

    两条线程的一切在这里就分开：``loop_tools`` 是详细工具规格（macOS 组），
    交互线程只在提示词里拿工具摘要（``interact_tools`` 默认空——它只说话）；
    两条线程各持一个 LLM 适配器实例。
    """

    def __init__(
        self,
        runtime: Any,
        *,
        loop_backend: Any = None,
        interact_backend: Any = None,
        loop_tools: Optional[list] = None,
        interact_tools: Optional[list] = None,
        run_tool: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.rt = runtime
        # 两条线程各自的适配器实例——今后各配各的模型（角色扮演 / 执行）。
        self.loop_backend = loop_backend or _LLMBackend()
        self.interact_backend = interact_backend or _LLMBackend()
        # 执行线程：拿 macOS 动作/取数工具。交互线程：默认不带可调用工具（只说话）。
        self.loop_tools = (
            loop_tools if loop_tools is not None else tool_manager.get_definitions(groups=["macos"])
        )
        self.interact_tools = interact_tools if interact_tools is not None else []
        self.run_tool = run_tool or tool_manager.execute
        # 提示词在此构建：执行线程注入本机环境（现取，不另设函数）；
        # 交互线程注入工具摘要（只有名字和一句描述，不是可调用规格）。
        apps = "、".join(sorted(p.stem for p in Path("/Applications").glob("*.app")))
        self.loop_prompt = LOOP_PROMPT.format(
            local_settings=(
                f"- 系统：macOS {platform.mac_ver()[0]}（{platform.machine()}）\n"
                f"- 工作目录：{os.getcwd()}\n"
                f"- 已装应用（连同系统自带 App，都可用 AppleScript 驱动）：{apps}\n"
                f"- 联网：run_shell 的 curl 可以上网；搜索用 curl -sL 'https://html.duckduckgo.com/html/?q=…'"
                f"（Google 会挡脚本），网页太长就配合 grep/sed 截取要点\n"
                f"- 工具域：macos（本机自动化；详细工具规格随请求附带）"
            )
        )
        digest = "\n".join(
            f"- {d['function']['name']}：{d['function'].get('description', '')}"
            for d in self.loop_tools
        )
        self.interact_prompt = INTERACT_PROMPT.format(tool_digest=digest or "-（这次没挂工具）")
        self.tasks: Queue = Queue()      # 用户任务 → 执行线程（天然把任务排成串行）
        self.channel: Queue = Queue()    # 执行线程 → 交互线程的唯一沟通结构
        self.running = True
        self._char = _first_character_name(runtime)
        self.loop_thread = threading.Thread(target=self._loop_body, name="agent-loop", daemon=True)
        self.interact_thread = threading.Thread(
            target=self._interact_body, name="agent-interact", daemon=True
        )

    # ── 生命周期 ─────────────────────────────────────────────────────────
    def start(self) -> None:
        self.loop_thread.start()
        self.interact_thread.start()

    def submit(self, task: str) -> None:
        self.tasks.put(task)

    def stop(self) -> None:
        self.running = False
        self.tasks.put(None)
        self.channel.put(None)

    # ── loop thread：只调工具，把类型化事件写进 channel ───────────────────
    def _loop_body(self) -> None:
        while self.running:
            task = self.tasks.get()
            if task is None:
                break
            self._execute(task)

    def _execute(self, task: str) -> None:
        """一次任务的 ReAct 循环：调工具取信息 / 执行动作，把事件流进 channel。

        开工先广播 ``request``——空闲时等价于「同时打到两个 loop」（交互线程的应声
        与这里的第一次 LLM 调用并行）；忙时任务在 tasks 队列里排队，叙述不会串台。
        执行线程不面向用户组织语言——它只产出 ``tool_output`` / ``done``，
        用户听到的话由交互线程去说。
        """
        started = time.time()
        self.channel.put(Report(kind="request", text=task))
        messages: list[dict] = [
            {"role": "system", "content": self.loop_prompt},
            {"role": "user", "content": task},
        ]
        for step in range(MAX_STEPS):
            out = self.loop_backend.complete(messages, tools=self.loop_tools)
            elapsed = time.time() - started
            if out is None:                            # API 断点
                self.channel.put(Report(kind="say", text=_BREAK_TEXT, rounds=step, duration=elapsed))
                return
            if not out.calls:                          # 不再需要工具 → 交给交互线程收尾
                self.channel.put(Report(kind="done", rounds=step, duration=elapsed))
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": out.content,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": c.arguments},
                        }
                        for c in out.calls
                    ],
                    **out.extra,
                }
            )
            for c in out.calls:
                result = self.run_tool(c.name, c.arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": c.id, "name": c.name, "content": result}
                )
                self.channel.put(
                    Report(kind="tool_output", text=result, tool=c.name,
                           rounds=step + 1, duration=time.time() - started)
                )
            # 预算元数据进上下文：模型每轮都看得到自己烧到第几轮、多少秒。
            messages.append(
                {"role": "user",
                 "content": f"[进度] 第 {step + 1} 轮完成，累计 {time.time() - started:.0f} 秒。"
                            f"预算：检索类 3 轮、动手类 5 轮。"}
            )
        self.channel.put(
            Report(kind="say", text=_LIMIT_TEXT, rounds=MAX_STEPS, duration=time.time() - started)
        )

    # ── interact thread：MVP 式会话循环——应声 → 听 channel → 收尾 ─────────
    def _interact_body(self) -> None:
        while self.running:
            report = self.channel.get()
            if report is None:
                break
            if report.kind == "request":   # 只有新任务才开启一段会话；上段任务的残留直接丢掉
                self._converse(report.text)

    def _converse(self, task: str) -> None:
        """一段任务会话（对齐 MVP 的 interactive_loop 内环）。

        先应一声（与执行线程的第一步并行），然后阻塞读 channel 逐条同步，
        直到 done / say / 超时收尾。每段会话上下文全新，状态都是局部变量。
        """
        messages: list[dict] = [
            {"role": "system", "content": self.interact_prompt},
            {"role": "user", "content": f"[人类请求]\n{task}"},
        ]
        self._say_via_llm(messages)        # 立刻应一声：「收到，我去查查」
        while True:
            try:
                report = self.channel.get(timeout=CHANNEL_TIMEOUT)
            except Empty:                  # 防意外死锁（对齐 MVP 的超时兜底）
                self._speak(_TIMEOUT_TEXT)
                return
            if report is None:
                return
            if report.kind == "say":       # 兜底：照原样念，会话就此结束
                self._speak(report.text)
                return
            if report.kind == "tool_output":
                messages.append({"role": "user", "content": f"[工具结果] {report.tool}\n{report.text}"})
                self._say_via_llm(messages)
                continue
            # done：收尾轮必走——结果没讲过就必须在这里讲；讲没讲过由模型看着上下文
            # 定夺（对齐 MVP：done 一定有机会把最终结果送出去）。
            messages.append(
                {"role": "user", "content": "[完成] 要是最终结果还没讲清楚，现在讲；讲清了就只输出空，一个字也别多说。"}
            )
            self._say_via_llm(messages)
            return

    def _say_via_llm(self, messages: list[dict]) -> None:
        """让交互线程的 LLM 就当前上下文说一句（也可以选择留空不说）。"""
        out = self.interact_backend.complete(messages, tools=self.interact_tools or None)
        if out is None:                    # API 断点：这句不说了，会话继续
            return
        spoken = out.content.strip()
        if not spoken:
            return
        messages.append({"role": "assistant", "content": spoken})
        self._speak(spoken)

    def _speak(self, text: str) -> None:
        # 唯一允许的另一处错误处理：UI bridge——喂给现有 TTS 管线，播不出也别拖垮线程。
        try:
            self.rt.tts_queue.put(LLMDialogMessage(name=self._char, text=text, asset_id="-1"))
        except Exception:
            pass


_SESSION: Optional[AgentSession] = None


def get_session() -> Optional[AgentSession]:
    """惰性拿到进程内唯一的会话（runtime 未就绪时返回 None）。"""
    global _SESSION
    rt = try_get_app_runtime()
    if rt is None:
        return None
    if _SESSION is None:
        _SESSION = AgentSession(rt)
        _SESSION.start()
    return _SESSION
