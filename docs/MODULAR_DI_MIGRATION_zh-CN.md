# Shinsekai 模块化 DI 迁移计划

> 状态：迁移计划，尚未实施。
> 日期：2026-10-16。
> 目标结构与依赖规则：[模块化 DI 目标架构](MODULAR_DI_DESIGN_zh-CN.md)。
> 基线：当前 #393 的聊天拆分；实际实施前以合并后的 main 重新确认文件与测试。
> 最终宿主源码位于 `src/shinsekai/`，SDK 位于 `src/sdk/`；下文目标路径省略这些前缀。

## 1. 迁移策略

按 feature 逐个形成“现有接口 → 注入的用例 → 唯一存储所有者”的可运行路径。
每次只切换一个明确范围，保留其他功能运行；不在一轮中重写所有实现或更换存储格式。

先修依赖和所有权，再进行对应目录迁移。新模块不依赖旧 bridge、全局配置管理器
或全局 runtime accessor。旧入口可以调用新模块，不能让新模块反向调用旧入口。

core 的业务代码随其所属 feature 迁移，不等最后再统一扫入另一个 shared 包。
独立的通用技术函数可以原位保持到消费者迁完后再归并，避免制造额外中间目录。

首要验收是修改局部化：通过真实的小功能比较迁移前后的手工修改范围。
core/DI 的建设随试点实际需要推进，不能先建立整套框架再等待证明它能减少改动。

src layout 与业务重构共同分阶段落地，但不使用一次性整仓改名：从第一个新模块开始
使用 `shinsekai.application.modules.*`，所属实现迁移一次到最终路径。
未迁移包继续由受限的旧装配入口使用；旧、新命名空间不保存同一实现的两份源码。
SDK 的物理移动独立提交，公开 `sdk.*` 导入保持不变。

## 2. 迁移前的清单与契约基线

第一份实施 PR 先建立可维护的简短清单，记录：

- 模块拥有的数据文件、缓存、锁、线程、子进程与关闭责任。
- 当前入口、公开 API/SDK、跨模块调用和所有写入者。
- 将迁移的模型、校验、默认值、兼容字段和持久化格式。
- 临时兼容入口及其尚未迁移的调用者，指定具体删除阶段。
- 已有测试和缺失的行为边界；生产代码与测试代码分别统计。

保留实际行为测试：API 成功/失败响应、YAML 加载与默认值、配置生效、文件操作、
启动与退出、历史保存、UNC/路径策略和资源访问授权。只补缺失的重要边界，
不复制一套与实现逐行对应的测试。

现有架构测试按迁移范围逐步收紧：对未迁移路径锁定现状，对新模块直接执行目标规则，
不新增反向依赖。现有 allowlist 不得扩大为整包豁免，不能先放开所有规则再等待以后修复。

### 2.1 用真实变更检查修改传播

为首批模块选择代表性变更，记录迁移前的调用链和手工同步点：

| 变更 | 目标修改范围 |
| --- | --- |
| 新增一个普通系统偏好字段 | settings 的权威模型/默认值、需要它的 UI 和测试；通用存储/HTTP 不随字段变化 |
| 新增角色内部规则或操作 | character 的用例、必要入口与测试；模块注册保持稳定，不扩展全局操作枚举和中央分发 |
| 替换角色存储后端 | character 的 persistence 和装配；角色业务用例及 API 契约保持稳定 |
| 新增跨故事/聊天功能 | workflow 与真正承担新职责的模块公开契约；不修改无关模块和 core 技术机制 |

分别记录：手工编辑文件、生成文件、触及的业务所有者、重复契约/字段/分发表、
实际需改变行为的层与仅做同步转发的层。前后端协议和真实数据迁移带来的必要修改要单列。
不规定脱离变更复杂度的固定文件数，也不把迁成一个巨型文件当作改进。

第一批实施 PR 应展示至少一个真实变更的前后对照；若只是路径变短、人工同步点未减少，
先调整接口与所有权，再推广该模块模板。公开 schema 的前端类型生成可增量引入，
不把整套代码生成工程设为第一阶段的前置条件。

## 3. 当前目录到目标所有者的映射

### 3.1 application、配置、bridge 与外部集成

| 当前实现 | 目标 | 要做的调整 |
| --- | --- | --- |
| `config/schema.py` | 各模块 `models.py` / 必需的 `schemas.py` | 按数据所有者拆模型，消除全局 AppConfig 的可写聚合 |
| `config/config_manager.py` | 各模块 persistence + 装配期兼容投影 | 拆单例、写入与缓存；每份数据只有一个权威 store |
| `config/character_manager.py`、`character_config.py`、`character_assets.py` | character | 配置/资产规则归角色；移除对完整全局配置的需求 |
| `config/background_manager.py` | background | 独立背景模型、存储和资源管理 |
| `config/mirror_env.py`、`network_proxy.py` | settings 的运行时适配 + bootstrap | 偏好归 settings，进程级生效归明确所有者 |
| `application/characters`、`backgrounds`、`effects` | 对应 feature module | 缩小依赖，并与自身模型、存储、routes 合并归位 |
| `application/chat` | chat | 复用 #393 组件，取消默认全局实例，显式装配宿主和子进程 |
| `application/story` | story + 必需的跨模块 workflow | 故事内部规则留模块，故事/聊天关联流程单独编排 |
| `application/runtime/state.py`、`context.py`、`services.py` | 各资源所有者 + bootstrap | 按状态/生命周期拆分，最后删除全局 accessor 与聚合状态 |
| `application/runtime/workers` 等聊天执行组件 | chat 的 runtime / presentation | 按实际消费者归属；只提取确实通用的执行机制 |
| `frontend_bridge_core/*` 的业务实现 | 对应模块 service / adapter | 业务、校验、持久化先归位，删除重复实现 |
| `frontend_bridge_core/routes/*` | 各模块 routes + `core/transport/http` | 业务路由归模块，通用匹配/HTTP/multipart 机制归 core；入口注入应用策略 |
| `frontend_bridge_core/transport/*` | `core/transport/websocket` + feature adapter | 通用连接/收发归 core；ChatEventSink、命令、资源 URL 和移动访问策略归 chat |
| `frontend_bridge.py` | bootstrap + 新进程入口 | 拆装配、运行时检查与守护；所有启动和打包调用切换后删除 |
| `ai/llm` | chat 的引擎/历史/提示词 + `integrations/ai/llm` | 产品对话策略和纯供应商请求/流协议分别归位，不能整包改名 |
| `ai/llm/template` | core/templates 引擎 + chat / story / reminders 的提示词 | 已确认 Section/TemplateContext 为通用组合机制；提示词内容与业务上下文归各模块 |
| `ai/memory` | memory + 所需供应商适配 | 记忆提取、绑定与持久化归模块；模型调用经注入能力 |
| `ai/tools` | 领域模块的工具入口 + tooling / integrations/mcp | 角色/故事/提醒操作归各自模块；协议机制与工具管理分开 |
| `ai/asr`、`tts`、`t2i`、`vision` | feature 策略 + `integrations/ai` 驱动 | 用户策略和生命周期归消费者，具体推理/服务协议归 integration |
| `plugin_system` | plugins 的产品用例 + `integrations/plugins` | 安装/更新政策归模块；加载/隔离/通信机制与业务分开 |
| `i18n` | `core/i18n` + 应用资源/装配 | 查找/插值/参数化回退归 core；产品文案放包资源、语言选择归 settings/bootstrap；保留 SDK 语言契约 |

这是一份按职责分解的映射，不要求当前每个文件整体搬走。
`application/media`、`model_providers` 等现有组合包也要逐函数判断所有者：
资源策略归 feature，供应商请求归 integration，真正通用的技术机制才归 core。

### 3.2 当前 core 的逐项处理

| 当前路径 | 处理结果 |
| --- | --- |
| `core/story/*` | 全部故事模型、编译、规则、运行、重放进入 story；纯计算也不改变业务归属 |
| `core/chat_history/*` | 聊天记录格式、归一化、文本投影和存储进入 chat/history |
| `core/messaging/*` | 轮次、合批、打断、对话解析与输出进入 chat；仅证明无领域语义的机制才可留 core |
| `core/sprite/selection.py` | 角色资产查询归 character；会话当前展示选择归 chat/presentation |
| `core/media/chat_attachments.py` | 聊天附件规则进入 chat |
| `core/media/effect_bindings.py`、`effect_image.py` | 效果定义/绑定归 effect；聊天应用效果的流程归 chat |
| `core/media/avatar/*` | 形象资源和运行时功能归 avatar；独立格式/供应商驱动可放其 adapter 或 integrations |
| `core/media/asset_import.py`、`file_operations.py` | 按调用链拆产品资源导入规则与通用文件/归档机制，避免整包留 core |
| `core/model_assets/*` | 模型目录、清单、安装/校验政策进入 model_assets；外部模型仓库适配独立归位 |
| `core/agent/*` | agent 存储、请求错误和进程策略进入 agent；外部 PI 协议适配与领域规则分开 |
| `core/app_update/*` | Shinsekai 更新、版本与包政策进入 app_update |
| `core/paths.py` | 产品安装/源码/数据根目录解析进入 bootstrap；通用路径操作按需保留 |
| `core/bootstrap/frozen_log.py` | 应用启动日志配置归 bootstrap |
| `core/downloads.py` | 保留/提取纯下载机制；按字节报告进度，用例保留原有阶段进度映射 |
| `core/runtime_env/*` | 保留参数化环境机制；产品 runtime profile、偏好、模型选型移交所属模块/装配 |
| `core/security/paths.py`、`__init__.py` 的 SDK 转发 | 调用者改用权威 SDK 工具后删除，不复制安全实现 |

每项拆分完成后，检查签名、常量、环境变量、错误类型和测试数据。
只改 import 不会自动消除领域语义；将 `ChatTurnService` 改名为 `GenericTurnService`
也不能使它满足 core 的准入标准。

### 3.3 最终物理路径与包名

| 源码类别 | 最终物理路径 | Python 导入前缀 |
| --- | --- | --- |
| feature 与应用装配 | `src/shinsekai/application` | `shinsekai.application` |
| 纯技术基础设施 | `src/shinsekai/core` | `shinsekai.core` |
| 外部驱动与协议适配 | `src/shinsekai/integrations` | `shinsekai.integrations` |
| 插件公共契约 | `src/sdk` | `sdk`，保持兼容 |
| React / Tauri | `frontend/src`、`frontend/src-tauri/src` | 沿用各自构建规则 |

`src` 不是 Python 包，不能把 import 改成 `src.*`。`data/`、`assets/`、用户 `plugins/`
和内嵌 `runtime/` 不是 Python 源码包，不随源文件移动。

### 3.4 从非 core 目录提取技术子系统

| 来源与目标 | 抽取要求 | 建议阶段 |
| --- | --- | --- |
| router / uploads → `core/transport/http` | 请求值不携带 BridgeState；去除业务任务/错误映射；上传资源所有权显式，复用既有安全工具 | 阶段 1 提取试点需要的最小机制，后续逐路由扩展 |
| tasks → `core/tasks` | 自己拥有登记表和锁；注入时钟/执行能力；文案、业务阶段与清理由用例提供 | 阶段 2–3，随首个完整异步用例验证 |
| 通用 header / URL 校验 → `core/security` | 校验机制与访问政策分开；SDK 安全工具保持单一实现和契约 | 随 HTTP 试点与资源用例迁移 |
| `_jsonify` → `core/serialization` | 保留当前响应值转换行为；字段选择留模块；更新真实消费者 | 阶段 1–3 |
| 语言包引擎 → `core/i18n` | 无全局产品语言、资源目录或 SDK 依赖；catalog/fallback 由装配提供 | 随 settings 语言生效迁移 |
| Section / TemplateContext → `core/templates` | 保持排序、禁用、上下文与空内容语义；业务提示词留模块 | 随 template/chat/story 迁移 |
| 线程执行机制 → `core/concurrency` | 拆掉 getCharacter 与全局 runtime；DagNode 适配不进 core | 阶段 5 |
| WS 连接机制 → `core/transport/websocket` | 与 ChatEventSink、快照归并、聊天事件和资源寻址彻底分离 | 阶段 5 |

这是从实际消费者出发的抽取清单，不要求先建立所有基础框架。
每个抽取 PR 保持原行为，直接替换调用者并删除旧实现；SDK 已公开工具单独评估兼容，
不得为了 core 的依赖规则再造第二套日志、安全或 DAG 实现。

## 4. 分阶段实施

### 阶段 0：稳定基线，完成范围划分

动作：完成 #393 的 review；锁定聊天启动、退出、身份、顺序和历史保存的测试。
建立第 2 节的依赖/写入者清单，并确认首批模块的公开边界。
记录当前入口、动态导入、Python 资源清单、包内静态文件和 SDK 导入方式，
确定新增 pyproject 的包发现、开发安装和打包暂存策略。

退出条件：源码启动与现有测试基线通过；每项首批数据有明确所有者；
未解决的功能缺陷与机械迁移分开记录。#393 不继续扩大为全项目架构 PR。

### 阶段 1：system settings 试点与最小 DI 装配

动作：

1. 先覆盖系统设置读取、保存、校验失败和原有副作用行为。
2. 构造项目路径和一个明确的系统设置 store，注入设置用例。
3. 将现有 system settings 路由绑定到该用例，保持 URL、请求/响应和文件格式。
4. 旧调用者通过限定适配读取/调用新所有者，移除其系统设置的第二份写入/缓存。
5. 只抽出这条路径需要的 HTTP 请求/响应与路由机制到 `core/transport/http`；
   旧请求 state 保留在旧适配器内，具体认证/来源策略仍由应用装配提供。
6. 固化后做独立的文件搬迁提交，建立 `modules/settings` 的真实入口。

最终路径使用 `src/shinsekai/application/modules/settings`。引入最小包发现与开发安装配置，
在首批包测试中验证规范的 `shinsekai.*` 导入。旧入口通过明确的装配边界调用新模块，
架构测试按完整包名前缀与真实源码目录判断，不能因为所有代码都以 shinsekai 开头而放过反向依赖。
相对导入同样需要解析到完整包名。新 core 的 DI/storage/logging 只实现试点真正需要的能力。

退出条件：新用例可以只用 store 与必要回调构造，不依赖 BridgeState 或 ConfigManager；
不构造角色/聊天/模型引擎也能测设置；两份临时项目数据不串用；现有读取与保存调用无回归。
进程全局环境与 i18n 不承诺多项目隔离，其更新由明确的进程所有者处理。

### 阶段 2：完整 settings 与供应商配置边界

动作：迁移 API 配置模型、默认值、校验和存储；对模型发现/连接测试注入供应商探测能力。
把代理、镜像、语言、服务路径等配置数据与实际运行时生效分开，明确谁在什么时候执行。
删除 bridge 中的配置主体实现，减少旧全局 AppConfig 的权威数据。

退出条件：API/system 各文件只有一个写入者；迁移前的 YAML 可直接加载；保存后旧缓存
不会覆盖新值。持久化、缓存更新、生效失败的顺序被测试固定，不能由可选事件观察者决定。
可能改变既有行为的错误处理修复使用独立提交，不借迁移悄悄改变失败协议。

### 阶段 3：character 的完整 feature 归位

动作：角色/立绘/语音模型、集合存储、资源校验与导入导出归入 character。
`CharacterUseCase(state)` 改为明确的角色 store、资产操作和所需语音/生成能力。
同一角色文件的读改写由唯一项目级所有者协调；运行时调用者读取明确快照。

退出条件：角色 service 不依赖完整应用配置；修改一个角色不丢失其他并发更新；
角色导入、删除、资产路径、参考音频和失败恢复的原行为保持。
旧配置/bridge 中对应实现和无调用者包装被删除。

### 阶段 4：background、effect、template 与形象资源

动作：按真实 feature 分别迁移数据、规则和路由，每个模块一个可审查 PR。
消化各自涉及的 core/media 与 core/sprite 逻辑。模板通过角色、背景公开查询获得信息，
不读其他模块的 YAML 和内部缓存。形象运行时按实际资源所有权归 avatar。

退出条件：相应 YAML/资产操作不再由旧 ConfigManager 或 bridge 实现；
UI、导入导出和模板到运行时的行为保持；core 不再拥有这些 feature 的选择/绑定政策。

### 阶段 5：chat 的显式对象图与核心业务回迁

动作：

1. 将 #393 的默认全局服务实例改为宿主/项目/会话范围显式装配。
2. 按实际所有者拆 BridgeState 中的聊天、流、下载能力与初始化状态，保留身份关联。
3. 将 `core/chat_history`、`core/messaging` 的业务与相关 ai/llm 对话策略迁入 chat。
4. 具体供应商调用留在 integration；角色、设置和启动数据通过明确的快照/能力进入运行时。
   尚未迁移的 story 等提供者由装配期的窄适配器连接，不让新 chat 导入其旧内部模型。
5. 子进程独立构造对象图，只接收可序列化启动数据，不继承服务定位器或活的父进程实例。
6. 保留 host/runtime/history/presentation/dialog_media 边界，最后机械迁入
   `src/shinsekai/application/modules/chat`。

退出条件：chat 的服务、worker 和 handler 不调用全局 runtime accessor；无导入时构造。
启动失败、异常退出、重复退出、快速切换、过期事件、无法终止和关闭失败测试通过；
历史保存与日志释放仍由各自所有者按既有顺序执行。

### 阶段 6：story 与跨模块 workflow

动作：把 `core/story` 和 `application/story` 组成 story 模块，保留编译/重放的确定性。
故事与聊天的关联、启动补偿和关闭协作由窄依赖的 workflow 编排，
story 与 chat 的内部实现不互相导入，不通过共享可写 state 通信。

退出条件：故事编译、选择、分支、版本、重放和会话关联无回归；
公开依赖图无环；失败与部分成功能被调用者观察；core 不再含故事模型或规则。

### 阶段 7：其余 feature 与 integrations 收口

动作：按依赖次序迁移 memory/knowledge、reminders、agent、tooling、plugins、
model_assets、image_generation、diagnostics、app_update、localization 等真实功能。
逐个清理 core/agent、core/model_assets、core/app_update 和剩余业务片段。
把 ai 与 plugin_system 中剩余的产品策略交给模块，纯外部驱动/宿主机制进入 integrations。

退出条件：integration 不导入产品模型或全局配置；SDK 不依赖宿主实现；
领域 AI 工具调用对应模块用例；每个已迁移 feature 删除其 bridge 与旧包中的重复实现。
整包技术改名放到依赖清理后，避免先搬 ai、再把其中业务搬第二次。

### 阶段 8：切换入口，删除过渡层

动作：新 `python -m shinsekai` 入口承载服务、运行时检查和 worker 子命令，更新 Tauri 的启动、
managed/resolver、父进程守护、退出、资源暂存与验证，以及源码启动/安装脚本。
更新全部生产调用、架构测试、打包资源检查和文档后，删除旧入口、bridge、
ConfigManager 聚合单例、BridgeState、全局 runtime accessor 和剩余兼容代码。

宿主实现全部使用 `src/shinsekai` 命名空间；SDK 独立迁到 `src/sdk` 并保持公共导入。
开发安装和构建的 wheel 必须包含正确的包与静态资源。把项目包安装到每次打包专用的
site-packages/资源目录，禁止改写共享 runtime 缓存。先前阶段若有旧包暂存方式，
在此阶段一并删除，确保只存在一套实现和一条正式启动路径。

退出条件：

- 生产代码和打包资源没有旧业务路径的实际依赖，单独允许文档和迁移历史引用。
- 源码启动、聊天子进程启动、隔离资源目录启动与退出通过。
- 从仓库外的工作目录测试安装包导入，清除外部 PYTHONPATH；SDK 可独立导入。
- 不通过 cwd 或 `__file__.parents` 推断用户数据根，已有项目目录和 YAML 无迁移副作用。
- Windows x64/arm64、Linux x64/arm64、macOS arm64 的构建、运行时资源和对应产物验证通过。
- 旧 SDK、API、用户 YAML、UNC/路径授权和数据恢复契约通过。
- core 无业务依赖、公开模块依赖无环、模块导入无启动副作用的架构检查全部执行。

## 5. 每个 PR 的提交方式和完成条件

建议按以下顺序组织一个 feature 的提交；纯搬迁始终独立：

1. 补缺失的行为/契约测试，使旧实现先通过。
2. 修依赖与所有权，注入窄能力，接入现有接口并删除被替代实现。
3. 单独机械迁移目录与导入，可通过 AST/导入对照检查行为没有额外变化。
4. 更新相应架构约束、资源清单和文档，移除已经没有调用者的过渡入口。

一个 PR 完成后必须能回答：数据谁拥有、资源谁关闭、模块依赖谁、旧实现删了哪些。
分别报告生产/测试增删行数和新增抽象的真实消费者。
同时说明代表性 feature 变更少了哪些中央注册、重复契约和转发修改；
若本次增加层次，给出它承担的具体校验、协议、存储或生命周期职责。
不为了“预留扩展”加入通用 Module 基类、自动扫描、服务定位器或层层转发。

若数据格式不变，阶段回退通过部署上一提交完成；不自动回滚或删除用户数据。
一份数据不能同时由新旧实现写入。确需切换旧调用者时，先让它们委托同一权威 store，
并在该阶段完成后删除临时适配，不保留两套实现让运行参数任意选择。
涉及真实数据格式升级的需求另开 PR，单独定义备份、幂等、恢复和版本兼容。

## 6. 现有 PR 的协调

- #393 先完成自身 review 和收尾，作为聊天内部解耦基线；不混入这一整套迁移。
- #394、#382、#346 可以继续独立 review。实施合并前重新检查当时的交集与 CI，
  不因架构规划冻结所有功能，也不把“没有文件交集”当作质量审查通过。
- #388 的知识库主体可直接按模块边界组织；设置字段和聊天初始化集成分别适配其所有者。
- #390、#341 等聊天功能在合并后的基线上适配；不恢复旧文件和全局依赖。
- [#335](https://github.com/RachelForster/Shinsekai/pull/335) 按 models/persistence/environment
  拆全局 config，与 feature 所有权不同。先 review 并吸收可复用代码和测试，再重新划范围，
  不把原方案整体合并设为模块化迁移的前置条件。

## 7. 迁移完成的判定

完成是依赖与所有权满足目标，而不是目录已经改名：

1. feature 从接口到存储归模块；跨模块只使用声明的公开能力，依赖图无环。
2. core 只留技术机制，不含聊天、故事、角色、产品路径和模型政策。
3. 没有 bridge 业务层、全局管理器聚合或业务代码中的容器查找。
4. 每份数据和每个资源都有单一所有者，失败与关闭顺序有验证。
5. 当前 API、SDK、数据、源码入口与打包产物的兼容检查通过。

不估计未经验证的固定工期；阶段 1 完成后，根据实际调用者数量、迁移成本和删减结果
调整后续 PR 大小，保持每一阶段都可运行、可审查、可回退。
