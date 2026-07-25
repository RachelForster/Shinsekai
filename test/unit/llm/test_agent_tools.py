"""agent_task 触发工具与角色卡能力声明。"""

from llm.tools.agent_tools import AGENT_CAPABILITY_NOTE, with_agent_capability


def test_capability_note_names_the_tool_and_forbids_denial():
    assert "agent_task" in AGENT_CAPABILITY_NOTE
    assert "我做不了" in AGENT_CAPABILITY_NOTE  # 明令禁止的措辞要写在纸面上


def test_with_agent_capability_appends_once_idempotently():
    card = "# 七海千秋\n人设正文……"
    once = with_agent_capability(card)
    assert once.startswith(card)
    assert "agent_task" in once
    assert with_agent_capability(once) == once  # 幂等：重复调用不叠加
