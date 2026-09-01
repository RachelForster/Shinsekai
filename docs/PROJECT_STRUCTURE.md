# Shinsekai 项目结构与依赖边界

> 状态：生效
> 适用范围：仓库内新增代码、重构和模块迁移
> 迁移状态与 OKR：见 [`PROJECT_STRUCTURE_MIGRATION.md`](PROJECT_STRUCTURE_MIGRATION.md)

本文只定义长期稳定的目录职责、依赖方向和代码放置规则。当前迁移进度、兼容路径和分阶段退出条件不在本文维护，避免目标架构与阶段性状态混在一起。

## 1. 总原则

- 按职责和稳定边界组织目录，不按历史入口或临时实现命名。
- `frontend_bridge_core/` 是接口适配层，只负责协议、安全、路由和 DTO 转换。
- 跨领域用例和进程生命周期放在 `application/`，不写进 bridge 或通用 `core/`。
- `sdk/` 是插件和外部扩展可依赖的公共契约，不能反向依赖宿主实现。
- `plugins/` 保存用户插件或本地插件内容；宿主插件平台源码放在 `plugin_system/`。
- `config/` 将配置领域规则、具体持久化和运行环境适配分开，不依赖 AI 或界面实现。
- 命名空间迁移先更新实现和内部引用，再按发布策略删除兼容入口。
- 产品 UI 只由 React/Tauri 承载；Qt 设置页、Qt 聊天窗和历史 Python UI 入口已退出。

### 1.1 `core` 与 `application` 的边界模型

本项目中的 `core/` 不是“所有业务逻辑”的同义词，也不等同于传统分层架构中的
service 层。这里采用 **Host Capability + Use Case** 的划分：

- `core/` 是可被复用的宿主基础能力（Host Capability）。它回答“怎样完成一个
  有明确输入输出的动作”，不拥有当前会话、当前任务或整个应用的运行状态。
- `application/` 是产品用例和流程所有者（Use Case / Process Owner）。它回答
  “这次用户操作要按什么顺序调用哪些能力”，并负责依赖装配、状态选择、任务、
  取消、进度和生命周期。

依赖方向固定为 `application -> core`，不能反向。`core/` 也不能通过动态导入、
全局 runtime accessor 或注入一个包含整套应用能力的 manager 来绕过这个方向。
当 `core/` 需要上层能力时，应接收一个针对当前动作的窄 `Protocol`、回调或值对象。

Repository 不是强制的顶层目录。只有当某个用例需要替换存储实现、隔离事务边界
或同时支持多种持久化后端时，才在对应能力域定义 repository 接口；实现放在最接近
存储机制的模块，application 只依赖该接口。简单、稳定的单一文件读写不必为了套用
传统三层结构而额外包装一层。

## 2. 依赖方向

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

具体约束：

| 来源 | 可以依赖 | 不可以依赖 |
| --- | --- | --- |
| `sdk/` | 标准库、第三方库、`sdk/` 内部模块 | `application/`、`ai/`、`config/`、`core/`、`plugin_system/`、bridge、前端或 Qt UI |
| `config/` | 标准库、第三方库、必要的 `sdk/` 契约 | AI provider、bridge、UI、插件宿主实现 |
| `core/` | 标准库、第三方库、`config/`、`sdk/` 契约 | `application/`、bridge、UI、具体 AI adapter、应用 runtime 或宽 manager；AI 能力由 application 通过窄契约注入 |
| `ai/` | `core/`、`config/`、`sdk/` | bridge、UI、旧 `llm/tts/asr/t2i` 实现路径 |
| `plugin_system/` | `core/`、`config/`、`sdk/` | bridge、UI、`application/` |
| `application/` | `ai/`、`core/`、`config/`、`plugin_system/`、`sdk/` | bridge 的具体传输实现、React 具体控件或历史 Qt UI |
| `frontend_bridge_core/` | `application/`、简单配置读写契约、传输层工具 | pip、下载、解压、模型加载、插件覆盖等主体业务 |
| `frontend/` | 前端自身的 app/entities/features/shared | Python 业务实现和本地配置文件直接读写 |

架构测试的依赖例外 allowlist 当前为空；新增反向依赖必须直接修正，不得增加例外。

## 3. 目标结构

```text
Shinsekai/
  frontend/
    src/
      app/
      entities/
      features/
      shared/
    src-tauri/

  frontend_bridge_core/
    routes/

  application/
    bootstrap/
    chat/
      handlers/
    diagnostics/
    media/
    model_assets/
    runtime/
    story/
    plugins/
    localization/

  config/
    domain/
      schema.py
      feature_flags.py
    repository/
      config_manager.py
      character_manager.py
      background_manager.py
      mcp_config.py
    environment/
      mirror_env.py
      network_proxy.py
      tts_provider_config.py

  ai/
    llm/
    memory/
    tts/
    asr/
    t2i/
    vision/
    story/
    tools/

  core/
    app_update/
    chat_history/
    media/
    messaging/
    model_assets/
    runtime_env/
    security/
    sprite/
    story/

  plugin_system/
    contributions/
    host/
    install/
    publisher/
    registry/
    requirements/
    update/

  plugins/
  sdk/
  tools/
  assets/
  data/
  docs/
  scripts/
  test/
```

该结构已经完成主路径切换。新业务实现不得重新引入根目录
`llm/asr/tts/t2i`、`core/plugins`、`core/runtime` 或 `ui`。

## 4. 目录职责

### `frontend/`

负责 React 设置中心、聊天界面和 Tauri 桌面壳。

```text
frontend/src/app       路由、providers、应用 shell
frontend/src/features  页面和业务功能 UI
frontend/src/entities  前端领域类型、schema、repository
frontend/src/shared    通用 UI、i18n、theme、platform adapter
frontend/src-tauri     Tauri 壳、打包配置和 Rust 侧能力
```

前端通过 platform adapter 和 bridge 协议访问 Python。不得直接实现配置文件读写、插件安装、模型下载或 Python runtime 管理。

### `frontend_bridge_core/`

只负责：

- HTTP/WebSocket 传输；
- 鉴权、CORS、上传和静态资源响应；
- request/response DTO 转换；
- 路由分发；
- task 创建、查询、取消和进度转发；
- 调用 application use case。

禁止直接实现：

- pip 和 runtime dependency 安装；
- 插件下载、解压、覆盖、更新与发布；
- 模型下载、缓存和 provider 选择；
- 聊天会话、进程和 worker 的主体生命周期；
- AI runtime 初始化。

### `application/`

负责跨领域用例、依赖注入和宿主生命周期：

```text
application/bootstrap/       进程启动、组合根、运行模式选择
application/chat/            聊天启动、停止、恢复和历史用例
application/chat/handlers/   LLM 输出到 TTS/UI event 的应用处理链
application/diagnostics/     日志快照与诊断包用例
application/effects/         特效配置与资源管理用例
application/media/           媒体标注等跨领域共享能力
application/model_assets/    模型与 TTS 资源下载用例
application/runtime/         app runtime、workers、workflow、shutdown
application/story/           剧情会话、分支状态仓库、人物 readiness 与演出编排
application/plugins/         插件安装、更新、发布等用例编排
```

application 可以组合多个能力域，但不实现具体 HTTP 或 UI 控件。
表示明确流程或动作的 application 模块优先使用 `动词_名词.py`，例如
`manage_branches.py`。只有作为整个领域唯一稳定入口时才使用
`management.py`；
不得使用无法说明职责的通用 `service.py`、`helpers.py` 或 `utils.py` 承载流程。
实时聊天命令统一通过稳定入口 `application/chat/commands.py` 分发；WebSocket
payload 解析与 ack 投影保留在 `frontend_bridge_core/transport/`。
聊天 provider、模板、历史、memory hooks 和可选能力降级统一由稳定组合入口
`application/chat/startup.py` 创建并返回 `ChatStartupContext`。
聊天 workflow、queues、`AppRuntime`、streaming/headless 模式和关闭持久化统一由
`application/chat/session_runtime.py` 的 `StreamingChatSession` 与
`HeadlessChatSession` 持有；背景、BGM、历史场景和初始立绘恢复集中在
`application/chat/presentation.py`；实时输入、分支、ASR 和 command dispatcher 的
适配集中在动词入口 `application/chat/wire_streaming_session.py`。`main.py` 只保留
进程 bootstrap、launch options、transport 和 session 四步装配。
application 是 `AppRuntime`、应用级 task、当前会话和 concrete manager 装配的唯一
所有者；这些对象不能下沉到 `core/`。application 可以把结果投影为稳定的 SDK event
或调用注入的 port，但不能直接构造 HTTP response、WebSocket frame 或 React DTO。
聊天 turn service 的 manager/queue 装配、初始立绘呈现、特效方案选择和 LLM 特效
用法提示都属于 `application/chat/`；`core/` 只保留对应的 admission policy、路径匹配
和标签解析能力。
特效配置、音频文件、标签、目录和导入导出由 `application/effects/management.py` 统一
管理；bridge 只解析请求并调用 `EffectUseCase.execute()`，不得另建文件操作入口。
AI、插件等下层能力需要通知宿主时，必须通过 `sdk/` 契约和 application
注入的 adapter 回调，不得反向导入 `application/`。
`application/story/` 负责把确定性剧情事务与聊天分支、持久化 generation、
人物档案 readiness、可降级演出资源和实时事件协调起来；文件提交、资源加载状态
和 global effect outbox 不得下沉到 `core/story/`。

### `config/`

负责：

- `config/domain/`：schema、默认值、feature flag、校验和纯规范化规则；
- `config/repository/`：`data/config/` YAML、MCP 配置及角色/背景受管资源的具体持久化；
- `config/environment/`：proxy、mirror、TTS 本地运行路径和进程环境变量适配。

这里的 `repository/` 是真实文件存储实现目录，不是要求每个模型都定义 Repository
接口。application 只有在需要替换后端、隔离事务或使用 fake 时才定义窄 Protocol；
简单配置读取可以直接使用具体 repository。`domain/` 不得导入 `repository/` 或
`environment/`，`environment/` 也不得反向依赖 `repository/`。

配置层不得导入 AI manager、bridge route、插件宿主或 UI。

### `ai/`

承载 AI 能力域：

```text
ai/llm/       LLM adapter、manager、prompt 和消息处理
ai/memory/    长期记忆、mem0 runtime、embedding/vector 配置
ai/tts/       TTS adapter 和 manager
ai/asr/       ASR adapter、manager 和 streaming controller
ai/t2i/       文生图 adapter 和 manager
ai/vision/    图片理解 adapter、manager 和 provider
ai/story/     AI 剧本生成、意图/语义评估、选角提案和安全上下文投影
ai/tools/     向 LLM 暴露能力的薄 tool wrapper
```

`ai/tools/` 只做参数校验、权限/上下文判断和领域服务调用。通用文件、图片或音频处理放在 `core/media/` 或 `tools/`。
`ai/story/` 只能返回候选意图、语义信号、选角 ID、剧本草稿或补丁；
权威剧情状态和演员表仍由 `core/story/` 裁决，并由 application 提交。

### `core/`

放置不依赖具体界面、传输或 AI provider 的宿主基础能力：

```text
core/app_update/    主程序版本检查、release 和更新包处理
core/chat_history/  聊天记录归一化、分支状态和会话文件存储
core/media/         文件、附件、媒体资源、安全格式和标签解析
core/messaging/     消息模型、流解析、对话协议和框架无关的 turn policy
core/model_assets/  模型下载、缓存、来源和进度
core/runtime_env/   Python、pip、依赖检测和运行环境诊断
core/security/      归档、下载来源等宿主安全校验及旧路径兼容入口
core/sprite/        立绘路径归一化和角色立绘匹配
core/story/         剧本 Schema、确定性规则、编译、事件、校验和路径模拟
```

一个 core API 应满足以下约束：

- 输入和输出明确，不读取当前会话、当前 task 或全局 application runtime；
- 单独测试时不需要启动应用、bridge、UI 或具体 AI provider；
- 可以做职责内的确定性计算或局部 I/O，但不决定产品流程和下一步动作；
- 需要上层协作时只接收窄回调、`Protocol` 或值对象，不接收
  `AppRuntime`、`BridgeState`、UI manager、LLM manager 等应用对象；
- 不静态或动态导入 `application/`。

如果代码负责选择配置、协调两个以上能力域、维护任务/取消/进度、决定失败降级，
或协调 UI、AI、插件和进程生命周期，它属于 `application/`，而不是 `core/`。
`core/story/` 必须保持确定性且无资源 I/O：可以定义 Schema、规则、事件、
`CastResolutionPlan` 和编译器，但不得加载人物文件、调用 LLM、持有模型句柄
或发出 React/传输层 DTO。

### `plugin_system/`

宿主内部插件平台：

```text
plugin_system/host/           加载、生命周期和宿主上下文
plugin_system/registry/       catalog 和远端 registry
plugin_system/install/        安装、覆盖和本地导入
plugin_system/update/         插件更新和源码包合并
plugin_system/publisher/      发布、metadata 和提交校验
plugin_system/requirements/   插件 requirements 解析和安装
plugin_system/contributions/  前端页面、配置页、聊天 UI 等贡献解析
```

通用 pip、索引和 PyTorch runtime 能力放 `core/runtime_env/`；插件系统只负责插件场景的编排。

### `plugins/`

用于用户安装插件、本地开发插件及其 assets、manifest 和扩展文件。它不是宿主实现目录，宿主源码不得迁入此处。

### `sdk/`

包含插件和外部扩展可依赖的稳定 API：

- 插件基类和注册 API；
- adapter 抽象；
- hooks、messages 和 tool registry；
- 宿主回调和运行期注入契约；
- UI contribution 数据类型；
- 公共日志、异常和校验契约；
- 不依赖宿主实现的跨层路径校验工具。

SDK 使用协议和注入点连接宿主，不直接导入宿主 manager、Qt 控件或 bridge。

### `tools/`

`tools/migrate_helper/` is the transitional bootstrap dialog for moving source-checkout
users to the React frontend. It is not a product UI surface and must not grow settings
or chat features; `webui_react.py` invokes it only when the React frontend cannot start
or when `--show-migration-helper` is requested.

保存本地资源处理和开发工具，例如图片裁剪、音频处理、资源转换和导入导出辅助函数。LLM tool wrapper 必须放在 `ai/tools/`。

## 5. 源码、生成物和运行时数据

| 路径 | 类型 | 规则 |
| --- | --- | --- |
| `frontend/src-tauri/resources/*` | Tauri 构建暂存物 | 由 `pnpm prepare:tauri-resources` 生成，禁止手工修改；根目录源码是唯一来源 |
| `frontend/dist/`、`build/`、`build_exe/` | 构建产物 | 不作为源码评审对象 |
| `data/` | 本地数据和默认资源 | 读写必须经过配置或领域服务 |
| `plugins/` | 用户/本地插件内容 | 不放宿主插件平台源码 |
| `cache/`、`logs/`、`output/`、`.tmp_*` | 运行时或测试产物 | 不得被源码模块依赖 |

## 6. 命名空间迁移规则

每次命名空间迁移按以下顺序进行：

1. 在目标目录建立实现和测试。
2. 更新仓库内部 import，并用架构测试禁止新增旧路径引用。
3. 若公开 SDK 需要兼容，兼容入口必须有明确的删除版本和测试。
4. 内部引用为零、验证通过后删除旧路径。

迁移不得把宿主实现暴露为新的 SDK 契约。

## 7. 测试和架构守卫

测试目录与目标职责对齐：

```text
test/unit/application/
test/unit/ai/
test/unit/core/
test/unit/frontend_bridge_core/
test/unit/plugin_system/
test/unit/sdk/
test/integration/
test/e2e/
```

`test/unit/architecture/` 负责校验依赖方向、禁止旧命名空间回流，并保持空
allowlist。O1 的锁定基线是永久上限；迁移完成后任何提交都不得新增、
替换或重新解释例外，修改本文或迁移台账也不能授权扩充基线。

## 8. 新代码放置速查

| 新能力 | 放置位置 |
| --- | --- |
| HTTP/WebSocket 路由与 DTO | `frontend_bridge_core/routes/` |
| 跨领域用例和生命周期 | `application/` |
| 剧情会话、存档和人物资源编排 | `application/story/` |
| LLM/TTS/ASR/T2I/Vision 实现 | `ai/<domain>/` |
| AI 剧本生成与场景理解 | `ai/story/` |
| LLM tool wrapper | `ai/tools/` |
| 确定性剧情模型、规则与编译 | `core/story/` |
| 模型下载和缓存 | `core/model_assets/` |
| Python、pip 和依赖环境 | `core/runtime_env/` |
| 跨层通用路径校验 | `sdk/path_utils.py` |
| 归档与下载来源安全 | `core/security/` |
| 插件 host/install/update/registry | `plugin_system/` |
| 本地配置 schema 和持久化 | `config/` |
| 插件公共契约 | `sdk/` |
| React/Tauri UI | `frontend/` |

拿不准放置位置时，按下面顺序判断：

1. 是否拥有一次用户操作、当前会话、任务或应用生命周期？是则放 `application/`。
2. 是否只完成一个输入输出明确、可独立测试的宿主动作？是则放 `core/`。
3. 是否绑定具体 AI provider、插件平台或传输协议？放对应的 `ai/`、
   `plugin_system/` 或 `frontend_bridge_core/`，由 application 编排。

文件名不是边界依据：`service.py` 既可能是 application use case，也可能是 core
capability；应根据它拥有的状态、协调范围和依赖方向判断。
