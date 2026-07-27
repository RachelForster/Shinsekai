# Shinsekai 项目结构迁移台账

> 基线提交：`87d9f4b8`
> 建立日期：2026-07-27
> 稳定结构约定：见 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md)

本文记录阶段性状态、兼容路径、PR 边界和可量化 OKR。每个 Objective 使用一个独立 PR，并按 O1 → O5 顺序合并。

## 1. 基线状态

| 领域 | 当前状态 | 基线规模 | 目标 |
| --- | --- | --- | --- |
| `ai/memory/` | 已落地，旧 tool 路径兼容中 | 14 个 Python 文件 | 正式 tool 入口迁入 `ai/tools/` |
| `ai/vision/` | 已落地 | 7 个 Python 文件 | 清除对旧 `llm.tools` 的依赖 |
| `ai/llm/` | 部分落地 | 仅少量实现 | 合并根目录 `llm/` |
| `core/messaging/` | 已落地 | 10 个 Python 文件 | 保持并清理应用层耦合 |
| `core/model_assets/` | 已落地 | 3 个 Python 文件 | 保持 |
| `core/runtime/` | 过渡状态 | 9 个 Python 文件 | 拆为 `application/runtime/` 与 `core/runtime_env/` |
| `core/handlers/` | 历史应用处理链 | 5 个 Python 文件 | 迁入 `application/chat/handlers/` |
| `core/plugins/` | 待迁移 | 14 个 Python 文件 | 拆入 `plugin_system/`、`core/runtime_env/`、`core/app_update/` |
| `plugin_system/` | 尚未建立 | 0 | 建立宿主插件平台 |
| `frontend_bridge_core/` | 业务过重 | 34 个 Python 文件 | 收敛为 transport/routes/task |
| `llm/asr/tts/t2i` | 旧命名空间 | 28 个 Python 文件 | 迁入 `ai/*` 并保留兼容层 |
| `ui/`、`webui.py`、`webui_qt.py` | 已决定废弃 | 不再迁移 UI 逻辑 | O5 删除或隔离剩余运行依赖 |

## 2. 基线依赖例外

O1 的架构测试精确记录 22 个历史“文件 → 顶层包”例外。后续 Objective 必须删除对应 allowlist 项，不得新增：

| 来源 | 反向依赖 | 退出 Objective |
| --- | --- | --- |
| `ai/memory/extraction.py` | `llm` | O4 |
| `ai/vision/service.py` | `llm` | O4 |
| `config/character_manager.py` | `llm` | O4 |
| `config/config_manager.py` | `core`、`llm`、`t2i`、`tts` | O3/O4 |
| `core/media/auto_annotation.py` | `ai` | O3 |
| `core/plugins/plugin_host.py` | `ai`、`ui` | O2/O5 |
| `core/plugins/publisher/metadata.py` | `frontend_bridge_core` | O2 |
| `core/runtime/workers.py` | `ai` | O3 |
| `sdk/chat_ui_context.py` | `ui` | O5 |
| `sdk/cli/registry_ops.py` | `core` | O2 |
| `sdk/logging/configure.py` | `core` | O3 |
| `sdk/logging/environment.py` | `ui` | O5 |
| `sdk/manager.py` | `config`、`llm` | O4/O5 |
| `sdk/plugin_host_context.py` | `config`、`ui` | O2/O5 |
| `sdk/register.py` | `llm` | O4 |
| `sdk/tool_registry.py` | `llm` | O4 |

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

PR 范围：

- 建立 `plugin_system/`；
- 将 `core/plugins/` 按职责拆入插件平台；
- 将通用 pip、index、PyTorch runtime 移入 `core/runtime_env/`；
- 将主程序更新逻辑移入 `core/app_update/`；
- bridge 仅调用插件用例服务。

关键结果：

- `core/plugins/` 的 14 个实现文件全部完成归位；
- 生产代码对 `core.plugins` 的引用从 38 个文件降至 0；
- bridge 不直接执行插件下载、解压、覆盖或 requirements 安装；
- host、registry、安装回滚、requirements 和 publisher 测试通过；
- 删除 O1 allowlist 中插件相关例外。

### O3：将 bridge 收敛为接口层

PR 范围：

- 建立 `application/`；
- 拆分 chat、runtime、handlers 和跨领域用例；
- 将 handler 分发改为 routes；
- Qt UI 不作为新 application 能力迁移，只保留 React/Tauri 所需事件契约。

关键结果：

- `frontend_bridge_core/handler.py` 不超过 500 行；
- bridge 中 pip、归档、模型下载、进程编排主体实现为 0；
- chat、runtime dependency、TTS 下载通过 application use case 调用；
- HTTP、task、聊天流契约测试全部通过；
- 删除 O1 allowlist 中 runtime、media 和 logging 相关例外。

### O4：统一 AI 命名空间

PR 范围：

- 将根目录 `llm/asr/tts/t2i` 实现迁入 `ai/*`；
- 建立 `ai/tools/`；
- 旧路径仅保留 re-export；
- SDK adapter 继续作为插件稳定入口。

关键结果：

- 生产代码对 `llm/asr/tts/t2i` 的引用数从 55/13/10/8 降至 0；
- `llm/tools/memory_tools.py` 成为纯兼容入口；
- 插件和外部扩展只通过 `sdk.adapters` 使用 AI 接口；
- AI 相关单元与集成测试通过；
- 删除 O1 allowlist 中 AI、config 和 tool registry 相关例外。

### O5：安全完成切换

PR 范围：

- 删除达到退出条件的兼容模块；
- 删除或隔离 Qt 设置 UI 与历史入口；
- 更新构建资源清单和最终文档；
- 完成跨平台打包验证。

关键结果：

- `ui/`、`webui.py`、`webui_qt.py` 不再承载产品 UI 逻辑；
- O1 allowlist 清零；
- 连续两次完整 CI 无旧路径回归；
- Windows、macOS、Linux Tauri smoke test 通过；
- 实际目录、测试目录和目标结构一致。

## 4. 迁移映射

| 当前路径 | 目标位置 | Objective | 说明 |
| --- | --- | --- | --- |
| `llm/tools/memory_tools.py` | `ai/tools/memory_tools.py` | O4 | 当前已是薄包装，最终只保留兼容 re-export |
| `llm/*` | `ai/llm/` | O4 | 先移动实现，再更新内部 import |
| `asr/*` | `ai/asr/` | O4 | SDK adapter 保持稳定 |
| `tts/*` | `ai/tts/` | O4 | 资源下载不放 adapter |
| `t2i/*` | `ai/t2i/` | O4 | SDK adapter 保持稳定 |
| `core/plugins/plugin_host.py` | `plugin_system/host/` | O2 | 加载、生命周期和 contribution 收集 |
| `core/plugins/registry_*` | `plugin_system/registry/` | O2 | catalog、状态和远端下载 |
| `core/plugins/package_download.py` | `plugin_system/install/` | O2 | 下载、校验、安全解压和替换 |
| `core/plugins/publisher/*` | `plugin_system/publisher/` | O2 | 共享路径安全迁到 `core/security/` |
| `core/plugins/plugin_requirements_install.py` | `plugin_system/requirements/` | O2 | 插件场景编排 |
| `core/plugins/pip_runner.py` | `core/runtime_env/pip_runner.py` | O2 | 通用 pip 子进程能力 |
| `core/plugins/pip_index_config.py` | `core/runtime_env/pip_index.py` | O2 | 通用镜像和 index 配置 |
| `core/plugins/pytorch_runtime.py` | `core/runtime_env/pytorch.py` | O2 | 通用 PyTorch runtime 选择 |
| `core/plugins/github_bundle_update.py` | `core/app_update/` + `plugin_system/update/` | O2 | 主程序和插件更新必须拆开 |
| `core/runtime/app_runtime.py` 等 | `application/runtime/` | O3 | 应用生命周期和 worker |
| `core/runtime/requirements.py` | `core/runtime_env/requirements.py` | O3 | 环境检测 |
| `core/handlers/*` | `application/chat/handlers/` | O3 | 不迁移 Qt 控件实现 |
| `frontend_bridge_core/chat.py` | routes + `application/chat/` | O3 | bridge 只保留协议 |
| `frontend_bridge_core/plugin_*.py` | routes + `application/plugins/` | O2/O3 | 插件能力先迁，路由随后收口 |

## 5. 通用退出条件

旧路径只有同时满足以下条件才能删除：

1. 仓库内部生产 import 为零；
2. 旧模块只剩 re-export，没有独立状态或业务逻辑；
3. 至少经过一个发布周期的弃用窗口；
4. 单元、集成、e2e 和 Tauri 打包检查通过；
5. 迁移台账已更新为完成。
