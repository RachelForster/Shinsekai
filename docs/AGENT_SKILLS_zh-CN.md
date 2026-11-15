# Agent Skills

Pi v1.0.4 使用 Agent Skills 格式：一个目录以 `SKILL.md` 为入口，YAML frontmatter 的 `name` 和 `description` 用于技能识别与路由，正文写任务流程。标准加载先向模型展示技能摘要，任务匹配后再读取正文。详见 [Pi 官方说明](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/docs/skills.md)。

Shinsekai 的技能内容由应用维护，公共 session 只保存 `skillRefs`。Pi Adapter 负责物化资源；技能文件本身不依赖 Pi RPC，也不进入角色扮演系统提示。

## 首批技能

```text
assets/agent/
  system-policy.md
  skills/
    shinsekai-guide/SKILL.md
    shinsekai-diagnostics/SKILL.md
    shinsekai-character-creation/SKILL.md
    shinsekai-plugin-development/SKILL.md
```

| 技能 | 使用时机 | 当前可交付内容 |
| --- | --- | --- |
| `shinsekai-guide` | 功能介绍、入口和使用方法 | 根据已有功能提供页面路径和操作步骤 |
| `shinsekai-diagnostics` | 报错、启动失败或 debug | 分析用户提供的证据，提出并区分修复与验证步骤 |
| `shinsekai-character-creation` | 创建或修改人物、收集人物素材 | 按需择一查询资料、保存人物，通过 HTTP 默认生成并导入 10 张 H3 静态立绘，准备所需语音 |
| `shinsekai-plugin-development` | 创建、扩展或修复插件 | 根据现有 SDK 起草代码，提供脚手架和检查流程 |

业务操作以实际工具目录为准。桌面助手已注入 `shinsekai.bridge.read`、`shinsekai.bridge.write`，复用现有 HTTP API 查询日志和配置、保存人物、导入立绘及管理插件，见 [HTTP 工具说明](AGENT_BRIDGE_HTTP_TOOLS_zh-CN.md)。桌面与 CLI 均开启 Pi 原生文件、搜索和 shell 工具；CLI 不自动注册桌面 HTTP 工具。技能在缺少能力时交付草稿与操作步骤，并据真实工具结果声明完成。

## 当前加载方式

`application/agent/skills.py` 保存显式技能清单及各技能版本，引用形式为 `skill:<name>@<version>`。人物创建技能为 `1.7.0`，故障排查为 `1.1.0`，其余保持 `1.0.0`；`ASSISTANT_PROFILE` 选择这四个引用，桌面助手和 Pi CLI 的新会话均使用它们。`prepare_pi_agent()` 默认解析随应用发布的文件路径，显式传入 `skill_paths` 时使用调用方的映射，包括空映射。

当前默认 `skillLoading=native`。Adapter 在首次打开会话时将选定技能保存为独立的 `SKILL.md` 快照，通过显式 `--skill` 路径交给 Pi。系统策略只保存通用行为规则；Pi 原生目录向模型展示名称、简介和路径，由模型根据任务选择并使用 `read` 读取正文。详细流程见 [系统提示实现](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/src/core/system-prompt.ts)。四份技能正文不再提前加入系统提示。

Pi 的 `read`、`bash`、`powershell`、`edit`、`write`、`grep`、`find`、`ls` 与注册的 HTTP 工具共同可用。理性、独立判断和如实报告结果仍由 `system-policy.md` 始终约束。`skillLoading=preload` 作为显式兼容选项保留，其合并策略仍受 65,536 UTF-8 字节上限约束；旧会话的全文提示快照不会自动缩减，使用新建 session 体验按需加载。

恢复已有 Pi 会话时使用原快照，不重新读取改变后的资源。旧会话的技能引用也保持原值；升级后要体验新技能，应新建助手 session。修改已发布的技能时更新版本和引用，已有快照不自动迁移。

桌面资源准备脚本已经包含 `assets/`，无需新增下载包或另一份模型配置。首批技能是自包含文本；以后增加 `references/` 或 `scripts/` 时，需要同步实现支持文件快照。

## 人物创建流程与工具接入

人物创建 `1.7.0` 的流程如下，技能正文自包含在同一个 `SKILL.md` 中，并说明 HTTP 工具、Pi 文件与 shell 工具的使用方式，以及异步受理和失败核对方式。技能入口直接给出新建字段、默认值、完整保存 JSON，以及「背景信息、性格特点、语言习惯」三段纯文本模板。新建只查名字列表防重名，不读取其他人物的设定作为范例；编辑才读取指定目标，新建保存后查询新人物核对。网页资料优先通过轻量 JSON/HTTP 接口（如 Bangumi API、MediaWiki `api.php`、`curl.exe`）获取，无需默认依赖 Playwright；仅纯前端动态渲染页面或用户指定浏览器时才调用浏览器插件。工具连续失败时先检查错误与实际状态；没有新证据时不重复相同调用，改用有效来源或已有直接 HTTP 能力，无法完成的部分明确报告。通用策略也要求仅展开当前任务需要的详情；`app.config` 只返回 API 和系统设置。

1. 需要浏览器时查询插件、加载状态和 Agent 工具是否可用。有安装与配置能力且任务已授权时自动补齐；否则引导安装。保留用户偏好，无偏好时 Windows 优先可启动的 Edge，再选 Chrome 或 Playwright Chromium；只配置插件后端。
2. 已有资料够用就不搜索；百科、官网等来源为备选关系，通常读取一个有效页面即可。关键缺项或冲突时才补查；同名或版本不明时确认身份。
3. 需要声音时从 B 站、官方音声等来源择一获取干净的单人角色语音。下载和处理时保留原文件及来源，核对人物、配音版本与语言，有 BGM 时优先更换素材再考虑人声分离。
4. 检测硬件、当前 GPT-SoVITS 环境和数据质量。单卡至少 8GB 是此流程的保守自动推荐训练门槛，不能替代版本与可用资源检查；不满足条件时截取 3–10 秒参考语音，并准备匹配文本、语言及现有推理服务。
5. 保存人物后复用一张参考图，通过 HTTP `characters.sprites.plan`（默认 count=10）、逐张 `render`、`import_generated` 生成并导入 10 张静态立绘。没有参考图时先生成一张基准图，再生成剩余 9 张。查任务确认完成，失败逐张处理，抠图可单独重试；只要官方素材时按用户范围跳过生成。
6. 仅按名字读取要编辑的人物，通过已有人物与资源用例保存，再查询该人物检查引用与语音合成结果；按实际状态交付设定、来源、素材和未完成事项。

自动下载优先采用 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，其命令行与音频提取方式适合宿主工具调用，音频提取依赖 ffmpeg/ffprobe。仓库现有音乐翻唱流程也已经使用它。用户提到的 [哔哩下载姬原仓库](https://github.com/leiurayer/downkyi)截至 2026-10-06 已公告停止维护并永久关停，不作为新增自动流程的默认依赖。站点支持和访问失败必须以实际下载结果为准。

[GPT-SoVITS 官方说明](https://github.com/RVC-Boss/GPT-SoVITS)支持约 5 秒参考声音的零样本推理，训练与推理的环境要求应分别评估。应用已有人物校验采用 3–10 秒参考音频范围；8GB 训练起点属于本技能策略。参考语音本身不能替代基础模型和可用的推理服务。

以下列出已接入的 HTTP 能力及仍需补充的能力，具体 operation 见 HTTP 工具说明：

| 能力 | 可复用入口 | Agent 接入情况 |
| --- | --- | --- |
| 插件查询、安装、配置 | `application/plugins/catalog.py`、`application/plugins/install_plugin.py`、插件前端配置 contribution | 已通过 HTTP 工具接入 |
| 网页搜索、导航、读取正文 | Playwright Browser 插件，ID `com.shinsekai.playwright_browser` | 已通过通用 HTTP 插件工具入口接入 Agent，按需发现 schema |
| 媒体搜索、下载、人声分离 | `application/characters/voice/pipeline/` 与 `tools/uvr5_headless_entry.py` | 已通过 `characters.voice.prepare` 接入（含 B 站语音合集检索、独立 `yt-dlp` 校验下载与内置 UVR5 分离） |
| GPU 检测与 TTS 环境 | `core/model_assets/tts_environment.py`、现有模型与凭据配置 | 已接推理环境查询与整合包下载；`characters.voice.prepare` 自动探测显卡批次与预训练白模 |
| 训练、转写、权重检查 | `application/characters/voice/pipeline/` 及可选批量训练插件 `local.gpt_sovits_batch_trainer` | `characters.voice.prepare` 默认免训练挂白模直用，支持 `train=true` 微调 `v2ProPlus` |
| 参考音频切片、质量与合成检查 | `application/characters/voice/pipeline/reference_selection.py`、`synthesis_verification.py` | 已通过 `characters.voice.prepare` 自动完成切片、ASR、声学优选与短句合成自检 |
| 人物保存、语音绑定、立绘导入 | `application/characters/management.py` 的 `CharacterUseCase` | 已完整接通人物保存、静态立绘生成导入与角色语音自动准备绑定 |
| 游戏资源提取 | 用户指定游戏对应的可用工具 | 尚无通用解包入口；缺少能力时提供准备步骤 |

HTTP 能力经 `AgentHostTool.from_models()`、`AgentProfile.tool_names` 和 `AgentService.tools` 显式注册，Pi 原生工具由 Adapter 启用。已加载浏览器插件的工具通过 HTTP 按插件查询和调用，无需角色聊天会话；插件、浏览器及其他媒体和训练依赖仍须实际可用。

## 如何编写新技能

1. 创建 `assets/agent/skills/<name>/SKILL.md`。目录名和 `name` 使用相同的小写字母、数字和连字符名称。
2. description 写清「做什么、什么时候使用」，正文写输入要求、执行步骤、失败恢复和完成依据。
3. 依据实际工具 schema 编写操作流程。没有工具时说明可交付的草稿或用户步骤，不虚构权限和操作结果。
4. 在应用显式清单和对应 profile 中登记引用及版本；由 Adapter 加载，不从用户机器扫描任意技能。

例如：

```markdown
---
name: shinsekai-example
description: 根据用户提供的资料整理示例任务。在用户要求整理该类资料时使用。
metadata:
  version: "1.0.0"
---

# 示例任务

整理已知资料，标出缺失信息，给出结果与验证依据。
```

在助手 UI 中使用普通请求，例如「介绍新世界的功能」「帮我分析这个启动错误」「创建一位修复师角色」「起草一个插件」。独立 Pi 的 `/skill:<name>` 是原生命令；Shinsekai 当前的消息接口把输入作为任务文本传入，不承诺原生命令菜单语义。

## 验证

测试检查技能格式、版本与路径、按需模式不预载正文、显式 preload 兼容、恢复快照、合并提示上限，以及默认和自定义映射。官方 Pi 的 HTTP 测试验证首个请求只有技能目录，模型调用原生 `read` 后对应正文进入上下文，同时验证文件写入、编辑、shell、HTTP 工具与会话重启。

```powershell
python -m pytest test/unit/application/agent/test_skills.py -q
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_http.py -q
```
