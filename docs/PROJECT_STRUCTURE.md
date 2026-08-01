# Shinsekai 项目结构与依赖边界

> 状态：生效
> 适用范围：仓库内新增代码、重构和模块迁移
> 迁移状态与 OKR：见 [`PROJECT_STRUCTURE_MIGRATION.md`](PROJECT_STRUCTURE_MIGRATION.md)

本文只定义长期稳定的目录职责、依赖方向和代码放置规则。当前迁移进度、兼容路径和分阶段退出条件不在本文维护，避免目标架构与阶段性状态混在一起。

## 1. 总原则

- 按职责和稳定边界组织目录，不按历史入口或临时实现命名。
- `frontend_bridge_core/` 是接口适配层，只负责协议、安全、路由和 DTO 转换。
- 跨领域用例和进程生命周期放在 `application/`，不写进 bridge 或通用 `core/`。
- `sdk/` 是插件和外部扩展可依赖的公共契约，不能反向依赖宿主实现；无宿主依赖的路径、文件事务、归档和进程启动安全原语属于稳定 SDK，具体决策见 [`PATH_SAFETY_SDK_DECISION.md`](PATH_SAFETY_SDK_DECISION.md)。
- `plugins/` 保存用户插件或本地插件内容；宿主插件平台源码放在 `plugin_system/`。
- `config/` 负责配置 schema、默认值、迁移和持久化，不依赖 AI 或界面实现。
- 命名空间迁移先更新实现和内部引用，再按发布策略删除兼容入口。
- 产品 UI 只由 React/Tauri 承载；Qt 设置页、Qt 聊天窗和历史 Python UI 入口已退出。

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
| `core/` | 标准库、第三方库、`config/`、`sdk/` | bridge、UI、具体 AI adapter；AI 能力由 application 注入 |
| `ai/` | `core/`、`config/`、`sdk/` | bridge、UI、旧 `llm/tts/asr/t2i` 实现路径 |
| `plugin_system/` | `core/`、`config/`、`sdk/` | bridge、UI、`application/` |
| `application/` | `ai/`、`core/`、`config/`、`plugin_system/`、`sdk/` | React 具体控件或历史 Qt UI |
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
    plugins/
    localization/

  config/
    config_manager.py
    schema.py
    character_manager.py
    background_manager.py
    mirror_env.py
    network_proxy.py

  ai/
    llm/
    memory/
    tts/
    asr/
    t2i/
    vision/
    tools/

  core/
    app_update/
    media/
    messaging/
    model_assets/
    runtime_env/
    security/
    sprite/

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
application/media/           媒体标注等跨领域用例
application/model_assets/    模型与 TTS 资源下载用例
application/runtime/         app runtime、workers、workflow、shutdown
application/plugins/         插件安装、更新、发布等用例编排
```

application 可以组合多个能力域，但不实现具体 HTTP 或 UI 控件。
AI、插件等下层能力需要通知宿主时，必须通过 `sdk/` 契约和 application
注入的 adapter 回调，不得反向导入 `application/`。

### `config/`

负责：

- `data/config/` 的读取和保存；
- schema、默认值、校验与配置迁移；
- 角色、背景和本地用户配置管理；
- proxy、mirror 和环境变量配置。

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
ai/tools/     向 LLM 暴露能力的薄 tool wrapper
```

`ai/tools/` 只做参数校验、权限/上下文判断和领域服务调用。通用文件、图片或音频处理放在 `core/media/` 或 `tools/`。

### `core/`

放置不依赖具体界面、传输或 AI provider 的宿主基础能力：

```text
core/app_update/    主程序版本检查、release 和更新包处理
core/media/         文件、附件、媒体资源和安全格式处理
core/messaging/     消息模型、流解析和对话协议
core/model_assets/  模型下载、缓存、来源和进度
core/runtime_env/   Python、pip、依赖检测和运行环境诊断
core/security/      下载来源、领域授权等宿主安全策略
core/sprite/        聊天记录、立绘和分支存储
```

如果代码需要同时协调 UI、AI、插件和进程生命周期，它属于 `application/`，而不是 `core/`。

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
- 不依赖宿主实现的跨层路径校验工具；
- `sdk.file_transactions`、`sdk.archive_paths` 和 `sdk.process_launch` 中明确导出的、调用方提供授权根与对象身份的安全原语。

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

迁移不得把宿主实现暴露为新的 SDK 契约。纯标准库、无宿主状态且由调用方
提供授权边界的安全原语可经独立架构决策升级为稳定 SDK；当前生效决定见
[`PATH_SAFETY_SDK_DECISION.md`](PATH_SAFETY_SDK_DECISION.md)。

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
| LLM/TTS/ASR/T2I/Vision 实现 | `ai/<domain>/` |
| LLM tool wrapper | `ai/tools/` |
| 模型下载和缓存 | `core/model_assets/` |
| Python、pip 和依赖环境 | `core/runtime_env/` |
| 跨层通用路径校验 | `sdk/path_utils.py` |
| 文件事务、归档成员与进程启动安全原语 | `sdk/file_transactions.py`、`sdk/archive_paths.py`、`sdk/process_launch.py` |
| 下载来源与领域授权策略 | `core/security/` |
| 插件 host/install/update/registry | `plugin_system/` |
| 本地配置 schema 和持久化 | `config/` |
| 插件公共契约 | `sdk/` |
| React/Tauri UI | `frontend/` |
