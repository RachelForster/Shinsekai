# Shinsekai AI 剧本系统设计

> 状态：草案
> 更新日期：2026-08-06
> 适用范围：AI 剧本生成、剧情节点运行时、剧情状态、对话分支存档与 React 创作界面
> 相关规范：[`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md)、[`CHAT_UI_THEME_GUIDE_zh-CN.md`](CHAT_UI_THEME_GUIDE_zh-CN.md)

## 1. 摘要

本文定义 Shinsekai 的 AI 剧本系统。系统允许用户输入一段自然语言剧情梗概，由 LLM 生成相对完整、可编辑、可校验、可运行的剧情工程；运行时由确定性的剧情引擎控制节点、条件、状态、动态演员表、解锁和结局，LLM 负责剧本创作、自由输入理解与对白演出。

核心定位是：

> 固定关键节点与规则，允许节点之间自由对话；AI 拥有创作权，剧情引擎拥有裁判权。

系统采用模块化单体架构，不引入独立微服务。依赖由上层指向下层：`frontend / CLI → frontend_bridge_core → application → ai / core / config / sdk`；下层能力不得反向导入 application、bridge 或 frontend。没有结构化剧本的现有自由聊天模式继续兼容。

实施早期先完成手写剧本的编译、确定性运行和会话闭环，再接入 AI 剧本编译器。不得先生成大量暂时无法校验或执行的剧本文件。

## 2. 背景与现状

### 2.1 已有能力

Shinsekai 当前已经具备以下基础：

- 用户可以通过聊天模板中的“情景”描述剧情走向。
- LLM 输出协议支持对白、旁白、选项、数值、场景、BGM、CG 和特效。
- 聊天舞台使用实时事件、快照和 React reducer 驱动。
- 对话历史支持回溯、重新生成、Fork、分支切换和分支树展示。
- 对话历史与分支元数据能够持久化。
- 长期记忆可以跨会话保留人物关系、事件和用户信息。
- 模板生成器与插件输出契约能够扩展 LLM 输出字段和要求。

### 2.2 当前不足

当前“剧情状态”主要存在于 Prompt、聊天历史、长期记忆或 LLM 生成的 `STAT` 文本中，因此不具备以下保证：

- 状态值不能作为权威数据稳定读取和修改。
- 选项只有显示文本，没有稳定的 `choiceId`、进入条件和效果。
- 对话分支只保存 `messages` 与 `history`，不保存语义剧情状态。
- LLM 可能提前触发锁定剧情、忘记前置条件或移动解锁门槛。
- 完整 Prompt 不能可靠隔离尚未解锁的秘密内容。
- 缺少不可到达节点、死路、变量引用和结局覆盖校验。
- 缺少从自然语言梗概生成结构化剧情工程的稳定协议。

### 2.3 当前系统形态判断

现有行为接近“完全即兴模式”：LLM 同时承担作者、自由输入理解、场景演出和部分状态判断。目标系统应演进为“受约束的边玩边写”：

- 开局生成并冻结近期剧情节点。
- 普通轮次只向场景 LLM 暴露当前可见上下文。
- 到达章节边界时，作者 LLM 可以扩写尚未承诺的未来。
- 已发布的条件、已经发生的事件和分支状态不得被 LLM 随意改写。

## 3. 目标与非目标

### 3.1 目标

系统必须支持：

1. 用户从自然语言剧情梗概创建剧本草稿。
2. AI 分阶段生成故事圣经、变量、节点、选择、条件、效果和结局。
3. 剧本经过结构校验和路径模拟后才能发布。
4. 剧情引擎确定性地执行条件、效果、节点跳转和结局判定。
5. 玩家在固定节点之间使用自然语言自由行动和对话。
6. LLM 只能提出剧情事件，不能直接修改权威状态。
7. LLM 可以从普通对话中提出预定义的语义信号，由规则引擎将其转换为受控的通用叙事指标变化。
8. 未解锁秘密在进入场景 LLM 上下文前被过滤。
9. 剧情状态与对话分支一起 Fork、切换、回溯和保存。
10. 旧聊天模板、旧存档和纯自由聊天模式继续可用。
11. 创作者可以局部编辑、重新生成、校验和发布剧本。
12. 剧本可以登记大量人物，并按场景使用固定、混合、角色职责或动态策略解析本轮 `ActiveCast`。
13. 剧情运行中可以在受控条件下导入、登场、退场、替换或晋升人物，而不要求开局固定完整演员表。

### 3.2 非目标

首版不包含：

- 通用编程语言或任意脚本执行。
- 多人联网同步剧情状态。
- 云端协作编辑和权限管理。
- 完整替代 Ren'Py、Unity 等传统视觉小说编辑器。
- 对每一句台词进行预写和严格锁定。
- 自动保证文学质量；系统只保证结构、状态和运行一致性。
- 在首版开放第三方插件直接修改剧情引擎内部状态。
- 根据剧情语义信号建立跨剧本的真实用户心理、人格或敏感属性画像。
- 允许 LLM 扫描本地角色目录、读取未经用户选择的 `.char` 文件或自行引用未登记人物。
- 让项目可登记人物数量等同于单场景可同时激活人物数量；后者必须受上下文、UI 和资源预算限制。

## 4. 术语

| 术语 | 含义 |
| --- | --- |
| 剧本工程 `StoryProject` | 可发布、可版本化的完整结构化剧本定义 |
| 故事圣经 `StoryBible` | 世界观、人物关系、秘密、主题与不可随意推翻的事实 |
| 节点 `StoryNode` | 一个可进入、可完成、可跳转的关键剧情锚点 |
| 选择 `StoryChoice` | 具有稳定 ID、条件、效果和目标节点的玩家行动 |
| 分支状态 `BranchStoryState` | 当前节点、branch 变量、道具、标记、完成节点和事件头 |
| 全局进度 `GlobalStoryProgress` | 不随 Fork 或回档撤销的结局、CG 和周目解锁 |
| 状态视图 `StoryStateView` | 规则求值时组合分支状态与全局进度的只读视图，不作为整体持久化 |
| 条件 `Condition` | 对状态进行只读判断的声明式表达式 |
| 效果 `Effect` | 对状态执行受控修改的声明式操作 |
| 剧情事件 `StoryEvent` | 已接受命令产生的不可变事实记录 |
| 叙事指标 `StoryMetric` | 具有范围、可见性、变化策略和阈值用途的数值型 `StoryVariable` |
| 语义信号定义 `SemanticSignalDefinition` | 剧本预先发布的语义判定标准及其受控效果 |
| 语义信号 `SemanticSignal` | LLM 从玩家自由文本中识别并提交的候选语义事件 |
| 剧情图 `NarrativeGraph` | 由场景、章节、Hub、分支和结局等 `StoryNode` 构成的剧情结构 |
| 逻辑图 `RuleGraph` | 由信号、指标引用、条件、策略、效果和解锁等类型化 `RuleNode` 构成的创作结构 |
| 规则节点 `RuleNode` | 具有稳定类型、配置和强类型端口的逻辑图节点，不等同于可进入的剧情节点 |
| 剧情程序 `StoryProgram` | `NarrativeGraph + RuleGraph` 校验并编译后的确定性运行时产物 |
| 正史 `Canon` | 当前世界线已经成立、可供 LLM 使用的事实集合 |
| 作者 LLM | 生成或扩写剧本工程，能够看到完整创作上下文 |
| 场景 LLM | 依据可见上下文理解自由输入，并生成对白、旁白和演出指令 |
| 意图解析 | 将玩家自由文本映射为当前节点允许的主动行动；它是场景 LLM 的逻辑职责，不要求独立模型 |
| 语义信号评估 | 判断玩家表达是否匹配预定义语义标准；它可由场景 LLM 或隔离的评估调用完成 |
| 承诺节点 | 已发布且条件被冻结、不能被动态作者随意修改的节点 |
| 剧情投影 `ActorContext` | 从完整剧本和当前状态中筛出的安全演出上下文 |
| 人物登记表 `CharacterRegistry` | 剧本可引用人物的稳定 ID、来源、版本、标签和加载策略目录 |
| 演员策略 `CastPolicy` | 场景声明的必需人物、角色职责、候选范围、排除项和人数约束 |
| 当前演员表 `ActiveCast` | 在本轮场景演出前已经由引擎解析并提交、允许正式发言的人物集合 |
| 选角规划器 `CastPlanner` | 可选的规则或 LLM 候选选择器，只能从引擎提供的合格人物 ID 中提案 |
| 剧本域人物 `StoryScopedCharacter` | 由剧本携带或作者 AI 生成并随剧本版本固化的人物 |
| 临时人物 `AdHocCharacter` | 在受限模板下临时生成、默认只在当前分支或场景存在的 NPC |

## 5. 设计原则

### 5.1 LLM 创作，程序裁决

LLM 可以创建节点、设置条件、提出事件和生成演出，但只有剧情引擎能够修改权威状态。任何由 LLM 直接输出的指标增减、道具或节点变化都只是候选数据。

### 5.2 先承诺，后判定

节点进入条件必须在玩家开始推进相关内容前写入已发布剧本。运行时按照已发布规则判断，作者 LLM 不得根据玩家当前数值临时提高门槛。

### 5.3 隐藏信息不进入场景演出上下文

不得仅依赖“不要剧透”的 Prompt 指令。未解锁节点正文、角色秘密和未来结局必须在程序侧投影阶段被移除。

### 5.4 状态与分支同生共死

Fork 对话时必须复制当时的 `BranchStoryState`；切换分支时必须同时恢复消息历史和分支剧情状态。`GlobalStoryProgress` 独立保存，不进入 Fork 或回档快照。

### 5.5 声明式规则，不执行任意代码

条件和效果使用受限 DSL。禁止通过 `eval`、Python 表达式、JavaScript 或模板表达式执行剧本输入。

### 5.6 兼容优先

没有 `StoryProject` 的会话沿用现有自由聊天流程。结构化选项、剧情快照和新事件必须经历兼容迁移，不能一次破坏旧协议。

### 5.7 主动意图与被动信号分离

`StoryIntent` 表示玩家试图执行的主动行为，例如进入地点、使用道具或质问角色；`SemanticSignal` 表示从普通表达中识别出的被动语义证据，例如独立推理、尊重边界、隐瞒事实或宣扬暴力。两者可以来源于同一条消息，但必须独立判定，并通过 `causeGroup` 防止同一含义重复产生效果。

### 5.8 创作图与运行时分离

创作界面可以把剧情、信号、指标、条件和效果全部表现为类型化节点，但运行时不得把它们视为同一种节点动态解释。`StoryNode` 代表玩家实际进入的剧情锚点；`RuleNode` 代表逻辑定义。发布时必须将两层图编译为受限的 `StoryProgram`，运行时只执行编译产物。

### 5.9 演员表晚绑定，但演出前必须解析

作者不需要在创作每个场景时列死所有出场人物，可以声明角色职责、候选标签和约束；但最终场景 LLM 开始生成对白前，剧情引擎必须把策略解析为稳定的 `ActiveCast` 和 `speakerAllowlist`。选角 LLM 只能提出已登记 ID，不能一边生成最终对白一边发明正式说话者。

## 6. 用户体验

### 6.1 从剧情梗概创建剧本

用户输入：

> 现代校园背景。玩家转校后认识了绫，两人调查旧校舍失踪事件。绫隐瞒了姐姐曾经失踪的事实。希望有友情结局、真相结局和一个坏结局，游玩时间约两小时。

用户可选参数包括：

- 预计游玩长度。
- 主要角色与可攻略角色。
- 主线、支线和结局数量。
- 剧情控制强度：严格、标准、自由。
- 是否向玩家显示锁定条件或模糊提示。
- 是否允许 AI 在章节边界动态扩写。
- 可使用的背景、BGM、CG、特效和人物资源。
- 人物登记表、默认演员策略、临时 NPC 策略和单场景最大激活人数。

系统生成草稿并显示：

- 生成假设与缺省决定。
- 故事圣经摘要。
- 状态变量列表。
- 剧情节点图。
- 结局覆盖情况。
- 校验错误与警告。

用户确认并发布后，剧本才可以启动。

### 6.2 编辑与局部重生成

用户可以：

- 修改节点标题、概要、条件、效果和跳转。
- 通过表单构建条件，不必直接编辑 YAML。
- 仅重新生成单个节点或一个章节。
- 保留已有 ID 和连接关系，仅重写演出说明。
- 对比 AI 修改前后的结构化差异。
- 试玩指定路径并查看状态变化。
- 将已发布版本复制为新草稿，不直接覆盖正在使用的版本。

### 6.3 运行时体验

聊天舞台继续保留自由输入、立绘、旁白、语音和资源演出。节点系统额外提供：

- 结构化选项。
- 任务和目标。
- 权威状态面板。
- 节点或路线解锁通知。
- 结局与周目完成界面。
- 分支树中的剧情节点和关键状态摘要。

### 6.4 控制强度

| 模式 | 未登记自由行动 | 关键状态变化 | 适用场景 |
| --- | --- | --- | --- |
| 严格 | 拒绝或转化为失败演出 | 仅结构化选择和已登记意图 | 解谜、攻略、强规则剧情 |
| 标准 | 允许即兴演出，但不改变关键状态 | 只执行已登记效果 | 默认模式 |
| 自由 | 可请求作者 LLM 生成候选支线 | 校验并提交后生效 | 沙盒、无限故事 |

## 7. 总体架构

```text
用户剧情梗概
      |
      v
AI 剧本编译器 ------> 剧本草稿 ------> 校验与路径模拟 ------> 已发布 StoryProject
                                                        |
玩家输入                                                v
   |                                              剧情运行时引擎
   v                                                    |
意图识别/语义信号/结构化选择 -----------------------------+
                                                        |
                                                        v
                                                   StoryEvent
                                                        |
                                                        v
                                      BranchStoryState + GlobalStoryProgress
                                                        |
                           +----------------------------+------------------+
                           |                                               |
                           v                                               v
              演员表解析 / 场景上下文投影                              分支与存档
                           |
                           v
                       场景 LLM
                           |
                           v
                    对白与演出事件
```

### 7.1 子系统

| 子系统 | 主要职责 | 建议位置 |
| --- | --- | --- |
| 剧本模型 | NarrativeGraph、RuleGraph、Schema、条件、效果、指标、语义信号、事件与序列化 | `core/story/` |
| 剧情运行时 | StoryProgram 编译、条件判定、事务效果、跳转、演员表解析与结局 | `core/story/` |
| 校验与模拟 | 类型端口、图结构、规则编译、路径覆盖和自动修复输入 | `core/story/` |
| AI 剧本编译 | 梗概分析、骨架生成、节点扩写与修复 | `ai/story/` |
| AI 上下文协调 | 作者与场景上下文隔离、意图解析、语义信号评估、可选选角提案与投影 | `ai/story/` |
| 会话与存档集成 | 生命周期、状态仓库、人物加载、演员表提交、分支与聊天协调 | `application/story/` |
| 协议适配 | HTTP/WebSocket DTO 与命令转发 | `frontend_bridge_core/routes/` |
| React 创作和运行 UI | 生成器、编辑器、校验报告和舞台展示 | `frontend/src/` |

### 7.2 依赖约束

- `core/story` 不得依赖 LLM、bridge 或 React。
- `ai/story` 可以依赖 `core/story`、`config` 和 `sdk`，不得依赖 bridge。
- `application/story` 编排 `core/story`、`ai/story`、聊天运行时和存储。
- `frontend_bridge_core` 只做协议校验和 DTO 转换，不执行剧情规则。
- React 不直接读写 `data/stories/`。
- 剧本格式成熟前不暴露为稳定 `sdk` 契约。
- `core/story`、`ai/story` 与 `application/story` 的长期职责同步记录在生效中的 `PROJECT_STRUCTURE.md`；实现不得另建平行的 story 宿主目录。

## 8. 剧本工程模型

### 8.1 顶层模型

```yaml
schemaVersion: 1
id: campus-mystery
version: 3
title: 旧校舍的雨声
status: published
startNodeId: transfer-day

metadata:
  language: zh-CN
  estimatedMinutes: 120
  generationMode: ai-assisted

bibleRef: story_bible.yaml
variablesRef: variables.yaml
castRef: cast.yaml
narrativeGraphRef: graph.yaml
logicGraphRef: logic_graph.yaml
chaptersRef:
  - chapters/chapter-1.yaml
  - chapters/chapter-2.yaml
  - chapters/chapter-3.yaml
assetsRef: assets.yaml
compiledProgramRef: compiled/story_program.json
```

顶层工程必须包含：

- `schemaVersion`：文件格式版本。
- `id`：剧本稳定 ID。
- `version`：已发布剧本版本。
- `startNodeId`：唯一入口节点。
- `metadata`：语言、长度、作者、生成模式等非运行数据。
- 故事圣经、变量、人物登记表、剧情图、逻辑图、章节、资源和编译产物引用。

### 8.2 状态变量定义

首版支持以下类型：

| 类型 | 示例 | 典型用途 |
| --- | --- | --- |
| `boolean` | `flags.shared_secret` | 是否发生过事件 |
| `integer` | `trust.ling` | 信任、怀疑、理智、声望、推理进度和计数 |
| `enum` | `route` | 当前路线或阶段 |
| `string_set` | `inventory` | 道具、线索、成就集合 |

变量定义示例：

```yaml
variables:
  trust.ling:
    type: integer
    initial: 0
    min: -100
    max: 100
    scope: branch
    visible: true

  suspicion.headmaster:
    type: integer
    initial: 0
    min: 0
    max: 100
    scope: branch
    visible: true

  insight.school_mystery:
    type: integer
    initial: 0
    min: 0
    max: 100
    scope: branch
    visible: true

  stress.player:
    type: integer
    initial: 20
    min: 0
    max: 100
    scope: branch
    visible: true

  concern.ling:
    type: integer
    initial: 0
    min: 0
    max: 100
    scope: branch
    visible: false

  health.player:
    type: integer
    initial: 100
    min: 0
    max: 100
    scope: branch
    visible: true

  flags.shared_secret:
    type: boolean
    initial: false
    scope: branch
    visible: false

  unlockedEndings:
    type: string_set
    initial: []
    scope: global
    visible: true
```

运行时不得创建未在变量表中声明的变量。节点完成与失败状态不属于普通变量，分别只保存在 `BranchStoryState.completedNodeIds` 和 `BranchStoryState.failedNodeIds`；`completed/failed` 条件与 `complete/fail` 效果只能访问这两个系统字段，不能再建立同义变量作为第二事实源。

`StoryMetric` 不是另一套状态存储类型，而是附着在 `integer` 变量上的通用策略元数据。不是所有整数变量都允许由自由文本语义信号修改；生命值、货币等确定性指标默认关闭语义输入。首版允许语义输入的指标必须是 `branch` 作用域；`global` 只允许结局、CG 等集合追加型进度，`run` 作用域在发布时拒绝。

### 8.3 节点模型

```yaml
id: old-school-gate
chapterId: chapter-2
title: 旧校舍门前
type: story
commitment: frozen

visibility:
  mode: hidden
  revealWhen:
    completed: investigation-preparation

enterWhen:
  all:
    - completed: investigation-preparation
    - gte: [trust.ling, 20]

exposedContext:
  summary: 夜晚的旧校舍已经封闭，绫表现得异常紧张。
  knownFacts:
    - 旧校舍五年前发生过失踪事件
  objectives:
    - 找到进入旧校舍的方法
    - 判断绫是否有所隐瞒

lockedContext:
  secrets:
    - 绫的姐姐曾在这里失踪

castPolicy:
  mode: mixed
  required: [ling]
  optionalQuery:
    anyTags: [school-staff, investigator]
  constraints:
    maxActive: 4

onEnter:
  - set: [flags.arrived_old_school, true]

choices:
  - id: ask-ling-directly
    label: 直接询问绫
    when: true
    effects:
      - increment: [trust.ling, -5]
      - set: [flags.questioned_ling, true]
    goto: ling-hesitates

  - id: use-old-key
    label: 使用管理员交出的钥匙
    when:
      contains: [inventory, old_school_key]
    effects:
      - remove: [inventory, old_school_key]
      - set: [flags.entered_old_school, true]
    goto: old-school-hall

freeformIntents:
  - id: investigate-side-window
    examples:
      - 看看侧面有没有窗户
      - 绕到旧校舍后面
    effects:
      - set: [flags.found_open_window, true]
    resultBeat: 玩家发现一扇没有锁好的侧窗。

presentation:
  scene: old_school_night
  bgm: mystery_low
  entryEffect: door_creak
```

### 8.4 节点状态

节点运行时状态为派生值，不重复写回剧本定义：

| 状态 | 含义 |
| --- | --- |
| `hidden` | 玩家不知道该节点存在 |
| `locked` | 节点可见，但进入条件未满足 |
| `available` | 条件满足，可以进入 |
| `active` | 当前所在节点 |
| `completed` | 节点已经完成 |
| `failed` | 节点因明确事件失败或永久关闭 |

### 8.5 条件 DSL

首版允许：

```yaml
all: [condition, ...]
any: [condition, ...]
not: condition
equals: [variable, value]
gte: [variable, number]
lte: [variable, number]
contains: [setVariable, value]
completed: nodeId
failed: nodeId
```

规则：

- 条件只能读取状态，不能产生副作用。
- 变量和值必须经过类型校验。
- `all: []`、`any: []` 等边界语义必须固定并测试。
- 不支持任意字符串表达式，例如 `"suspicion > 30"`。

### 8.6 效果 DSL

首版允许：

```yaml
set: [variable, value]
increment: [integerVariable, delta]
add: [setVariable, value]
remove: [setVariable, value]
complete: nodeId
fail: nodeId
appendCanon: fact
unlockEnding: endingId
```

`complete/fail` 只修改分支节点集合；`unlockEnding` 转换为 `GlobalStoryProgress.unlockedEndings` 的幂等集合追加。变量效果按照变量定义的 scope 路由，首版不得对 global 集合执行 `remove` 或覆盖。

所有效果必须在一个逻辑 `StoryTransaction` 中完成：

1. 复制当前 `BranchStoryState`，并读取带 revision 的 `GlobalStoryProgress`。
2. 按变量 scope 将效果路由到分支副本或受限的全局单调效果集合，并校验全部效果。
3. 计算节点和结局变化。
4. 生成分支事件、命令结果和全局 effect outbox。
5. 原子提交新的分支 generation；在返回成功 ack 前幂等应用全局 outbox。

任一校验失败时不得提交分支 generation。分支提交后发生进程中断时，通过持久 outbox 恢复未完成的全局单调效果；具体协议见 12.3 和 12.6。

### 8.7 叙事指标与语义信号

#### 8.7.1 定位

语义信号系统用于处理普通对话中没有显式结构化选择、但具有剧情意义的表达。它是通用能力，不以好感度或角色关系作为底层抽象。

典型指标包括：

- 信任、尊重、敌意、依赖和警戒。
- 怀疑度、推理进度和线索理解程度。
- 压力、恐惧、勇气、理智和腐化程度。
- 阵营声望、道德倾向和世界稳定度。
- 某个话题、人物或事件的认知程度。

指标变化来源分为三类：

| 来源 | 例子 | 是否需要 LLM 判断 |
| --- | --- | --- |
| 确定性剧情效果 | 使用道具、完成节点、点击选择 | 否 |
| 系统计算 | 受到伤害、时间流逝、资源消耗 | 否 |
| 自由文本语义信号 | 质疑权威、正确推理、尊重边界 | 是 |

#### 8.7.2 指标策略

```yaml
metrics:
  trust.ling:
    variable: trust.ling
    semanticInput:
      enabled: true
      perTurnCap: 2
      perSceneCap: 4
      perChapterCap: 15
      repeatWindowTurns: 10

  suspicion.headmaster:
    variable: suspicion.headmaster
    semanticInput:
      enabled: true
      perTurnCap: 5
      perSceneCap: 12
      repeatWindowTurns: 3

  insight.school_mystery:
    variable: insight.school_mystery
    semanticInput:
      enabled: true
      perTurnCap: 3
      perSceneCap: 8
      repeatWindowTurns: 5

  stress.player:
    variable: stress.player
    semanticInput:
      enabled: true
      perTurnCap: 3
      perSceneCap: 10
      repeatWindowTurns: 3

  concern.ling:
    variable: concern.ling
    semanticInput:
      enabled: true
      perTurnCap: 4
      perSceneCap: 10
      repeatWindowTurns: 5

  health.player:
    variable: health.player
    semanticInput:
      enabled: false
```

策略规则：

- `variable` 必须引用已声明的 `integer` 变量。
- 允许语义输入的 `variable` 必须是 `branch` 作用域。
- `semanticInput.enabled: false` 时，任何 LLM 候选信号都不得修改该指标。
- 每轮、每场景和每章节限额按指标分别计算。
- 指标最终值仍受变量 `min/max` 约束。
- 限额、重复窗口和去重状态属于分支状态并随回档恢复。

#### 8.7.3 信号定义

LLM 不直接选择变量或增减值。剧本预先定义稳定的信号 ID、判定标准和效果：

```yaml
semanticSignals:
  - id: question-authority
    description: 玩家基于具体理由质疑校长或学校官方说法
    visibility: public
    scope: story
    allowedSpeechActs: [endorsement]
    minimumConfidence: medium
    effectsByStrength:
      weak:
        - increment: [insight.school_mystery, 1]
        - increment: [suspicion.headmaster, 1]
      medium:
        - increment: [insight.school_mystery, 2]
        - increment: [suspicion.headmaster, 2]
      strong:
        - increment: [insight.school_mystery, 3]
        - increment: [suspicion.headmaster, 4]

  - id: reckless-risk
    description: 玩家提出明显危险且缺乏准备的行动
    visibility: public
    scope: story
    allowedSpeechActs: [endorsement]
    minimumConfidence: medium
    effectsByStrength:
      weak:
        - increment: [stress.player, 1]
      medium:
        - increment: [stress.player, 2]
        - increment: [concern.ling, 2]
      strong:
        - increment: [stress.player, 3]
        - increment: [concern.ling, 4]
```

一个信号可以影响多个指标，但所有目标变量和效果必须在发布时冻结。信号 `scope` 可以是整个剧本、指定章节或指定节点，也可以增加只读 `when` 条件。运行时根据当前节点、状态和可见性生成当轮信号目录。LLM 只能选择目录中存在的 `signalId`，不能发明变量、信号或 `delta`。

#### 8.7.4 候选信号

场景 LLM 或隔离的语义评估调用可以提出：

```json
{
  "signalId": "question-authority",
  "strength": "strong",
  "confidence": "high",
  "speechAct": "endorsement",
  "sourceMessageId": "message-128",
  "evidence": "用户指出校长在避重就轻，并建议调查旧档案"
}
```

允许的强度为 `weak/medium/strong`，允许的置信度为 `low/medium/high`。首版不让 LLM 返回任意浮点强度或数值增减。

语义评估必须区分：

```text
endorsement   用户认同或主张
rejection     用户明确反对
quotation     引述他人
hypothetical  假设讨论
question      提问
sarcasm       讽刺
roleplay      明确的戏中戏或引用扮演
ambiguous     无法判断
```

默认只有信号定义明确允许的 speech act 才能产生效果；`quotation`、`question` 和 `ambiguous` 默认拒绝。

#### 8.7.5 接受策略

规则引擎依次检查：

1. `signalId` 是否存在并对当前节点可见。
2. 信号目标指标是否允许语义输入。
3. speech act 和置信度是否满足定义。
4. 同类信号是否在重复窗口内已经出现。
5. 当前轮、场景和章节是否达到限额。
6. 是否与同一消息产生的主动剧情事件重复计分。
7. 全部效果能否通过变量类型与范围校验。

接受后才产生 `SemanticSignalAccepted` 和一个或多个 `MetricChanged` 事件。拒绝可以记录受限的诊断原因，但不写入玩家可见 Canon。

#### 8.7.6 去重与防刷

每个候选信号生成去重键：

```text
character-or-scope + signalId + semanticFingerprint + repeatWindow
```

重复表达相同观点不应持续增加指标。新的具体证据、不同情境中的实际行动或对既有承诺的兑现，可以形成新的 fingerprint。

同一消息可能同时产生主动 Intent 和被动 SemanticSignal。两者必须共享 `causeGroup`：

```json
{
  "causeGroup": "message-128:ling:protect-companion"
}
```

如果主动剧情事件已经对同一人物和同一语义产生更高权重效果，被动信号只保留演出提示，不重复修改指标。

#### 8.7.7 阈值解锁

节点不关心指标变化来源，只读取最终权威状态：

```yaml
id: discover-headmaster-secret
unlockWhen:
  all:
    - gte: [suspicion.headmaster, 60]
    - gte: [insight.school_mystery, 40]
    - contains: [inventory, archive_photo]
```

指标事务提交后，运行时只重新计算依赖已变化变量的规则。条件首次由 false 变为 true 时产生 `NodeUnlocked`；是否立即进入仍由节点 `activation` 策略决定。

### 8.8 类型化节点图与编译

#### 8.8.1 两层图模型

剧本工程同时包含两种图：

```text
NarrativeGraph
  ├── SceneNode
  ├── ChapterNode
  ├── HubNode
  ├── StoryNode
  └── EndingNode

RuleGraph
  ├── EventSourceNode
  ├── IntentNode
  ├── SemanticSignalNode
  ├── MetricReferenceNode
  ├── ConditionNode
  ├── PolicyNode
  ├── EffectNode
  ├── RouterNode
  ├── UnlockNode
  ├── CastNode
  └── PresentationNode
```

两层图可以在编辑器中联动展示，但领域语义不同：

- `StoryNode` 是玩家能够进入、完成、失败或离开的剧情锚点。
- `RuleNode` 是创作期逻辑定义，不能作为当前剧情节点写入 `BranchStoryState.currentNodeId`。
- `MetricReferenceNode` 只通过 `StoryStateView` 按变量声明的 scope 读取值，不保存另一份当前值。
- `SemanticSignalNode` 表示信号定义；每次实际触发产生 `SemanticSignalAccepted` 事件，不在工程中复制新节点。

#### 8.8.2 规则节点类型

| 类别 | 节点类型 | 输入 | 输出 | 用途 |
| --- | --- | --- | --- | --- |
| 事件源 | `on-choice` | 选择事件 | `StoryEvent` | 监听结构化选择 |
| 事件源 | `on-intent` | 主动意图 | `StoryEvent` | 监听自由输入映射的行动 |
| 事件源 | `semantic-signal` | 候选信号 | `SemanticSignalEvent` | 定义并接收预定义语义信号 |
| 事件源 | `on-node-completed` | 节点完成事件 | `StoryEvent` | 在节点完成后触发后续逻辑 |
| 状态引用 | `metric-ref` | 变量 ID | `Integer` | 引用叙事指标当前值 |
| 状态引用 | `flag-ref` | 变量 ID | `Boolean` | 引用布尔状态 |
| 策略 | `confidence-gate` | 候选信号 | 接受/拒绝事件 | 检查最低置信度 |
| 策略 | `speech-act-gate` | 候选信号 | 接受/拒绝事件 | 检查认同、引述、提问等语义行为 |
| 策略 | `deduplicate` | 候选事件 | 去重后的事件 | fingerprint 与重复窗口 |
| 策略 | `rate-limit` | 候选事件 | 限额后的事件 | 每轮、场景和章节限额 |
| 策略 | `strength-map` | `weak/medium/strong` | 预定义效果集合 | 将定性强度映射为固定效果 |
| 条件 | `compare` | 数值或枚举 | `Boolean` | `gte/lte/equals` |
| 条件 | `all/any/not` | `Boolean` | `Boolean` | 组合条件 |
| 条件 | `contains` | 集合和值 | `Boolean` | 道具、线索和标签判断 |
| 效果 | `increment-metric` | 已接受事件 | `Effect` | 增减整数变量 |
| 效果 | `set-variable` | 已接受事件 | `Effect` | 设置布尔、枚举或整数 |
| 效果 | `add/remove-set` | 已接受事件 | `Effect` | 修改道具或标签集合 |
| 效果 | `append-canon` | 已接受事件 | `Effect` | 追加当前世界线事实 |
| 流程 | `router` | 条件与事件 | 命名事件出口 | 按条件选择后续规则 |
| 流程 | `unlock` | `Boolean` 或事件 | `NodeUnlocked` | 解锁剧情、结局、CG或选项 |
| 流程 | `enter-story-node` | 已接受事件 | `NodeEntered` | 请求进入剧情节点 |
| 演员 | `character-ensure` | 人物引用 | `CharacterReady` | 确保人物已登记并可加载 |
| 演员 | `cast-resolve` | 场景、状态与演员策略 | `CastResolved` | 解析并提交当前演员表 |
| 演员 | `character-enter/exit` | 已接受事件 | `CastChanged` | 受控登场或退场 |
| 演员 | `character-replace` | 已接受事件与人物引用 | `CastChanged` | 按约束替换当前人物 |
| 演员 | `character-preload/unload` | 人物引用 | `ResourceLifecycleCue` | 提示应用层预载或释放非权威资源 |
| 演出 | `presentation` | 剧情事件 | 演出提示 | 场景、BGM、CG和特效配置 |

首版不开放任意自定义节点代码。新增节点类型必须在宿主中注册明确的 Schema、端口和编译规则。

#### 8.8.3 强类型端口

每个端口都声明数据类型或事件类型：

```text
SemanticSignalNode.accepted  → SemanticSignalEvent
MetricReferenceNode.value   → Integer
ConditionNode.result        → Boolean
EffectNode.effect           → Effect
StoryNode.enter             → StoryTransition
CharacterEnsureNode.ready   → CharacterReadyEvent
CastResolveNode.resolved    → CastResolvedEvent
PresentationNode.cue        → PresentationCue
```

允许连接：

```text
MetricReferenceNode.value → CompareNode.left
CompareNode.result        → UnlockNode.when
SemanticSignal.accepted   → StrengthMapNode.signal
CastResolveNode.resolved  → PresentationNode.eventInput
```

禁止连接：

```text
StoryNode.transition      → CompareNode.integerInput
MetricReferenceNode.value → BgmPresentation.eventInput
BooleanCondition.result   → IncrementMetric.amount
CharacterPreloadNode.cue  → CastResolveNode.policyInput
```

编译器禁止隐式类型转换。需要转换时必须使用有明确语义的宿主节点。

#### 8.8.4 示例

```text
[SemanticSignal: question-authority]
               |
               v
       [SpeechActGate]
               |
               v
       [ConfidenceGate]
               |
               v
         [Deduplicate]
               |
               v
          [RateLimit]
               |
               v
         [StrengthMap]
          |          |
          v          v
[suspicion +N]  [insight +N]
          |          |
          +-----+----+
                v
      [suspicion >= 60]
                |
      [insight >= 40]
                |
      [has archive_photo]
                |
              [All]
                |
                v
[Unlock: discover-headmaster-secret]
                |
                v
[StoryNode: 校长的秘密]
```

#### 8.8.5 保存格式

```yaml
logicGraph:
  version: 1
  nodes:
    - id: signal-question-authority
      type: semantic-signal
      config:
        signalId: question-authority

    - id: suspicion-metric
      type: metric-ref
      config:
        variable: suspicion.headmaster

    - id: suspicion-threshold
      type: condition.gte
      config:
        value: 60

    - id: unlock-headmaster-secret
      type: unlock
      config:
        storyNodeId: discover-headmaster-secret

  edges:
    - from:
        nodeId: suspicion-metric
        port: value
      to:
        nodeId: suspicion-threshold
        port: input

    - from:
        nodeId: suspicion-threshold
        port: result
      to:
        nodeId: unlock-headmaster-secret
        port: when
```

节点坐标、折叠、颜色和分组等编辑器布局信息放在独立 `editorState`，不参与运行时哈希和规则语义。

#### 8.8.6 单一事实源与编译产物

不得让可视化图、节点内联 DSL 和运行时规则成为三份可以独立修改的事实源。

采用以下规则：

1. `NarrativeGraph + RuleGraph` 是 AI 生成剧本和所有编辑器保存后的规范创作源。
2. 节点中的 `when/effects/unlockWhen` 等内联 DSL 仅作为手写和旧格式导入简写；加载时转换为具有稳定 ID 的 `RuleGraph`，下次保存时写回规范图结构。
3. 同一逻辑规则不得同时由内联 DSL 和显式 `RuleNode` 定义；检测到重复所有权时阻止发布，不采用隐式覆盖顺序。
4. 发布器将规范化 IR 编译为不可编辑的 `StoryProgram`。
5. `StoryProgram` 保存源版本、Schema 版本和 `sourceHash`。
6. 运行时只加载通过校验且 hash 匹配的 `StoryProgram`。
7. 用户修改任意源节点后，已有编译产物失效，必须重新校验和发布。

```text
可视化类型节点图 / 内联简写 DSL
               |
               v
          NormalizedRuleIR
               |
      类型检查、图校验、优化
               |
               v
           StoryProgram
               |
               v
         确定性剧情运行时
```

#### 8.8.7 编译规则

编译器至少执行：

1. 解析节点和端口 Schema。
2. 解析所有变量、剧情节点、信号和资源引用。
3. 验证端口类型、必需输入和连接基数。
4. 将内联 DSL 与逻辑图转换为统一 IR。
5. 展开固定模板节点，例如语义信号的置信度、去重和限额链。
6. 构建变量到条件、条件到解锁节点的依赖索引。
7. 合并同一事务中的效果并生成确定执行顺序。
8. 输出只包含宿主支持指令的 `StoryProgram`。
9. 计算 `sourceHash` 并保存诊断源映射。

运行时错误必须能通过源映射定位到原始 `RuleNode` 和端口。

#### 8.8.8 循环与执行边界

- 同一事务中的组合逻辑循环禁止发布。
- 事件触发效果、效果再同步触发原事件的循环禁止发布。
- `StoryNode` 之间允许形成叙事循环，但每次循环必须跨越明确的玩家轮次或节点边界。
- 允许循环的剧情边必须设置重复策略、退出条件或编辑器警告。
- `NodeUnlocked` 默认只产生解锁事件，不在同一事务中递归执行该节点全部 `onEnter` 效果。
- 连锁解锁放入有界事件队列，并设置单轮最大级联深度。
- 任意自循环、无限定时器和运行时动态创建节点不属于首版能力。

#### 8.8.9 创作模式

简单模式不要求用户手工连图。表单操作生成固定图模板：

```text
语义信号
  → speech act / 置信度
  → 去重 / 限额
  → 指标效果
  → 阈值条件
  → 解锁剧情
```

高级模式允许编辑强类型节点和端口，但仍不能绕过 Schema 与编译器。AI 作者可以生成或修改逻辑图，但输出必须作为图补丁经过类型检查、编译和完整剧本校验。

### 8.9 动态人物与演员表晚绑定

#### 8.9.1 人物登记表

剧本工程可以登记大量人物，不要求所有人物在启动会话时加载。登记表保存稳定身份与来源，人物完整档案按需解析：

```yaml
version: 1

defaults:
  maxActive: 8
  preserveCurrentCast: true

initialCast: [ling]

characters:
  - id: ling
    source:
      type: local-library
      characterId: ling
      revision: sha256:7f9d...
    tags: [student, investigator, main-cast]
    roles: [companion]

  - id: detective-zhou
    source:
      type: embedded
      path: characters/detective-zhou.yaml
    tags: [adult, police, investigator]
    roles: [authority, clue-provider]

adHocPolicy:
  enabled: true
  maxPerScene: 2
  persistScope: branch
  requirePromotionForReuse: true
```

支持的来源为：

- `local-library`：用户已安装并明确授权给剧本的人物，已发布剧本固定其 revision 或内容摘要。
- `embedded`：随剧本包保存的 `StoryScopedCharacter`，路径必须位于剧本目录内。
- `user-imported`：用户在 UI 中明确选择的 `.char` 文件；校验成功后转换为登记项，LLM 不能自行扫描路径。
- `author-generated`：作者 LLM 输出的 `CharacterDraft`；通过人物 Schema、内容和资源校验后，固化为剧本域人物再登记。

“不限人物数量”表示产品不把人物池限制为开局所选的少量角色，而不是允许无界资源占用。登记表可以很大并使用分页、索引和按需加载；每个场景的 `ActiveCast`、单次导入大小、预载数量和 Prompt 体积仍有明确上限。

#### 8.9.2 场景演员策略

每个场景或节点可以使用以下模式：

| 模式 | 声明方式 | 适用场景 |
| --- | --- | --- |
| `fixed` | 明确列出全部人物 ID | 关键对峙、告白、结局 |
| `mixed` | 固定必需人物，再从候选池补充 | 大多数主线场景 |
| `role-based` | 声明必须承担的剧情职责 | “任意医生”“任意知情警员” |
| `dynamic` | 仅声明候选范围、约束和选择策略 | Hub、派对、开放探索 |

完整示例：

```yaml
castPolicy:
  mode: role-based
  required: [ling]
  requiredRoles:
    - role: authority
      count: 1
      prefer: [detective-zhou]
  optionalQuery:
    anyTags: [investigator, witness]
    allConditions:
      - available: true
      - alive: true
      - sameLocationAs: player
  forbidden: [headmaster]
  constraints:
    minActive: 2
    maxActive: 4
    preserveCurrentCast: true
    requireLoadedAssets: false
  selection:
    strategy: continuity-then-priority
    allowAiProposal: true
  fallback:
    onMissingRole: use-narrator
    onLoadFailure: continue-without-optional
```

`required` 和关键剧情职责属于已发布承诺。可选人物可以随分支状态变化；如果关键人物缺失，运行时必须执行声明的 fallback、跳转失败节点或停止并给出诊断，不得静默让 LLM 改写剧情责任。

#### 8.9.3 解析与提交顺序

每轮最终演出前执行：

```text
CastPolicy + CharacterRegistry + BranchStoryState
  → 确定性过滤：登记、版本、存活、可用、地点、条件、排除项
  → 绑定 required 与 requiredRoles
  → 按连续性和优先级解决无歧义候选
  → 可选 CastPlanner 从剩余 candidateIds 中提出选择
  → 引擎重新校验 ID、人数、职责、资源与 revision
  → core/story 输出不执行 I/O 的 CastResolutionPlan
  → application/story 加载最终演出所需的最小人物档案
  → 必需人物失败时在未提交计划上执行已发布 fallback 并重新校验
  → 原子提交下一版 BranchStoryState、ActiveCast、roleBindings 和 CastResolved
  → 提交后按需预载立绘、语音等可降级演出资源
  → 生成 ActorContext 与 speakerAllowlist
  → 场景 LLM 最终演出
```

`CastPlanner` 可以是规则实现、与场景 LLM 共用的工具调用阶段，或单独模型。它只接收合格 `candidateIds` 和非秘密选择理由，只返回人物 ID 与职责绑定。引擎是最终裁决者；非法 ID、超员、缺少职责或过期 revision 一律拒绝。

`CastResolutionPlan` 是纯数据，不包含已打开文件、模型句柄或加载状态。人物档案读取和资源生命周期属于 application；core 只生成稳定人物 ID、fallback 决策和 `ResourceLifecycleCue`。

#### 8.9.4 生命周期与按需加载

人物是否能参与剧情和人物资源是否已载入必须分开建模：

- 权威剧情状态：`available`、`unavailable`、`active`、`offstage`、`dead` 或剧本自定义布尔条件，随分支保存。
- 应用层加载状态：`not-loaded`、`loading`、`loaded`、`failed`，属于可重建缓存，不写入 `BranchStoryState`。
- `character-preload` 可以提前加载下一场候选；`character-unload` 只能释放缓存，不代表人物死亡或退场。
- 最终演出所需的最小人物档案属于提交前 readiness gate。必需人物加载失败时，application 在尚未提交的 `CastResolutionPlan` 上执行 fallback；没有合法 fallback 时拒绝本次命令，剧情效果和 revision 均不提交。
- 立绘、Live2D、语音模型等可降级演出资源在提交后加载；这类失败不回滚已经提交的剧情效果，可选资源降级并产生 application 级诊断事件。

#### 8.9.5 中途登场、退场与临时 NPC

场景可以通过规则节点或场景 LLM 工具请求人物变化：

```json
{
  "id": "tool-entry-7",
  "name": "request_character_entry",
  "arguments": {
    "characterId": "detective-zhou",
    "reasonId": "player-called-police",
    "expectedNodeId": "old-school-gate",
    "expectedRevision": 42
  }
}
```

引擎检查人物已登记、仍存活且可用、地点或到达路线成立、当前节点允许该 `reasonId`、人数未超限，然后返回新的权威演员表。模型收到工具结果后才能生成该人物已经登场的对白。`request_character_exit` 和 `request_character_replace` 使用相同的 revision 与策略校验。内部工具调用继承触发本轮的客户端 `commandId`，并使用 provider tool-call ID 形成 `commandId:toolCallId` 幂等键；重复工具调用返回原工具结果。

临时路人、店员等 NPC 可以由 `AdHocCharacter` 模板创建，但必须先生成稳定 ID、最小档案和作用域，再登记到当前分支，之后才可进入 `speakerAllowlist`。需要跨场景复用时执行 `PromoteAdHocCharacter`，将其升级为剧本域人物；未晋升临时人物在作用域结束后不进入长期 Canon 人物目录。

#### 8.9.6 类型化演员节点

创作界面可提供以下宿主节点：

```text
CharacterEnsureNode.ready       → CharacterReadyEvent
CastResolveNode.resolved        → CastResolvedEvent
CharacterEnterNode.changed      → CastChangedEvent
CharacterExitNode.changed       → CastChangedEvent
CharacterReplaceNode.changed    → CastChangedEvent
CharacterPreloadNode.cue        → ResourceLifecycleCue
CharacterUnloadNode.cue         → ResourceLifecycleCue
```

节点只能引用 `CharacterRegistry` 中的稳定 ID、已声明的角色职责或受限候选查询。`CastResolvedEvent` 可以连接演出节点，不能直接作为整数、条件或人物档案使用；人物预载事件不能修改权威剧情状态。

#### 8.9.7 Speaker Allowlist

`ActorContext` 只为 `ActiveCast` 提供完整人物档案，并动态生成如下约束：

```json
{
  "speakerAllowlist": ["ling", "detective-zhou", "NARR", "SYSTEM"]
}
```

正式对白项的 `characterId` 必须属于该列表。未在场人物只以已知事实、消息来源或被提及对象出现，不获得完整秘密和行为指令。场景 LLM 输出未登记或未激活人物时，结构校验拒绝该响应并进行受限修复，不能自动把幻觉人物加入演员表。

## 9. 剧情运行时

### 9.1 输入命令

运行时接受以下领域命令：

```text
StartStory
SelectChoice
PerformIntent
ApplySemanticSignals
RegisterStoryCharacter
ResolveCast
RequestCharacterEntry
RequestCharacterExit
ReplaceCharacter
PromoteAdHocCharacter
EnterNode
CompleteNode
ApplyAuthorPatch
RestoreBranchSnapshot
```

命令示例：

```json
{
  "type": "SelectChoice",
  "commandId": "018f6f9a-6ef1-7c61-9b4f-0c91eb94d1f0",
  "branchId": "branch-3",
  "choiceId": "use-old-key",
  "expectedNodeId": "old-school-gate",
  "expectedRevision": 42
}
```

所有会修改剧情或演员状态的命令都必须携带客户端生成的稳定 `commandId`、目标 `branchId` 和 `expectedRevision`。`expectedNodeId` 在节点相关命令中额外用于拒绝过期选项。

application 按分支持久化一个有界幂等索引：

```text
commandId → payloadHash + accepted/rejected + resultingRevision + eventIds + ack
```

- 首次收到命令时，在会话串行化边界内检查 revision、执行并保存结果。
- 相同 `commandId` 与相同 payload 重试时返回原 ack 和事件范围，不再次执行效果。
- 相同 `commandId` 携带不同 payload 时拒绝为协议错误。
- 新 `commandId` 携带过期 revision 时返回冲突和最新可见快照。
- 幂等索引随分支检查点保存；裁剪事件前必须保留仍可能重试的命令结果。

### 9.2 输出事件

core/story 的权威领域事件示例：

```text
StoryStarted
ChoiceSelected
VariableChanged
ItemAdded
ItemRemoved
NodeUnlocked
NodeEntered
NodeCompleted
ObjectiveCompleted
CanonAppended
SemanticSignalAccepted
SemanticSignalRejected
MetricChanged
CharacterRegistered
CastResolved
CharacterEntered
CharacterExited
AdHocCharacterPromoted
EndingUnlocked
EndingReached
```

领域事件不直接包含 HTML、URL、文件句柄、模型对象或 React 组件信息。演出适配层负责转换。

人物加载状态属于 application/story 的可重建资源事件，不参与 `BranchStoryState` 重放：

```text
CharacterLoadStarted
CharacterLoaded
CharacterLoadFailed
CharacterResourceReleased
```

core 可以产生 `ResourceLifecycleCue`，application 执行实际 I/O 后再发出上述事件，并按需转换为实时协议事件。两类事件必须使用不同的类型命名空间和持久化策略。

### 9.3 节点进入流程

```text
接收行动
  → 按 branchId 检查 commandId 幂等索引
  → 检查会话、节点与 revision
  → 查找当前节点允许的 choice/intent
  → 计算 when 条件
  → 在副本上应用效果并计算 unlock 与目标节点 enterWhen
  → 解析 CastPolicy，生成 CastResolutionPlan
  → application 加载最小人物档案；失败时在计划上执行演员 fallback
  → 在同一分支提交中写入 BranchStoryState、ActiveCast、StoryEvent 与命令结果
  → 提交后按需加载可降级演出资源
  → 生成 ActorContext
  → 调用场景 LLM
  → 发出演出事件
```

状态与 `ActiveCast` 必须作为同一分支 revision 提交，并先于场景 LLM 的最终演出调用。只要场景具有对白，就不存在“演员表尚未决定”的最终演出请求；LLM 或可降级演出资源失败时，状态保持已提交，前端可以使用原 `commandId` 的结果重试演出，不重复执行效果或再次选角。

### 9.4 自由输入

玩家自由文本先经过场景理解阶段，返回候选意图：

```json
{
  "intentId": "investigate-side-window",
  "confidence": 0.91,
  "evidence": "玩家明确表示想绕到旧校舍后方检查窗户"
}
```

剧情引擎只接受当前节点 `freeformIntents` 中存在的 ID。

- 高置信且允许：执行意图效果。
- 低置信：作为普通对话，不改变关键状态。
- 意图不存在：按控制强度拒绝、即兴或请求作者扩写。
- 场景理解输出中的 `effects` 字段一律忽略；效果只能来自已发布节点。

当前节点可以额外发布人物登场意图或 `reasonId`。玩家说“给周警官打电话”时，场景 LLM 只能请求已发布的 `request_character_entry`；引擎验证成功并返回新 `ActiveCast` 后，周警官才能在最终对白中发言。

### 9.5 被动语义信号

玩家自由文本无论是否匹配主动 Intent，都可以同时产生零个或多个候选 `SemanticSignal`。一个玩家输入轮次的推荐编排为：

```text
玩家文本
  → 识别主动 Intent 与候选 SemanticSignal
  → 引擎验证并执行主动 Intent
  → 语义信号策略去重、限额并选择效果
  → 在同一 StoryTransaction 中提交可接受的指标变化
  → 重新计算依赖变化指标的节点条件
  → 生成关系、推理、压力等非数值化演出提示
  → 场景 LLM 生成最终对白 JSON
```

场景 LLM 可通过内部工具提交候选信号：

```json
{
  "id": "tool-signal-4",
  "name": "propose_semantic_signals",
  "arguments": {
    "expectedNodeId": "old-school-gate",
    "expectedRevision": 42,
    "sourceMessageId": "message-128",
    "signals": [
      {
        "signalId": "question-authority",
        "strength": "strong",
        "confidence": "high",
        "speechAct": "endorsement"
      }
    ]
  }
}
```

工具 Schema 中的 `signalId` 应动态限制为当前场景可供评估的信号 ID。即使 Provider 支持严格 `enum`，引擎仍需验证节点、revision、信号可见性和策略限额。

不允许语义信号修改状态时，场景 LLM 仍可对玩家表达作出自然反应，但该表达不产生权威指标变化或解锁事件。

### 9.6 重新生成与回溯

- 重新生成场景演出不得重复执行剧情效果。
- 重新生成场景演出不得重新提交或重复接受语义信号。
- 回溯到某个用户输入前，必须恢复与该历史位置对应的分支检查点和 `headEventId`。
- Fork 必须从历史位置对应的剧情状态创建新分支，而不是复制分支当前最新状态。
- 清空历史时同时清理分支级剧情状态，但不得清除全局解锁。
- 重新生成演出复用该历史位置已经提交的 `ActiveCast`，不得重新运行非确定性选角。
- 回溯、Fork 和切换分支必须连同 `castState` 恢复；人物加载缓存可以重新建立，不属于存档事实。

## 10. AI 剧本编译器

### 10.1 编译阶段

AI 生成不得依赖单次大 Prompt。标准流水线为：

1. **需求提取**：题材、人物池、冲突、秘密、长度、路线、结局与限制。
2. **假设确认**：为缺失信息生成显式默认值，保存到草稿元数据。
3. **故事圣经**：世界规则、人物动机、秘密和不可变事实。
4. **人物设计**：建立 `CharacterRegistry`、稳定人物 ID、角色职责与标签；缺失人物只生成 `CharacterDraft`，不直接引用本地文件。
5. **状态设计**：限制变量数量，为每个变量说明用途、作用域和是否允许语义输入。
6. **剧情骨架**：生成 `NarrativeGraph` 的章节、关键节点和结局连通关系。
7. **演员规划**：为节点生成 `CastPolicy`，标明固定人物、必需职责、动态候选、人数上限和失败 fallback。
8. **章节扩写**：逐章生成节点、选择、意图、语义信号定义、条件和效果。
9. **逻辑图生成**：将信号、指标、演员、策略、条件、效果和解锁连接为类型化 `RuleGraph`。
10. **资源绑定**：仅从传入的可用资源 ID 和已登记人物 ID 中选择。
11. **图编译**：规范化内联 DSL、检查端口并生成 `StoryProgram`。
12. **静态校验**：Schema、引用、类型、演员职责、可达性和秘密暴露检查。
13. **路径模拟**：覆盖结局、关键节点和演员表可解析性。
14. **定向修复**：将结构化错误报告交给修复 LLM，只允许提交补丁。

每一步使用结构化输出，并保存中间产物，支持失败后续跑和局部重生成。

### 10.2 生成预算

为控制复杂度，首版建议默认限制：

- 8～25 个剧情节点。
- 3～8 个核心状态变量。
- 1 条主线、1～3 条支线。
- 2～4 个结局。
- 每个节点 2～4 个结构化选择。
- 每个节点不超过 8 个自由意图。
- 每个场景不超过 12 个可见语义信号定义。
- 项目人物登记表不设面向用户的小型固定上限，但受包大小、索引和导入资源预算约束。
- 每个场景默认最多 8 个激活人物；关键场景建议 2～5 个，以控制对白一致性和 Prompt 体积。

超出限制的长篇剧本先生成全局骨架，再按章节延迟生成。

### 10.3 AI 补丁协议

局部重生成不得直接重写整个工程。编译器输出受限补丁：

```json
{
  "baseVersion": 3,
  "operations": [
    {
      "op": "replace-node",
      "nodeId": "old-school-gate",
      "preserve": ["id", "incomingEdges"],
      "value": {}
    }
  ]
}
```

补丁必须经过：

- Schema 校验。
- 基础版本检查。
- 引用完整性检查。
- 承诺边界检查。
- 完整剧本重新校验。

### 10.4 动态扩写

动态作者只允许修改未承诺的未来区域：

| 区域 | 运行时策略 |
| --- | --- |
| 已发生节点 | 不可修改，只能追加新的解释事件 |
| 当前节点 | 不可修改进入条件；可补充不影响规则的演出说明 |
| 已承诺的近期节点 | 条件、效果和秘密冻结 |
| 未承诺的远期节点 | 允许重写或替换 |

如果剧情需要推翻既有事实，必须创建新的正式剧情事件，例如“发现钥匙是复制品”，不得删除旧 Canon。

## 11. LLM 上下文隔离

### 11.1 作者上下文

作者 LLM 可以看到：

- 完整故事圣经。
- 隐藏秘密和未来结局。
- 已发布节点和未发布草稿。
- 玩家已经发生的 Canon 和当前风格偏好。

作者输出只能进入草稿或候选补丁，不能直接进入运行状态。

### 11.2 场景理解上下文

场景 LLM 的意图解析与语义信号评估阶段只需要看到：

- 当前节点 ID。
- 当前 `ActiveCast` ID，以及节点允许请求登场的候选人物 ID 或 `reasonId`。
- 当前允许的自由意图及少量示例。
- 当前可评估的语义信号 ID、判定标准和允许的 speech act。
- 玩家输入。
- 必要的已知事实。

场景理解阶段不需要看到未来节点正文。公开信号标准可以与场景演出上下文共用；包含角色秘密或隐藏判定依据的信号必须在隔离的评估调用中处理，演出阶段只接收最终的 `performanceHint`。

### 11.3 选角上下文

需要 AI 解决多个同等合格候选时，`CastPlanner` 只能看到：

- 已经过确定性过滤的 `candidateIds`。
- 每个候选的公开角色职责、标签、优先级和与当前场景有关的连续性摘要。
- `requiredRoles`、人数约束和选择目标。
- 当前分支中已经公开的人物关系事实。

它不得看到被排除人物、未解锁秘密、完整人物 Prompt 或本地文件路径。输出只包含所选 ID、职责绑定和简短 reason code。简单策略不需要调用 LLM；如果共用场景模型，选角仍是最终演出前的独立工具阶段。

### 11.4 场景演出上下文

场景 LLM 的最终演出阶段可以看到：

- 当前节点的 `exposedContext`。
- 当前权威状态的可见投影。
- 已发生 Canon。
- 当前行动结果。
- 已接受语义信号产生的非数值化反应提示。
- `ActiveCast` 中人物的完整可见档案、角色职责和必要关系摘要。
- 动态 `speakerAllowlist` 以及允许使用的场景和资源。
- Shinsekai 现有对白 JSON 输出契约。

场景 LLM 的最终演出阶段不得看到：

- `lockedContext`。
- 未解锁节点正文。
- 隐藏结局条件。
- 其他对话分支的状态。
- 作者内部推理与修复报告。
- 隐藏语义信号的完整判定依据。
- 未激活人物的完整档案、秘密、人格 Prompt 和演出资源。

对白 JSON 的 `characterId` Schema 应按本轮 `speakerAllowlist` 生成严格 enum，并始终保留 `NARR` 与 `SYSTEM`。Provider 不能生成动态 enum 时，应用层仍须逐项校验。

### 11.5 场景 LLM 工具循环

意图解析、语义信号评估和最终场景演出可以使用同一个场景模型，但不能省略“先裁决、后演出”的时序：

```text
场景 LLM 返回 tool_call
  → 剧情引擎执行 Intent、SemanticSignal 和/或人物变更请求
  → 引擎解析并提交新的 ActiveCast
  → 工具返回权威状态与 speakerAllowlist
  → 同一个场景 LLM 返回 Shinsekai dialog JSON
```

这表示同一个模型和同一轮会话上下文，不保证只有一次模型推理。Provider 不支持可靠工具调用时，降级为“结构化理解请求 → 引擎裁决 → 结构化对白请求”。不得把候选状态变化和假定成功的对白合并成一次未经裁决的最终 JSON。

### 11.6 调用频率

- 普通聊天且无需指标评估：场景 LLM 直接演出。
- 自由行动或允许语义输入：场景 LLM 工具循环，然后继续演出。
- 隐藏语义标准：隔离的评估调用、引擎裁决，然后场景 LLM 演出。
- 结构化选择：剧情引擎，然后场景 LLM 演出。
- 角色职责有多个等价候选：规则优先；确有叙事取舍时调用 `CastPlanner`，提交演员表后再演出。
- 中途人物登场：场景 LLM 工具请求、引擎裁决并返回新 allowlist，然后由同一模型继续演出。
- 章节边界或自由模式扩写：作者 LLM，校验后在后续轮次生效。

作者 LLM 不应在每一轮调用。

## 12. 状态、事件与存储

### 12.1 BranchStoryState

`BranchStoryState` 只包含随对话分支 Fork、回档和切换的权威状态：

```json
{
  "schemaVersion": 2,
  "storyId": "campus-mystery",
  "storyVersion": 3,
  "sourceHash": "sha256:5b90...",
  "branchId": "branch-3",
  "revision": 42,
  "currentNodeId": "old-school-gate",
  "variables": {
    "trust.ling": 35,
    "suspicion.headmaster": 24,
    "flags.shared_secret": false,
    "inventory": ["old_school_key"]
  },
  "semanticSignalState": {
    "chapterMetricUsage": {
      "trust.ling": 4,
      "suspicion.headmaster": 7
    },
    "recentFingerprints": [
      "question-authority:archive-records"
    ]
  },
  "castState": {
    "registeredStoryCharacterIds": ["ling", "detective-zhou"],
    "activeCharacterIds": ["ling"],
    "offstageCharacterIds": ["detective-zhou"],
    "storyScopedCharacterIds": ["detective-zhou"],
    "adHocCharacterIds": [],
    "roleBindings": {
      "companion": "ling"
    },
    "resolvedForNodeId": "old-school-gate",
    "castRevision": 7
  },
  "completedNodeIds": ["transfer-day", "investigation-preparation"],
  "failedNodeIds": [],
  "canon": [
    {
      "id": "canon-12",
      "text": "绫同意与玩家夜探旧校舍",
      "sourceEventId": "01J4M7W3J8MZQ6V1E6H0NBB7R8"
    }
  ],
  "headEventId": "01J4M7W3J8MZQ6V1E6H0NBB7R8"
}
```

`variables` 只保存定义为 `branch` 的变量；加载器发现 `global` 或未支持的 `run` 变量被写入此处时必须拒绝存档。`castState` 同样属于分支权威状态，随历史检查点、Fork 和回档恢复。`loadedCharacterIds`、立绘纹理和语音模型句柄不写入存档；这些是根据 `ActiveCast` 可重建的 application 缓存。项目静态登记表保存在 `StoryProgram`。

### 12.2 GlobalStoryProgress

`GlobalStoryProgress` 与聊天分支分开保存，键空间至少包含用户资料和剧本 ID：

```json
{
  "schemaVersion": 1,
  "profileId": "local-default",
  "storyId": "campus-mystery",
  "revision": 8,
  "variables": {
    "unlockedEndings": ["truth-ending"],
    "unlockedCgs": ["old-school-truth"]
  },
  "appliedCommandIds": [
    "018f6f9a-6ef1-7c61-9b4f-0c91eb94d1f0"
  ]
}
```

全局进度不进入 `BranchStoryState`、分支检查点或聊天快照。Fork 和回档只能恢复分支状态，不能撤销已经获得的结局、CG 或周目解锁。首版全局效果只允许集合追加等单调、可幂等操作；删除、计数递减和任意覆盖不属于首版能力。

### 12.3 作用域与跨存储提交

| 作用域 | 随 Fork 复制 | 随回档恢复 | 权威存储 | 示例 |
| --- | --- | --- | --- | --- |
| `branch` | 是 | 是 | `BranchStoryState` | 信任、怀疑、压力、道具、当前节点、人物生死 |
| `run` | 不支持 | 不支持 | 无 | 本周目共享元数据 |
| `global` | 否 | 否 | `GlobalStoryProgress` | 结局图鉴、CG、二周目解锁 |

首版正式支持 `branch` 和 `global`；Schema 可以保留 `run` 枚举值，但发布器必须拒绝实际使用，直到其 Fork 和回档语义另行确定。

一次命令可以逻辑上同时产生分支效果与全局解锁，但两个文件存储之间不假设存在操作系统级事务。application 使用 durable outbox 保证：

1. core 在内存中验证完整 `StoryTransaction`，生成分支事件和只包含单调操作的 `globalEffects`。
2. 分支 generation 原子提交时一并写入以 `commandId` 为键的 global effect outbox。
3. application 在返回成功 ack 前，将 outbox 幂等应用到 `GlobalStoryProgress` 并原子替换进度文件。
4. 如果进程在分支提交后、全局应用前退出，恢复流程先排空 outbox，再开放会话。
5. 同一 `commandId` 的全局效果重复应用必须得到相同结果；分支回档不生成反向全局效果。

因此，对用户可观察的成功命令仍满足全部效果已提交；崩溃窗口由持久 outbox 恢复，而不是依赖跨目录 rename。

### 12.4 分支事件日志

事件日志用于调试、历史位置映射、幂等结果、分支 Fork 和剧本升级诊断。会话可以共用一个有界日志，但每条事件必须携带分支身份和因果父事件：

```json
{
  "id": "01J4M7W3J8MZQ6V1E6H0NBB7R8",
  "sessionEventSeq": 108,
  "branchId": "branch-3",
  "branchRevision": 42,
  "parentEventId": "01J4M7VXR6SS2NA7K7N3Y3M4B1",
  "type": "NodeEntered",
  "timestamp": 1786000000000,
  "storyId": "campus-mystery",
  "storyVersion": 3,
  "sourceHash": "sha256:5b90...",
  "nodeId": "old-school-hall",
  "cause": {
    "commandId": "018f6f9a-6ef1-7c61-9b4f-0c91eb94d1f0",
    "choiceId": "use-old-key"
  }
}
```

- `id` 在整个会话内唯一，不由 branch revision 推导。
- `sessionEventSeq` 只用于日志排序和实时诊断，不能作为分支重放范围。
- `headEventId` 与 `parentEventId` 形成分支因果链；Fork 后第一条新事件指向 Fork 检查点的 head。
- 重放从检查点沿目标分支因果链前进，不能按全局行号范围应用事件。
- application 资源加载事件不写入该领域日志，也不参与状态重放。

首版采用“快照为主、有限事件日志为辅”，不要求完全事件溯源。裁剪日志前必须生成包含完整 `BranchStoryState`、`headEventId` 和幂等索引的检查点，并保留所有活动分支仍引用的祖先事件。

### 12.5 文件结构

```text
data/stories/campus-mystery/
  manifest.yaml
  story_bible.yaml
  variables.yaml
  cast.yaml
  graph.yaml
  logic_graph.yaml
  characters/
    detective-zhou.yaml
  chapters/
    chapter-1.yaml
    chapter-2.yaml
    chapter-3.yaml
  assets.yaml
  editor_state.json
  compiled/
    story_program.json
  revisions/
    0003/

data/story_progress/<profile-id>/
  campus-mystery.json

data/chat_history/<session-id>/
  session.json
  generations/
    0000000041/
      active.json
      branches.json
      story-events.jsonl
      global-effects-outbox.json
    0000000042/
      active.json
      branches.json
      story-events.jsonl
      global-effects-outbox.json
```

`session.json` 是小型原子指针，只引用当前和上一份完整 generation。所有读写必须经过 application 注入的领域仓库；React 和 bridge 不直接访问这些文件。聊天清理、导入、导出和诊断归档必须显式覆盖 generation 与 outbox 文件，但不能递归删除不属于会话存储的内容。

### 12.6 分支存储升级与原子提交

generation 中的 `branches.json` 使用版本 2：

```json
{
  "version": 2,
  "generation": 42,
  "activeBranchId": "branch-3",
  "branches": {
    "branch-3": {
      "id": "branch-3",
      "parentBranchId": "main",
      "forkedFromEventId": "01J4M7VXR6SS2NA7K7N3Y3M4B1",
      "messages": [],
      "history": [],
      "branchStoryState": {},
      "storyCheckpoints": [],
      "processedCommands": {}
    }
  }
}
```

`storyCheckpoints` 中每项至少保存 `historyEntryId`、`branchRevision`、`headEventId`、完整分支状态或其受校验快照引用，以及状态 hash。Fork 必须从目标历史项对应的检查点创建，不能从源分支当前最新状态复制。

每次保存按以下顺序执行：

1. 在同一会话目录内创建新的临时 generation，完整写入 active、branches、有限事件日志、幂等索引和 outbox。
2. 关闭并尽可能刷新全部文件，校验 generation 内部版本、hash 和引用。
3. 将临时 generation 重命名为最终编号；失败时不修改当前指针。
4. 通过临时文件加原子 replace 更新 `session.json.currentGeneration`，并保留 `previousGeneration`。
5. 启动恢复只读取指针指向且校验完整的 generation；当前损坏时回退上一代并给出诊断，不把不同 generation 的文件混合。

迁移规则：

- 没有 `session.json` 时按版本 1 读取根目录 `active.json` 和 `branches.json`，此时 `branchStoryState` 为 `null`。
- 第一次版本 2 保存创建完整 generation 并最后切换 `session.json`；成功前不覆盖或删除版本 1 文件。
- 非剧本会话可以继续使用版本 1；进入版本 2 后，active、branches 和 story state 始终来自同一 generation。
- 剧本版本或 `sourceHash` 不兼容时停止恢复并给出明确诊断，不静默重置进度。
- generation 生成、指针替换或 outbox 应用失败时不返回成功 ack；恢复后使用 `commandId` 继续未完成提交。

## 13. 实时协议与前端类型

### 13.1 结构化选项

新增：

```ts
interface ChatOption {
  id: string;
  label: string;
  enabled: boolean;
  lockedReason?: string;
  source: "llm" | "story";
  expectedNodeId?: string;
  expectedRevision?: number;
}
```

兼容期：

```ts
type ChatOptionPayload = string | ChatOption;
```

最终 `options.show` 使用 `ChatOption[]`，剧情选项通过 `select-story-choice` 提交：

```json
{
  "commandId": "018f6f9a-6ef1-7c61-9b4f-0c91eb94d1f0",
  "branchId": "branch-3",
  "choiceId": "use-old-key",
  "expectedNodeId": "old-school-gate",
  "expectedRevision": 42
}
```

### 13.2 ChatSnapshot 扩展

```ts
interface StoryRuntimeSnapshot {
  storyId: string;
  storyVersion: number;
  revision: number;
  currentNodeId: string;
  currentNodeTitle: string;
  activeCast: StoryCharacterView[];
  objectives: StoryObjectiveView[];
  visibleVariables: StoryVariableView[];
  unlockedNotifications: StoryUnlockView[];
  ending?: StoryEndingView;
}

interface ChatSnapshot {
  // existing fields
  story?: StoryRuntimeSnapshot;
}
```

快照只包含运行界面需要的可见投影，不返回完整 `BranchStoryState`、`GlobalStoryProgress` 或秘密内容。

### 13.3 新事件

```text
story.state.replace
story.node.entered
story.node.unlocked
story.objective.updated
story.cast.replace
story.character.entered
story.character.exited
story.character.load_failed
story.ending.reached
story.error
```

事件继续使用现有 `v`、`seq`、`ts` 和快照折叠规则。`story.state.replace` 应能完整恢复剧情 UI，其他事件用于增量展示和动画。

### 13.4 新命令

```text
select-story-choice
perform-story-intent
request-character-entry
request-character-exit
promote-ad-hoc-character
dismiss-story-notification
request-story-inspector
```

旧 `submit-option` 在兼容期内继续接受字符串；结构化剧情选项优先使用 `select-story-choice`，避免工具确认选项与剧情选项共享模糊 payload。

除只读 `request-story-inspector` 外，新命令统一使用 9.1 的命令 envelope。ack 至少返回 `commandId`、`branchId`、accepted/rejected、resultingRevision 和 `eventIds`。

## 14. 与现有聊天运行时的集成

### 14.1 先抽取会话编排

当前分支、回溯、重新生成和命令处理仍有一部分集中在 `main.py` 的闭包中。接入剧情系统前，应先抽取：

```text
application/bootstrap/chat_runtime.py
application/chat/conversation_session.py
application/chat/conversation_branch_service.py
application/story/session.py
application/story/branch_integration.py
```

`main.py` 只保留：

- 启动参数解析。
- 调用 `application.bootstrap.chat_runtime` 的单一入口。
- 将启动失败转换为进程退出码。

`application/bootstrap/chat_runtime.py` 负责依赖组装、运行模式选择和 workflow 启停；`application/chat/conversation_session.py` 负责 stream command 到 application service 的分发。不得把命令路由、条件解析、效果执行、分支状态或剧情存档继续留在 `main.py`。

### 14.2 模板集成

自由聊天模式继续使用当前 `scenario + system template`。

剧本模式改为：

```text
输出契约与当前 ActiveCast 人物档案
  + 当前 ActorContext
  + 当前行动结果
  + 可用资源投影
  + JSON 格式提醒
```

不把完整 `StoryProject`、完整人物登记表或未在场人物 Prompt 拼接进 system prompt。现有模板生成器若按启动时 `selectedCharacters` 一次性构造所有人物配置，应改为按本轮 `ActorContext` 构造；旧 `selectedCharacters` 在剧本模式中迁移为 `initialCast`，在自由聊天模式中保持原行为。

### 14.3 STAT 集成

- 自由聊天模式：继续接受 LLM 生成的 `STAT`。
- 剧本模式：权威状态由 `StoryStateView` 投影，LLM `STAT` 默认忽略或仅作为非权威演出文本。
- 前端统一使用 `stats.update` 或新的剧情状态投影渲染，不能展示互相矛盾的两套数值。

### 14.4 资源演出

节点 `presentation` 中只保存资源 ID。`application/story/presentation.py` 将其解析为现有场景、BGM、CG 和特效事件。

人物立绘、Live2D、TTS voice、短期记忆视图和人物工具权限也按 `ActiveCast` 动态绑定。人物进入时先建立资源与记忆投影，人物退出时停止新增对白并允许延迟释放缓存；长期记忆仍按稳定 `characterId` 隔离，不能因演员替换串写到其他人物。

资源缺失时：

- 剧情状态仍然提交。
- 发出可诊断警告。
- 使用透明场景、静音或无特效降级。
- 不因资源播放失败回滚剧情事务。

## 15. React 界面

### 15.1 路由与功能目录

```text
frontend/src/entities/story/
  types.ts
  repository.ts
  schema.ts

frontend/src/features/story-generator/
frontend/src/features/story-editor/
frontend/src/features/story-validator/
frontend/src/features/story-runtime/
```

建议新增设置中心路由：

```text
/settings/stories
/settings/stories/new
/settings/stories/:storyId/edit
/settings/stories/:storyId/validate
```

### 15.2 生成器

生成器包含：

- 剧情梗概文本框。
- 角色、长度、路线和控制模式。
- 可用资源选择。
- 分阶段生成进度与日志。
- 取消、失败重试和从中间步骤继续。
- 生成假设预览。

生成使用现有长任务模式，不阻塞前端请求。

### 15.3 编辑器

首版优先实现：

- 节点列表与基础连接关系。
- 节点属性表单。
- 条件和效果构建器。
- 变量与叙事指标管理。
- 语义信号目录、强度效果、可见性、限额和重复窗口管理。
- 只读或半交互的 `NarrativeGraph + RuleGraph` 自动布局视图。
- 从运行时事件反查规则节点的执行路径高亮。
- 校验问题定位。
- YAML/JSON 高级只读预览或可选编辑。
- 人物登记表：来源、版本、标签、职责、资源状态和剧本域人物管理。
- 场景 `CastPolicy` 编辑器：固定/混合/职责/动态模式、候选条件、最大人数和 fallback。
- 指定节点的演员表解析预览，展示每个候选的接受或排除 reason code。

简单模式中的表单操作生成固定类型化图模板；用户不需要理解端口和事件流。高级模式的自由拖拽连线可以后置，首版先保证表单编辑、自动布局图、类型错误定位和编译预览可用。

### 15.4 聊天舞台

聊天舞台增加：

- 当前章节或节点的轻量显示。
- 目标/任务抽屉。
- 权威状态面板。
- 按剧本展示策略显示或隐藏指标变化；默认通过演出反馈而不是直接弹出数值增减。
- 解锁通知。
- 结构化选项的锁定与原因展示。
- 人物登场、退场和替换提示；调试模式可查看当前演员表，正常演出无需持续显示技术状态。
- 结局弹层。

这些元素应沿用现有聊天主题 token，不把设置中心风格直接搬入演出窗口。

## 16. 校验与路径模拟

### 16.1 错误等级

| 等级 | 行为 | 示例 |
| --- | --- | --- |
| error | 阻止发布 | 起点不存在、变量类型错误、目标节点缺失 |
| warning | 允许发布但需确认 | 某结局只有一条极窄路径、节点没有资源 |
| info | 提供优化建议 | 变量过多、节点选项文本重复 |

### 16.2 静态校验

至少检查：

- Schema 与版本。
- ID 唯一性。
- 节点、变量、资源和结局引用。
- 条件和值的类型匹配。
- 起始节点和终止节点。
- 不可到达节点。
- 无出口且非结局节点。
- 明显无限循环。
- 道具只有消费没有来源。
- 节点在进入前要求自己完成。
- 互斥条件同时要求成立。
- `lockedContext` 被复制到 `exposedContext`。
- `StoryMetric` 引用了不存在、非整数或禁止语义输入的变量。
- `run` 作用域被实际使用，或 `global` 变量声明了非单调效果。
- 节点完成/失败状态被重复声明为普通变量。
- `SemanticSignalDefinition` ID 重复、效果目标缺失或强度映射不完整。
- 信号限额、重复窗口或信号目录超出允许范围。
- 隐藏信号的判定标准被复制到场景演出可见上下文。
- `RuleNode` 类型未知或节点配置不符合对应 Schema。
- 人物 ID、来源和固定 revision 无效或重复。
- 剧本包内人物路径越界，或外部人物没有用户授权记录。
- `CastPolicy.required`、`forbidden`、标签查询和职责引用不存在。
- `minActive > maxActive`、固定人物超出 `maxActive` 或同一人物被绑定到互斥职责。
- 关键场景的必需职责在任意可达状态下都没有候选，且未声明 fallback。
- 演员变化规则可能让必需人物在对白前离场，或让未登记人物进入 `speakerAllowlist`。
- `character-enter/exit/replace` 节点端口类型、revision 和事件原因引用错误。
- 必需端口没有连接、连接数量超限或端口类型不匹配。
- `MetricReferenceNode` 保存了重复状态而不是引用变量 ID。
- 同一事务存在组合逻辑循环或事件—效果自触发循环。
- `StoryProgram.sourceHash` 与创作源不一致。
- 编译后的规则无法通过源映射定位到创作节点。

### 16.3 路径模拟

模拟器使用抽象状态遍历，不调用 LLM。输出：

- 每个结局的可达路径数量或上限估计。
- 关键节点的最短路径。
- 不可达节点。
- 状态空间截断原因。
- 可能的软锁和重复循环。
- 关键节点中无法满足的必需人物、职责绑定和演员 fallback 路径。

为防止状态爆炸，需要配置：

- 最大探索状态数。
- 最大路径深度。
- 整数变量离散化策略。
- 重复状态哈希。

模拟结果不是形式化证明，但应捕获常见结构错误。

## 17. 安全与鲁棒性

### 17.1 数据安全

- 不执行剧本内任意代码。
- 文件引用经过既有安全路径校验。
- 导入包限制文件数量、单文件大小、总大小和嵌套深度。
- 拒绝绝对路径、目录穿越和符号链接逃逸。
- 剧本 ID、节点 ID 和资源 ID 使用受限字符集。
- 外部 `.char` 只能由用户选择或已授权引用导入；LLM 工具不接受任意文件路径，只接受应用层发放的导入 token。
- `embedded` 与 `author-generated` 人物只能写入当前剧本域，不能静默安装到用户全局人物库。
- 人物档案、头像、语音和模型资源分别限制大小、类型与解压总量，导入失败不得留下半登记状态。

### 17.2 Prompt 安全

- 用户梗概和导入剧本属于不可信内容。
- 作者、场景理解、隐藏语义评估和最终场景演出的系统指令分层组装。
- 剧本正文不能覆盖输出协议、工具权限或宿主系统指令。
- 人物档案和临时 NPC 描述同样属于不可信内容，不能扩大 `speakerAllowlist`、人物工具权限或本地文件访问范围。
- `lockedContext` 的过滤发生在 Python 数据层，而不是 Prompt 文本层。
- 隐藏 `SemanticSignalDefinition` 的判定依据只进入隔离评估上下文；场景演出阶段只接收受控反应提示。

### 17.3 资源限制

- 条件树限制深度和节点数量。
- 单节点限制选择、自由意图和可见语义信号数量。
- Canon 和事件日志设置大小上限与压缩策略。
- 登记表分页和按 ID 索引；限制单场 `ActiveCast`、候选池投影、并行人物加载数与角色档案 Prompt token。
- 超出场景人数上限时按已发布优先级和连续性策略裁剪可选人物，不得裁掉 `required` 后继续静默演出。
- LLM 修复尝试设置次数上限。
- 动态扩写失败时继续使用当前已发布剧情，不破坏存档。

### 17.4 用户画像边界

- `StoryMetric` 与 `SemanticSignal` 表示当前虚构剧情中的运行状态，不等同于对真实用户人格、道德或心理状况的判断。
- 信号定义不得要求推断宗教、健康、性取向等与剧情行为无关的敏感现实属性。
- 语义指标默认使用 `branch` 作用域，不跨剧本复用；需要全局作用域时必须由创作者显式声明并向用户展示。
- 用户应能查看、重置或清除当前剧本产生的语义指标状态。
- 默认日志不记录信号 evidence 原文；诊断记录使用 `sourceMessageId`、受限 reason code 和不可逆 fingerprint。

## 18. 可观测性与诊断

建议记录以下结构化事件：

```text
story.compile.started
story.compile.phase_completed
story.compile.failed
story.validation.completed
story.runtime.command_rejected
story.runtime.transition_committed
story.semantic_signal.accepted
story.semantic_signal.rejected
story.metric.changed
story.cast.resolve_started
story.cast.resolved
story.cast.rejected
story.character.load_failed
story.runtime.actor_failed
story.branch.forked
story.restore.failed
story.migration.completed
```

日志不得默认记录：

- 完整用户剧情正文。
- 未解锁秘密。
- LLM API Key。
- 完整 Prompt 与模型原始响应。

剧情检查器应提供仅本地可见的诊断视图：

- 当前节点和 revision。
- 最近剧情事件。
- 可见变量和隐藏变量的受控开发视图。
- 某个选项不可用的条件解释。
- 最近语义信号、拒绝原因、去重键和指标限额使用情况。
- 当前场景演出上下文预览。
- 当前 `ActiveCast`、职责绑定、候选过滤 reason code、加载状态和动态 `speakerAllowlist`。

## 19. 测试策略

### 19.1 `core/story` 单元测试

- 每个条件运算符。
- 每个效果运算符。
- 类型错误和边界值。
- 事务回滚。
- branch/global 变量按声明路由，`BranchStoryState` 拒绝全局变量。
- `completedNodeIds/failedNodeIds` 是节点状态唯一事实源。
- 节点状态派生。
- 结局判定。
- 相同命令幂等性。
- 校验器与模拟器。
- 叙事指标上下限、每轮/场景/章节限额。
- 语义信号强度映射、重复窗口和 `causeGroup` 去重。
- 同一消息主动 Intent 与被动信号不重复计分。
- RuleGraph 端口类型、连接基数、禁止循环和级联深度。
- 图源与内联 DSL 规范化为相同 IR 后具有等价行为。
- StoryProgram 编译确定性、sourceHash 和诊断源映射。
- 四种 `CastPolicy` 模式、候选过滤、职责绑定、人数上下限和稳定排序。
- CastPlanner 提交非法/未登记 ID、超员或过期 revision 时被拒绝。
- 缺少必需职责时按声明 fallback 行为执行。
- `CastResolutionPlan` 保持纯数据且不执行人物或资源 I/O。

建议使用属性测试验证：

- 状态永远符合变量 Schema。
- 失败事务不改变 revision。
- 沿同一分支因果链重放得到相同状态，兄弟分支事件不会串入。

### 19.2 application 集成测试

- 启动剧本会话。
- 结构化选择完整闭环。
- 自由输入意图映射。
- 普通对话语义信号的接受、拒绝、限额和阈值解锁。
- 引用、提问、讽刺、假设、重复表达和言行不一致场景。
- 场景 LLM 失败后的演出重试。
- 同一 `commandId` 重试返回原 ack，不重复执行；相同 ID 的不同 payload 被拒绝。
- 两个分支从同一检查点交错提交后，各自恢复到正确的 `headEventId` 和状态。
- 在 generation 完成、指针切换、global outbox 应用等边界注入崩溃，恢复时不会混合不同 generation。
- 分支回档不撤销 `GlobalStoryProgress`；未完成 global outbox 在会话开放前被幂等排空。
- 两个相邻场景使用不相交演员表时按需加载、提交、退场和恢复。
- 中途登场、退场、替换与临时 NPC 晋升完整闭环。
- Fork 后不同分支拥有不同 `ActiveCast`，回档恢复演员表但重新建立加载缓存。
- 必需人物最小档案加载失败时在提交前执行 fallback；无 fallback 时剧情 revision 不变。
- 可降级演出资源在提交后加载失败时保留剧情状态并发出 application 事件。
- 清空、回溯、重新生成、Fork 和切换分支。
- 剧本版本不匹配恢复。
- 非剧本聊天回归。

### 19.3 协议测试

- 新旧选项 payload 兼容。
- WebSocket 命令 ack 包含 `commandId`、`branchId`、结果 revision 和事件 ID；重试返回同一结果。
- `story.*` 事件折叠进快照。
- 重连恢复和重复事件忽略。
- 秘密字段不出现在快照和 DTO 中。
- `story.cast.replace` 与人物进入/退出事件可折叠成一致的 `activeCast` 快照。
- 未激活或未登记人物不会通过 DTO、对白事件或重连快照成为 speaker。

### 19.4 前端测试

- 生成进度与取消。
- 节点和条件表单。
- 校验问题定位。
- 锁定选项不可点击。
- 过期 revision 的选择错误处理。
- 任务、状态、解锁和结局展示。
- 旧自由聊天界面无回归。
- 人物登记、演员策略编辑、解析预览和登退场展示。

### 19.5 端到端测试剧本

仓库应包含一个小型、无敏感内容的固定剧本：

- 6～8 个节点。
- 一个数值变量、一个布尔标记和一个道具集合。
- 两个结局。
- 一条锁定路线。
- 一个自由输入意图。
- 一个影响至少两个叙事指标的语义信号。
- 一个由指标阈值解锁的节点。
- 一段由 RuleGraph 编译并可追踪到源节点的解锁逻辑。
- 至少一次 Fork 后状态差异。
- 回档其中一个分支后，全局结局解锁保持不变。
- 至少两个演员表不相交的相邻场景。
- `fixed`、`mixed` 和 `role-based` 选角各一例。
- 一次通过工具循环发生的中途人物登场。
- 一次人物资源加载失败及可重复的降级结果。

该剧本不通过 LLM 生成，确保 E2E 可重复。

## 20. 兼容与迁移

### 20.1 功能开关

初期增加：

```text
story_runtime_enabled
story_structured_options_enabled
story_ai_compiler_enabled
story_dynamic_author_enabled
story_semantic_signals_enabled
story_dynamic_cast_enabled
```

默认只在开发环境或显式启用时开放。成熟后按顺序移除实验开关，而不是永久保留多套分支代码。

### 20.2 旧聊天模板

- 没有 `storyId` 的启动请求走现有流程。
- 旧 `scenario` 仍可保存和启动。
- 剧本模式可以把原情景文本作为 AI 编译器输入，但不能自动把旧模板标记为已发布结构化剧本。
- 旧模板中的 `selectedCharacters` 在转换为剧本草稿时生成 `CharacterRegistry` 和 `initialCast`；转换前的自由聊天仍保持固定人物行为。

### 20.3 旧选项

- 接收端先支持 `string | ChatOption`。
- 发送端在剧情模式优先发送 `ChatOption`。
- 工具确认保留独立结构，不与剧情选择混用。
- 完成所有调用方迁移和测试后，再删除纯字符串剧情选项。

### 20.4 旧分支存档

- 版本 1 继续可读。
- 只有用户启动结构化剧本时才创建版本 2 剧情字段。
- 不自动为旧历史猜测剧情状态。
- 导入旧聊天作为剧本素材属于独立的 AI 转换功能，不属于存档迁移。

## 21. 实施阶段

### 21.1 推进原则与里程碑

实施按“编译 → 确定性执行 → 会话闭环 → 动态人物 → LLM 演出 → AI 创作”的依赖顺序推进。每个阶段必须形成可运行、可回归的纵向切片，不把多个尚未稳定的 LLM 能力同时接入。

- 在阶段 5 前，所有流程必须能使用确定性的 `StubSceneRenderer` 完成，不依赖模型才能测试状态正确性。
- Schema、命令和实时事件先以内部联系契约发布；通过兼容测试后再成为稳定外部协议。
- 每个阶段都保留旧自由聊天路径，并通过功能开关逐步启用。
- `CharacterRegistry`、`CastPolicy` 与 `castState` 属于基础运行能力；AI 选角、临时 NPC 和动态作者属于后续增强。

| 里程碑 | 完成阶段 | 可验证结果 |
| --- | --- | --- |
| Engine Alpha | 阶段 2 | 手写剧本可编译、模拟并确定性运行 |
| Runtime Alpha | 阶段 4 | 真实聊天舞台可保存分支并动态切换人物 |
| Playable MVP | 阶段 5 | 自由文本、受控状态和 LLM 对白形成完整游玩闭环 |
| Creator MVP | 阶段 7 | 用户可从梗概生成、编辑、发布和完成剧本 |
| Post-MVP | 阶段 8 | 开放动态作者与临时 NPC 等高不确定能力 |

### 阶段 0：冻结基线并抽取会话编排

交付：

- 为现有自由聊天、分支、回溯、重新生成和 Fork 建立基线 E2E 与协议快照测试。
- 将分支状态和命令处理从 `main.py` 抽到 `application/chat` service，将依赖组装和 workflow 生命周期移入 `application/bootstrap`。
- 建立 `application/story` 入口和剧情功能开关，但不改变默认行为。
- 保持 `PROJECT_STRUCTURE.md`、架构守卫和 Tauri 资源验证与新增 story 子目录一致。
- 明确旧 `selectedCharacters`、聊天历史和模板的兼容边界。

退出标准：`main.py` 只解析入口参数、调用 application bootstrap 并映射退出码；功能开关关闭时，基线测试与现有协议保持一致。

### 阶段 1：剧本 Schema 与编译骨架

交付：

- `StoryProject`、`NarrativeGraph`、`RuleGraph`、变量、条件、效果和事件 Schema。
- `CharacterRegistry`、`CastPolicy`、人物职责和演员节点 Schema。
- 内联 DSL 到规范化 IR 的转换、强类型端口检查和 `StoryProgram` 编译骨架。
- `sourceHash`、源映射、版本校验和结构化诊断。
- 一个固定、手写、无敏感内容的测试剧本工程。

本阶段不接会话存档、不调用 LLM，也不加载真实人物资源。

退出标准：相同创作源能够重复生成字节级稳定或语义等价的 `StoryProgram`；非法引用、端口和循环在发布前被拒绝并定位到源节点。

### 阶段 2：确定性剧情内核与模拟器

交付：

- `BranchStoryState`、`GlobalStoryProgress`、`StoryStateView`、领域命令、领域事件、revision、幂等和事务回滚。
- 节点进入、选择、Intent、条件、效果、解锁和结局判定。
- `StoryMetric`、`SemanticSignalDefinition`、去重、限额和 `causeGroup` 的纯逻辑；信号输入使用测试夹具，不调用模型。
- 纯逻辑 `CastResolver`：固定、混合、职责和动态候选模式，以及稳定排序和 fallback。
- 路径模拟、演员表可解析性检查和属性测试。
- `StubSceneRenderer`，仅把权威结果转换为可断言的演出占位事件。

退出标准：纯领域测试能够把固定剧本从起点运行到所有测试结局；沿分支因果链重放得到相同状态；branch/global 变量不会进入错误存储；所有测试场景的 `ActiveCast` 都可确定性复现。

### 阶段 3：会话、存档与实时协议闭环

交付：

- `StorySession` 与聊天会话编排集成。
- 分支存储版本 2、generation 指针、历史检查点、因果 `headEventId`、幂等索引、global effect outbox 和原子保存。
- `branchStoryState` 与 `castState` 的 Fork、回档、切换、重连和重启恢复；全局进度不随分支恢复。
- 结构化选项、剧情快照、实时事件和兼容命令。
- 聊天舞台最小节点、目标、状态和演员表调试视图。
- 旧存档只读迁移、过期 `sourceHash` 拒绝和可恢复诊断。

人物资源仍使用测试替身，场景演出仍使用 `StubSceneRenderer`。

退出标准：手写剧本可以在真实聊天舞台完成、回档、Fork、切换和恢复；相同 `commandId` 返回相同结果；在 generation 和 outbox 的每个崩溃窗口恢复后，消息、分支状态、事件头和全局解锁保持一致；分支切换同时恢复对应 `ActiveCast`。

### 阶段 4：动态人物与资源适配

交付：

- `local-library`、`embedded`、`user-imported` 和 `author-generated` 的人物来源解析接口。
- 人物 revision 固定、导入 token、安全路径校验和剧本域隔离。
- 人物档案按需加载、缓存、预载、释放和失败状态机。
- `ActiveCast` 到立绘、Live2D、TTS、人物记忆和工具权限的动态绑定。
- 人物登记、登场、退场、替换以及资源失败 fallback 的 application service。
- 将旧 `selectedCharacters` 转换为剧本 `initialCast` 的显式迁移流程。

本阶段先支持已登记人物和剧本域人物；`AdHocCharacter` 的运行时生成与晋升不作为阻塞项。

退出标准：两个演员表不相交的相邻场景可以在聊天舞台正确加载和释放人物；必需人物 readiness 失败在提交前执行 fallback，可降级演出资源失败发生在提交后且不改变剧情事实；重启后从 `castState` 重建资源。

### 阶段 5：场景 LLM、自由输入与受控演出

交付：

- 作者上下文、场景理解上下文、选角上下文和 `ActorContext` 的程序侧隔离。
- 场景 LLM 工具循环：Intent、SemanticSignal 和人物变更请求先裁决，最终对白后生成。
- 动态 `speakerAllowlist`、对白 JSON Schema、非法 speaker 拒绝和受限修复。
- 自由文本意图识别与预定义语义信号评估。
- 可选 `CastPlanner`；确定性选择始终优先，复杂歧义场景才调用模型。
- 隐藏秘密、隐藏信号标准和未在场人物档案的隔离测试。
- 模型失败、超时、重复工具调用和演出重试的降级策略。

退出标准：自由输入不能越权改变状态；模型只能提交已发布 Intent、signal ID 和人物 ID；最终对白只能由本轮 `ActiveCast` 发言；演出重试不重复执行状态效果或选角。

### 阶段 6：AI 剧本编译器

交付：

- 从梗概到需求、圣经、人物、状态、剧情图、逻辑图和资源绑定的多阶段生成任务。
- `CharacterDraft`、人物职责、场景 `CastPolicy` 和 fallback 的结构化生成。
- 中间产物、取消、失败续跑、局部重生成和受限补丁协议。
- 静态校验、路径模拟、演员表模拟和定向修复循环。
- 固定评测集、结构通过率、结局覆盖率和生成成本指标。
- 最小剧情梗概生成页面，可预览假设与校验结果。

退出标准：固定评测集中的梗概能够稳定生成通过 Schema、引用、最低可达性、演员表和秘密隔离校验的草稿；失败任务可以从最近阶段恢复。

### 阶段 7：创作编辑器与发布闭环

交付：

- 节点、变量、条件、效果、语义信号和结局编辑器。
- 人物登记表、`CastPolicy`、职责绑定、候选过滤和演员表预览编辑器。
- NarrativeGraph 与 RuleGraph 自动布局、端口诊断和编译源映射。
- AI 补丁差异、局部重生成、撤销和发布前校验。
- 草稿、发布版本、资源依赖和存档兼容管理。
- 从编辑器启动测试分支和指定路径试演。

退出标准：用户无需编辑原始 YAML/JSON，即可从梗概生成、修正、发布并完成一个多结局、多场景动态演员剧本。

### 阶段 8：动态作者与临时人物增强

交付：

- 章节边界动态扩写、承诺边界和补丁审批策略。
- `AdHocCharacter` 模板、稳定 ID、场景/分支作用域和 `PromoteAdHocCharacter`。
- 动态候选剧情、临时人物与既有 Canon 的冲突检测。
- 运行中作者调用预算、审计日志、失败降级和关闭开关。

退出标准：动态作者只能修改未承诺区域；临时人物必须先登记再发言；关闭动态能力后，已发布剧本仍可仅依赖确定性路径完整运行。

## 22. 风险与取舍

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 状态与聊天历史不同步 | 回档或 Fork 后世界线错乱 | 单一 generation、原子指针、因果事件头和恢复校验 |
| AI 生成图结构不完整 | 无法发布或游戏软锁 | 多阶段生成、静态校验、路径模拟、定向修复 |
| Prompt 泄露隐藏剧情 | 剧透和体验破坏 | 程序侧 ActorContext 投影与 DTO 秘密测试 |
| 选项协议迁移影响旧 UI | 聊天路径回归 | 联合类型兼容、双路径测试、分阶段迁移 |
| `main.py` 继续膨胀 | 难以测试和演进 | 阶段 0 作为前置条件 |
| 变量与节点过多 | 状态空间爆炸 | 生成预算、模拟上限、编辑器警告 |
| 通用节点图过度复杂 | 简单用户难以上手，运行语义难以调试 | 简单模式固定模板、强类型端口、编译产物和源映射 |
| 创作图与运行规则漂移 | 编辑器显示与真实执行不一致 | 单一创作源、sourceHash、修改后强制重新发布 |
| LLM 误判语义信号 | 无依据的指标变化或玩家被错误评价 | speech act、置信度、受限目录、低增量和可诊断拒绝 |
| 玩家重复表达刷指标 | 绕过关键剧情和阈值 | fingerprint、重复窗口、章节限额和 causeGroup 去重 |
| 动态作者移动门槛 | 玩家失去公平感 | 承诺边界、版本化补丁和不可变 Canon |
| LLM 调用成本增加 | 延迟和费用上升 | 作者按章节调用，结构化选择跳过场景理解调用，公开信号共用场景 LLM 工具循环 |
| 人物池过大导致 Prompt 与资源膨胀 | 延迟、显存占用和人物一致性下降 | 登记表按需索引、ActiveCast 上限、只投影当前人物、预载与释放预算 |
| 动态选角破坏剧情连续性 | 人物无故出现、职责错位或分支事实冲突 | 状态过滤、连续性优先、职责绑定、确定性提交和 fallback |
| LLM 发明未登记说话者 | 资源错误、秘密泄露和角色串线 | 动态 speaker enum、响应校验、受限修复，禁止自动登记 |
| 外部人物导入越权 | 本地文件泄露或恶意资源载入 | 用户选择 token、相对路径校验、包限额、剧本域隔离 |
| 必需人物加载失败 | 关键场景无法演出 | 预载、加载诊断、显式替代/旁白/失败节点策略 |

## 23. 关键决策

本文作出以下初始决策：

1. 剧情系统是核心宿主能力，不以插件作为最终实现。
2. 首版采用模块化单体，不拆独立服务。
3. 运行时状态由确定性引擎控制，LLM 不直接写状态。
4. 默认模式为“标准”：允许自由演出，不允许未登记行动改变关键状态。
5. 先支持 `branch` 与 `global` 两种状态作用域。
6. 先实现手写剧本闭环，再实现 AI 编译器和可视化编辑器。
7. 完整剧本不进入场景 LLM 的演出 Prompt，必须通过 ActorContext 投影。
8. 剧情状态跟随对话历史位置保存，Fork 从历史检查点复制。
9. 结构化剧情选项使用稳定 ID 和 revision，不以显示文本作为身份。
10. 已发布剧本采用版本化不可变策略，编辑产生新草稿或新版本。
11. 自由文本数值变化使用通用 `StoryMetric + SemanticSignal`，不建立好感度专用底层系统。
12. LLM 只能提交预定义 `signalId`、强度与语义证据，实际指标效果由引擎决定。
13. 意图解析和最终场景演出默认共用场景模型，但始终保持先裁决、后演出的工具调用时序。
14. 创作层使用 `NarrativeGraph + RuleGraph` 两层类型化节点图，`StoryNode` 与 `RuleNode` 不共享运行语义。
15. 运行时只执行经过类型检查和 hash 校验的 `StoryProgram`，不直接解释可视化图或任意自定义节点。
16. 剧本人物采用登记表与演员表分离：项目可以登记大量人物，单场 `ActiveCast` 必须有界。
17. 场景可以晚绑定人物，但每次最终演出前必须先确定性解析并提交 `ActiveCast` 与 `speakerAllowlist`。
18. `CastPlanner` 仅在等价候选需要叙事取舍时提出登记 ID；确定性过滤、职责校验和最终提交始终由引擎完成。
19. 正式说话者必须先登记并激活；临时 NPC 也必须先生成稳定最小档案和作用域，不能由对白输出隐式创建。
20. 人物加载状态属于可重建缓存，人物参与状态属于随分支保存的权威剧情状态。

## 24. 待评审问题

以下问题需要在对应阶段开始前确定：

1. `run` 作用域是否有明确产品需求，还是由 `branch/global` 组合覆盖。
2. 剧本工程默认使用 YAML、多文件 JSON，还是内部统一 JSON、导出时提供 YAML。
3. 结构化选项是否直接替换 `submit-option`，或长期保留独立 `select-story-choice`。
4. 回溯采用每个用户轮次完整快照，还是检查点加事件重放。
5. 动态作者默认关闭，还是在 AI 生成剧本中默认按章节启用。
6. 锁定条件应支持完全隐藏、模糊提示和完整显示中的哪些组合。
7. 本地 `profileId` 采用单一默认资料还是显式多资料，以及资料删除、导出和合并策略。
8. 发布后的补丁如何处理正在运行的旧版本存档。
9. 是否需要首版提供剧本包导入导出与签名来源提示。
10. AI 编译器的固定评测集、结构通过率和最低发布阈值如何定义。
11. 语义信号定义只存于剧本工程，还是允许角色配置提供可复用基础信号并由剧本覆盖。
12. 隐藏信号默认使用独立评估调用，还是只在明确启用的严格剧情中开放。
13. 指标变化是否默认对玩家隐藏，仅通过角色反应表达，还是由剧本逐项配置展示策略。
14. 内联 DSL 是否长期作为可编辑创作源，还是只作为导入兼容和简单模式的序列化简写。
15. RuleGraph 的可复用子图是否进入首版，还是等核心节点类型稳定后再开放。
16. `ActiveCast.maxActive` 默认值采用 6 还是 8，以及移动端是否使用更低演出上限。
17. `local-library` 人物默认固定 revision，还是允许用户显式选择跟随本地人物更新。
18. `AdHocCharacter` 默认关闭，还是仅在自由控制模式中默认开启。
19. `CastPlanner` 默认与场景模型共用工具阶段，还是只对复杂场景启用独立小模型。

## 25. MVP 验收标准

首个面向真实用户的 MVP 必须满足：

- 可以从一个已发布的手写或 AI 生成剧本启动聊天。
- 至少支持布尔、整数和集合变量。
- 条件和效果由剧情引擎确定性执行。
- 结构化选择具有稳定 ID、条件和锁定原因。
- 自由输入可以映射到登记意图，但不能越权修改状态。
- 普通对话可以提出预定义语义信号，但不能发明指标、信号或增减值。
- 至少一个非好感度叙事指标可以由受控语义信号变化并解锁节点。
- 语义信号具备 speech act 判断、重复去重、限额和同轮主动事件防重复计分。
- 至少一个类型化 RuleGraph 可以编译为确定性 StoryProgram，并通过 sourceHash、端口和循环校验。
- MetricNode 和 SemanticSignalNode 只引用定义与状态，不产生重复的权威存储。
- 至少两个相邻场景可以使用不相交演员表，不要求开局加载全部人物。
- `fixed`、`mixed` 和 `role-based` CastPolicy 可以确定性解析；缺少职责时执行已发布 fallback。
- 场景 LLM 可以通过工具请求一次中途人物登场，并在引擎返回新 allowlist 后继续演出。
- Fork、回档和重连恢复分支对应的 `ActiveCast`，但不持久化人物加载缓存。
- 动态对白 Schema 拒绝未登记或未激活的 `characterId`。
- 至少一个剧本域人物或受限临时 NPC 可以按需登记、加载和进入场景。
- `STAT` 或状态面板展示权威状态。
- 未解锁秘密和隐藏信号标准不出现在场景演出上下文、实时事件和前端快照中。
- 回档、重新生成、Fork、切换分支和重启恢复不产生重复效果。
- 至少两个结局可以通过路径模拟和真实 E2E 到达。
- 旧自由聊天、旧模板和非剧本会话不受影响。
- AI 剧本生成失败、场景演出生成失败和资源缺失都有可恢复的降级行为。

满足上述标准后，Shinsekai 才具备“用户输入剧情梗概，AI 生成相对完整节点控制，并在自由对话中可靠执行”的基础产品能力。
