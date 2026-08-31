# Shinsekai 项目结构迁移台账

> 基线提交：`87d9f4b8`
> 建立日期：2026-07-27
> 稳定结构约定：见 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md)

本文记录阶段性状态、兼容路径、PR 边界和可量化 OKR。O1 → O5 完成首次目录迁移；
O6 锁定 `core/` 与 `application/` 的语义边界，O7 按该边界迁移现存的高置信度
流程编排，O8 按功能逐个将 bridge 中的主体实现收口到 application。

## 1. 基线状态

| 领域 | 当前状态 | 基线规模 | 目标 |
| --- | --- | --- | --- |
| `ai/memory/` | 已落地，正式使用 `ai.tools` | 14 个 Python 文件 | 保持 |
| `ai/vision/` | 已落地，旧 tool 依赖已清除 | 7 个 Python 文件 | 保持 |
| `ai/llm/` | O4 已落地，O5 已删除旧入口 | 规范 AI 实现目录 | 保持统一 AI 边界 |
| `core/messaging/` | 已落地 | 10 个 Python 文件 | 保持并清理应用层耦合 |
| `core/model_assets/` | 已落地 | 3 个 Python 文件 | 保持 |
| `application/runtime/` | O3/O5 已落地 | 通用 runtime 与标准线程 worker | 保持应用编排边界 |
| `application/chat/handlers/` | O5 已落地 | TTS 与 presentation 处理链 | 保持框架无关 |
| `core/runtime/`、`core/handlers/` | O5 已删除 | 0 | 禁止重新引入 |
| `core/plugins/` | O5 已删除 | 0 | 禁止重新引入 |
| `plugin_system/` | O2 已落地 | host/install/publisher/registry/requirements/update | 保持宿主插件平台边界 |
| `frontend_bridge_core/` | O3/O5 已收敛 | routes + transport helpers | 只保留接口适配 |
| `llm/asr/tts/t2i` | O5 已删除 | 0 | 统一使用 `ai/*` |
| `ui/`、`webui.py`、`webui_qt.py` | O5 已删除 | 0 | 产品 UI 只由 React/Tauri 承载 |

## 2. 基线依赖例外

O1 的完整依赖矩阵精确记录 56 个历史“文件 → 顶层包”例外，分布在
38 个文件中。`LOCKED_BASELINE_VIOLATIONS` 是永久上限；后续 Objective
只能从活动 allowlist 删除对应项，不得新增或替换。O2、O3 与 O4 完成后
活动集合剩余 11 项，O5 已删除最后这些例外。当前 `ALLOWED_VIOLATIONS`
为空，架构测试不再接受历史反向依赖。

## 3. Objective 与 PR 边界

### O1：让目录边界可执行

PR 范围：

- 将稳定目录约定与迁移台账拆分；
- 明确依赖方向、目标结构、生成目录和 Qt UI 废弃策略；
- 建立 AST import-boundary 测试；
- 以精确 allowlist 锁定当前反向依赖。

完成条件：

- 文档可以区分“已落地、过渡、目标”；
- CI 自动阻止新增反向依赖；
- allowlist 与基线例外一一对应；
- 工作区全部既有测试通过。

### O2：完成插件平台独立

状态：已通过 PR 286 合入 `main`。

PR 范围：

- 建立 `plugin_system/`；
- 将 `core/plugins/` 按职责拆入插件平台；
- 将通用 pip、index、PyTorch runtime 移入 `core/runtime_env/`；
- 将主程序更新逻辑移入 `core/app_update/`；
- 保持 bridge 的既有 `core.plugins` 兼容入口，禁止在 O2 新增
  bridge → `plugin_system` 依赖；
- 将 `plugin_system/` 加入 Tauri 资源暂存，并校验代表性宿主文件存在。

关键结果：

- `core/plugins/` 的 14 个实现文件全部完成归位；
- 生产代码对 `core.plugins` 的引用从 38 个文件降至 0；
- 插件实现进入 `plugin_system/`，bridge 到 application 的收口留给 O3；
- host、registry、安装回滚、requirements 和 publisher 测试通过；
- 删除 O1 allowlist 中插件实现相关例外；
- `prepare-tauri-resources` 与 `verify-tauri-resources` 覆盖 `plugin_system/`。

### O3：将 bridge 收敛为接口层

PR 范围：

- 建立 `application/`，包括最小 `application/plugins/` 用例门面；
- 拆分 chat、runtime、handlers 和跨领域用例；
- 将 handler 分发改为 routes；
- 将插件 bridge 从 `core.plugins` 兼容入口切换到
  `application/plugins/`，bridge 不直接依赖 `plugin_system/`；
- 将 `application/` 加入 Tauri 资源暂存并校验代表性 use case；
- Qt UI 不作为新 application 能力迁移，只保留 React/Tauri 所需事件契约。

关键结果：

- `frontend_bridge_core/handler.py` 从 1779 行降为 14 行兼容入口，HTTP 分发迁入 `routes/api.py`；
- bridge 中 subprocess、归档、pip、模型下载和 TTS 包下载主体实现为 0；
- chat 进程/初始化、runtime dependency、模型资产、TTS 下载、诊断包和插件更新均通过 application use case 调用；
- WebSocket client transport 位于 `frontend_bridge_core/transport/`，application
  只保留 event sink 契约和快照归并；
- HTTP、application、plugin system 共用的路径校验收敛到
  `sdk.path_utils`；旧 `core.security.paths` 与 bridge path helper 仅保留兼容导出；
- chat 启动参数通过受控 JSON 环境配置传递，子进程 argv 只包含可信解释器和入口；
- `application/` 禁止反向依赖 bridge 或 Qt UI；旧 AI 实现通过 `sdk.llm_runtime`
  使用宿主回调，不得反向导入 application；
- 默认与 headless workflow 已切换到 `application.runtime.workers`，旧
  `core.runtime.workers` 和 `core.handlers` 仅保留兼容入口；
- HTTP、task、聊天流、application 用例和兼容导入契约测试通过；
- Tauri 资源清单已包含 application；
- 活动 allowlist 从 48 项降至 28 项；React/Tauri workers 已迁入
  `application/runtime/`，剩余 Qt UI manager 例外按“不迁移 Qt 控件”决策转入 O5 删除。

### O4：统一 AI 命名空间

状态：已在 O4 PR 落地，等待合并。

PR 范围：

- 将根目录 `llm/asr/tts/t2i` 实现迁入 `ai/*`；
- 建立 `ai/tools/`；
- 旧路径仅保留 re-export；
- SDK adapter 继续作为插件稳定入口。

关键结果：

- 非 Qt 生产代码对 `llm/asr/tts/t2i` 的引用数从 55/13/10/8 降至 0，3 个 Qt 调用点明确转入 O5 删除；
- `llm/tools/memory_tools.py` 成为纯兼容入口；
- 插件和外部扩展通过 `sdk.adapters` 与 `sdk.tool_protocol` 使用稳定接口，SDK 不反向依赖 AI 实现；
- LLM、ASR、TTS、T2I 与 tool 实现统一由 `ai/*` 承载，Tauri 资源校验覆盖新的规范路径；
- AI 相关单元与集成测试通过；
- 删除 O1 allowlist 中 AI、config 和 tool registry 相关例外，活动集合剩余 11 项。

### O5：安全完成切换

状态：已在 O5 PR 落地，等待合并。

PR 范围：

- 删除达到退出条件的兼容模块；
- 删除 Qt 设置 UI、Qt 聊天 UI 与历史入口；
- 更新构建资源清单和最终文档；
- 完成本地测试、前端测试和 Tauri 资源验证。

关键结果：

- `ui/`、`webui.py`、`webui_qt.py` 已删除，React/Tauri 成为唯一产品 UI；
- `application/runtime/workers.py` 使用标准库线程，不再依赖 `QThread`；
- `core/plugins`、`core/runtime`、旧 bridge alias 与根目录 AI alias 已删除；
- QtPy 与 `pyqt-toast` 已退出运行依赖和 Tauri manifest；PySide6 仅保留在源码
  `requirements.txt` 中供 `tools/migrate_helper/` 迁移入口使用，不进入 Tauri
  desktop-core runtime；
- O1 allowlist 清零；
- Tauri 资源校验同时验证规范目录存在、历史目录不存在；
- Windows 本地验证由本 PR 执行，macOS/Linux smoke test 由 CI 执行；
- 实际目录、测试目录和目标结构一致。

### O6：锁定 core 与 application 的职责边界

状态：本分支实现。

PR 范围：

- 将 `core` 明确定义为 Host Capability，将 `application` 明确定义为 Use Case / Process Owner；
- 说明 application runtime、当前会话、任务和 concrete manager 的所有权；
- 明确 repository 只在存在可替换存储或事务边界时引入，不建立空泛的顶层 repository 层；
- 将字面量动态导入纳入现有依赖矩阵，防止通过 `importlib` 或 `__import__` 绕过边界；
- 禁止 `core/` 引用 `AppRuntime`、`BridgeState` 和 application runtime accessor；
- 删除无生产引用的 `core.media.auto_annotation` 残留兼容入口，并将单测归位到 application。

完成条件：

- 新代码放置可以通过“流程所有权”与“独立能力”规则明确判断；
- `core -> application` 的静态和字面量动态依赖都由同一架构测试阻止；
- 架构 allowlist 继续为空；
- 不迁移 O7 计划中的 chat wiring、演出编排等主体业务。

### O7：迁移 chat wiring 与演出编排

状态：本分支实现。

PR 范围：

- 将 chat turn service 的 config、queue、LLM/UI manager 装配从
  `core/messaging/chat_turn_wiring.py` 迁到 `application/chat/turn_wiring.py`；
- 将初始立绘的配置选择和 UI 更新迁到 `application/chat/initial_sprite.py`，
  `core/sprite/selection.py` 只保留值输入的路径匹配；
- 将特效方案选择、运行期 keyword map 和 LLM prompt catalog 迁到
  `application/chat/effects.py`；
- 将重复的音频标签解析收敛到 `core/media/effect_audio.py`，main 与 bridge
  不再各自维护一份解析循环；
- 将对应单测按职责归位，并禁止 core 再接收 LLM/UI manager 或新增 wiring 模块。

完成条件：

- `core/` 中不再出现 chat manager/queue composition 或 UI 演出调用；
- main、bridge 只调用 application use case，不复制特效解析逻辑；
- 纯路径匹配、turn policy 和标签解析可脱离 application 独立测试；
- 架构 allowlist 保持为空，既有聊天行为和协议不变。

### O8：让 Bridge 真正变薄

状态：按功能拆分独立 PR。第一阶段 Effects 已完成；本分支实现第二阶段
Backgrounds 和 Characters。

迁移策略：按功能拆分独立 PR，不一次处理全部 bridge。

第一阶段 PR 范围：

- 将 Effect 配置增删改、音频文件复制和删除、标签保存、目录管理及包导入导出
  迁到 `application/effects/management.py`；
- 通过 `EffectRequest -> EffectUseCase.execute()` 提供单一 application 入口；
- `frontend_bridge_core/effects.py` 只保留 request 解析、依赖装配和 response 投影；
- HTTP 路径、请求 payload 和响应格式保持不变，前端无需修改；
- 删除 `tools/file_util.py` 中不再使用的 Effect 导入导出重复实现；
- 增加架构守卫，阻止 Effect 文件、归档和配置主体逻辑回流 bridge。

第一阶段完成条件：

- Effect bridge 不导入 `shutil`、`pathlib`、`yaml`、`zipfile` 或配置模型；
- Effect route 不再直接调用文件工具或修改 config manager；
- 文件访问继续受 trusted roots、managed directory 和 archive path 校验约束；
- Effect application、bridge adapter、HTTP 既有测试及 Tauri 资源验证通过。

第二阶段 PR 范围：

- 将背景资源上传、删除、导入导出和配置与资源联合更新迁入
  `application/backgrounds/management.py`；
- 将角色保存校验、资源上传删除、语音校验和导入导出迁入
  `application/characters/management.py`；
- `backgrounds`、`characters` 和 `effects` 按业务领域建立 application
  一级目录；`application/media/` 只保留跨领域媒体能力；
- 每个领域只暴露一个 bridge 执行入口，由 application operation 明确区分用例；
- 标签、缩放、翻译等简单配置读写继续保留在 bridge，不为机械转发增加空用例；
- 上传临时目录仍由 HTTP transport 创建和清理，application 只接收获准访问的文件根目录。

第二阶段完成条件：

- Backgrounds 和 Characters bridge 不再直接调用资源 manager 或包导入导出实现；
- HTTP 路由与响应字段保持不变，前端无需修改；
- 两个领域分别由架构守卫锁定唯一 use case 入口和禁止回迁的资源操作；
- 架构 allowlist 保持为空。

### O9：将 `main.py` 收敛为聊天进程入口

状态：按职责拆分独立 PR；第一阶段迁移对话分支管理。

迁移策略：保留 `main.py` 作为进程 composition root，按可独立测试的用户动作和
生命周期逐步迁移，不把全部逻辑一次搬入另一个大文件。流程模块统一采用
`动词_名词.py` 命名。

第一阶段 PR 范围：

- 将分支创建、切换、重命名、树投影和持久化迁到
  `application/chat/manage_branches.py`；
- `main.py` 只装配消息、UI、持久化和提交回调，不再持有 branch state；
- 增加分支操作直接单测和入口架构守卫。

后续阶段：

- 实时命令分发迁到 `application/chat/dispatch_commands.py`；
- provider、插件、模板和历史启动装配迁到
  `application/chat/initialize_chat.py`；
- streaming/headless 生命周期迁到 `application/chat/run_session.py`；
- 完成后 `main.py` 只保留进程环境、transport 装配、模式选择和顶层异常处理。

## 4. 迁移映射

| 当前路径 | 目标位置 | Objective | 说明 |
| --- | --- | --- | --- |
| `llm/tools/memory_tools.py` | `ai/tools/memory_tools.py` | O4/O5 | 已完成；旧路径已删除 |
| `llm/tools/file_tools.py` | `core/media/file_operations.py` + `ai/tools/file_tools.py` | O4/O5 | 已完成；旧路径已删除 |
| `llm/tools/mcp_config_file.py` | `config/mcp_config.py` | O4/O5 | 已完成；旧路径已删除 |
| `llm/*` | `ai/llm/` | O4/O5 | 已完成；旧路径已删除 |
| `asr/*` | `ai/asr/` | O4/O5 | 已完成；SDK adapter 保持稳定 |
| `tts/*` | `ai/tts/` | O4/O5 | 已完成；旧路径已删除 |
| `t2i/*` | `ai/t2i/` | O4/O5 | 已完成；SDK adapter 保持稳定 |
| `core/plugins/plugin_host.py` | `plugin_system/host/` | O2 | 加载、生命周期和 contribution 收集 |
| `core/plugins/registry_*` | `plugin_system/registry/` | O2 | catalog、状态和远端下载 |
| `core/plugins/package_download.py` | `plugin_system/install/` | O2 | 下载、校验、安全解压和替换 |
| `core/plugins/publisher/*` | `plugin_system/publisher/` | O2 | 共享路径安全迁到 `core/security/` |
| `core/plugins/plugin_requirements_install.py` | `plugin_system/requirements/` | O2 | 插件场景编排 |
| `core/plugins/pip_runner.py` | `core/runtime_env/pip_runner.py` | O2 | 通用 pip 子进程能力 |
| `core/plugins/pip_index_config.py` | `core/runtime_env/pip_index.py` | O2 | 通用镜像和 index 配置 |
| `core/plugins/pytorch_runtime.py` | `core/runtime_env/pytorch.py` | O2 | 通用 PyTorch runtime 选择 |
| `core/plugins/github_bundle_update.py` | `core/app_update/` + `plugin_system/update/` | O2 | 主程序和插件更新必须拆开 |
| `core/runtime/app_runtime.py` 等 | `application/runtime/` | O3/O5 | runtime 已迁；worker 已改为标准线程 |
| `core/runtime/requirements.py` | `core/runtime_env/requirements.py` | O3 | 环境检测 |
| `core/handlers/*` | `application/chat/handlers/` | O5 | 已迁移框架无关处理链，Qt 控件实现已删除 |
| `frontend_bridge_core/chat.py` | routes + `application/chat/` | O3 | bridge 只保留协议 |
| `frontend_bridge_core/plugin_*.py` | routes + `application/plugins/` | O2/O3 | O2 迁实现并保留兼容调用；O3 将 catalog/updates 收口到 application 门面 |
| `frontend_bridge_core/model_assets.py`、`tts.py` | `application/model_assets/` | O3 | bridge 只创建 task 并转发结果 |
| `frontend_bridge_core/logs.py` | `application/diagnostics/` | O3 | 诊断归档不在传输层实现 |
| `core/media/auto_annotation.py` | `application/media/` | O3/O6 | AI 能力由 application 编排；O6 删除残留兼容入口并归位单测 |
| `core/messaging/chat_turn_wiring.py` | `application/chat/turn_wiring.py` | O7 | manager、queue 与消息 port 装配属于 application |
| `core/sprite/initial_sprite.py` | `core/sprite/selection.py` + `application/chat/initial_sprite.py` | O7 | core 只做路径匹配，配置选择和 UI 呈现由 application 负责 |
| main/bridge 特效标签解析 | `core/media/effect_audio.py` + `application/chat/effects.py` | O7 | 单一解析能力，application 负责方案选择与 prompt/runtime 投影 |
| `frontend_bridge_core/effects.py` 主体实现 | `application/effects/management.py` | O8/阶段 1 | bridge 只保留 HTTP adapter，配置与资源操作统一经过 EffectUseCase |
| `frontend_bridge_core/backgrounds.py` 资源变更 | `application/backgrounds/management.py` | O8 PR 2 | bridge 仅保留协议、翻译和简单标签写入 |
| `frontend_bridge_core/characters.py` 资源变更 | `application/characters/management.py` | O8 PR 2 | 保存校验、文件操作和多步骤更新由 application 编排 |
| `main.py` 对话分支闭包 | `application/chat/manage_branches.py` | O9/阶段 1 | 分支状态、操作和持久化归 application，入口只装配窄回调 |

## 5. 通用退出条件

旧路径通常只有同时满足以下条件才能删除：

1. 仓库内部生产 import 为零；
2. 旧模块只剩 re-export，没有独立状态或业务逻辑；
3. 已按发布策略完成弃用窗口，或由项目决策明确提前终止该能力；
4. 单元、集成、e2e 和 Tauri 打包检查通过；
5. 迁移台账已更新为完成。

O5 根据“废弃 Qt UI 逻辑”的明确项目决策加速删除 Qt 与仅服务于该 UI
的兼容入口；稳定插件扩展继续通过 `sdk.adapters`、frontend contribution
和 JSON 事件契约提供。
