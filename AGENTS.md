# AGENTS.md — Shinsekai 开发与架构约束

> 面向所有在本仓库工作的 AI Agent 与开发者。修改任何代码前，请先阅读本文件并严格遵守以下红线；完整设计细节分别见 [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md)、[`docs/STORAGE_ARCHITECTURE_PLAN_zh-CN.md`](docs/STORAGE_ARCHITECTURE_PLAN_zh-CN.md) 与 [`docs/PROMPT_AND_I18N_ARCHITECTURE_PLAN_zh-CN.md`](docs/PROMPT_AND_I18N_ARCHITECTURE_PLAN_zh-CN.md)。

---

## 0. 核心铁律（TL;DR）

1. **禁止乱改架构**：严禁打破分层依赖方向，严禁向架构测试 allowlist 新增例外，严禁重建已退役顶层目录（`llm/`、`asr/`、`tts/`、`t2i/`、`ui/`）。
2. **禁止直接文件 I/O**：配置、目录实体、会话与持久化状态必须走 `sdk/adapters/storage.py` + `core/storage/`（`StorageLayout` / `FileDocumentStore` / `SqliteEngine` / `core/storage/stores/`）或 `core/packaging/`，禁止业务代码直接读写 `data/` 文件或硬编码 `Path.cwd()`。
3. **禁止在 `.py` 中写大段 Prompts**：所有内置提示词必须放到 `ai/llm/template/catalog/{zh_CN,en,ja}/*.yaml`，并用 `Section` / `I18nSection` / `PromptSpec` 组装；禁止在模块导入期调用 `.render()`。
4. **禁止未经 i18n 的 Message**：前端 UI、表单 Schema、任务状态、Bridge 异常与任务消息必须走三语字典或结构化 `errorCode`/`AppError`；禁止新增硬编码中文/日文字符串。
5. **单文件必须 `<= 500` 行**：`.py`、`.ts`、`.tsx`、`.rs`、`.css` 源码文件不得超过 500 行；接近或超过时按职责拆分，禁止无意义拆分或堆积 `utils.py`/`helpers.py`。
6. **必须过测试与格式检查**：提交与提 PR 前必须通过 `pytest`、前端 `pnpm format:check`、`pnpm lint:types`、`pnpm test`（及变更涉及时的覆盖率门禁与 Rust 检查）；提 PR 时必须在描述中说明需手动测试的部分。

---

## 1. 严格遵守分层架构与依赖边界

### 1.1 固定依赖方向（DAG）

```text
frontend / CLI
       |
       v
frontend_bridge_core
       |
       v
  application
       |
       +------> ai
       +------> plugin_system
       +------> core
       +------> config
                    |
                    v
                   sdk
```

### 1.2 各层职责与禁止导入约束

以下边界由 `test/unit/architecture/`（`test_import_boundaries.py`、`test_bridge_resource_boundaries.py`、`test_chat_runtime_boundaries.py`、`test_llm_boundaries.py`）和 `frontend/src/test/architecture/characterVisualBoundaries.test.ts` 通过 AST 自动强制检查：

| 目录 / 层级             | 核心职责                                                                                   | 允许依赖                                            | 严格禁止                                                                                                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdk/`                  | 插件与跨层稳定公共契约（Protocol、异常、路径/IO 原语、语言代码）                           | 标准库、基础三方库、`sdk/`                          | 导入 `ai`、`application`、`config`、`core`、`frontend_bridge_core`、`plugin_system`、`ui` 或任何旧顶层包                                                                                                        |
| `config/`               | 配置纯内存 Pydantic 模型（`config/models/`）、`ConfigBackendPort`、`ConfigManager` 门面    | 标准库、Pydantic、`sdk/`                            | 导入 `ai`、`application`、`core`、`frontend_bridge_core`、`plugin_system`、`ui`（含动态 `importlib` 绕过）                                                                                                      |
| `core/`                 | 可复用宿主基础能力（Host Capability：输入输出明确、无应用会话状态）                        | 标准库、三方库、`config/`、`sdk/`                   | 导入 `application`、`ai`、`frontend_bridge_core`、`ui`；禁止引用 `AppRuntime`、`BridgeState`、`get_app_runtime`、`llm_manager`、`ui_worker` 等应用对象；`core/story/` 必须保持确定性且无资源/文件 I/O           |
| `ai/`                   | AI 能力域（`llm`、`memory`、`knowledge`、`tts`、`asr`、`t2i`、`vision`、`story`、`tools`） | `core/`、`config/`、`sdk/`                          | 导入 `application`、`frontend_bridge_core`、`ui`；`ai/tools/` 只做薄包装；`ai/llm/{llm_manager,chat_loop,request_runner,tool_session,conversation_history}.py` 不得耦合具体 Provider Adapter 或 `ConfigManager` |
| `plugin_system/`        | 宿主插件平台（加载、安装、更新、发布、依赖、贡献解析）                                     | `core/`、`config/`、`sdk/`                          | 导入 `ai`、`application`、`frontend_bridge_core`、`ui`；宿主源码不得迁入用户插件目录 `plugins/`                                                                                                                 |
| `application/`          | 跨领域用例编排（Use Case）与进程/会话生命周期、依赖装配根                                  | `ai/`、`core/`、`config/`、`plugin_system/`、`sdk/` | 导入 `frontend_bridge_core`、`ui`、具体传输模块（`http`/`socket`/`websocket`/`websockets`）或 `webbrowser`；禁止返回 `/api/...` URL                                                                             |
| `frontend_bridge_core/` | HTTP/WebSocket 传输、鉴权、DTO 转换、路由分发、调用 Use Case                               | `application/`、简单配置契约、传输工具              | 导入 `ai`、`core`、`plugin_system`、`ui`、`subprocess`、`tarfile`、`zipfile`；禁止承载下载/解压/配置/业务编排                                                                                                   |
| `frontend/`             | React UI 与 Tauri 桌面壳（`app -> features -> entities -> shared`）                        | 前端自身各层与 bridge 协议                          | `modules/character-visual` 禁止依赖 `entities`/`features`/`app`/`shared/platform`/`shared/desktop`，外部仅通过 `index.ts` 与 `app/avatarFormats.ts` 接入；禁止前端直接读写本地配置文件                          |

### 1.3 架构禁令

- **禁止扩大例外基线**：`test/unit/architecture/test_import_boundaries.py` 中 `ALLOWED_VIOLATIONS` 已清零并永久锁定，任何提交不得新增或重新引入跨层依赖。
- **禁止重建已退役路径**：不得在仓库根目录重新引入 `llm/`、`asr/`、`tts/`、`t2i/`、`ui/`，或 `core/plugins/`、`core/runtime/`；`main.py` 必须保持 `<= 150` 行纯装配入口。
- **禁止手改构建/生成产物**：`frontend/src-tauri/resources/*`（由 `pnpm prepare:tauri-resources` 生成）、`frontend/dist/`、`frontend/src/shared/platform/standalone/ai/generatedTemplateLocales.json`（由同步脚本生成）一律禁止手工编辑。
- **禁止随意新建顶层目录**：新能力必须按 `docs/PROJECT_STRUCTURE.md` 归位，未在设计文档确认前不得新增顶层业务目录。

---

## 2. 统一 Storage 架构（禁止直接文件 I/O）

### 2.1 存储抽象与分层实现

所有持久化抽象与引擎分为三层，详见 `docs/STORAGE_ARCHITECTURE_PLAN_zh-CN.md`：

1. **抽象端口契约（`sdk/adapters/storage.py`）**：
   - `ManagedBackend` / `Migratable`：统一生命周期（`name`、`status() -> BackendStatus`、`migrate()`、`close()`）。
   - `Codec[T]`：纯内存 `bytes <-> Model` 编解码与历史兼容清洗。
   - `ReadableDocument[T]` / `DocumentStore[T]`：整文档原子读写（`revision`、`get()`、`save()`、`update()`）。
   - `ReadableCatalog[K, T]` / `CatalogStore[K, T]`：按主键单条原子存取（`get()`、`list_all()`、`put()`、`patch()`、`delete()`）。
   - `UnitOfWork`：跨仓储单事务边界（`with uow.atomic():`）。
2. **统一存储基础设施（`core/storage/`）**：
   - **唯一路径解析源**：所有 `data/` 路径必须通过 `StorageLayout(project_root)`（`core/storage/layout.py`）解析，**严禁**在业务代码中硬编码 `Path("data/...")` 或 `Path.cwd()`。
   - **声明式配置与 UI 状态**：`api.yaml`、`system_config.yaml`、`mcp.yaml`、`plugins.yaml`、`user_prompt_presets.json` 与 `data/state/ui_state.json` 使用 `FileDocumentStore[T]`（`core/storage/file_store.py`）配合 `PydanticYamlCodec` / `PydanticJsonCodec`（`core/storage/codecs.py`），内置 `RLock`、`(mtime_ns, size)` 增量重载与 `sdk/file_io.py:durable_rename` 原子发布。
   - **高频实体与跨表关联（`data/shinsekai.db`）**：通过 `SqliteEngine`（`core/storage/sqlite_engine.py`，统一 WAL、`busy_timeout`、`foreign_keys=ON`、`ContextVar` 嵌套事务、`PRAGMA user_version` 迁移）与 `core/storage/stores/` 下的领域仓储操作：
     - `SqliteCharacterCatalog`（`CharacterCatalogPort`）
     - `SqliteBackgroundCatalog`（`BackgroundCatalogPort`）
     - `SqliteEffectCatalog`（`EffectCatalogPort`）
     - `SqliteConversationStore`
     - `SqliteKnowledgeBindingStore`
     - `UnifiedReminderStore`
   - **生命周期总线与装配根**：`StorageHub`（`core/storage/hub.py`）与 `AppStores`（`application/runtime/stores.py`）负责注册全部后端、启动期顺序 `migrate_all()`、健康诊断 `statuses()` 与关闭期逆序 `close_all()`。
   - **单元测试替身**：单测优先使用 `InMemoryDocumentStore`、`InMemoryCatalogStore`、`NoopUnitOfWork`（`core/storage/in_memory.py`），零磁盘副作用。
3. **统一资产打包层（`core/packaging/`）**：
   - 角色包（`.char`/`.cha`）、背景包（`.bg`）、特效包（`.effect`）导入导出统一走 `core/packaging/{character_package,background_package,effect_package,zip_io}.py` 与 `CatalogStore`，使用 `tempfile.TemporaryDirectory()` 隔离并发解压与路径穿越校验；禁止再通过 `tools/file_util.py` 或业务函数直接覆写 YAML/DB 或创建 `./temp_*_{pid}` 目录。

### 2.2 Storage 使用禁令

- **禁止绕过存储层做直接文件 I/O**：在 `application/`、`ai/`、`config/`、`frontend_bridge_core/`、`plugin_system/` 中，不得使用裸 `open()`、`Path.read_text/write_text`、`yaml.safe_dump`、`json.dump` 或手写 `sqlite3.connect` 来读写业务配置、角色/背景/特效目录、会话索引、提醒或绑定数据；若需扩展存储，应新增或扩展 `DocumentStore` / `CatalogStore` / `core/storage/stores/`，并通过窄 `Protocol` 注入。
- **禁止把 `StorageHub` / `ConfigManager` 当全局单例扩散**：`StorageHub` 与 `AppStores` 只驻留在装配根（`application/runtime/` / `application/bootstrap/`）；下游消费方应接收窄端口（如 `ReadableDocument[ApiConfig]`、`CharacterCatalogPort`、`EffectCatalogPort`），而非直接全局导入 `ConfigManager` 或 `StorageHub`。
- **保持 Model 纯净**：`config/models/` 下所有模型不得导入 `sqlite3`/`yaml`/`core.storage`、不得使用会触发磁盘 `os.stat` 的 `pydantic.FilePath`、不得修改 `os.environ`；只读摘要投影（如 `CharacterSummary`）使用 `ConfigDict(frozen=True)`。旧字段兼容清洗放进 `Codec.decode()`；主库索引列或表结构变更按序追加到 `core/storage/migrations/main_db.py` 的 `MAIN_DB_MIGRATIONS`。
- **底层文件原语**：`core/` 内部确实需要写入本地媒体/缓存/模型文件时，必须使用 `sdk/path_utils.py` 校验路径边界，并通过临时文件 `fsync` + `sdk/file_io.py:durable_rename(..., replace=True)` 原子发布。

---

## 3. Prompt 架构（禁止在 `.py` 中写大段 Prompts）

### 3.1 单一事实源与核心原语

所有内置系统/业务 Prompt 以 `ai/llm/template/` 为唯一体系：

- **Prompt YAML 唯一事实源**：`ai/llm/template/catalog/{zh_CN,en,ja}/*.yaml`，包含 6 个受守卫域：`dialog`、`extraction`、`generation`、`perception`、`session`、`story`。使用 YAML 多行块标量（`|` 保留尾换行、`|-` 去除尾换行）。三语文件集合、点路径 key 与 `{placeholder}` 变量必须 100% 一致，由 `test/unit/ai/llm/template/test_catalog_integrity.py` 强制校验。
- **核心组装原语（`ai/llm/template/core/`）**：
  - `Section` / `TextSection` / `I18nSection`（`section.py`）：不可变 Composite 节点。自定义节点实现 `_render_self(context)` 与 `_resolve_children(context)`，**禁止重写 `render()`**。
  - `TemplateContext`（`context.py`）：携带显式 `locale`（由 `sdk.lang.normalize_lang(system_config.ui_language)` 归一化）与可选 `translator: sdk.lang.Translator`（`sdk/lang.py`），渲染上下文按请求传递，禁止缓存在节点或全局状态中。
  - `PromptCatalog`（`catalog.py`）：加载与格式化受信任 YAML 词条。
  - `PromptSpec`（`prompt_spec.py`）：声明 `system_builder` / `user_builder` 与语种策略：
    - `PromptLanguagePolicy.FOLLOW_UI`：跟随 `ui_language`；
    - `PromptLanguagePolicy.LOCKED_CONTRACT`（配合 `locked_locale`）：用于受下游正则/小模型/英文动作词强约束的契约（如立绘标签或 ComfyUI 动作短语），即使锁定语种也必须纳入 `PromptSpec` + YAML catalog 管理。

### 3.2 Prompt 开发约束

- **禁止在 `.py` 中硬编码多句 Prompt 或手拼 `messages`**：除 `@tool(description=...)` 工具契约描述按设计保持代码内联外，所有提示词文本（含 system、user、summary、repair、extraction、generation）必须迁入 `catalog/<locale>/<domain>.yaml` 并经 `I18nSection` + `PromptSpec` 渲染。
- **禁止模块导入期静态求值**：AST 守卫禁止在 `ai/llm/template/` 的模块顶层调用 `.render()` / `.render_system()` / `.render_user()`，防止导入时锁死语种。
- **严格区分受信任文案与非受信任文本（防格式注入）**：只有 `catalog/*.yaml` 词条可走 `I18nSection` / `context.tr(...)` 插值；用户输入、对话历史、角色设定原文、OCR 字幕、知识库条目、异常文本等动态内容**必须**使用 `TextSection` 或 `json.dumps`，严禁传入 `str.format()` / `Formatter`。
- **上下文注入哨兵头**：记忆、知识库、服装、关系等系统注入块必须通过 `ai/llm/template/session/context_blocks.py` 使用固定 ASCII 协议头（如 `[Shinsekai:memory]`、`[Shinsekai:knowledge]`、`[Shinsekai:outfit]`、`[Shinsekai:relation]`）。
- **保持纯模板层独立**：`ai/llm/template/{core,extraction,generation,perception,prompts,session,story}` 不得导入 `application`、`config`、`core`、`frontend_bridge_core`（`dialog` 不得导入 `application`、`frontend_bridge_core`）。
- **Standalone 同步不可省略**：修改 `ai/llm/template/catalog/` 下任意 YAML 后，必须执行 `python -m ai.llm.template.sync_standalone` 更新只读产物 `frontend/src/shared/platform/standalone/ai/generatedTemplateLocales.json`，并运行 `--check` 确认无差异。

---

## 4. 全栈 i18n 架构（禁止未经 i18n 的 Message）

### 4.1 前端 UI 唯一事实源（`frontend/src/shared/i18n/`）

- **三语切片字典**：所有前端用户可见文案放在 `frontend/src/shared/i18n/messages/{zh_CN,en,ja}/*.ts`（15 个域切片在 `zh_CN.ts`/`en.ts`/`ja.ts` 汇总并由 `messages.ts` 导出 `MessageKey`）。`frontend/src/test/shared/i18n/i18n.test.ts` 强制校验三语域集合、key 集合（跨切片无重名）与 `{param}` 占位符完全一致。
- **统一消费方式**：
  - React 组件通过 `useI18n()` / `useOptionalI18n()` 调用 `t(key, values)`；
  - 表单 Schema（`frontend/src/shared/form-schema.ts` + `frontend/src/entities/config/schema.ts`）使用 `*Key`（`labelKey`、`descriptionKey`、`placeholderKey`、`disabledReasonKey`、`titleKey`、`FormOption.labelKey`），由 `SchemaDrivenForm.tsx` 统一翻译；
  - 后台任务状态映射走 `TaskProgress.tsx` 的 `task.phase.*`、`task.packageStatus.*`、`task.depStatus.*` 词条；
  - 持久化内部枚举值（如 `"硅基流动"`、`"豆包"`、`"通义千问"`、`"透明场景"`、`"默认"`）**不得修改存储键名**，仅在展示层通过 `frontend/src/shared/i18n/domainLabels.ts` 转换显示文案；内置自设通过不可变主键 `id = "__self__"`（`SELF_PERSONA_ID`）识别，其 `name` 可直接重命名（默认 `"自设"`，仅在仍为默认名时由展示层本地化）。
- **硬编码零容忍**：`frontend/src/test/architecture/i18nHardcodeBoundary.test.ts` 的 `LOCKED_FRONTEND_CJK_ALLOWLIST` 已清零（`[]`）。禁止在 `features/`、`app/`、`entities/`、`shared/` 新增任何未经 i18n 的中文/日文字符串或体系外独立多语字典。

### 4.2 Bridge / SDK 结构化错误与后端 `i18n/`

- **禁止裸抛自然语言或靠中文前缀分支**：
  - 业务逻辑与 Bridge 统一抛出 `AppError(error_code, params=..., fallback_message=..., http_status=...)`（`sdk/exception/types.py`）或带 `reasonCode` 的 `DownloadError`；
  - 后台任务 `ProgressSnapshot`（`sdk/exception/types.py`）通过 `titleKey`/`titleParams`、`messageKey`/`messageParams`、`errorCode`/`errorParams` 传递结构化信息；
  - 前端统一经 `formatPlatformError(error, t)`（`frontend/src/shared/platform/errors.ts`）映射 `error.<errorCode>` 并插值渲染；
  - `test/unit/architecture/test_i18n_boundaries.py` 中 `LOCKED_BRIDGE_CJK_FILES` 已清零（`frozenset()`），且明确禁止 `.startswith("找不到")` / `.startswith("请")` 等中文消息前缀分支判断。
- **Python `i18n/` 边界**：`i18n/locales/*.json` 仅保留少量后端进程直出通知。需要后端本地化时优先传显式 `locale` 调用 `tr_in_bundle(key, locale, **kwargs)` 或 `bind_language(locale)` 上下文，避免依赖进程全局可变 `_current`；严禁把已裁剪的 `template_gen` 或废弃 Qt 命名空间加回 `i18n/locales/`。

---

## 5. 文件体积与拆分规范（单文件 `<= 500` 行）

- **硬性上限**：每个源码文件（`.py`、`.ts`、`.tsx`、`.rs`、`.css`）原则上保持 **`<= 500` 行**（单元测试、纯静态数据字典切片与兼容旧大文件改造期间也应尽量控制在 500 行内）。
- **拆分原则**：
  - 新增代码会导致文件超过 500 行，或对既有 > 500 行的遗留大文件做实质性功能修改时，**必须按单一职责（内聚子模块）先行或同步拆分**；
  - 拆分参考示例：`frontend/src-tauri/src/runtime/{managed,manifest,python_env,python_probe,pytorch,resolver}.rs`、`ai/llm/template/dialog/sections/*.py`、`config/models/*.py`；
  - 需要保持外部 import 兼容时，在原入口模块或 `__init__.py` / `index.ts` 保留薄重导出门面，并确保 `test_import_boundaries.py` 与 `characterVisualBoundaries.test.ts` 全部通过；
  - **禁止**机械按行数切成 `foo_part1.py`/`foo_part2.py`，**禁止**新建 `helpers.py`、`utils.py`、`common.py` 垃圾桶文件来塞拆分出来的函数。

---

## 6. 文件与目录命名规范

| 语言 / 区域                           | 目录与文件命名                                                                | 规则与示例                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Python 通用**                       | 目录 `snake_case/`，文件 `snake_case.py`                                      | 模块名体现领域职责；存储实现用 `*_store.py`（`character_store.py`），打包用 `*_package.py`（`character_package.py`）                                                                                                                                                                                                        |
| **Python `application/`**             | 动作入口用 `verb_noun.py`                                                     | 面向 bridge 的公开用例必须使用动词短语，如 `start_chat.py`、`stop_chat.py`、`download_model.py`、`install_plugin.py`、`generate_character.py`、`build_effect_context.py`；仅整个域唯一稳定入口可使用 `management.py`；**禁止**在 `application/` 中出现 `service.py`、`manager.py`、`helpers.py`、`utils.py`（单测强制禁止） |
| **Python 测试**                       | `test/unit/<layer>/test_<module>.py`                                          | 目录结构与源码层对齐（`architecture/`、`ai/`、`application/`、`config/`、`core/`、`frontend_bridge_core/`、`plugin_system/`、`sdk/`）                                                                                                                                                                                       |
| **Frontend 目录**                     | `kebab-case/`                                                                 | 如 `features/api-settings/`、`features/character-editor/`、`modules/character-visual/`、`entities/character/`                                                                                                                                                                                                               |
| **Frontend 组件与样式**               | `PascalCase.tsx` + 同名 `PascalCase.css`                                      | 如 `ApiSettingsPage.tsx` + `ApiSettingsPage.css`、`TaskProgress.tsx` + `TaskProgress.css`、`SchemaDrivenForm.tsx`                                                                                                                                                                                                           |
| **Frontend Hooks / TS 模块**          | Hook `useCamelCase.ts`，非组件 `camelCase.ts`                                 | 如 `useAgentConversation.ts`、`domainLabels.ts`、`httpTransport.ts`、`apiSettingsUtils.ts`；i18n 域切片按小写领域命名（`messages/<locale>/<domain>.ts`）                                                                                                                                                                    |
| **Frontend 测试**                     | 单元测试 `frontend/src/test/**/*.test.{ts,tsx}`；E2E `frontend/e2e/*.spec.ts` | 测试文件路径镜像 `src/` 结构                                                                                                                                                                                                                                                                                                |
| **Rust（`frontend/src-tauri/src/`）** | `snake_case.rs` 与 `snake_case/` 子模块                                       | 与 Rust 标准模块命名一致；配套单元测试放在对应模块或 `<module>/tests.rs`                                                                                                                                                                                                                                                    |
| **脚本与文档**                        | 辅助脚本就近放在所属模块目录；文档用 `UPPER_SNAKE_CASE.md`                    | 禁止把业务辅助脚本堆入顶层 `scripts/` 或 `assets/`；中文设计文档以 `_zh-CN.md` 结尾                                                                                                                                                                                                                                         |

---

## 7. 提交前必过检查（Tests, Format Check, Type Check & PR）

### 7.1 Commit 与 PR 规范

- Commit 标题受 `.husky/commit-msg`（`scripts/presubmit.py`）强制校验，必须符合 Conventional Commits 且 `<= 100` 字符：
  `<type>(optional-scope)!: summary`（允许类型：`feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`revert`）。
- 遵循 `CONTRIBUTING.md`「One PR, one concern」，PR 描述关联对应 Issue，且严禁为图省事删除测试、放宽断言或使用 `SKIP_PRESUBMIT=1` 绕过检查。
- **PR 必须包含需手动测试说明**：提 PR 时必须在描述中单列「需手动测试（Manual Testing）」小节：
  - 明确列出自动化测试无法覆盖、需人工验证的场景、前置条件、操作步骤与预期结果（例如 UI 交互与视觉表现、角色渲染/立绘/Live2D/VRM、本地模型或外部 API 联调、TTS/ASR 音视频链路、Tauri 桌面壳与系统集成、数据/配置迁移等）；
  - 若本次变更不涉及需手动验证项（如纯文档更新或已被自动化测试充分覆盖的内部重构），也须显式注明「无需手动测试」并简述原因，不得省略该小节。

### 7.2 必过验证命令

- **Python（仓库根目录执行）**：
  - 全量测试（与 `.husky/pre-push` 一致）：`python -m pytest -v --tb=short --strict-markers -p no:warnings`
  - 快速架构与 Prompt 守卫：`python -m pytest test/unit/architecture/ test/unit/ai/llm/template/`
  - Standalone Prompt 同步校验：`python -m ai.llm.template.sync_standalone --check`
  - 覆盖率门禁（`sdk`、`core/messaging`、`i18n` 综合覆盖率 `>= 85%`）：`python -m pytest --cov --cov-config=.coveragerc --cov-report=term-missing`
- **Frontend（`frontend/` 目录执行）**：
  - Prettier 格式检查（`endOfLine: lf`、`printWidth: 120`、`trailingComma: all`）：`pnpm format:check`（自动修复：`pnpm format`）
  - TypeScript 类型检查：`pnpm lint:types`
  - 单元测试与前端架构守卫：`pnpm test`
  - 覆盖率门禁（行覆盖率与语句覆盖率均 `>= 85%`）：`pnpm test:coverage`
  - 涉及前端/Tauri 资源构建时：`pnpm build`（及按需 `pnpm verify:tauri-resources`）
- **Rust（修改 `frontend/src-tauri/` 时执行）**：
  - 格式检查：`cargo fmt --manifest-path frontend/src-tauri/Cargo.toml --check`
  - 单元测试：`cargo test --manifest-path frontend/src-tauri/Cargo.toml`
