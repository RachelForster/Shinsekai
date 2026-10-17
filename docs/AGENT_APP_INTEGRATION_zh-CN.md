# Agent 应用接入

设置页导航栏的「助手」打开普通聊天抽屉。每个 Agent session 对应一个 tab，支持新建会话、切换、关闭空闲会话、发送消息、查看流式回复、停止任务及回答 Agent 的提问。草稿按会话保存；关闭抽屉保留草稿和缓存，并停止 UI 轮询。原实用工具页面仍在 `/settings/tools`，助手顶部提供入口。

助手回复和任务摘要按 Markdown 渲染，支持标题、列表、引用、链接、代码块及 GFM 表格；流式片段与恢复后的消息使用相同渲染方式。没有选中的有效会话时隐藏消息输入区，创建会话后显示，关闭最后一个会话后再次隐藏。

每轮回复显示当前活动、目标及耗时，包括启动进程、模型处理与生成回复、读取技能、文件读写、搜索、执行命令和 HTTP 业务调用。展开「执行过程」可查看每一步的状态与耗时；运行时默认展开，结束后折叠。HTTP 步骤可继续展开参数与结果。等待输入和停止状态优先显示；任务终止时仍没有结束事件的步骤标记为已停止或已中断，不推断成功。

活动沿用持久化事件与现有游标接口，重开抽屉或应用后可恢复已记录的执行过程；旧任务没有记录的原生工具活动无法补出。Pi 原生工具仅记录动作和最多 512 字符的目标，凭据文本与已知运行凭据脱敏；不复制文件正文、完整输出或内部推理文本。更换后端可继续发送同一公共活动契约。

## 运行期与退出

`AppRuntime.services` 和 `BridgeState.services` 使用同一 `ApplicationServices` 生命周期接口。实际 Agent owner 是设置页 bridge 的 services；角色扮演进程的 AppRuntime 不启动第二份 Agent，也不接入角色委托。

bridge 完成配置和 HTTP server 装配后，调用 `services.start_agent()`。`AgentRuntime` 在后台读取现有模型配置、准备官方 Pi 运行包并启动任务调度。HTTP 的 runtime snapshot 提供阶段和进度，下载不阻塞 bridge 就绪。模型未配置或准备失败时，历史仍可读取；配置好模型后可在助手中重试。

bridge 将实际监听地址、端口和鉴权 token 交给 transport 层的 HTTP 工具工厂，通过 `start_agent(tools=...)` 注册两类业务工具。工具调用复用原有 HTTP routes，模型配置变更后仍保留注册项；凭据不进入工具 schema 或 worker。

Agent 查询人物时只取得名字列表，插件列表只取得标识、名称及状态；确定目标后按需读取一个人物或插件的详情。配置查询仅返回 API 和系统设置，避免人物库和资源列表自动进入模型上下文。精简视图由宿主固定，原前端请求保持完整响应。

Agent worker 仍按第一个任务启动，使用桌面发行包已有的 Python runtime。Tauri 的资源准备脚本已包含 `application/`、`ai/`、`core/` 和 `assets/`，不需要另装 Node。Pi 的进程和配置只在 worker 内创建。

所有 session、task、event 和提交幂等记录保存在项目 `data/agent/agent.sqlite`。应用重启后，已中断的任务保留终态，排队任务暂停；助手提供显式继续执行入口。运行期模型变更时，必须先完成或取消非终态任务，再应用当前模型。旧模型的 session 保留历史，并要求新建 session。

交互式助手默认不设置任务墙钟时限或宿主工具调用次数上限，模型等待、工具执行和长任务可以持续到完成；用户可以通过「停止」中断任务。助手 profile 由宿主开启 `use_current_limits`，新任务采用当前执行限额，所以旧 session 后续消息也不再受旧的 1 分钟、5 分钟或 20 次工具调用上限约束。每个任务仍在提交时固定最终限额；已有排队、运行和终态任务保持原值，提交重试也保持原任务。调用方显式提供的 `wallTimeMs`、`maxToolCalls` 等限制继续生效；工具名单、模型、系统策略和 skill 快照保留原会话绑定。

显式设置墙钟时限的其他 Agent profile 继续执行上限检查，超时错误的 `details` 提供 `limit=wallTimeMs`、`limitMs` 和 `elapsedMs`。助手 UI 将该错误与旧版同名错误显示为本地化的中断原因，已有超时任务可以在同一 session 发送新消息继续，不自动重放已经执行的操作。

关闭抽屉只影响界面订阅。关闭角色聊天只关闭聊天进程。退出、重启桌面应用时，Tauri 先调用 Agent stop 接口等待收尾，再处理聊天和 bridge 退出；bridge 的正常退出、信号和父进程丢失路径也调用同一 services 清理。Agent 停止接收新任务，取消活动任务并回收 worker/Pi 进程树。运行包准备取消后不能迟到启动 worker。

## HTTP

以下接口复用 bridge token 和 Origin 校验。Agent 的读取接口即使来自 loopback 也要求 token，返回的 DTO 使用公共 camelCase 契约。错误返回 `error`、`errorCode` 和 `agentError`，方便 UI 选择恢复方式。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/agent/runtime` | 准备状态、进度、模型变更、恢复队列状态 |
| POST | `/api/agent/runtime/start` | 重试准备或应用当前模型配置 |
| POST | `/api/agent/runtime/stop` | 应用退出时停止 Agent |
| POST | `/api/agent/queue/resume` | 显式恢复排队任务 |
| GET | `/api/agent/backends` | 公共后端描述；worker 尚未握手时未标记 ready |
| GET / POST | `/api/agent/sessions` | 分页读取会话 / 按宿主当前配置创建会话 |
| POST | `/api/agent/sessions/{sessionId}/close` | 关闭无活动任务的会话，保留记录 |
| POST | `/api/agent/sessions/{sessionId}/tasks` | 提交 `{requestId, text}`，立即返回受理回执 |
| GET | `/api/agent/tasks` | 通过 `sessionId`、重复 `status` 参数、`cursor`、`limit` 查询任务 |
| GET | `/api/agent/tasks/{taskId}` | 读取权威任务状态 |
| GET | `/api/agent/tasks/{taskId}/events` | 通过 `afterSeq`、`limit` 重放事件 |
| POST | `/api/agent/tasks/{taskId}/cancel` | 请求停止，返回是否受理及当前状态 |
| POST | `/api/agent/tasks/{taskId}/input` | 提交 `{inputRequestId, value}`；确认值必须是 boolean |
| POST | `/api/agent/tasks/{taskId}/detach` | 用户将任务转为独立生命周期 |
| GET | `/api/agent/artifacts/{artifactId}?revision=...` | 读取指定 revision 的 artifact |

前端不能指定 origin、权限、profile、模型、任务限额或任意资源 context。创建 session 使用空对象；普通消息只接受 requestId 和 text。UI 任务绑定固定用户来源，使用 detached 生命周期，仍随整个应用退出而停止。公共接口不包含 API Key。

UI 使用事件游标归并文本，重复页不会重复拼接消息，未知事件仍推进游标。完成文本覆盖此前流式片段；会话重新打开时可从持久化事件恢复。HTTP 受理回执丢失后，发送重试使用原 requestId，避免重复执行。

已加载插件的工具可通过 `/api/plugins/{plugin_id}/tools` 按需查询，通过 `/api/plugins/{plugin_id}/tools/{tool_name}/invoke` 调用。Agent 仍只注册两个通用 HTTP 工具，目标插件的 schema 在需要时才读取。`ApplicationServices` 持有插件工具执行线程，连续浏览器调用和关闭浏览器使用同一线程；不需要运行角色聊天。浏览器检索、打开页面和读取正文在执行过程显示对应动作、搜索词和网址。

## 验证与范围

测试覆盖真实 worker 与 HTTP server、严格读取鉴权、来源与权限防注入、分页错误、提交幂等、恢复暂停、配置变更、退出收尾，以及 UI tab、草稿、取消和输入。官方 Pi binary 的附加测试通过本地模拟模型服务验证 HTTP 对话、应用重启后的原生会话恢复和活动运行退出，不调用用户模型。

```powershell
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_http.py -q
```

前端有 1280px 与 390px 的浏览器流程测试。开发环境浏览器预览使用明确标注的示例回复；桌面和 bridge HTTP 使用实际 Pi。

活动测试还覆盖事件重放与去重、交错宿主与原生工具、当前动作在回复输出后保持可见、结束状态、计时、抽屉恢复及两种宽度的布局。官方 Pi 测试验证原生 read、write、edit 和 shell 的开始与结束事件经 worker、数据库与 HTTP 回传。

本阶段提供应用生命周期、HTTP 和普通聊天 UI，新会话由 Pi 按需加载功能介绍、诊断、人物创建和插件开发四个 skills，见 [技能说明](AGENT_SKILLS_zh-CN.md)。桌面助手已可通过 [HTTP 工具](AGENT_BRIDGE_HTTP_TOOLS_zh-CN.md) 修改人物、导入已有立绘、读取日志、管理插件，并调用已加载浏览器插件进行搜索、导航与读取正文；同时开启 Pi 原生文件、搜索及 shell 工具，可编写文件并调用实际可用的本机程序。媒体专用接口及角色委托仍需后续接入。升级后新建 session 使用新增工具操作、人物创建 skill `1.5.1` 和新提示快照。
