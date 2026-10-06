# Pi Adapter 接入

本阶段实现通用 Agent 的 Pi backend。宿主仍使用 `AgentClient` / `AgentService`，Pi 类型和原生 RPC 命令止于 worker 内的 adapter。应用生命周期、HTTP 和助手 UI 已接入，见 [应用接入说明](AGENT_APP_INTEGRATION_zh-CN.md)；实际业务工具和角色委托待后续接入。

## 运行

先在现有 API 设置中选择 LLM 提供商，配置模型、基础地址和 API Key，然后在项目 Python 环境运行：

```powershell
python -m application.agent --backend pi --task "介绍你可以如何协助排查问题"
```

首次使用会下载官方 Pi v1.0.4，显示安装进度，按固定 SHA-256 清单验证后安装。已验证的运行包会复用；无需单独安装 Node 或 Bun。也可以用 `--pi-binary <path>` 指定已安装的同版本官方 binary，worker 会核对版本。

每次 CLI 调用创建一个新 session。应用客户端可保留 `session_id`，向同一 session 继续提交任务。CLI 的默认 `basic` profile 没有业务工具；模型只能回答文本，不能自行读写应用或文件。

## 复用现有模块

- `core.downloads.download_archive` 从已有 TTS 下载器提取，保留进度、取消、`.part` 临时文件、校验和成功后替换逻辑。原 TTS 入口继续引用同一实现。
- `PiRuntimeManager` 使用现有 `filelock` 依赖串行安装，缓存官方 archive，检查安装文件，安全解压到临时目录，再切换到完整版本目录。失败和取消保留此前安装。
- `prepare_pi_agent()` 通过现有 `ConfigManager.get_llm_api_config()` / `update_llm_info()` 读取模型与凭据，并复用提供商 URL 默认值和 Claude URL 标准化。
- ChatGPT、Deepseek、Gemini、豆包、通义千问与 Ollama 使用 OpenAI compatible API；Claude 使用 Anthropic messages API。Ollama 可以无 Key；其他提供商复用已保存的 Key。未映射的插件提供商返回能力错误。

没有新增另一份模型或凭据配置。当前 Pi 使用 API 设置中选中的模型。模型、地址等连接信息形成稳定 `model_ref`，session 固定该引用；配置变更后应重新装配 service。API Key 可以轮换，下一次 worker 启动会重新读取。

## 应用装配

```python
from config.config_manager import ConfigManager
from application.agent.management import AgentService
from application.agent.pi_configuration import prepare_pi_agent

setup = prepare_pi_agent(ConfigManager())
service = AgentService(
    "data/agent/agent.sqlite",
    backend=setup.backend,
    worker_environment=setup.worker_environment,
    # 可注入已有的 AgentProfile 和 AgentHostTool 注册项。
)
service.start()
# AgentSessionRequest 的 backend_id="pi", model_ref=setup.model_ref。
# 在应用退出时调用 service.close()。
```

运行包存放在 `data/agent/runtimes/pi/`；Pi 配置、资源快照和原生 session 存放在 `data/agent/pi-sessions/<session_id>/`。这是应用私有目录，Pi 不读取用户已有 `.pi` 配置、项目 context、MCP 或自动发现的扩展。桌面 bridge 使用现有 Python runtime 启动独立 worker，并负责应用退出时的清理。

API Key 经宿主到 worker 的私有环境传入。公共 DTO、任务数据库、启动参数和 `models.json` 不包含 Key；`models.json` 仅包含环境变量引用。宿主后台启动隐藏 worker，已有进程树管理覆盖它启动的 Pi 子进程。

## 工具、输入与事件

宿主工具仍通过 `AgentHostTool.from_models()` 和 profile 注册。随应用提供的 `assets/agent/pi-host-tools.ts` 将工具转换为 Pi 工具，使用合法且稳定的原生名称；回调恢复公共工具名并保留 Pi call ID。

extension 通过仅监听 loopback、每次任务生成随机 token 的私有通道调用 adapter，再由 `AgentHostPort` 请求宿主执行。Pi 内建工具、MCP 和第三方扩展均不进入当前工具集合。实际校验、授权、幂等及写操作结果仍由宿主记录。

Pi RPC 的 `prompt` 响应只代表受理，`agent_end` 也不是整个运行的完成。adapter 持续消费 LF 分帧的 JSONL，直到 `agent_settled` 才生成终态；将文本和 provider 报告的 token 数转换为公共事件。取消先清空排队消息、请求 abort，再确认子进程退出；未确认结束的运行不能报告成功。

Pi input、select、confirm 和 editor 请求映射为公共用户输入。外部资源和 artifact 引用需要宿主先物化为文本；未物化引用返回能力错误。当前不声明 token 硬上限或结构化结果能力。

Pi 原生 session 可在下一个任务或 worker 重启后恢复。缺失历史或不匹配的绑定返回明确错误；公共层不会接收原生 session 文件。应用崩溃后的排队任务仍需显式恢复。

## 验证

常规测试包含安装与损坏修复、取消、共享下载器回归、配置映射、凭据轮换、协议异常、流式事件、工具 ID、输入和稳定终态。另有使用官方 binary 与本地模型测试服务的验证，默认不会从网络下载或调用用户的模型：

```powershell
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_binary.py -q
```

官方参考：[v1.0.4 与 SHA256SUMS](https://github.com/earendil-works/pi/releases/tag/v1.0.4)、[RPC](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/rpc.md)、[模型配置](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/models.md)、[扩展](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/extensions.md)。
