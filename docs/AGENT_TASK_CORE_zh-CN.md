# Agent 通用任务核心

本阶段实现 [系统设计](AGENT_SYSTEM_DESIGN_zh-CN.md) 的阶段 A。公共 API 与具体 backend 分离，执行循环在独立 worker 进程中运行。当前 `mock` backend 用于验证任务和工具契约。

## 运行一个任务

在项目 Python 环境中运行：

```powershell
python -m application.agent --task "验证 Agent 独立任务" --database data/agent/agent.sqlite
```

命令先输出 `queued` 回执，再输出最终任务快照。结果里的 `workerPid` 是实际执行进程，区别于 CLI 的宿主进程。数据库保存 session、task、增量事件、输入请求、文本 artifact 和工具调用记录。

应用重启后，未收尾的执行变为 `interrupted`；此前排队的任务保持暂停。CLI 通过 `--resume-queue` 明确恢复队列，应用组合根通过 `service.resume_queue()` 执行同一动作。

## 在应用中装配

```python
from application.agent.management import AgentService
from sdk.agent import AgentOrigin, AgentSessionRequest, AgentTaskRequest

origin = AgentOrigin(kind="user", caller_id="assistant-panel")

with AgentService("data/agent/agent.sqlite") as service:
    client = service.bind(origin)
    session = client.create_session(AgentSessionRequest(
        backend_id="mock", profile_id="basic", model_ref="mock-model",
    ))
    receipt = client.submit_task(AgentTaskRequest(
        request_id="a-stable-request-id", session_id=session.session_id,
        origin=origin, input={"text": "检查语音服务连接"}, lifetime="detached",
    ))
    # 在 UI 或 transport 的后续查询中获取结果；提交不等待模型生成。
    snapshot = client.get_task(receipt.task_id)
    events = client.read_events(receipt.task_id, after_seq=0)
```

实际应用应在启动组合根持有 service，应用退出时调用 `close()`。上下文管理器适合独立运行和测试。关闭会取消正在执行的任务；排队任务保留以便下次恢复。

`bind()` 的身份、允许的 profiles 和 administrator 标志必须由可信宿主选择。只有用户来源可获得管理员客户端，用于助手面板查看、接管不同调用方的任务。角色来源默认不可用，组合根接入真实聊天状态后提供 `origin_valid` 回调。

## 注册宿主工具

`application.agent.execute_host_tool.AgentHostTool.from_models()` 接收输入模型、输出模型、工具说明及执行函数，并生成 SDK 的工具定义。执行函数接收任务快照和 `AgentHostToolCall`，返回 `AgentHostToolResult`。输入模型建议使用 `ConfigDict(extra="forbid", strict=True)`，资源授权、revision 检查和实际业务调用在函数中完成。

通过 `AgentProfile(tool_names=(...))` 指定工具名单，在 `AgentService(profiles=(...), tools=(...))` 注入注册项。session 会保存 profile 快照。模型、skill 和后端不能自行添加工具。

默认情况下，任务限额采用 session 的 profile 快照，请求只能收紧限额。可信宿主可以通过 `AgentProfile(use_current_limits=True)` 让之后提交的新任务采用当前 profile 的执行限额；不会改写已有任务和提交幂等记录，也不更新 session 的工具、技能及其他权限快照。交互式助手启用此策略，`wall_time_ms=None` 表示不设置任务墙钟上限；其他 profile 默认仍保存限额快照。

写入、执行工具必须返回与当前调用 ID、工具名关联的 `AgentEffect`，说明 `applied`、`not_applied` 或 `unknown`。后端最终结果不能覆盖宿主操作记录；artifact 也由宿主 `publish_text_artifact()` 创建，并按真实 revision 读取。

同一任务中的同一 `callId` 和相同参数返回已记录结果；不同参数返回 `IDEMPOTENCY_CONFLICT`。崩溃留下未完成记录时返回未知结果，不自动执行第二次。工具与外部业务存储之间没有跨库事务，恢复时保留不确定性。

## 执行与协议约束

- 有界 FIFO 队列，一次运行一个任务；不同 session 串行执行。
- private stdin/stdout 上运行 UTF-8 JSONL / JSON-RPC 2.0，单帧最多 1 MiB。协议 reader、writer 与请求处理分开，工具和输入等待不阻塞取消或心跳。
- backend 通过 `AgentHostPort` 请求工具和用户输入。工具活动、输入状态、artifact 及最终操作事实由宿主记录。
- backend 可以报告与宿主当前状态一致的 `task.status` 进度，不能自行改变任务生命周期。`task.completed` 等待 backend 迭代器结束后才发布。
- 相同 worker 事件只入库一次；未知事件保存后在公共读取时跳过，并推进游标。晚到的旧 attempt 或终态事件不会重复完成任务。
- 墙钟时限包含输入等待；工具预算计算唯一调用，也包括被拒绝的调用。不支持的 token 限额返回明确的能力错误。
- 取消先阻止新工具，再请求 worker 停止。已经开始的写操作仍需核对；未知结果报告 `interrupted`，不报告撤销。
- Windows 使用隐藏进程和 Job Object 管理进程树；其他平台使用进程组。宿主退出或 supervisor 关闭会清理执行进程。

输入请求带独立有效期，只能由真实用户回答。相同回答幂等，不同回答冲突；过期或已停止任务的回答被拒绝。`waiting_input` 占用当前执行槽。

mock backend 不声明原生 session 恢复或精确 token 限额。旧 session 的 worker 已更换时，创建新 session 并显式携带之前的结果继续工作。

## 验证与后续接入

```powershell
python -m pytest test/unit/application/agent test/unit/core/agent test/unit/sdk/test_agent_contracts.py test/unit/architecture/test_import_boundaries.py -q
```

测试使用真实 worker 子进程，覆盖提交、串行队列、幂等、事件重放、取消、输入、宿主写入竞争、进程崩溃、数据库 owner 和恢复暂停。

Pi adapter、运行包下载与校验、现有配置复用、session 映射及工具 extension 已接入，见 [Pi 接入说明](AGENT_PI_zh-CN.md)。应用生命周期、HTTP 与 React 助手入口也已实现，见 [应用接入说明](AGENT_APP_INTEGRATION_zh-CN.md)。实际人物与诊断工具、业务 skills 和角色 inbox 按后续阶段接入。
