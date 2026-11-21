# Shinsekai 统一存储架构与 ConfigManager 重构方案

日期：2026-11-21。本文记录 Shinsekai 存储层重构的架构选型、SOLID 抽象接口定义、目录结构、数据库表结构、模型纯净化规范、资产包导入导出（Import/Export）重构方案、分阶段实施路线，以及面向存量用户的自动迁移与容灾机制。

---

## 1. 现状诊断与核心设计原则

### 1.1 现状五大痛点

1. **大配置文件全量重写与全量 `reload()` 放大开销**
   - `config/config_manager.py` 将 `api.yaml`、`characters.yaml`、`system_config.yaml`、`background.yaml`、`effect.yaml` 捆绑在一个 `AppConfig` 单例下管理。
   - 当前工作区 `data/config/characters.yaml` 已达到 ~271 KB（41 个角色、1,133 张立绘，单角色最高 574 张立绘）。修改单张立绘的台词、口型（`mouth_sync`）或一条关系图谱边，都会触发 PyYAML 对全量角色文件重新序列化落盘。
   - `application/characters/management.py` 等入口在写入后频繁调用 `config_manager.reload()`，每次都会把 5 个 YAML 文件全部重新解析并校验一遍。

2. **缺少稳定主键 `character_id`，跨存储关联脆弱**
   - 角色长期以可变的 `name` 作为关联键散落在不同存储中。角色重命名时，`application/characters/management.py` 需要在保存 `characters.yaml` 后，手动串联修补 `data/knowledge/knowledge.db`（`character_knowledge_bindings`）、`data/config/template_tab_last_launch.json`、`data/config/conversations/*.json`，任何一步失败即出现悬挂关联；`data/reminders.sqlite3` 中的 `character_name` 甚至尚未纳入联动。

3. **`ConfigManager` 职责过载，成为高耦合“上帝单例”**
   - 生产代码中有 38 个文件直接引用 `ConfigManager`。多进程场景（主桥接进程、独立聊天进程、Agent Worker）下各自持有的 `_config` 内存缓存容易陈旧。
   - `config/schema.py`（642 行）把低频全局设置、高频资产目录、环境变量副作用（`apply_network_proxy_environment` / `apply_mirror_environment`）与 UI 运行态（`chat_window_geometry_b64`）混在一起。
   - 存在已不被 React 前端使用、仅剩单测调用的历史方法（如 27 个参数的 `ConfigManager.save_api_config_new`），造成双轨维护。

4. **路径解析与持久化原语各自为政**
   - **路径不统一**：`ConfigManager` 使用硬编码相对路径 `Path("data/config/...")`，`core/knowledge/bindings.py` 使用 `Path.cwd()`，`application/reminders/management.py` 则读取环境变量 `SHINSEKAI_PROJECT_ROOT` / `EASYAI_PROJECT_ROOT`。
   - **写入不统一**：虽然 `sdk/file_io.py` 提供了跨平台原子发布函数 `durable_rename`，但 `config/config_manager.py` 与 `application/chat/conversation_library.py` 各自手写临时文件替换；`config/mcp_config.py` 与 `application/chat/history/session_store.py` 直接覆写目标文件（异常中断有损坏风险）；各 SQLite 模块也重复编写建连、`PRAGMA` 与锁逻辑。

5. **资产包导入/导出与模型双轨重复，加字段易静默丢数据**
   - `config/character_config.py` 维护了一个独立的非 Pydantic 中间类 `CharacterConfig`（24 个构造参数 + `parse_dic`），`tools/file_util.py` 的 `export_character` 又手写了硬编码字典。每新增一个角色字段，必须同步改 `Character`、`CharacterConfig.__init__`、`CharacterConfig.parse_dic` 和 `export_character` 字典至少 3~4 处——**当前已出现静默丢字段 bug**：`Character.portrait_sprite_index`（以及 `display_name`）未同步写入 `CharacterConfig` 与 `export_character`，导致角色包导出再导入后被重置为默认值。
   - `tools/file_util.py:import_character` 绕过 `ConfigManager`，在函数中直接读写硬盘上的 `data/config/characters.yaml`；角色迁入 `shinsekai.db` 后该路径会失效。且导入/导出使用 `Path(f'./temp_export_{os.getpid()}')` / `Path(f'./temp_import_{os.getpid()}')` 落在当前工作目录下，同进程并发导入导出时会发生临时目录冲突。

### 1.2 核心设计原则（务实混合架构，拒绝过度设计）

1. **按数据形态与访问特征分层存储**
   - **声明式全局配置保留 YAML**：`api.yaml`、`system_config.yaml`、`mcp.yaml`、`plugins.yaml` 体积小（1~3 KB）、低频变更，保留纯文本 YAML 以便极端配置错误（如代理/本地服务路径异常导致 UI 无法启动）时人工排障恢复。
   - **高频实体目录与跨实体关联状态迁入主业务 SQLite（`data/shinsekai.db`）**：统一收纳 `characters`、`backgrounds`、`effects`、`conversations`、`character_knowledge_bindings`、`reminders`。
   - **单角色不做多表碎拆，采用「索引列 + 单行 `payload_json`」模式**：实测角色中拥有数百张立绘的属于少数（极端 574 张立绘序列化为 JSON 仅约 45 KB，Python C 扩展 `json` 编解码配合 SQLite 单行读写约 0.2~0.3 ms）。在主表抽取 `id`、`name`、`sprite_prefix` 等关键索引列，主体保持 JSON，既消除跨角色写放大和改名级联难题，又避免新增模型字段时频繁写子表 `ALTER TABLE` 迁移。
   - **重型隔离库物理保持独立，生命周期统一纳管**：单存档会话库 `data/chat_history/<session>/history.db`（随存档文件夹独立导出/删除）与向量记忆库 `data/memory/shinsekai_store.db`（含大量 embedding BLOB 与 FTS5 索引）、`AgentStore` 保留独立数据库文件，但全部实现统一托管契约，由应用根统一管理健康检查与关停。
2. **职责与包依赖分离，但不制造双套重复 Model**
   - 领域 Model 不含任何磁盘 I/O（去除 `pydantic.FilePath` 对磁盘的 `os.stat` 耦合）与环境变量修改副作用，旧版本脏数据迁移下沉到存储边界的 `Codec`；同时不写“Domain Model + ORM Entity + Mapper”两套字段重复的类。

---

## 2. SOLID 存储抽象接口与职责边界

所有存储抽象契约定义在 `sdk/adapters/storage.py`，仅依赖 Python 标准库，零磁盘 I/O 与第三方库依赖，延续 `sdk/adapters/memory.py` 与 `sdk/adapters/session.py` 的 `Protocol` + 不可变值对象风格。

### 2.1 接口定义（`sdk/adapters/storage.py`）

```python
"""Narrow SOLID ports for unified storage management and typed persistence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
K = TypeVar("K", contravariant=True)

BackendKind = Literal["yaml", "json", "sqlite", "memory"]


@dataclass(frozen=True, slots=True)
class BackendStatus:
    """Observability snapshot reported by any managed storage backend."""

    name: str
    kind: BackendKind
    location: str
    healthy: bool = True
    schema_version: int | None = None
    detail: str = ""


@runtime_checkable
class ManagedBackend(Protocol):
    """Minimal lifecycle contract shared by all storage engines and stores."""

    @property
    def name(self) -> str:
        """Unique logical backend identifier (e.g. 'settings.api', 'db.main')."""

    def status(self) -> BackendStatus:
        """Return current health, physical path, and schema version."""

    def close(self) -> None:
        """Release file locks, flush WAL checkpoints, or close DB connections."""


@runtime_checkable
class Migratable(Protocol):
    """Segregated capability for backends requiring schema or data migration."""

    def migrate(self) -> None:
        """Idempotently upgrade storage to the current schema version."""


class Codec(Protocol[T]):
    """Pure in-memory serializer/validator separating format compatibility from models."""

    def decode(self, raw: bytes) -> T: ...
    def encode(self, value: T) -> bytes: ...
    def default(self) -> T: ...


@runtime_checkable
class ReadableDocument(Protocol[T_co]):
    """Read-only whole-document view for AI/runtime consumers."""

    @property
    def revision(self) -> str:
        """Opaque revision token; changes only when persisted content changes."""

    def get(self) -> T_co:
        """Return an immutable value or safe snapshot of the current document."""


@runtime_checkable
class DocumentStore(ReadableDocument[T], Protocol[T]):
    """Mutable whole-document port for settings and UI runtime state."""

    def save(self, value: T) -> str:
        """Validate and atomically persist value; return new revision."""

    def update(self, mutator: Callable[[T], T]) -> T:
        """Atomically load, mutate, validate, and persist under store lock."""


@runtime_checkable
class ReadableCatalog(Protocol[K, T_co]):
    """Read-only keyed entity collection port."""

    @property
    def revision(self) -> str: ...
    def get(self, key: K) -> T_co | None: ...
    def list_all(self) -> tuple[T_co, ...]: ...


@runtime_checkable
class CatalogStore(ReadableCatalog[K, T], Protocol[K, T]):
    """Keyed entity collection supporting single-item atomic writes."""

    def put(self, key: K, item: T) -> str:
        """Insert or replace one entity without rewriting unrelated items."""

    def patch(self, key: K, mutator: Callable[[T], T]) -> T:
        """Atomically update one entity in place; raise KeyError if missing."""

    def delete(self, key: K) -> bool:
        """Delete one entity by key; return True if it existed."""


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction scope across repositories sharing one SQLite engine."""

    def atomic(self) -> AbstractContextManager[None]:
        """Execute all participating repository writes in one atomic transaction."""
```

> **领域窄扩展端口示例**：当领域需要特定查询时，通过组合扩展窄 `Protocol`，不污染通用 `CatalogStore`：
> ```python
> class CharacterCatalogPort(CatalogStore[str, Character], Protocol):
>     def list_summaries(self) -> tuple[CharacterSummary, ...]: ...
>     def get_by_name(self, name: str) -> Character | None: ...
>     def get_by_sprite_prefix(self, prefix: str) -> Character | None: ...
>     def ensure_self_persona(self) -> Character: ...
> ```

### 2.2 职责对照与防过度设计边界

| 组件 / 契约 | 唯一职责 | 刻意**不做**的过度设计边界 |
| :--- | :--- | :--- |
| **`ManagedBackend` / `Migratable`** | 统一纳管全部异构存储后端（YAML、JSON、主 SQLite、独立 SQLite 引擎）的迁移、诊断与关闭 | 不强行统一 YAML 与 SQLite 的读写或查询方法 |
| **`Codec[T]`** | 负责 `bytes <-> Model` 编解码与历史字段兼容清洗 | 不把脏数据迁移和磁盘读写塞进业务 Model |
| **`ReadableDocument` / `DocumentStore`** | 隔离“只读消费者（`ai/*`）”与“写操作（设置保存）”对整块配置的权限 | 不给整块 YAML 配置假造按条件分页/过滤接口 |
| **`ReadableCatalog` / `CatalogStore`** | 按唯一主键存取实体，实现单条原子更新 | 不发明通用 `filter(**kwargs)` Query DSL 或手写 ORM 元类 |
| **`UnitOfWork`** | 为共享同一 `SqliteEngine` 的多个仓储提供跨表原子提交边界 | 不向业务层暴露原生 `sqlite3.Connection` |
| **`StorageHub`** | 仅驻留在启动装配根（`AppStores` / `ApplicationServices`），负责注册、顺序 `migrate_all()`、诊断 `statuses()` 与逆序 `close_all()` | **严禁把 `StorageHub` 当作新全局单例在业务模块中到处 `import`**（否则只是给 `ConfigManager` 换壳） |

### 2.3 核心引擎协作机制

1. **`StorageHub`**（`core/storage/hub.py`）
   - 持有 `StorageLayout`，按顺序注册所有后端实例并校验 `name` 唯一性；
   - 启动期按注册顺序执行所有 `Migratable.migrate()`；
   - 退出期按**注册逆序**调用 `close()`（确保上层 Store 先于共享底层 Engine 关闭），统一接入 `ApplicationServices.close()` 与 `frontend_bridge.py` 关停链路；
   - 现有的 `SqliteHybridStore`（向量记忆库）、`AgentStore`、`ConversationSessionPort` 仅需补齐 `name` 与 `status()` 即可并网纳管。

2. **`FileDocumentStore[T]`**（`core/storage/file_store.py`）
   - 组合 `Codec[T]`、线程 `RLock` 与文件状态 `(mtime_ns, size)` 缓存：文件未变时直接返回不可变快照，外部进程或人工修改后按需懒重读；
   - 写入时序列化 -> 临时文件 `fsync` -> 复用 `sdk/file_io.py` 的 `durable_rename(..., replace=True)` 原子发布。

3. **`SqliteEngine`**（`core/storage/sqlite_engine.py`）
   - 同时实现 `ManagedBackend`、`Migratable`、`UnitOfWork`；
   - 统一配置 `PRAGMA journal_mode=WAL`、`PRAGMA busy_timeout=5000`、`PRAGMA foreign_keys=ON`、`PRAGMA synchronous=NORMAL`（或按配置 `FULL`）；
   - 通过 `contextvars.ContextVar` 跟踪当前协程/线程激活的写连接：外层 `uow.atomic()` 开启 `BEGIN IMMEDIATE`，嵌套调用自动降级为 `SAVEPOINT`；各共享同一引擎的仓储直接读取活跃连接，**仓储方法签名无需透传 `conn` 参数**；
   - 基于 `PRAGMA user_version` 在 `BEGIN IMMEDIATE` 下幂等执行版本化迁移。

---

## 3. 项目代码目录结构

```text
sdk/
  adapters/
    storage.py                  # [新增] 纯 SOLID 存储抽象契约（Protocols + BackendStatus）

core/
  storage/                      # [新增] 统一存储基础设施层
    __init__.py
    layout.py                   # StorageLayout(project_root)：唯一路径解析源，消灭 Path.cwd()
    hub.py                      # StorageHub：后端注册、顺序迁移、健康诊断与逆序 close_all()
    codecs.py                   # PydanticYamlCodec / PydanticJsonCodec + 旧版本字段清洗器
    file_store.py               # FileDocumentStore[T]：RLock + mtime_ns 缓存 + durable_rename 原子写
    sqlite_engine.py            # SqliteEngine：WAL + ContextVar 嵌套事务 + user_version 迁移
    sqlite_catalog.py           # SqliteCatalogStore[T]：通用「主键 + 唯一索引列 + payload_json」实现
    in_memory.py                # InMemoryDocumentStore / InMemoryCatalogStore（单测零磁盘替身）
    migrations/
      __init__.py
      main_db.py                # shinsekai.db DDL 迁移 + 存量 YAML/小库首次自动导入器
    stores/                     # [新增] 基于通用存储原语封装的领域仓储（置于 core 遵循严格分层 DAG）
      __init__.py
      character_store.py        # SqliteCharacterCatalog（实现 CharacterCatalogPort，含自设置顶兜底与 revision 控制）
      media_stores.py           # SqliteBackgroundCatalog / SqliteEffectCatalog
      conversation_store.py     # SqliteConversationStore
      knowledge_binding_store.py # SqliteKnowledgeBindingStore
      reminder_store.py         # UnifiedReminderStore

  packaging/                    # [新增] 统一资产包导入/导出层（替代 tools/file_util.py 与 config/character_config.py）
    __init__.py
    zip_io.py                   # 安全 Zip 解压（防 Zip Slip）、TemporaryDirectory 隔离与并发安全打包
    character_package.py        # 角色包（.char/.cha）Pass-Through 序列化与资源路径重定位
    background_package.py       # 背景包（.bg）Pass-Through 序列化与资源路径重定位
    effect_package.py           # 特效包（.effect）收编自 application/effects/management.py

config/
  models/                       # [新增] 拆分原 642 行 config/schema.py，纯内存 Pydantic 模型（零磁盘 I/O）
    __init__.py
    common.py
    api_settings.py             # ApiConfig 及领域分组模型
    system_settings.py          # SystemConfig（移出窗口坐标与环境变量副作用）
    mcp_settings.py             # McpConfig
    ui_state.py                 # UiRuntimeState（窗口几何 + 模板页上次启动快照）
    character.py                # Character / CharacterSummary / Sprite / ModelSprites / SpriteTransition / RelationGraph
    media_catalog.py            # Background / Effect
    app_config.py
  backend_port.py               # [新增] ConfigBackendPort 纯协议（零 core/application 依赖）
  schema.py                     # [保留兼容] 从 config/models/* 重导出符号，保证现有 import 不断裂
  character_config.py           # [退役/薄兼容] 废弃手写中间类，由 Character / 兼容包装器替代
  config_manager.py             # [薄门面] 优先委托给 ConfigBackendPort（AppStores），保留 YAML 回退兼容

tools/
  file_util.py                  # [薄兼容包装] 原 export/import_character、background 委托至 core/packaging/

application/
  runtime/
    stores.py                   # [新增] AppStores 容器与 build_app_stores(project_root) 装配工厂
    services.py                 # [修改] 挂载 AppStores，在 ApplicationServices.close() 中调用 hub.close_all()
```

---

## 4. 磁盘存储分层与 `data/shinsekai.db` 表结构

### 4.1 `data/` 目录物理结构

```text
data/
  config/                         # [声明式全局配置：低频、人类可读可手改]
    api.yaml                      # LLM / TTS / T2I / Vision / Perception / Memory 参数
    system_config.yaml            # 语言 / 字号 / 主题 / ASR / 代理镜像 / 翻唱流水线配置
    mcp.yaml                      # MCP Server 配置（由直接覆写升级为原子写）
    plugins.yaml                  # 插件启用清单
    legacy_backup/                # [自动生成] 升级迁移完成后旧数据文件的无损时间戳归档目录
      <YYYYMMDD_HHMMSS>/
  state/                          # [高频 UI 运行态：从正式配置剥离]
    ui_state.json                 # 合并原 system_config.chat_window_geometry_b64 + template_tab_last_launch.json
  cache/                          # [可安全清理重建的远端缓存]
    llm_model_capabilities.json   # 从 data/config/ 迁入（~152 KB）
    plugin_registry_downloads.json # 从 data/config/ 迁入
    perception_voice_styles.json
    huggingface/ & perception-gguf/
  shinsekai.db                    # [主业务 SQLite 数据库（WAL 模式）]
  chat_history/<session>/
    history.db                    # [保持独立] 单存档聊天树与快照，便于按目录备份/删除
  memory/
    shinsekai_store.db            # [保持独立，并入 StorageHub] 向量 BLOB + FTS5 混合检索库
  sprite/ speech/ models/ backgrounds/ bgm/ character_templates/ chat_ui_themes/  # 二进制媒体与模板文件保持原位
```

### 4.2 主业务库 `data/shinsekai.db` 表结构（DDL）

```sql
-- 1. 外部存量数据一次性导入标记表（结构演进由 PRAGMA user_version 控制）
CREATE TABLE IF NOT EXISTS storage_migrations (
    name        TEXT PRIMARY KEY,
    applied_at  REAL NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

-- 2. 角色目录表（内置「自设」固定 id = '__self__'）
CREATE TABLE IF NOT EXISTS characters (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sprite_prefix TEXT NOT NULL UNIQUE,
    is_builtin    INTEGER NOT NULL DEFAULT 0,
    pinned        INTEGER NOT NULL DEFAULT 0,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT NOT NULL,
    updated_at    REAL NOT NULL
);

-- 3. 背景组目录表
CREATE TABLE IF NOT EXISTS backgrounds (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sprite_prefix TEXT NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT NOT NULL,
    updated_at    REAL NOT NULL
);

-- 4. 特效方案目录表
CREATE TABLE IF NOT EXISTS effects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT NOT NULL,
    updated_at    REAL NOT NULL
);

-- 5. 命名会话索引表（替代 data/config/conversations/*.json）
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    history_path  TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    updated_at    REAL NOT NULL
);

-- 6. 角色-知识库绑定表（替代 data/knowledge/knowledge.db，绑定稳定 character_id）
CREATE TABLE IF NOT EXISTS character_knowledge_bindings (
    character_id  TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    knowledge_id  TEXT NOT NULL,
    created_at    REAL NOT NULL,
    PRIMARY KEY (character_id, knowledge_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_knowledge_id
    ON character_knowledge_bindings(knowledge_id);

-- 7. 角色提醒表（替代 data/reminders.sqlite3；character_id 为角色稳定 ID 或全局 '*'）
CREATE TABLE IF NOT EXISTS reminders (
    id             TEXT PRIMARY KEY,
    character_id   TEXT NOT NULL,
    title          TEXT NOT NULL,
    message        TEXT NOT NULL,
    due_at         REAL NOT NULL,
    recurrence     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    claim_token    TEXT,
    claim_until    REAL NOT NULL DEFAULT 0,
    delivery_count INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_status_due
    ON reminders(status, due_at);

CREATE TABLE IF NOT EXISTS reminder_heartbeat (
    id      INTEGER PRIMARY KEY,
    seen_at REAL
);
```

---

## 5. 各个 Model 明细与纯净化规范

### 5.1 统一纯净化准则

1. **禁止磁盘 I/O 与环境副作用**：Model 层不 `import yaml`、`sqlite3` 或 `core.storage`，不在模型校验器中检查文件是否存在，也不隐式修改 `os.environ`。
2. **默认不可变（`ConfigDict(frozen=True)`）**：消除外部通过引用就地修改内存字段后落盘失败导致的脏内存状态；所有变更通过 `model_copy(update=...)` 配合 `DocumentStore.update` / `CatalogStore.patch` 完成。
3. **单一模型复用**：不拆分重复的 `Domain Model` 与 `Storage Entity` 类，仅在列表场景需要剪裁大 JSON 时定义只读投影（如 `CharacterSummary`）。
4. **旧格式兼容逻辑移交 `Codec`**：原 `schema.py` 中的 `DefaultIfNone` 脏字段修复、历史版本号转换等统一收口到各 `Codec.decode()` 前置清洗管线。

### 5.2 Model 清单

| Model | 所在模块 | 核心字段与改造要点 | 对应存储端口与物理位置 |
| :--- | :--- | :--- | :--- |
| **`ApiConfig`** | `config/models/api_settings.py` | 保持与 `api.yaml` 现有键名 100% 兼容；保留纯业务校验（如 `compact_target_ratio` 上限钳位）；将 `vision_config_version` 与 `GGUF_MODEL_ID` 历史迁移钩子移入 `ApiConfigCodec` | `DocumentStore[ApiConfig]`<br>`data/config/api.yaml` |
| **`SystemConfig`** | `config/models/system_settings.py` | 保留界面语言、字号、主题、ASR、代理镜像、`music_cover_*` 参数；移出 `chat_window_geometry_b64`；环境变量写入（`apply_network_proxy_environment` / `apply_mirror_environment`）移交应用启动与设置保存 UseCase 显式执行 | `DocumentStore[SystemConfig]`<br>`data/config/system_config.yaml` |
| **`McpConfig`** | `config/models/mcp_settings.py` | 将原 `config/mcp_config.py` 中的裸字典结构化为 `McpConfig(enabled, default_call_timeout, servers)` | `DocumentStore[McpConfig]`<br>`data/config/mcp.yaml` |
| **`UiRuntimeState`** | `config/models/ui_state.py` | 承载 `chat_window_geometry_b64: str` 与 `template_last_launch: dict[str, Any]`，与正式配置文件解耦 | `DocumentStore[UiRuntimeState]`<br>`data/state/ui_state.json` |
| **`Character`**<br>**`CharacterSummary`** | `config/models/character.py` | 1. 新增稳定主键 `id: str`（自设固定 `"__self__"`，常规角色为 UUID hex）；<br>2. **`Sprite.path` 与 `Sprite.voice_path` 由 `pydantic.FilePath` 改为纯 `str`**，彻底消灭 `List[Union[Sprite, dict]]`；文件存在性校验下放至上传/保存 UseCase；<br>3. 子值对象包含 `Sprite`、`ModelSprites`、`SpriteTransition`、`PortraitCrop`、`RelationGraph`；<br>4. 仅当非 `relation_graph` 静态字段变化时才更新静态资源 `revision`；<br>5. `CharacterSummary` 只暴露列表摘要字段，免除侧边栏列表对大段设定与立绘 JSON 的解析 | `CharacterCatalogPort`<br>`data/shinsekai.db` -> `characters` |
| **`Background`** | `config/models/media_catalog.py` | 新增稳定主键 `id: str`；`sprites` 同样统一为纯 `Sprite` 序列而非 `Union[Sprite, dict]` | `BackgroundCatalogPort`<br>`data/shinsekai.db` -> `backgrounds` |
| **`Effect`** | `config/models/media_catalog.py` | 新增稳定主键 `id: str`；保留音频、图片及绑定音频列表结构 | `EffectCatalogPort`<br>`data/shinsekai.db` -> `effects` |
| **`ConversationRecord`** | `application/chat/conversation_library.py` | 封装 `id`、`history_path`、`title`、`created_at`、`launch`，保持 HTTP 响应格式向后兼容 | `CatalogStore[str, ConversationRecord]`<br>`data/shinsekai.db` -> `conversations` |

---

## 6. 资产包导入与导出重构方案（Pass-Through + 路径重定位，加字段零改动）

为彻底消除“每次给 `Character` / `Background` / `Effect` 新增字段都要重写 `CharacterConfig` 和导入导出字典”的维护负担，在 `core/packaging/` 下引入统一的 **「全字段透传（Pass-Through）+ 专职路径重定位器（Asset Relocator）」** 架构。

### 6.1 核心机制

1. **退役 `CharacterConfig` 中间类，全链路直用 Pydantic Model**
   - 取消 `config/character_config.py` 中的 `CharacterConfig` 手写参数转发层；导入导出直接以领域 Model（`Character`、`Background`、`Effect`）为唯一数据契约。
2. **导出（Export）：`model_dump` 自动透传 + 局部路径改写**
   - 直接通过 `entity.model_dump(mode="json", exclude={"id", "is_builtin", "pinned", "undeletable"})` 生成导出载荷：所有标量字段、文本字段与纯嵌套值对象（如 `portrait_sprite_index`、`portrait_crop`、`sprite_groups`、`pronunciation_map`、`relation_graph` 及未来新增的任意配置字段）**全部自动导出，无需修改打包代码**。
   - **专职路径重定位器**只介入显式声明的资源路径字段，负责安全校验（`safe_existing_file_path`）、收集依赖文件入包并重写为包内相对路径：
     - **角色包（`.char` / `.cha`）**：`sprites[*].path`、`sprites[*].voice_path`、`sprites[*].mouth_sync`、`sprite_transitions[*]`、`avatars[*]`（模型与状态依赖）、`gpt_model_path` / `sovits_model_path` / `refer_audio_path`；
     - **背景包（`.bg`）**：`sprites[*].path`、`bgm_list[*]`；
     - **特效包（`.effect`）**：`audio_list[*]`、`image_list[*]`、`image_audio_list[*]`。
   - 包内继续输出与现有规范 100% 兼容的 `character.yaml` / `background.yaml` / `effect.yaml`（+ `manifest.json`），历史导出包无需转换即可直接导入。
3. **导入（Import）：安全临时目录 + 冲突消解 + `Codec.decode()` 直接重建**
   - 使用 `tempfile.TemporaryDirectory()` 替代基于 `os.getpid()` 的当前目录临时文件夹，彻底消除并发导入导出冲突与残留。
   - 先在临时目录完成安全解压（防 Zip Slip 路径穿越）及资产完整性校验（口型 manifest、过渡视频帧数、Avatar 模型依赖索引校验）。
   - 通过注入的 `CatalogStore`（`CharacterCatalogPort` / `BackgroundCatalogPort` / `EffectCatalogPort`）检查并自动消解 `name` 与 `sprite_prefix` 冲突，生成全新本地稳定主键 `id`（UUID）。
   - 将包内相对路径拷贝至 `StorageLayout` 管理的本地资源目录并回填路径，剔除保留标志（`is_builtin` / `pinned` / `undeletable`）后，**将整份字典直接交由对应 `Codec.decode()` 反序列化为领域 Model**：
     - 未来新增普通字段由导入流程原样透传保存；
     - 若用户拿新版导出的包导入旧版软件，Pydantic 默认忽略未知扩展字段（或保留已知兼容结构），实现前向兼容不崩溃。

### 6.2 职责解耦与写入回滚

- **归档层不碰数据库（SRP / DIP）**：`core/packaging/` 只负责 `Archive (.char/.bg/.effect) <-> (Staged Entity, Copied Media Dir)`，不直接读写 YAML 或连接 `shinsekai.db`。
- **事务化入库与失败清理**：导入持久化统一由应用层 UseCase（如 `CharacterUseCase._import_packages`）通过 `CatalogStore.put()` 在 SQLite 事务内完成写入；若数据库写入失败，UseCase 负责清理本次新拷贝的资源目录，保证文件系统与数据库状态一致。

### 6.3 防漏字段契约测试（Round-Trip Contract Test）

- 在单元测试中为 `Character`、`Background`、`Effect` 建立自动往返契约测试：动态校验（或显式填充）模型上除系统保留位外的**每一个字段均为非默认值**，执行 `export -> import -> 对比还原模型`。
- 以后无论谁在 `config/models/` 中新增任何字段：
  - 若是普通数据字段，自动通过透传且测试立即绿灯；
  - 若是携带外部文件的新资源字段，必须在路径重定位器中显式声明处理策略，否则往返测试会立刻报错提醒，彻底杜绝静默丢字段回归。

---

## 7. 分阶段重构路线

为保证全仓 38 处 `ConfigManager` 引用和既有测试平稳过渡，采用 4 阶段渐进落地，每个阶段独立合入且单测全绿：

### 阶段 1：落地 SOLID 接口与 `core/storage/` 基础设施
- 新增 `sdk/adapters/storage.py` 及 `core/storage/{layout,hub,codecs,file_store,sqlite_engine,sqlite_catalog,in_memory}.py`。
- 补充针对原子覆盖写、崩溃恢复、`mtime_ns` 增量重载、`ContextVar` 嵌套事务及 `user_version` 迁移的完备单元测试。
- 本阶段不改动任何现有业务模块，零回归风险。

### 阶段 2：拆解纯 Model，收口配置文件与状态缓存层
- 拆分 `config/models/*`，保留 `config/schema.py` 重导出以保持既有导入路径兼容；移除 `Sprite` 的 `FilePath` 磁盘检查。
- 将 `api.yaml`、`system_config.yaml`、`mcp.yaml`、`ui_state.json` 接入 `FileDocumentStore`；将缓存文件从 `data/config/` 迁入 `data/cache/`。
- 清理 `ConfigManager.save_api_config_new` 等废弃接口及对应冗余单测。

### 阶段 3：启用 `shinsekai.db`、自动迁移、重构导入导出与 `ConfigManager` 门面化
- 实现 `CharacterCatalogPort`、`BackgroundCatalogPort`、`EffectCatalogPort`、SQLite 版 `Conversation` / `KnowledgeBindings` / `ReminderStore` 及启动自动迁移器 `core/storage/migrations/main_db.py`。
- 落地 `core/packaging/`（替代 `CharacterConfig` 与 `tools/file_util.py` 对 `characters.yaml` 的直写），接入 `CatalogStore.put()` 并补充 `Character` / `Background` / `Effect` 全字段 `export -> import` 往返契约测试。
- 将 `config/config_manager.py` 缩减为委托给 `AppStores` 的薄兼容门面（Facade），外部调用方无感平滑切换。
- 改造 `application/characters/management.py` 等 UseCase：角色重命名简化为单行 `name` 更新，删除跨 4 套存储手打级联补丁代码，删除写入后的全量 `config_manager.reload()`。

### 阶段 4：全生命周期并网与调用方去单例化
- 为 `SqliteHybridStore` 与 `AgentStore` 补齐 `ManagedBackend` 适配并注册进 `StorageHub`，统一接入 `ApplicationServices.close()` 与 `frontend_bridge.py` 退出关停流程。
- 逐步将业务 UseCase 与 AI 工具（`ai/tools/character_tools.py` 等）改为直接通过构造参数注入所需窄 Port（`ReadableDocument` / `CharacterCatalogPort`），最终仅在兼容层保留旧门面。

---

## 8. 更新后的数据自动迁移与容灾机制

### 8.1 更新链路全覆盖（无需用户或外部脚本干预）

Shinsekai 存在三种更新路径，均不会执行外部安装期数据脚本：
1. **应用内在线更新**：`core/app_update/github_bundle.py` 中的 `overwrite_merge_app_tree` 显式跳过本机 `plugins/` 与 `data/` 目录，重启后加载新代码；
2. **安装包覆盖升级**：`main.py` 在打包态指向用户原有的 `SHINSEKAI_PROJECT_ROOT/data`；
3. **源码 `git pull` 更新**：本地工作区 `data/` 目录原样保留。

因此，所有数据升级统一在**进程启动阶段由 `StorageHub.migrate_all()` 自动执行**，用户无感知完成升级。

### 8.2 存量用户首次升级的 5 步原子迁移协议

当新版软件首次在包含旧版 YAML / 散落 SQLite 的 `data/` 目录启动时，`main_db.py` 按以下容灾协议运行：

1. **跨进程文件锁保护**
   - 迁移前先获取 `data/.storage_migration.lock` 文件排他锁，防止桌面主进程、HTTP Bridge 与子进程并发启动时重复触发迁移。
2. **幂等标记检查（`storage_migrations`）**
   - 检查 `v1_import_yaml_catalogs`、`v1_import_knowledge_bindings`、`v1_import_reminders`、`v1_relocate_state_and_cache` 等迁移键是否已记录。
   - **已完成的迁移在后续启动时直接跳过（耗时 < 1 ms）**；即使日后用户在界面中主动清空了角色或提醒，也不会从历史备份重新导入（与 `application/reminders/migration.py` 的迁移防重放原则一致）。
3. **稳定 `character_id` 生成与跨库关系缝合**
   - 读取旧 `data/config/characters.yaml`：为「自设」固定分配 `"__self__"`，为其余角色生成稳定 `character_id`（基于规范化角色名确定性生成 UUID 或新 UUID），在内存中构建 `name_lower -> character_id` 映射表。
   - 紧接着读取旧 `data/knowledge/knowledge.db`、`data/reminders.sqlite3`、`data/config/conversations/*.json`，将原存储的 `character_name` 自动解析转换为对应的 `character_id`（若遇到指向已删除角色的孤儿提醒记录，安全保留原名称/标记而不中断迁移）。
   - 同时提取旧 `system_config.yaml` 的 `chat_window_geometry_b64` 与 `template_tab_last_launch.json` 合并写入 `data/state/ui_state.json`，并将缓存文件移入 `data/cache/`。
4. **单事务原子提交（All-or-Nothing）**
   - 所有目录表、关联表写入以及 `storage_migrations` 完成记录在**同一个 `BEGIN IMMEDIATE` SQLite 事务**内提交。
   - 若迁移中途发生断电、磁盘满或强杀进程，SQLite 自动回滚至空状态，所有旧 YAML 与原 SQLite 文件毫发无损，下次重启自动重试。
5. **旧文件无损备份归档（严禁直接删除）**
   - 事务提交确认成功后，将已迁出的旧源文件（`characters.yaml`、`background.yaml`、`effect.yaml`、旧 `knowledge.db`、旧 `reminders.sqlite3`、旧 `conversations/`）统一移动到 `data/config/legacy_backup/<YYYYMMDD_HHMMSS>/` 并附带 `README.txt` 说明。
   - 既彻底消除双数据源并存引起的状态漂移，又保证用户在极端情况下回退旧版本时拥有 100% 完整备份。

### 8.3 后续版本持续迭代时的自动演进规则

新存储架构就位后，后续日常版本发布的数据兼容分为三类自动处理：

- **新增配置项或实体属性（最常见）**：直接在 `config/models/` 对应模型增加带默认值的字段，**无需编写迁移代码**；旧数据读取时由 Pydantic 自动补全默认值，下次保存自动写回新字段。
- **字段重命名或值域调整**：在对应 `Codec.decode()` 的预处理函数中做纯内存字典映射，读取旧配置或旧 `payload_json` 时实时升级。
- **SQLite 索引列扩展或新增表**：在 `core/storage/migrations/main_db.py` 的 `MIGRATIONS` 序列中追加 `Migration(version=N, up=...)`，下次启动由 `SqliteEngine.migrate()` 比对 `PRAGMA user_version` 自动按序执行升级。
