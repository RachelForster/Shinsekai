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
| `shinsekai-character-creation` | 创建或修改人物 | 人物简介、详细人设和资源需求草稿 |
| `shinsekai-plugin-development` | 创建、扩展或修复插件 | 根据现有 SDK 起草代码，提供脚手架和检查流程 |

业务操作以宿主实际注册的工具为准。当前 basic profile 没有业务工具，不能自动读取日志、保存人物、写文件、执行插件检查或安装插件。技能会在缺少这些能力时交付草稿与操作步骤，并据真实工具结果声明完成。

## 当前加载方式

`application/agent/skills.py` 保存显式技能清单及版本。首版引用为 `skill:<name>@1.0.0`；`ASSISTANT_PROFILE` 选择这四个引用，桌面助手和 Pi CLI 的新会话均使用它们。`prepare_pi_agent()` 默认解析随应用发布的文件路径，显式传入 `skill_paths` 时使用调用方的映射，包括空映射。

Pi 内置文件读取工具当前关闭，而且 v1.0.4 在没有 `read` 或 `bash` 工具时不会加入原生技能目录，见 [系统提示实现](https://github.com/earendil-works/pi/blob/v1.0.4/packages/coding-agent/src/core/system-prompt.ts)。首版设置 `skillLoading=preload`：Adapter 在首次打开 Pi 会话时将选定技能保存到独立的 `SKILL.md` 路径，并将完整正文加入系统策略快照；同时保留 Pi 的显式技能注册。合并后的系统策略上限为 65,536 UTF-8 字节。

技能正文按任务使用，预载不授予任何新工具权限。理性、独立判断和如实报告结果仍由 `system-policy.md` 始终约束。底层的 `skillLoading=native` 选项只保留显式技能注册而不预载正文；完整的按需方案还需要受限资源读取与 Pi 技能目录投影，当前助手使用 preload。

恢复已有 Pi 会话时使用原快照，不重新读取改变后的资源。旧会话的技能引用也保持原值；升级后要体验新技能，应新建助手 session。修改已发布的技能时更新版本和引用，已有快照不自动迁移。

桌面资源准备脚本已经包含 `assets/`，无需新增下载包或另一份模型配置。首批技能是自包含文本；以后增加 `references/` 或 `scripts/` 时，需要同步实现支持文件快照及相应宿主工具。

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

测试检查技能格式、版本与路径、无读取工具时的正文可用性、恢复快照、合并提示上限，以及默认和自定义映射。官方 Pi 的 HTTP 测试还检查发送给模型的系统消息确实包含完整技能正文，并验证会话重启后继续使用。

```powershell
python -m pytest test/unit/application/agent/test_skills.py -q
$env:SHINSEKAI_TEST_PI_BINARY = "<已验证的官方 pi.exe 路径>"
python -m pytest test/unit/application/agent/test_pi_http.py -q
```
