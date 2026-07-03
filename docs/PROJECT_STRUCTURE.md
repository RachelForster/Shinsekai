# Shinsekai 文件目录结构约定

本文规定 Shinsekai 后续开发时“代码应该放在哪里”。目标不是立刻重排全部历史代码，而是先统一边界：新代码按本文放置，旧代码在改动时逐步迁移。

## 总原则

- 按职责命名目录，而不是按历史入口或临时实现命名。
- `frontend_bridge_core/` 只做前端到 Python 的桥接，不承载长期业务实现。
- `config/` 保留在根目录，继续作为本地配置和用户数据读写层。
- `sdk/` 保持干净，只放插件和外部扩展会依赖的稳定 API。
- 新增通用能力优先放到明确子域，例如 `core/model_assets/`、`core/runtime/`、`plugins/`、`ai/memory/`。

## 目标结构

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
    handler.py
    state.py
    tasks.py
    routes/

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
    tools/

  core/
    model_assets/
    runtime/
    media/
    sprite/
    app_update/

  plugins/
    host/
    registry/
    install/
    update/
    publisher/
    requirements/

  sdk/
  tools/
  assets/
  data/
  docs/
  scripts/
  test/
```

这个结构是目标状态。短期内可以保留现有 `llm/`、`tts/`、`asr/`、`t2i/`、`core/plugins/`、`frontend_bridge_core/*.py`，但新增或重构时应向目标结构靠拢。

## 目录职责

### `frontend/`

保留现状，负责 React 前端和 Tauri 桌面壳。

```text
frontend/src/app       路由、providers、应用 shell
frontend/src/features  页面和业务功能 UI
frontend/src/entities  前端领域类型、schema、repository
frontend/src/shared    通用 UI、i18n、theme、platform adapter
frontend/src-tauri     Tauri 桌面壳、打包配置、Rust 侧能力
```

不要把 Python 业务逻辑、配置读写、插件安装逻辑写进前端。前端通过 platform adapter 调用 bridge。

### `frontend_bridge_core/`

这是前端和 Python 后端之间的桥接层。它可以保留，但应该逐步瘦身。

可以放：

- HTTP route 分发；
- request/response 转换；
- task 创建、查询、取消；
- 调用 `config/`、`core/`、`ai/`、`plugins/` 的薄服务函数。

不建议放：

- 插件安装和更新的主体逻辑；
- 模型下载、缓存、解压；
- runtime 依赖安装；
- mem0 初始化、向量库配置；
- 角色、背景、媒体资源的复杂业务处理。

如果某个 bridge 文件开始包含大量业务逻辑，应把实现抽到对应领域目录，bridge 只保留入口。

### `config/`

`config/` 保留在根目录，职责是本地配置和用户数据读写。

可以放：

- `data/config/` 的读取和保存；
- 系统配置 schema 和校验；
- 角色、背景配置管理；
- proxy、mirror、环境变量配置；
- 配置默认值和迁移逻辑。

不建议放：

- LLM/TTS/ASR/T2I 调用；
- 插件安装；
- 模型下载；
- HTTP route；
- Tauri 打包和更新逻辑。

### `ai/`

目标目录，用来承载 AI 能力域。当前可以先逐步迁移，不要求一次完成。

建议最终拆分：

```text
ai/llm/       LLM adapter、manager、prompt 和消息处理
ai/tts/       TTS adapter、manager
ai/asr/       ASR adapter、manager
ai/t2i/       文生图 adapter、manager
ai/memory/    长期记忆、mem0 runtime、embedding/vector 配置
ai/tools/     把 AI 能力包装成 LLM tool 的薄层
```

长期记忆最终建议拆成：

```text
ai/memory/config.py      mem0、embedding、Qdrant 配置
ai/memory/runtime.py     mem0 初始化、后台加载、状态
ai/memory/service.py     memory search/add/delete
ai/tools/memory_tools.py LLM tool 注册和参数包装
```

### `core/`

`core/` 放宿主程序的通用能力。它不应该依赖 React，也不应该是插件 SDK 的公共承诺。

建议子域：

```text
core/model_assets/  模型下载、缓存检测、模型源、下载进度
core/runtime/       Python runtime、依赖检测、运行诊断
core/media/         文件、路径、安全校验、媒体资源处理
core/sprite/        聊天记录、立绘、分支存储等角色演出数据
core/app_update/    主程序更新、GitHub Release、updater manifest
```

已经新增的模型下载进度逻辑应放在：

```text
core/model_assets/downloads.py
```

未来如果增加 ModelScope 或其他模型源，可以继续放：

```text
core/model_assets/cache.py
core/model_assets/sources.py
core/model_assets/modelscope.py
```

### `plugins/`

插件系统已经是独立子系统，最终应从 `core/plugins/` 和 `frontend_bridge_core/plugin_*.py` 中逐步整理出来。

目标结构：

```text
plugins/host/          插件加载、生命周期、宿主上下文
plugins/registry/      插件索引、catalog、远端 registry
plugins/install/       安装、覆盖、导入本地插件
plugins/update/        插件更新、源码包合并
plugins/publisher/     插件发布、提交校验
plugins/requirements/  插件依赖安装
```

bridge 中只保留 API 入口，前端只保留 UI。

### `sdk/`

`sdk/` 是给插件和外部扩展使用的稳定接口，不放宿主内部实现。

可以放：

- 插件基类和注册 API；
- tool registry；
- hooks；
- 插件 UI contribution 类型；
- adapter 抽象；
- 日志、异常、校验等可暴露给插件的工具。

不建议放：

- 主程序更新；
- 模型下载；
- 插件安装实现；
- bridge route；
- 前端页面实现。

### `tools/`

`tools/` 指本地资源处理工具和脚本，不是 LLM tool 注册层。

可以放：

- 图片裁剪、背景处理；
- 音频处理；
- 资源导入导出辅助工具；
- 开发/迁移脚本中可复用的工具模块。

LLM 可调用工具最终应放到 `ai/tools/` 或对应领域的 tool wrapper 中。

### `test/`

测试目录应尽量跟源码职责对齐。新增测试优先按目标结构放：

```text
test/unit/core/model_assets/
test/unit/core/runtime/
test/unit/ai/memory/
test/unit/plugins/
test/unit/frontend_bridge_core/
test/unit/sdk/
```

历史测试不要求立即搬迁；当对应源码迁移或重构时，再同步移动测试。

## 迁移优先级

### 第一优先级：瘦身 `frontend_bridge_core/`

把 bridge 中的业务实现抽出来。bridge 保留 API 和 task 生命周期，业务进入 `core/`、`ai/`、`plugins/`。

优先候选：

- 插件安装和更新；
- runtime dependency 安装；
- TTS 包下载；
- 主程序更新；
- 模型下载。

### 第二优先级：拆分长期记忆

`llm/tools/memory_tools.py` 当前职责较多。后续改长期记忆时，优先拆到 `ai/memory/`，LLM tool 文件只做包装。

### 第三优先级：插件系统独立

把 `core/plugins/` 和 `frontend_bridge_core/plugin_*.py` 中的插件业务逐步迁移到顶层 `plugins/`。

### 暂不优先迁移

- `config/`：保留根目录；
- `frontend/src`：现有 feature-sliced 结构可继续使用；
- `sdk/`：保持稳定；
- `assets/`、`data/`、`docs/`、`scripts/`：保持现状即可。

## 新代码放置规则

- 新的模型下载、缓存、来源逻辑：放 `core/model_assets/`。
- 新的 runtime 检测和依赖安装逻辑：放 `core/runtime/`。
- 新的长期记忆业务逻辑：放 `ai/memory/`。
- 新的 LLM tool 包装：放 `ai/tools/`，或在迁移前暂放 `llm/tools/`。
- 新的插件安装/更新/registry 逻辑：放 `plugins/`。
- 新的 HTTP API：入口放 `frontend_bridge_core/`，实现放对应领域目录。
- 新的本地配置读写：放 `config/`。

