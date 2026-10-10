# Agent 复用 bridge HTTP API

桌面助手通过两个通用宿主工具访问现有 HTTP routes：`shinsekai.bridge.read` 用于查询，`shinsekai.bridge.write` 用于保存、安装和执行插件动作。业务仍由原路由及其已有用例处理，不需要先迁移所有 bridge 业务逻辑。

## 调用链与装配

```text
Pi → Pi Adapter → AgentService 工具校验与执行记录
   → bridge transport HTTP 适配器 → 现有 HTTP routes → 原业务实现
```

HTTP 实现位于 `frontend_bridge_core/transport/agent_http_tools.py`。`frontend_bridge.py` 绑定 HTTP server 后，将实际地址、端口和 token 交给工具工厂，再通过 `ApplicationServices.start_agent(tools=...)` 注入 `AgentRuntime`。application 只依赖 `AgentHostTool`；模型配置变更后重建 service 时继续保留这些工具。工具不依赖 Pi，其他 backend 也可复用同一注册项。

模型只提供 `operation`、`params` 和 `body`。地址、HTTP 方法、路径模板及鉴权 header 由宿主确定；不接受模型提供的 URL、headers 或任意接口路径。HTTP 请求直接访问当前 server，不使用环境代理，也不跟随重定向。工具列表不包含 `/api/agent/*`，避免递归请求 Agent 自身。

bridge token 只保存在宿主 HTTP client 中，不传到 worker、提示词或工具 schema。响应中的凭据字段、已识别的秘密值与常见凭据文本会脱敏，同时保留人物正文、插件 schema 等业务内容。单个响应上限为 512 KiB，默认请求超时为 30 秒；插件工具调用为 90 秒，以覆盖浏览器启动与网页导航。

CLI 没有桌面 bridge，因此不自动注册这两个 HTTP 工具。桌面与 CLI 均开启 Pi 内置文件、搜索和 shell 工具；MCP 保持关闭。宿主工具与技能引用固定在 session 快照中；升级后新建助手 session 使用新增插件工具操作和人物创建 skill `1.5.1`。原生文件与命令结果不经过本 HTTP 适配器的脱敏、call ID 去重或操作记录，详见 [Pi 工具说明](AGENT_PI_zh-CN.md)。

## 已注册操作

`params` 仅包含该操作要求的标识字段，名称必须匹配；没有标识参数时省略。宿主将标识编码进路径或查询参数，并固定列表的精简视图，模型不能覆盖 `view`。`body` 沿用原 HTTP API 的 JSON 参数，GET 不接受请求体。工具 schema 的枚举和描述提供当前操作清单。

| read operation | HTTP API | 参数及用途 |
| --- | --- | --- |
| `app.status` | GET `/api/health` | 应用状态 |
| `app.config` | GET `/api/config?view=agent` | 仅脱敏 API 和系统设置 |
| `characters.list` | GET `/api/characters?view=names` | 仅人物名字字符串列表 |
| `characters.get` | GET `/api/characters?name=...` | `params.name`；一个人物的完整配置 |
| `plugins.list` | GET `/api/plugins?view=summary` | 仅 `id`、`title`、`enabled`、`loaded` |
| `plugins.status` | GET `/api/plugins/status` | 加载状态 |
| `plugins.registry` | GET `/api/plugins/registry?view=summary` | 仅 `id`、`displayName`、`installed`；`id` 用作安装来源 |
| `plugins.inspect` | GET `/api/plugins/{plugin_id}/ui` | 页面、配置 schema 和动作 |
| `plugins.tools` | GET `/api/plugins/{plugin_id}/tools` | 仅指定已加载插件的工具名称、说明、输入 schema、分组和风险 |
| `tasks.get` | GET `/api/tasks/{task_id}` | bridge 后台任务状态与结果 |
| `logs.list` | GET `/api/logs` | 日志列表 |
| `logs.read` | POST `/api/logs/read` | `body.path` |
| `files.browse` | POST `/api/files/browse` | `body.path`、可选 `body.showHidden` |
| `tts.environment` | GET `/api/config/tts-bundle/recommendation` | GPU 与推理环境推荐 |

| write operation | HTTP API | 参数及用途 |
| --- | --- | --- |
| `characters.save` | POST `/api/characters` | `body.character`；编辑时带 `body.originalName` |
| `characters.sprites.import` | POST `/api/characters/sprites/upload` | `body.name`、`body.paths`；可选 `body.spriteTags` 为与路径一一对应的新立绘标签，不覆盖旧立绘标签 |
| `tools.sprite-prompts.generate` | POST `/api/tools/sprite-prompts` | `body.characterName`、`body.count`；使用已配置的 LLM Adapter 编写提示词，返回后台任务 |
| `tools.sprites.generate` | POST `/api/tools/sprites/generate` | `body.characterName`、`body.referenceImages`（1–10 个本地图片路径）、`body.prompts`；`body.provider` 为 `configured` 或 `gemini`，可选 `body.outputDir`、`body.autoLabel`、`body.seed`（-1 随机）；返回后台任务，启用标注时结果包含与 `files` 对齐的 `labels` 和逐图 `labelErrors` |
| `plugins.install` | POST `/api/plugins/install` | `body.source`，沿用已有安装和下载机制 |
| `plugins.enable` | POST `/api/plugins/{plugin_id}/enabled` | `body.enabled` |
| `plugins.configure` | POST `/api/plugins/{plugin_id}/ui/{page_id}/config` | `body.values`，先 inspect |
| `plugins.action` | POST `/api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}` | `body.values`，使用插件提供的真实动作 |
| `plugins.tools.invoke` | POST `/api/plugins/{plugin_id}/tools/{tool_name}/invoke` | `body.arguments`，按目标工具的真实 schema 调用 |
| `tasks.cancel` | POST `/api/tasks/{task_id}/cancel` | 取消 bridge 后台任务 |
| `tts.install` | POST `/api/config/tts-bundle/download` | `body.kind`：`genie`、`gptso`、`gptso50` |

人物和插件先查名字或精简列表，确定任务目标后再读单项详情，不批量展开无关设定、资源或配置。精简在 HTTP 路由序列化响应前完成，人物库或插件说明较大时，列表不会因这些详情触及 512 KiB 限额。前端不带 `view` 的原有列表与配置请求保持完整响应。

例如 `characters.list` 的 `data` 为 `["Alice", "Bob"]`。只需要编辑 Alice 时，再调用：

```json
{
  "operation": "characters.get",
  "params": {"name": "Alice"}
}
```

姓名作为一个查询参数编码，可包含空格、斜杠和特殊符号；目标不存在时返回错误，不回退到全部人物。`app.config` 也不包含人物、背景、特效或插件列表。

例如检查选定的浏览器插件配置：

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

此示例只展示参数结构。实际保存必须保留未要求改变的配置，不能将脱敏占位符写回凭据字段。人物编辑通过 `characters.get` 读取目标的完整配置，保存后仍按该人物名字重新查询核对；当前人物 HTTP API 没有 revision 条件写入。

浏览器插件的设置动作与 LLM 工具是两个入口。先调用 read 的 `plugins.tools`，`params.plugin_id` 为 `com.shinsekai.playwright_browser`；仅在返回目录确实包含相应名称时调用，例如 write：

```json
{
  "operation": "plugins.tools.invoke",
  "params": {
    "plugin_id": "com.shinsekai.playwright_browser",
    "tool_name": "playwright_search_web"
  },
  "body": {"arguments": {"query": "人物名 作品名 百度百科"}}
}
```

`playwright_navigate` 接收 `url`，`playwright_get_text` 的 `arguments` 为 `{}`；网页正文位于 `data.result`。工具目录按插件查询，不提前把所有插件工具 schema 放入模型上下文。插件必须已经加载并启用，调用只能选择目录内、来源属于该插件包的工具；参数校验失败、插件报错不会记为成功执行。目录读取即使在 loopback 也要求 bridge token 和可信 Origin，调用沿用写接口鉴权。

`application/plugins/tools.py` 复用已加载的 ToolManager，由 `ApplicationServices` 持有唯一执行线程。浏览器启动、后续操作和退出清理在同一线程执行，避免多次 HTTP 请求切换线程导致 Playwright 会话失效。不依赖角色聊天进程，也不在 Pi worker 重新加载插件。退出应用时先等待 Agent 工具收尾，再清理使用过的插件及执行线程。助手活动区显示真实插件工具名称，并显示搜索词、网址或定位选择器。

## 受理、完成与失败

成功返回结构为 `httpStatus`、`data`、`taskId` 和 `accepted`。HTTP 202 的 `accepted=true` 只记录“已提交后台任务”这一操作事实，不能据此声称插件安装或模型下载完成。保留 `taskId`，通过 `tasks.get` 查询 `data.status`、进度和结果；后台状态包括 `queued`、`running`、`succeeded`、`failed`、`cancelled`，成功时的 `phase` 为 `completed`。避免在一个模型回合中反复忙轮询。

停止 Agent 生成不会自动取消已经提交的 bridge 任务；用户要停止安装或下载时使用 `tasks.cancel`。这些 bridge 任务沿用原有进程内任务表，不具有 Agent 数据库的跨应用重启恢复能力。

HTTP 适配器不自动重试写请求。请求失败、响应丢失或无法解析时，写操作记录为 `unknown`，先查询现有状态再决定是否重试。发出请求前发现路径参数错误时记录为 `not_applied`。AgentService 按同一 Agent task 的 call ID 去重；不同 call ID 的同一业务请求仍需按原 API 的语义核对。

HTTP 工具只暴露上表明确选择的 JSON 接口。已加载浏览器插件的搜索、导航和正文读取可通过插件工具接口调用；插件未安装、未启用、浏览器缺失或搜索服务不可用时仍需按实际错误处理。媒体下载、音频切片与合成测试、游戏解包取决于插件提供的真实工具或本机实际可用的程序；开启工具不等于相关依赖已安装。GPU 推理推荐也不能替代训练资格检查。

## 验证

测试覆盖注册清单与真实路由匹配、输入校验、路径与姓名查询编码、鉴权 header、响应脱敏、错误与响应限额、后台受理语义、重复工具调用去重和模型变更后保留工具。真实 HTTP 测试验证超过响应限额的详情集合仍能返回精简列表、单项查询不带其他人物、配置查询不序列化人物库，以及原前端完整响应保持兼容。官方 Pi binary 的 HTTP 测试通过本地模型服务验证完整调用链，确认人物设定没有随名字列表进入模型上下文。

```powershell
python -m pytest test/unit/application/agent/test_bridge_http_tools.py -q
python -m pytest test/unit/frontend_bridge_core/test_agent_query_views.py -q
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_http.py -q
```
