"""把任务派发给执行代理的触发工具。

主对话的角色调用它，即可把一件需要在 macOS 上动手的事交给
loop thread + interact thread：后台一边做一边语音汇报，本次调用只负责派发、立即返回。
"""

from __future__ import annotations

from sdk.tool_registry import tool
from core.agent import get_session

# 附加到角色卡末尾的系统级能力声明：光有工具描述压不过 8KB 人设的角色扮演惯性
# （角色会入戏地岔开话题），必须让角色在人设层面就知道自己有真实的一双手。
AGENT_CAPABILITY_NOTE = """

## 真实执行能力（系统级，优先于人设习惯）
你不是只能聊天：你有一双真实的手——工具 agent_task。它背后是一条后台执行线程，能在用户的 macOS 上上网搜索查资料、读系统信息（电量/音量/时间）、看日历备忘录文件、开应用、跑命令。
- 用户要求查真实信息、上网搜索、或实际动手时：先调用 agent_task 派发，再照角色口吻用一句话告诉用户你已经去办了。
- 不要用人设口吻推脱或把话题岔开，绝不要说「我做不了」「我没法上网」「不如你来告诉我」。派发完照常保持角色表达。
- 进度和结果由系统自动转述给用户，你不需要复述；task 里只写要办的事本身，绝不要写「汇报」「告诉用户」「语音」之类的要求。"""


def with_agent_capability(template: str) -> str:
    """把执行能力声明拼到角色卡后面（幂等）。"""
    if AGENT_CAPABILITY_NOTE.strip() in template:
        return template
    return template + AGENT_CAPABILITY_NOTE


@tool(name="agent_task", group="default", risk="low",
      description="你在用户 macOS 上的双手和眼睛。凡是聊天里答不上、需要真实信息或实际动手的事"
                  "——上网搜索查资料、查电量音量时间、看日历备忘录文件、开应用开网页、跑命令改设置"
                  "——一律派给它，绝不要回答「我做不了」「我没法上网」「我没有搜索工具」。它由后台"
                  "执行线程异步完成；进度和结果由系统自动转述给用户。本次调用只负责派发、立即返回。"
                  "task: 用一句话说清要办的事本身——不要在 task 里写「汇报」「告诉用户」「语音」，"
                  "转述不归执行线程管。")
def agent_task(task: str) -> dict:
    session = get_session()
    if session is None:
        return {"error": "runtime not ready"}
    session.submit(task)
    return {
        "status": "已派发给后台执行线程，它正在办，并会边做边用语音向用户汇报进度和结果",
        "task": task,
        "note": "回复用户时：用一句话说你已经去办了、结果马上就来。不要编造结果，也绝不要说你做不了。",
    }
