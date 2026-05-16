"""
工具执行管理 — 统一管理超时、冷却期（loading）、风险确认。
在 ToolManager（注册 / 查找）之上加一层执行策略，llm_manager 不直接调 ToolManager.execute()。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeoutError
from typing import Callable

from sdk.tool_registry import ToolNotReady
from llm.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

# 各工具组的冷却时长（秒）
GROUP_COOLDOWN_SECONDS: dict[str, float] = {
    "memory": 300.0,   # mem0 embedding 模型下载 / 加载，首次 2-5 分钟
    "vision": 600.0,   # Moondream 模型下载 / 加载，首次 2-10 分钟
}


class ToolExecutor:
    """在 ToolManager 之上管理超时、冷却与风险确认。

    用法::

        executor = ToolExecutor(tool_manager, default_timeout=120.0)
        result = executor.execute(
            "memory_search",
            '{"query":"foo"}',
            risk_confirm=my_confirm_fn,
        )
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        *,
        default_timeout: float = 120.0,
        cooldown_map: dict[str, float] | None = None,
    ) -> None:
        self._tm = tool_manager
        self._default_timeout = default_timeout
        self._cooldown_map: dict[str, float] = dict(cooldown_map or GROUP_COOLDOWN_SECONDS)
        self._cooldowns: dict[str, float] = {}  # group_name → cooldown_until timestamp
        self._pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="tool-exec"
        )

    # ── public API ──────────────────────────────────────────────────────

    def execute(
        self,
        name: str,
        arguments_json: str,
        *,
        risk_confirm: Callable[[str, str, str], bool] | None = None,
    ) -> str:
        """执行一个工具，带超时、冷却与风险控制。

        Returns:
            JSON 字符串 —— 正常结果或 ``{"error": ...}`` / ``{"status":"loading",...}``
        """
        group = self._tm.get_tool_group(name)

        # 1. 冷却期：仍做探活执行（模型可能已加载完），但缩短超时
        in_cooldown = self._is_in_cooldown(group)
        timeout = 5.0 if in_cooldown else self._default_timeout

        # 2. 风险确认
        risk = self._tm.get_tool_risk(name)
        if risk != "low" and risk_confirm is not None:
            if not risk_confirm(name, risk, arguments_json):
                return json.dumps(
                    {"cancelled": True, "reason": f"User denied {name}"},
                    ensure_ascii=False,
                )

        # 3. 带超时执行
        try:
            fut = self._pool.submit(self._tm.execute, name, arguments_json)
            result = fut.result(timeout=timeout)
        except ToolNotReady as e:
            secs = self._cooldown_map.get(group, self._default_timeout)
            self._cooldowns[group] = time.time() + secs
            logger.info(
                "Tool '%s' (group=%s) not ready, cooldown %.0fs: %s",
                name, group, secs, e.message,
            )
            return json.dumps(
                {"status": "loading", "message": e.message},
                ensure_ascii=False,
            )
        except FutTimeoutError:
            if in_cooldown:
                # 冷却期探活超时 → 返回冷却消息
                return self._cooldown_message(group)
            logger.warning("Tool '%s' timed out after %.0fs", name, timeout)
            result = json.dumps(
                {"error": f"Tool '{name}' timed out after {timeout:.0f}s"},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("Tool '%s' unexpected error", name)
            result = json.dumps(
                {"error": f"Tool '{name}' failed: {e}"},
                ensure_ascii=False,
            )

        # 4. 工具执行成功 → 清除该组冷却（若存在）
        if in_cooldown:
            self._cooldowns.pop(group, None)
            logger.info("Tool '%s' succeeded, cleared cooldown for group '%s'", name, group)

        # 5. 若返回 loading → 设置冷却（兼容未迁移到 ToolNotReady 的旧工具）
        self._maybe_set_cooldown(group, result)

        return result

    def set_group_cooldown(self, group: str, seconds: float) -> None:
        """手动为一个工具组设置冷却时长。"""
        self._cooldown_map[group] = float(seconds)

    def clear_cooldown(self, group: str | None = None) -> None:
        """清除冷却（``group`` 为 None 时清除全部）。"""
        if group is None:
            self._cooldowns.clear()
        else:
            self._cooldowns.pop(group, None)

    def is_in_cooldown(self, group: str) -> bool:
        return self._check_cooldown(group) is not None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)

    # ── internal ────────────────────────────────────────────────────────

    def _is_in_cooldown(self, group: str) -> bool:
        """检查时间戳是否仍在冷却期内（不生成消息）。"""
        until = self._cooldowns.get(group, 0.0)
        return until > time.time()

    def _cooldown_message(self, group: str) -> str:
        """生成冷却期提示消息 JSON。"""
        until = self._cooldowns.get(group, 0.0)
        remaining = max(0, int(until - time.time()))
        return json.dumps(
            {
                "status": "loading",
                "message": (
                    f"该工具组仍在冷却中（剩余约 {remaining} 秒），"
                    "请直接告诉用户稍等，不要重复调用。"
                ),
            },
            ensure_ascii=False,
        )

    def _check_cooldown(self, group: str) -> str | None:
        """若该组处于冷却期则返回冷却消息；否则返回 None。"""
        if not self._is_in_cooldown(group):
            return None
        return self._cooldown_message(group)

    def _maybe_set_cooldown(self, group: str, result: str) -> None:
        if _result_is_loading(result):
            secs = self._cooldown_map.get(group, self._default_timeout)
            self._cooldowns[group] = time.time() + secs
            logger.info(
                "Tool group '%s' entered cooldown for %.0fs", group, secs
            )


def _result_is_loading(result: str) -> bool:
    """检测工具结果是否为 loading 状态。"""
    if not result:
        return False
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, dict) and parsed.get("status") == "loading"
