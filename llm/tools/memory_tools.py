"""
与当前用户相关的长期记忆。

- **Python 3.10+**。未安装 ``brainctl`` 时使用项目内 ``data/memory/llm_memory.sqlite`` 的轻量实现；
  已安装则优先使用 ``brainctl`` 提供的 :mod:`agentmemory`（``Brain``）。
- 可选：``pip install brainctl``（PyPI 上该包 classifiers 多为 3.11+；3.10 环境可继续用内置库或自行尝试安装）。
- 默认 ``agent_id`` 为 ``easyaidesktop-user``，可通过 ``EASYAI_BRAIN_AGENT_ID`` 或 ``BRAINCTL_AGENT_ID`` 覆盖。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from sdk.tool_registry import tool

logger = logging.getLogger(__name__)

_BrainCls: Any = None


def _try_import_brain() -> Any:
    global _BrainCls
    if _BrainCls is not None:
        return _BrainCls
    try:
        from agentmemory import Brain as _B  # type: ignore[import-not-found]

        _BrainCls = _B
    except ImportError:
        _BrainCls = False  # type: ignore[assignment]
    return _BrainCls


def _memory_db_path() -> Path:
    er = os.environ.get("EASYAI_PROJECT_ROOT")
    base = Path(er).resolve() if er else Path.cwd()
    d = base / "data" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "llm_memory.sqlite"


def _default_agent_id() -> str:
    return (
        (os.environ.get("EASYAI_BRAIN_AGENT_ID") or os.environ.get("BRAINCTL_AGENT_ID") or "")
        .strip()
        or "easyaidesktop-user"
    )


def _serialize_hit(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        try:
            return dict(item.model_dump())
        except Exception:
            pass
    if hasattr(item, "__dict__"):
        d = {
            k: v
            for k, v in vars(item).items()
            if not str(k).startswith("_")
        }
        return {k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v)) for k, v in d.items()}
    return {"value": str(item)}


class _SqliteMemoryBackend:
    """无 brainctl 时的降级存储，API 形状与 ``Brain`` 调用侧兼容。"""

    __slots__ = ("_agent_id", "_conn")

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        path = _memory_db_path()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id)"
        )
        self._conn.commit()

    def search(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        lq = q.lower()
        cur = self._conn.execute(
            """
            SELECT id, content, category, created_at
            FROM memories
            WHERE agent_id = ?
              AND (instr(lower(content), ?) > 0 OR instr(lower(category), ?) > 0)
            ORDER BY id DESC
            LIMIT ?
            """,
            (self._agent_id, lq, lq, max(1, min(int(limit), 200))),
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "content": r[1], "category": r[2], "created_at": r[3]}
            for r in rows
        ]

    def remember(
        self, content: str, category: str = "user", force: bool = False
    ) -> dict[str, Any]:
        _ = force  # 降级库不做去重门控
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO memories (agent_id, content, category, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (self._agent_id, content, category, now),
        )
        self._conn.commit()
        rid = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        return {"id": rid, "content": content, "category": category, "created_at": now}

    def forget(self, memory_id: str | int) -> None:
        mid = int(memory_id) if not isinstance(memory_id, int) else memory_id
        self._conn.execute(
            "DELETE FROM memories WHERE id = ? AND agent_id = ?",
            (mid, self._agent_id),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.debug("SqliteMemoryBackend.close 失败", exc_info=True)


class BrainMemoryTools:
    """
    长期记忆进程内单例：优先 ``agentmemory.Brain``，否则 :class:`_SqliteMemoryBackend`。
    所有调用在同一把 :class:`~threading.RLock` 内序列化。
    """

    _backend: Any | None = None
    _agent_id_bound: str | None = None
    _lock = threading.RLock()

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._close_backend_unlocked()
            cls._agent_id_bound = None

    @classmethod
    def _close_backend_unlocked(cls) -> None:
        if cls._backend is None:
            return
        if hasattr(cls._backend, "close"):
            try:
                cls._backend.close()
            except Exception:
                logger.debug("memory backend close 失败", exc_info=True)
        cls._backend = None

    @classmethod
    def _ensure_backend(cls) -> Any:
        aid = _default_agent_id()
        B = _try_import_brain()
        with cls._lock:
            if cls._backend is not None and cls._agent_id_bound == aid:
                return cls._backend
            cls._close_backend_unlocked()
            if B:
                cls._backend = B(agent_id=aid)
                logger.debug("长期记忆后端: agentmemory.Brain")
            else:
                try:
                    cls._backend = _SqliteMemoryBackend(aid)
                except OSError as e:
                    raise RuntimeError(
                        f"长期记忆无法初始化内置库（需可写 data/memory）：{e}"
                    ) from e
                logger.info(
                    "长期记忆使用内置 SQLite（未安装 brainctl）。"
                    "可选：pip install brainctl（多为 Python 3.11+）以增强能力。"
                )
            cls._agent_id_bound = aid
            return cls._backend

    @classmethod
    def agent_id(cls) -> str:
        return _default_agent_id()

    @classmethod
    def search(cls, query: str, *, limit: int = 15) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"error": "query 不能为空：请说明要检索的记忆关键词或问题。"}
        lim = max(1, min(int(limit), 50))
        try:
            with cls._lock:
                brain = cls._ensure_backend()
                try:
                    raw = brain.search(q, limit=lim)
                except TypeError:
                    raw = brain.search(q)
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("memory_search 调用失败")
            return {"error": str(e)}

        if isinstance(brain, _SqliteMemoryBackend):
            hits = raw if isinstance(raw, list) else list(raw or [])
        elif raw is None:
            hits = []
        elif isinstance(raw, (list, tuple)):
            hits = list(raw)
        else:
            hits = [raw]
        hits = hits[:lim]
        return {
            "agent_id": cls.agent_id(),
            "query": q,
            "count": len(hits),
            "memories": [_serialize_hit(h) for h in hits],
        }

    @classmethod
    def remember(
        cls,
        content: str,
        *,
        category: str = "user",
        force: bool = False,
    ) -> dict[str, Any]:
        text = (content or "").strip()
        if not text:
            return {"error": "content 不能为空：请写出要保存的、与用户相关的事实或偏好。"}
        cat = (category or "user").strip() or "user"
        try:
            with cls._lock:
                brain = cls._ensure_backend()
                ret: Any
                if isinstance(brain, _SqliteMemoryBackend):
                    ret = brain.remember(text, cat, force=bool(force))
                else:
                    try:
                        ret = brain.remember(text, category=cat, force=bool(force))
                    except TypeError:
                        try:
                            ret = brain.remember(text, category=cat)
                        except TypeError:
                            ret = brain.remember(text, cat)
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("memory_remember 调用失败")
            return {"error": str(e)}

        out: dict[str, Any] = {"ok": True, "agent_id": cls.agent_id(), "category": cat}
        if ret is not None:
            out["result"] = _serialize_hit(ret) if not isinstance(ret, (str, int, float, bool)) else ret
        return out

    @classmethod
    def forget(cls, memory_id: str) -> dict[str, Any]:
        mid = (memory_id or "").strip()
        if not mid:
            return {"error": "memory_id 不能为空：请先通过 memory_search 获取 id。"}
        try:
            with cls._lock:
                brain = cls._ensure_backend()
                if isinstance(brain, _SqliteMemoryBackend):
                    brain.forget(mid)
                else:
                    try:
                        brain.forget(mid)
                    except (TypeError, ValueError):
                        brain.forget(int(mid))
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("memory_forget 调用失败")
            return {"error": str(e)}
        return {"ok": True, "agent_id": cls.agent_id(), "memory_id": mid}


@tool(
    name="memory_search",
    description=(
        "从长期记忆库中按关键词检索与用户相关的重要记忆（偏好、事实、约定等）。"
        "在回答需要跨会话个人上下文的问题前应优先调用。"
        "参数 query：检索语句；limit：最多返回条数（默认 15，最大 50）。"
    ),
)
def memory_search(query: str, limit: int = 15) -> dict[str, Any]:
    return BrainMemoryTools.search(query, limit=limit)


@tool(
    name="memory_remember",
    description=(
        "将一条与用户相关的重要信息写入长期记忆（已装 brainctl 用其库，否则用内置 SQLite）。"
        "content：要保存的简短事实或偏好；category 建议 user、preference、identity、convention 等；"
        "force=true 在 brainctl 下可绕过写入门控，内置库中无去重逻辑该参数可忽略。"
    ),
)
def memory_remember(content: str, category: str = "user", force: bool = False) -> dict[str, Any]:
    return BrainMemoryTools.remember(content, category=category, force=force)


@tool(
    name="memory_forget",
    description=(
        "删除一条长期记忆。memory_id 须来自 memory_search 返回的 id。"
        "brainctl 下多为软删除，内置 SQLite 为硬删除。"
    ),
)
def memory_forget(memory_id: str) -> dict[str, Any]:
    return BrainMemoryTools.forget(memory_id)
