# Agent 复用 bridge HTTP API

桌面助手通过两个通用宿主工具访问现有 HTTP routes：`shinsekai.bridge.read` 用于查询，`shinsekai.bridge.write` 用于保存、安装和执行插件动作。业务仍由原路由及其已有用例处理，不需要先迁移所有 bridge 业务逻辑。

## 调用链与装配

```text
Pi → Pi Adapter → AgentService 工具校验与执行记录
   → bridge transport HTTP 适配器 → 现有 HTTP routes → 原业务实现
```

HTTP 实现位于 `frontend_bridge_core/transport/agent_http_tools.py`。`frontend_bridge.py` 绑定 HTTP server 后，将实际地址、端口和 token 交给工具工厂，再通过 `ApplicationServices.start_agent(tools=...)` 注入 `AgentRuntime`。application 只依赖 `AgentHostTool`；模型配置变更后重建 service 时继续保留这些工具。工具不依赖 Pi，其他 backend 也可复用同一注册项。

模型只提供 `operation`、`params` 和 `body`。地址、HTTP 方法、路径模板及鉴权 header 由宿主确定；不接受模型提供的 URL、headers 或任意接口路径。HTTP 请求直接访问当前 server，不使用环境代理，也不跟随重定向。工具列表不包含 `/api/agent/*`，避免递归请求 Agent 自身。

bridge token 只保存在宿主 HTTP client 中，不传到 worker、提示词或工具 schema。响应中的凭据字段、已识别的秘密值与常见凭据文本会脱敏，同时保留人物正文、插件 schema 等业务内容。单个响应上限为 512 KiB，默认请求超时为 30 秒。

CLI 没有桌面 bridge，因此不自动注册这两个 HTTP 工具。桌面与 CLI 均开启 Pi 内置文件、搜索和 shell 工具；MCP 保持关闭。宿主工具与技能引用固定在 session 快照中；升级后新建助手 session 使用按需加载和人物创建 skill `1.3.0`。原生文件与命令结果不经过本 HTTP 适配器的脱敏、call ID 去重或操作记录，详见 [Pi 工具说明](AGENT_PI_zh-CN.md)。

## 已注册操作

`params` 仅包含路径模板中的字段，名称必须匹配；没有路径参数时省略。`body` 沿用原 HTTP API 的 JSON 参数，GET 不接受请求体。工具 schema 的枚举和描述提供当前操作清单。

| read operation | HTTP API | 参数及用途 |
| --- | --- | --- |
| `app.status` | GET `/api/health` | 应用状态 |
| `app.config` | GET `/api/config` | 脱敏配置 |
| `characters.list` | GET `/api/characters` | 当前人物和资源配置 |
| `plugins.list` | GET `/api/plugins` | 已安装插件 |
| `plugins.status` | GET `/api/plugins/status` | 加载状态 |
| `plugins.registry` | GET `/api/plugins/registry` | 安装来源目录 |
| `plugins.inspect` | GET `/api/plugins/{plugin_id}/ui` | 页面、配置 schema 和动作 |
| `tasks.get` | GET `/api/tasks/{task_id}` | bridge 后台任务状态与结果 |
| `logs.list` | GET `/api/logs` | 日志列表 |
| `logs.read` | POST `/api/logs/read` | `body.path` |
| `files.browse` | POST `/api/files/browse` | `body.path`、可选 `body.showHidden` |
| `tts.environment` | GET `/api/config/tts-bundle/recommendation` | GPU 与推理环境推荐 |

| write operation | HTTP API | 参数及用途 |
| --- | --- | --- |
| `characters.save` | POST `/api/characters` | `body.character`；编辑时带 `body.originalName` |
| `characters.sprites.import` | POST `/api/characters/sprites/upload` | `body.name`、`body.paths` |
| `plugins.install` | POST `/api/plugins/install` | `body.source`，沿用已有安装和下载机制 |
| `plugins.enable` | POST `/api/plugins/{plugin_id}/enabled` | `body.enabled` |
| `plugins.configure` | POST `/api/plugins/{plugin_id}/ui/{page_id}/config` | `body.values`，先 inspect |
| `plugins.action` | POST `/api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}` | `body.values`，使用插件提供的真实动作 |
| `tasks.cancel` | POST `/api/tasks/{task_id}/cancel` | 取消 bridge 后台任务 |
| `tts.install` | POST `/api/config/tts-bundle/download` | `body.kind`：`genie`、`gptso`、`gptso50` |

例如检查浏览器配置：

```json
{
  "operation": "plugins.inspect",
  "params": {"plugin_id": "com.shinsekai.playwright_browser"}
}
```

根据返回的真实页面 ID、schema 和当前配置，调用 write：

```json
{
  "operation": "plugins.configure",
  "params": {
    "plugin_id": "com.shinsekai.playwright_browser",
    "page_id": "playwright_browser"
  },
  "body": {"values": {"browser_type": "msedge"}}
}
```

此示例只展示参数结构。实际保存必须保留未要求改变的配置，不能将脱敏占位符写回凭据字段。人物编辑也先读取列表，传入完整人物配置，保存后重新查询核对；当前人物 HTTP API 没有 revision 条件写入。

## 受理、完成与失败

成功返回结构为 `httpStatus`、`data`、`taskId` 和 `accepted`。HTTP 202 的 `accepted=true` 只记录“已提交后台任务”这一操作事实，不能据此声称插件安装或模型下载完成。保留 `taskId`，通过 `tasks.get` 查询 `data.status`、进度和结果；后台状态包括 `queued`、`running`、`succeeded`、`failed`、`cancelled`，成功时的 `phase` 为 `completed`。避免在一个模型回合中反复忙轮询。

停止 Agent 生成不会自动取消已经提交的 bridge 任务；用户要停止安装或下载时使用 `tasks.cancel`。这些 bridge 任务沿用原有进程内任务表，不具有 Agent 数据库的跨应用重启恢复能力。

HTTP 适配器不自动重试写请求。请求失败、响应丢失或无法解析时，写操作记录为 `unknown`，先查询现有状态再决定是否重试。发出请求前发现路径参数错误时记录为 `not_applied`。AgentService 按同一 Agent task 的 call ID 去重；不同 call ID 的同一业务请求仍需按原 API 的语义核对。

HTTP 工具只暴露上表明确选择的 JSON 接口。网页搜索、导航、读取正文，媒体下载、音频切片与合成测试、游戏解包尚无专用 HTTP 接口；Pi 可通过 shell 调用本机实际可用的程序，并通过文件工具编写插件。开启工具不等于相关依赖已安装。安装角色浏览器插件不会自动把它的角色聊天工具注册给 Agent；GPU 推理推荐也不能替代训练资格检查。

## 验证

测试覆盖注册清单与真实路由匹配、输入校验、路径编码、鉴权 header、响应脱敏、错误与响应限额、后台受理语义、重复工具调用去重和模型变更后保留工具。官方 Pi binary 的 HTTP 测试通过本地模型服务验证完整的 Pi 工具调用、真实 bridge 人物查询和工具结果回传。

```powershell
python -m pytest test/unit/application/agent/test_bridge_http_tools.py -q
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_http.py -q
```
