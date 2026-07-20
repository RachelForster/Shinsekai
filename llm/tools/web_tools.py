"""挂给执行代理的联网工具。

`web_search` 走 Brave Search 的 LLM grounding 接口（/res/v1/llm/context），
直接返回适合喂给模型的检索上下文——比 curl 搜索引擎 HTML 再 grep 可靠得多。
Key 从 ApiConfig（data/config/api.yaml，不入库）或环境变量读取，绝不写死在代码里。
"""

from __future__ import annotations

import os

import requests

from sdk.tool_registry import tool

_LIMIT = 50000
_ENDPOINT = "https://api.search.brave.com/res/v1/llm/context"


def _api_key() -> str:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if key:
        return key
    try:
        from config.config_manager import ConfigManager
        return str(ConfigManager().config.api_config.brave_search_api_key or "").strip()
    except Exception:
        return ""


@tool(name="web_search", group="web", risk="low",
      description="上网搜索（Brave Search）。q: 搜索关键词，英文关键词命中率更高。"
                  "返回带来源 URL 的检索上下文，直接可用；需要读整页时再配合 curl。")
def web_search(q: str) -> str:
    key = _api_key()
    if not key:
        return ("(web_search 未配置：请在 data/config/api.yaml 的 brave_search_api_key "
                "或环境变量 BRAVE_SEARCH_API_KEY 里填入 Brave Search API Key)")
    r = requests.get(
        _ENDPOINT,
        params={"q": q},
        headers={"X-Subscription-Token": key},
        timeout=30,
    )
    if r.status_code != 200:
        return f"(web_search HTTP {r.status_code}: {r.text[:300]})"
    return r.text.strip()[:_LIMIT] or "(no results)"
