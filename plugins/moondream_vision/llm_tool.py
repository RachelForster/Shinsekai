"""
Moondream 视屏能力暴露给 LLM 的 function-calling 工具。

模块被 ``plugin`` 导入时登记到 :mod:`sdk.tool_registry`；
宿主在 ``ensure_plugins_loaded`` 时统一注入 :class:`~llm.tools.tool_manager.ToolManager`。
"""

from __future__ import annotations

import logging
from typing import Any

from sdk.tool_registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="moondream_query_screen",
    description=(
        "截取指定显示器画面，用本地 Moondream2 视觉模型根据屏幕像素回答你的问题。"
        "当用户描述界面、错误提示、网页/应用里写了什么、当前窗口内容等需要「看屏」时使用。"
        "传入 question：用清晰的英文提问，例如 'What is the URL in the address bar?'"
        "可选 monitor_index：mss 监视器编号；默认 -1 表示使用插件设置里的 monitor_index；0 为虚拟全桌面，1 为主屏。"
    ),
)
def moondream_query_screen(question: str, monitor_index: int = -1) -> dict[str, Any]:
    """
    根据当前屏幕截图回答 question。
    """
    q = (question or "").strip()
    if not q:
        return {"error": "question 不能为空：请说明要根据屏幕回答什么。"}

    try:
        from plugins.moondream_vision.capture_infer import grab_screen_png
        from plugins.moondream_vision.config_model import load_config
        from plugins.moondream_vision.local_infer import infer_screen_png
        from plugins.moondream_vision import runtime
    except ImportError as e:
        return {"error": f"Moondream 插件依赖未就绪: {e}"}

    try:
        cfg_path = runtime.plugin_config_path()
    except RuntimeError:
        return {
            "error": "Moondream 尚未完成初始化。请先启动主程序并确保 Moondream 识屏插件已加载。",
        }

    cfg = load_config(cfg_path)
    mi = int(monitor_index)
    if mi >= 0:
        cfg.monitor_index = mi
    cfg.clamp()

    try:
        png = grab_screen_png(cfg.monitor_index)
        text = infer_screen_png(png, q, cfg)
    except Exception as e:
        logger.exception("moondream_query_screen 推理失败")
        return {"error": str(e)}

    return {
        "answer": text,
        "monitor_index": int(cfg.monitor_index),
    }
