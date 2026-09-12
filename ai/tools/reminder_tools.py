"""Character-accessible scheduling, independent of chat window timers."""

from sdk.llm_runtime import get_llm_host_runtime
from sdk.tool_registry import tool


@tool(group="default", description=(
    "管理角色日程提醒。action=list/create/update/cancel。用户要求提醒时必须调用此工具，"
    "只有返回 ok=true 才能说已设置。create 需要 character_name(现有角色全名)、title、message(角色口吻的提醒正文)，"
    "以及 remind_at(未来 ISO 本地日期时间，如 2026-09-13T23:00:00) 或 delay_minutes(相对分钟数)，二选一。"
    "recurrence=once/daily/weekly，默认 once；每日/每周以首次时间按电脑本地时间重复。"
    "list 返回当前本地时间和日程；不确定今天日期时先 list。update/cancel 必须用 list 返回的 id 填 reminder_id；"
    "update 只填写要修改的字段。提醒需要 Shinsekai 桌面程序保持运行（可以收起到托盘），不是系统关机闹钟。"
))
def manage_reminders(action: str, reminder_id: str = "", character_name: str = "", title: str = "",
                     message: str = "", remind_at: str = "", delay_minutes: str = "", recurrence: str = ""):
    return get_llm_host_runtime().manage_reminders({
        "action": action, "reminder_id": reminder_id, "character_name": character_name,
        "title": title, "message": message, "remind_at": remind_at,
        "delay_minutes": delay_minutes, "recurrence": recurrence,
    })
