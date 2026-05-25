# 非 UI 历史改动撤销记录

日期：2026-05-25

背景：本分支已 rebase 到最新 `main`（`upstream/main`）。rebase 过程中，旧分支历史里仍包含一批非 UI 提交。为保持本分支聚焦 React/界面改动，本轮重新按最新 `main` 恢复这些非 UI 路径。

## 保留范围

- `frontend/**` React 设置中心、组件、样式、前端测试与视觉基线。
- React 前端运行入口和 bridge：`frontend_bridge.py`、`webui_react.py`、`start-react.*`、相关启动脚本。
- UI 可见文案和设置页链接，例如自绘文件管理器根目录显示为 `Shinsekai`。
- React 前端说明文档：`design.md`、`frontend/README.md`、README 中的 React 设置中心说明。

## 跳过或恢复的非 UI 历史提交

### `0852b10 fix(config): normalize provider defaults and asset paths`

处理：rebase 时跳过。

位置：
- `config/config_manager.py`
- `test/unit/managers/test_config_manager.py`

原因：配置默认值和资源路径归一化属于后端配置行为，不属于 UI。

### `fdfc3da fix(packages): harden character and background package paths`

处理：rebase 时跳过。

位置：
- `tools/file_util.py`
- `test/unit/tools/test_character_import.py`

原因：角色/背景包导入导出安全逻辑不属于 UI。

### `40ed1d1 refactor(runtime): use explicit worker queues`

处理：rebase 时跳过。

位置：
- `core/handlers/tts_message_handler.py`
- `core/handlers/ui_message_handler.py`
- `core/runtime/app_runtime.py`
- `core/runtime/ui_update_manager.py`
- `core/runtime/workers.py`
- `main.py`
- `test/integration/test_workers.py`
- `test/unit/test_workers_behavior.py`

原因：runtime worker 调度架构不属于 UI。

## rebase 后重新恢复到 `main` 的路径

以下路径曾因旧历史提交残留差异，已按最新 `main` 恢复：

- `assets/system/workflow/headless.yaml`
- `core/plugins/plugin_host.py`
- `core/runtime/workflow.py`
- `core/sprite/chat_ui_service.py`
- `core/sprite/sprite_cli.py`
- `docs/PLUGIN_DEVELOPER_GUIDE.md`
- `environment.yml`
- `install.bat`
- `install.command`
- `llm/history_manager.py`
- `llm/llm_manager.py`
- `requirements.txt`
- `scripts/install.sh`
- `sdk/graph.py`
- `sdk/manager.py`
- `sdk/register.py`
- `test/llm/test_stream_tool_call_accumulation.py`
- `test/unit/managers/test_tts_manager.py`
- `test/unit/test_chat_history.py`
- `test/unit/tools/test_dag_graph.py`
- `tts/tts_adapter.py`
- `tts/tts_manager.py`

这些文件对应的历史内容包括 TTS、LLM、SDK DAG、插件 SDK、workflow/runtime、安装依赖和聊天历史解析等非 UI 改动。

## 自绘文件管理器提交中的非 UI 混入处理

保留：
- `frontend/**` 自绘文件管理器实现。
- `frontend_bridge.py` 中 `Project -> Shinsekai` 根目录标签。
- `frontend_bridge.py` 中移除旧 `/api/files/pick` tkinter 文件选择接口，前端已改用自绘 `/api/files/browse`。

丢弃：
- `frontend_bridge.py` 中角色 GPT/SoVITS/reference audio 路径保存归一化逻辑。
- `tools/file_util.py` 中模型路径转换逻辑。
- `test/unit/tools/test_character_import.py` 中相关模型路径测试。
