# 文档驱动舞台底座与会话行为 SDK（SessionBehavior）设计方案

> 状态：草案
> 日期：2026-11-21
> 追踪 Issue：#447
> 相关规范：[`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md)、[`AI_STORY_SYSTEM_DESIGN_zh-CN.md`](AI_STORY_SYSTEM_DESIGN_zh-CN.md)、[`SIMPLE_STORY_NODES_zh-CN.md`](SIMPLE_STORY_NODES_zh-CN.md)、[`PLUGIN_DEVELOPER_GUIDE.md`](PLUGIN_DEVELOPER_GUIDE.md)

---

## 1. 摘要与产品定位

### 1.1 问题与目标

Shinsekai 目前已经具备完整的多角色声画舞台底座（静态立绘 / Live2D / MMD、情绪与服装分组匹配、多角色 TTS 语音合成、`NARR` 旁白、`CHOICE` 选项、`STAT` 数值面板、背景 / BGM / 音效及回放录屏导出），但在现有 `story` 剧本系统之外，创作者与玩家还存在一类高频诉求：

- **长篇小说剧场化演出**：直接导入本地 PDF 或 TXT 小说，**不生成剧情选项、不改写主线分支**，尽量忠实原文细节与对话，由 AI 担任分镜导演将其逐段转译为带旁白、立绘表情、语音与氛围调度的连续视觉小说演出，并支持无输入点击/自动连播与章节跳转。
- **同底座延展玩法与社区插件赋能**：一旦具备“文档切片摄取 + 演员映射 + 舞台完播调度 + 可定制记忆压缩 + 分支安全状态槽”，同一套共有底座即可平滑支撑：
  - **教科书 / 论文 Galgame 伴读讲堂**：1～2 位本地角色担任讲师与学伴，结合 `NARR` 黑板展示公式/代码与 `CHOICE` 随堂测验闯关（答对放行、答错留堂换例重讲）。
  - **TRPG 跑团 DM 模组**：非线性章节/地点切片检索、真随机投骰工具，以及远期低权限访客联机房间。
  - **既有社区插件（2D RPG、人格模型、陪伴陪玩等）**：补齐无立绘 NPC 说话权、舞台真实播完回调、回档同步状态槽与压缩保留指令四大共性能力缺口。

### 1.2 核心定位与演进纪律

核心定位：

> **将宿主“文档切片、舞台调度、状态快照与上下文压缩”机制抽离为共有内核；将“选角、交互控件、推进节奏、压缩保留规则”收口为可插拔的 `SessionBehavior` 策略协议。**

演进纪律严格遵循项目一贯做法：

1. **先内后外**：在协议未经极端场景充分验证前，**不急于向公开 `sdk/` 锁定稳定签名**；先在 `core/` 与 `application/` 内部定型 `SessionBehavior` 接口。
2. **双极端样板校验**：先以 **「小说剧场」（零交互流式连播，Phase 1～3 MVP）** 与 **「Galgame 讲堂」（强交互出题闯关，Phase 4）** 两个相反象限的内置模式验证接口完备性，确认无死角后再升格暴露至 `sdk/` 供社区插件注册。
3. **兼容既有会话**：现有普通自由聊天、简化节点 `story` 剧本（[`SIMPLE_STORY_NODES_zh-CN.md`](SIMPLE_STORY_NODES_zh-CN.md)）与旧存档格式保持 100% 兼容。

---

## 2. 现状诊断与四大核心底座缺口

对照当前代码实现，阻断“长文档连续演出”与“导演型玩法插件”的瓶颈集中在以下 4 处：

### 2.1 缺口 ①：缺少舞台真实完播回调（`on_playback_idle`）与无副作用预取机制

- **现状**：`sdk/hooks.py` 中的 `MESSAGE_ADDED`（`MessageAddedContext`）在 LLM 刚吐完一轮 JSON、消息写入 `ConversationHistory` 时即刻触发；此时 `dialog_queue` 与 `presentation_queue` 才刚开始向前端舞台送出第 1 句台词与 TTS 音频。
- **痛点**：
  - 若在 `message_added` 中立即触发下一段生成，会直接打断当前排队朗读的台词或导致队列顺序冲突；
  - 若等全部播完后再请求 LLM 生成下一段，用户读完每段最后一句都会卡住干等 5～15 秒；
  - 若直接复用 `LLMManager.chat()` 做后台预取，会提前把输入和回复写进受管历史、触发副作用钩子，且取消预取会直接调用共享 `llm_adapter.cancel()` 误杀前台请求。

### 2.2 缺口 ②：角色绑定强校验与无立绘路人（NPC）通道阻断

- **现状**：
  - `core/messaging/dialog_output.py` 的 `has_valid_dialog_output()` 强制校验：除 `CG` / `CHOICE` / `COT` / `NARR` / `STAT` 等系统关键字外，所有条目都必须携带 `sprite`（indexed 模式）或 `vibe`（semantic 模式）。
  - `ai/llm/chat_loop.py` 与 `ai/llm/dialog_repair.py` 未感知会话角色绑定表，且 `_repair_prompt()` 要求所有非固定系统条目都必须带 `sprite`/`vibe`。
  - `application/chat/presentation/handlers/dialog_media.py` 的 `CharacterMediaHandler.handle()` 在 `rt.config.get_character_by_name(name_s)` 返回 `None` 时直接抛出 `ValueError(f"未找到角色配置: {name_s}")`。
  - 实际上，下游 `application/chat/presentation/handlers/presentation.py` 的 `CharacterDialogUiHandler.handle()` **已经具备兜底显示能力**（找不到 `character_config` 时会跳过立绘并用 `#84C2D5` 默认色渲染对话框），只是消息在更早的校验层和媒体层就被拦截了。
- **已敲定的美术与交互决策（明确不生成四张“无脸黑衣人”预设立绘）**：
  - 经过方案评估，决定**不采用“成男 / 成女 / 萝莉 / 正太四张无脸黑衣人预设图”**作为未匹配角色的替身，原因有三：
    1. **立绘槽位挤占**：舞台立绘池上限仅为 3 个 LRU 槽位（`frontend/src/features/chat-stage/state/sprites.ts` 中 `CHAT_STAGE_SPRITE_SLOT_COUNT = 3`），路人甲、店小二频繁上台会直接把正在对戏的男女主真立绘挤出舞台；
    2. **表现割裂**：静态黑衣人无法做微表情反应，且与角色揭晓真身后的实际发型/体型/服饰轮廓前后不一致；
    3. **维护冗余**：引入无意义静态占位资源不如复用正统视觉小说的克制做法。
  - **最终采用方案**：
    1. **未绑定本地皮套的纯龙套 / 路人 NPC**（如“店小二”“路人甲”）：通过**逐说话人绑定判定**走**纯对话框演出通道**——对话框正常显示路人名称与台词，不占用 3 人立绘槽、不切换场上主角立绘、不触发 TTS 语音；已绑定皮套的正式演员依然严格强制校验 `sprite` / `vibe`；
    2. **已绑定本地皮套但原文尚未揭晓身份的角色**（如 `？？？` / `神秘少女` 初登场，作为可选增强）：直接复用其对应本地角色的真实立绘/Live2D 资源，并在前端渲染层叠加暗影剪影滤镜（如低亮度暗影效果），揭晓真名时撤除滤镜——保证剪影轮廓与动作变化和本人 100% 一致。

### 2.3 缺口 ③：缺少随聊天回档 / 分支原子恢复的会话状态槽

- **现状**：
  - 如 [`PLUGIN_DEVELOPER_GUIDE.md`](PLUGIN_DEVELOPER_GUIDE.md) 所述，当前插件内部状态通常自行读写 `data/plugins/` 下的文件。
  - 现有 `SqliteSessionStore.append_turn()` 对每条 turn 单独 `commit()`，而分支身份与分支树元数据写入独立且直接覆写的 `branches.json`（`core/chat_history/storage.py` 中 `save_branch_state()`）。
- **痛点**：仅在 `history.db` 旁额外建表无法防止跨语句/跨文件崩溃分裂——若在 `chunk_feed`、assistant turn、状态快照或 `branches.json` 的相邻写入间发生崩溃，恢复后会出现“新对话历史配旧章节游标或错误分支身份”；执行 `revert_chat_history` 或切换分支时，状态也必须按单一权威提交/恢复协议同步回退或迁移。

### 2.4 缺口 ④：压缩钩子不可定制、文档摄取缺少 PDF 支持、新建会话与提交协议缺位

- **现状**：
  - `sdk/hooks.py` 的 `BeforeCompactContext` 仅暴露只读快照字段（`messages`、`older_messages`、`recent_messages`、`session_id`、`up_to_seq`），`ai/llm/compact_manager.py` 的 `_create_compact_prompt()` 使用固定通用闲聊总结提示词，行为模式或插件无法声明“压缩早期历史时必须保留人物别名表 / 错题薄弱点 / 核心人格参数”。
  - `core/knowledge/import_sources.py` 已实现 UTF-8 / UTF-16 / GB18030 自动编码探测，但仅支持 `.txt` 与 `.json`；`requirements-runtime-core.txt` 尚未引入 PDF 解析依赖。
  - 现有 `application/story/generation.py` 面向 `MAX_SYNOPSIS_CHARS = 20_000` 字的梗概进行三阶段浓缩建图与自由发挥，无法直接承接几十万字长篇原文的忠实逐段演出。
  - 现有通用 `submit-option` 命令退化为纯文本字符串且无版本校验，缺乏可去重与乐观并发校验的提交契约；`frontend/src/features/chat-workspace/ChatWorkspacePage.tsx` 当前仅硬编码 `"normal"` 与 `"story"` 两种新建会话形态。

---

## 3. 分层架构：6 项共有内核 vs 4 大行为策略协议

### 3.1 依赖方向

严格遵守 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) 与 `test/unit/architecture/test_import_boundaries.py` 守护的单向依赖规则，不新增任何架构例外：

```text
frontend (新建向导 / 选角映射表 / 舞台章节目录抽屉 / 无输入连播控制)
   │
   ▼
frontend_bridge_core (文档上传解析预览路由 / 启动载荷 / 权威行为命令与跳章转发)
   │
   ▼
application (SessionBehavior 内部编排 / 演员与 NPC 路由 / 独立预取器 / 原子提交与文档回收)
   ├──▶ ai (CompactManager 可扩展压缩提示 / 纯净预取生成入口 / 逐说话人修复 / 记忆过滤)
   ├──▶ plugin_system (后续开放插件行为注册接入)
   ├──▶ core (core/document 共享仓库与切片 / history.db 单事务协议 / 内部来源谓词 / 校验谓词)
   └──▶ config (读取本地角色目录与普通模板默认参数)
          │
          ▼
         sdk (Phase 1 仅扩展 BeforeCompactContext；Phase 4 验证成熟后开放行为插件契约)
```

同时，运行时装配优先复用到现有的 `application/chat/capabilities/contracts.py`（`SessionCapability` 与 `TurnContextProvider`）机制，不将业务状态硬塞进通用会话启动脚本。

### 3.2 什么是「共有的」？（宿主机制，归 `core/` + `application/` + `ai/`）

以下 6 项机制由宿主统一实现并确保线程、存储与回档安全，上层模式与插件无需重复造轮子：

| 序号 | 共有宿主内核 | 负责职责 | 核心位置 |
| --- | --- | --- | --- |
| 1 | **共享文档仓库与弹性切片** | TXT 多编码解码、PDF 文本与书签 TOC 提取、PDF 硬回车修复、扫描版空文本拦截、按段落与引号边界切成 ~800 字切片；按 `doc_id` 存放在内容寻址共享库 `data/documents/<doc_id>/` 并提供应用层引用计数与可恢复清理生命周期 | `core/document/`、`application/` |
| 2 | **统一内部来源谓词与单事务快照提交** | 定义 `SYNTHETIC_INTERNAL_SOURCES` 共享判定（含 `chunk_feed`），全面收口 UI、宿主投影、回放、感知注入、活跃度与长期记忆提取；在 `history.db` 定义 `commit_behavior_turn` 单事务提交与写前恢复日志协议，确保与 `active.json`/`branches.json` 一致恢复 | `core/chat_history/`、`ai/memory/`、`application/perception/`、`commands.py` |
| 3 | **选角与别名路由表（`CastingMap`）** | 维护 `小说角色名 / 别名表 → 本地角色 ID` 的映射与「显示原名 / 替换本地角色名」开关；在 OpenCC 简繁转换前先按原始名与别名归一匹配 | `application/` |
| 4 | **逐说话人媒体校验与 NPC 放行** | 由 `CastingMap` 派生 `speaker_requires_media` 谓词透传给最终 JSON 校验与 `dialog_repair`：已绑定角色仍强制校验 `sprite`/`vibe`，仅未绑定路人 NPC 与 `"？？？"` 放行纯文本 `PresentationMessage`；支持已绑定角色的暗影剪影态 | `core/messaging/dialog_output.py`、`ai/llm/`、`dialog_media.py` |
| 5 | **真实完播回调与纯请求独立预取器** | 监测舞台字幕/TTS 真正播完的 `playback_idle` 时机；新增无副作用纯生成入口 `run_speculative_dialog_generation` 并使用独立 `prefetch_adapter` 与请求级 `PrefetchHandle`（绝不写入历史或误杀前台请求）；配合 `BehaviorStateEnvelope` 发布乐观锁版本号与 `stagePolicy` | `ai/llm/`、`application/chat/runtime/`、`frontend/src/features/chat-stage/` |
| 6 | **Token 计数与压缩执行骨架** | 复用 `CompactManager` 精确计算上下文 Token、保护最近 `recent_message_limit` 条消息、调度 `BeforeCompactContext` 收集自定义指令并写入 `compact_checkpoints` | `ai/llm/compact_manager.py`、`sdk/hooks.py` |

### 3.3 什么是「行为定义的」？（四大策略接口与形态对比）

任何文档驱动玩法或导演型会话模式，本质上只需通过 `SessionBehavior` 实现 4 个策略接口（配合双阶段权威命令与状态跃迁协议，见 4.3.D）：

| 策略接口 | 核心职责 | 📖 小说剧场（Phase 3 MVP） | 🎓 Galgame 讲堂（Phase 4） | 🎲 TRPG 跑团 DM（远期） |
| --- | --- | --- | --- | --- |
| **1. `CastingPolicy`<br>选角策略** | 声明开局如何建立演员与本地角色的绑定关系 | **`extract_and_map`**：抽样前几片提取主要角色 + 别名表 + 第一人称「我」，供用户映射本地皮套；未映射角色走无立绘 NPC | **`pick_actors`**：直接从本地角色库挑选 1 名「主讲老师」+ 可选 1 名「捧哏学伴」 | **混合选角**：1 名角色或旁白任 DM + 1～N 名本地角色任 AI 队友 / 玩家角色，模组 NPC 走无立绘通道 |
| **2. `InteractionPolicy`<br>交互策略** | 声明舞台界面开关与播完后的默认行为（随 `BehaviorStateEnvelope` 下发） | • `hideInputLayer = True`<br>• `useChoice = False`<br>• `useNarration = True`<br>• `playbackEndAction = "auto_advance"`（点屏幕/Auto 带版本号触发下一片） | • `hideInputLayer = False`（允许随时打断提问）<br>• `useChoice = True`（带稳定 `optionId` 的出题选项）<br>• `useStat = True`（掌握度）<br>• `playbackEndAction = "wait_user"` | • `hideInputLayer = False`<br>• `useChoice` 可选、`useStat = True`（HP/SAN/线索）<br>• 支持注册 `@tool`（如真随机投骰、模组切片检索） |
| **3. `ProgressionPolicy`<br>推进策略** | 通过 `on_command`（权威校验输入/选项/完播）+ `build_turn_input` + `on_assistant_turn`（生成新版状态信封与跃迁）控制进程 | • `on_command`：校验 `expectedBehaviorRevision` 与 `expectedChunkId` 后接收完播或跳章<br>• `build_turn_input`：注入本片 800 字正文 + 120 字后文 `lookahead`<br>• `on_assistant_turn`：回复合法即 **100% 确定性**推进游标并开启 `prefetch_next=True`（零额外裁判请求） | • `on_command`：基于 `optionId` 与 `expectedBehaviorRevision` 权威判定作答或自由提问，过期重复点击直接拒绝<br>• `build_turn_input`：规定**核心公式/代码/题干放入 `NARR` 黑板**避免 TTS 念错<br>• `on_assistant_turn`：出题后 `stay`，答对 `advance`，答错 `stay` 留堂重讲；支持 `jump` 复习 | • 开局注入模组总纲隐藏背景；玩家提交行动后 DM 依场景按需 `jump(chunk_id)` 或调检索工具翻阅对应地点/NPC 切片<br>• `behavior-command` 预留可选 `player_id / display_name` 以兼容多真人同回合攒批 |
| **4. `CompactionPolicy`<br>压缩策略** | 通过 `BeforeCompactContext` 注入总结必须保留的域内记忆 | 要求压缩摘要完整保留：**已登场人物标准名与外号/称呼映射、第一人称「我」身份、人物关系与主线进展** | 要求压缩摘要保留：**已掌握的核心概念清单、玩家答错或反复追问过的薄弱知识点** | 要求压缩摘要保留：**调查员当前状态、关键持有线索、已触发事件与 NPC 态度** |

> **远期多人联机安全边界（TRPG 备忘）**：
> 当前 `frontend_bridge_core/transport/mobile_access.py` 中的 `MobileAccessTransport` 会通过 URL 参数携带高权限宿主凭证 `shinsekai_bridge_token`（仅供房主本人手机使用）。未来若开放跨网络网友联机跑团，**严禁向外部访客分发 `shinsekai_bridge_token`**，必须独立提供绑定单端口与单会话作用域的低权限 `room_invite_token`（访客仅能接收当前舞台演出事件与以指定角色身份提交行动）。

---

## 4. 长篇小说上下文、指代消解与权威协议设计

### 4.1 放弃“全书梗概浓缩”，采用“原生多轮切片 + 达阈值自动压缩”

针对几十万字小说，核心设计原则是不在导入期用 LLM 把全书压缩成几十字节点要求，而是：

1. **原汁原味喂料**：将小说切成 ~800 字切片后，按顺序以 `source="chunk_feed"` 的内部消息追加进原生 `ConversationHistory`，由常规对话大模型逐片演译成标准 `dialog` JSON（关闭 `[本地时间 ...]` 前缀以免时间噪音污染剧本）。
2. **严格隔离内部消费方**：`chunk_feed` 仅对 `ConversationHistory`（LLM 请求历史）与 `CompactManager`（摘要压缩）可见；通过统一的内部来源谓词，彻底从 UI 历史、回放、屏幕感知注入、会话活跃度计数与长期记忆提取/召回路径中排除（文档剧场默认隔离个人长期记忆写入，防止虚构小说情节污染用户的个人长期记忆）。
3. **达阈值自然压缩 + 近期原文无缝衔接**：
   - 每轮切片（约 800 字原文 + 对应 `dialog` JSON ≈ 2,000～2,500 tokens）顺次进入历史，按默认 `128k` 上下文与 `0.4` 压缩阈值估算，可连续演出约 20 轮（~1.6 万字）才触发一次 `CompactManager.auto_compact_if_needed()`。
   - 压缩触发时，早期历史在 `CompactionPolicy` 指导下提炼成包含**全人物别名映射与主线**的摘要，同时 `CompactManager` **完整保留最近 `recent_message_limit`（默认 20 条）消息（约最近 8,000 字的原文与已消解说话人的 `dialog`）**，跨压缩边界的代词指代与语气绝不断档。
4. **命中 Prefix KV Cache**：由于只向历史末尾追加新切片而不反复拼接/改写前文系统提示词或上下文块，前面几十轮消息前缀完全稳定，在主流 LLM 接口上可稳定命中前缀缓存，显著降低延迟与输入成本。

### 4.2 切口指代消解三保险

为彻底解决切分边界处的“他/她”指代丢失、先出引号后写说话人（倒装提示语）以及悬疑藏名问题，增加三道轻量防御：

1. **弹性引号保护切分**：目标切片长度为 800 字（允许弹性区间 500～1,300 字）。遇到空行/场景分隔线优先切分；若到达 800 字附近时仍处于未闭合引号内或连续对白段落中（上下相邻段均以引号开头），切分器自动向后顺延至该段连续对话结束后的叙述段再落刀。
2. **向后只读偷看窗（`lookahead`）**：喂给 LLM 当前切片 `chunk.text` 时，附带下一片开头约 120 字作为只读预览 `chunk.lookahead`，Prompt 明确标注 **“仅供确认末尾倒装署名与代词指代，严禁在本轮提前演出”**。
3. **悬疑角色 `？？？` 规范与不可编造约束**：Prompt 明确规定“忠实还原原文情节点与核心台词，不得提前剧透或编造后续剧情”；对于原文刻意隐瞒身份的初登场声音或黑影，统一输出 `character_name: "？？？"`（或原文称谓如 `"门外的男声"`），待演到揭晓段落再切换回标准名与绑定皮套。

### 4.3 核心数据模型与协议草案

#### A. 内容寻址共享文档与切片模型（`core/document/models.py`）

```python
@dataclass(frozen=True, slots=True)
class DocumentChapter:
    id: str
    title: str
    index: int
    start_chunk_index: int
    end_chunk_index: int  # exclusive

@dataclass(frozen=True, slots=True)
class DocumentChunk:
    id: str
    chapter_id: str
    index: int
    text: str             # 本轮实际待演出的正文（约 500~1300 字）
    lookahead: str = ""   # 下一片开头约 120 字只读预览（防倒装署名）
    char_start: int = 0
    char_end: int = 0

@dataclass(frozen=True, slots=True)
class DocumentManifest:
    doc_id: str           # SHA-256(源文件字节 + 切片算法版本号)
    schema_version: int
    title: str
    source_type: Literal["txt", "pdf"]
    source_filename: str
    total_chars: int
    chapters: tuple[DocumentChapter, ...]
    chunks: tuple[DocumentChunk, ...]

@dataclass(frozen=True, slots=True)
class SessionDocumentBinding:
    schema_version: int
    doc_id: str
    behavior_id: str
    bound_at_ms: int
```

- 持久化目录结构：`data/documents/<doc_id>/` 下仅允许固定白名单文件名 `manifest.json`、`chapters.json`、`chunks.jsonl`；会话目录仅保存轻量绑定文件 `<session_dir>/document-binding.json`。

#### B. 选角绑定模型（`CastingMap`）

```python
@dataclass(frozen=True, slots=True)
class CastBinding:
    source_name: str                    # 文档内标准角色名（或显示原名）
    aliases: tuple[str, ...] = ()       # 别名/外号/简称集合（供匹配与 Prompt 参照）
    target_character_id: str = ""       # 绑定的本地角色名；为空则走无立绘纯对话 NPC
    display_mode: Literal["source_name", "actor_name"] = "source_name"
    is_first_person_narrator: bool = False
```

#### C. 跨 SQLite 与分支投影的单一提交与崩溃恢复协议

在 `core/chat_history/sqlite_session_store.py` 确立 **`history.db` 为唯一权威事实源（Single Source of Truth）**，`active.json` 与 `branches.json` 降级为可确定性重建的派生投影（且将 `core/chat_history/storage.py` 的 `save_branch_state()` 改造为 `tempfile` + `fsync` + `os.replace` 原子写入，消除直接覆盖写导致截断损坏的隐患）。

```sql
CREATE TABLE IF NOT EXISTS session_state_snapshots (
    branch_id TEXT NOT NULL DEFAULT 'main',
    up_to_seq INTEGER NOT NULL,
    namespace TEXT NOT NULL,
    behavior_revision INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (branch_id, up_to_seq, namespace)
);
```

- **版本锚点**：`session_meta` 持久化权威 `active_branch_id` 与递增 `branch_tree_revision`；初始化会话时写入 `up_to_seq = 0, behavior_revision = 1` 的初始状态快照 `initial_state_json`。
- **单事务写入与写前日志顺序**：
  - 所有操作通过 `SqliteSessionStore` 写锁串行化；涉及 LLM 流式/异步生成的行为回合，先参考 `application/story/prompt_turns.py` 的 `PromptTurnJournal` 写入原子预写日志 `<session_dir>/behavior-turn-journal.json`（含 `_behaviorTurnId`、`branch_id`、`expected_behavior_revision`、`chunk_feed_message`、`assistant_message`、`next_state_json`）。
  - 随后在单一连接 `BEGIN IMMEDIATE ... COMMIT` 事务内通过 `commit_behavior_turn(...)` 原子完成：**① 插入 `chunk_feed` turn（若本轮存在）→ ② 插入 `assistant` turn → ③ 写入/覆盖该 `up_to_seq = assistant_turn.seq` 对应的 `session_state_snapshots`（含 `behavior_revision + 1`）**。
  - SQLite 事务提交成功后，再原子刷新派生文件 `active.json` 与 `branches.json`，最后删除 `behavior-turn-journal.json`。
- **全生命周期分支与截断规则**：

| 操作 | SQLite 单事务内动作（Authority） | 派生投影同步（Derived） |
| --- | --- | --- |
| **Append** | 写入输入 turn + 回复 turn + 新状态快照（递增 `behavior_revision`） | 原子重写 `active.json` / `branches.json` 后清理 journal |
| **Fork** | 将源分支 `seq <= fork_seq` 的 `turns`、`compact_checkpoints` 及该截点最新 `session_state_snapshots`（若无则继承 `up_to_seq = 0`）克隆至新 `branch_id`；递增 `branch_tree_revision` | 原子写入含新分支节点的 `branches.json` |
| **Switch** | 先裁决完未决 journal；更新 `session_meta.active_branch_id`，递增 `branch_tree_revision`，读取目标分支 `<= MAX(turns.seq)` 最新状态快照 | 按目标分支权威 turns 原子重建 `active.json` 与 `branches.json` |
| **Rename** | `branch_id` 创建后不可变，仅修改展示名 `label`（无需改主键）；若导入/迁移必须重映射 `branch_id`，则同事务级联更新 `turns`、`compact_checkpoints`、`session_state_snapshots` 与 `session_meta` | 原子更新 `branches.json` 对应分支 `label` |
| **Truncate** | 删除 `branch_id` 下 `seq > cutoff` 的 `turns`、`compact_checkpoints` 与 `up_to_seq > cutoff` 的 `session_state_snapshots`；恢复 `<= cutoff` 最新状态快照（至少回落到 `up_to_seq = 0` 初始快照） | 原子重建 `active.json` / `branches.json` 并下发最新 `BehaviorStateEnvelope` |
| **Clear** | 保留 `document-binding.json`，删除目标分支 `turns`、`compact_checkpoints` 与 `up_to_seq > 0` 快照，将 `up_to_seq = 0` 初始快照复制为最新激活态并递增值守 `behavior_revision` | 清空并发重建 `active.json` / `branches.json`，清除 journal |
| **启动 / 崩溃恢复** | **裁决顺序**：① 读 `behavior-turn-journal.json`：若 `turns` 已存在对应 `_behaviorTurnId` 的 `assistant` 回复但缺快照，则幂等补写快照；若仅残留孤立 `chunk_feed` turn 而无回复，则删除该孤立尾部 turn 并回退；② 删除 `up_to_seq > COALESCE(MAX(turns.seq), 0)` 的任何悬空快照；③ 清除 journal | 以 `history.db` 为准强制覆盖修复落后的 `active.json` 与 `branches.json` |

#### D. 权威且幂等的行为状态跃迁协议（Phase 1～3 位于 `application/session_behavior/protocol.py`）

```python
@dataclass(frozen=True, slots=True)
class InteractionPolicy:
    hide_input_layer: bool = False
    use_choice: bool = True
    use_stat: bool = False
    use_narration: bool = True
    playback_end_action: Literal["wait_user", "auto_advance"] = "wait_user"

@dataclass(frozen=True, slots=True)
class BehaviorOption:
    option_id: str
    label: str
    value: str = ""

@dataclass(frozen=True, slots=True)
class BehaviorStateEnvelope:
    behavior_id: str
    behavior_revision: int
    current_chunk_id: str
    current_chunk_index: int
    phase: Literal["playing", "awaiting_input", "ended"]
    active_options: tuple[BehaviorOption, ...]
    stage_policy: InteractionPolicy
    custom_state: Mapping[str, Any]
    last_command_id: str = ""

@dataclass(frozen=True, slots=True)
class BehaviorCommand:
    command_id: str
    kind: Literal["playback_completed", "select_option", "submit_freeform", "jump_chapter"]
    expected_behavior_revision: int
    expected_chunk_id: str
    option_id: str = ""
    text: str = ""
    target_chapter_id: str = ""

@dataclass(frozen=True, slots=True)
class CommandResolution:
    accepted: bool
    error_code: str = ""          # 例如 "behavior.stale_revision" / "behavior.invalid_option"
    error_message: str = ""
    action: Literal["noop", "run_turn", "consume_prefetch", "jump_state"] = "noop"
    target_chunk_index: int | None = None
    next_state: BehaviorStateEnvelope | None = None  # 仅 jump_state 等纯状态跃迁直接提交

@dataclass(frozen=True, slots=True)
class BehaviorTransition:
    next_state: BehaviorStateEnvelope
    prefetch_next: bool = False

class SessionBehavior(Protocol):
    behavior_id: str

    def on_command(
        self,
        command: BehaviorCommand,
        state: BehaviorStateEnvelope,
    ) -> CommandResolution: ...

    def build_turn_input(
        self,
        *,
        command: BehaviorCommand,
        chunk: DocumentChunk | None,
        state: BehaviorStateEnvelope,
        actor_id: str = "",          # 预留字段：单人为空，多人联机时标识发言玩家
        display_name: str = "",      # 预留字段：玩家显示名
    ) -> str: ...

    def on_assistant_turn(
        self,
        *,
        assistant_message: Mapping[str, Any],
        state: BehaviorStateEnvelope,
        command_id: str,
    ) -> BehaviorTransition: ...

    def compaction_instructions(self, state: BehaviorStateEnvelope) -> Sequence[str]: ...
```

- **命令去重与乐观并发校验（OCC）**：前端在用户点击“下一句 / 自动连播”、选择 `CHOICE` 选项或跳章时，统一通过专用实时命令 `behavior-command` 提交（带唯一 `commandId`、`expectedBehaviorRevision` 与 `expectedChunkId`），而非退化为无版本的普通 `submit-option` 字符串。
- **幂等与防重放**：服务端维护最近已处理的 `command_id` 去重集合（含 `BehaviorStateEnvelope.last_command_id` 持久化记录）；重复重连投递的同一 `command_id` 直接幂等返回已提交快照，版本号过期的并发点击直接返回 `behavior.stale_revision` 拒绝，杜绝“连播双击 / Auto 竞态 / 重连重复扣题推进”。
- **Hydration 与事件同步**：`BehaviorStateEnvelope`（含 `behaviorRevision`、`activeOptions` 与 `stagePolicy`）不仅随增量事件 `behavior.state.replace` 实时推向前端，也同步写入 `_chat_snapshot()`（`hydrate` 快照）保证刷新与断线重连后前端持有的版本号与 UI 策略严格对齐。

---

## 5. 分阶段实施路线与模块清单

### Phase 1：补齐 4 项宿主共有底座原语

1. **逐说话人媒体校验谓词与演员皮套映射路由**
   - `core/messaging/dialog_output.py`：`has_valid_dialog_output()` 不使用全局布尔开关，改为接收逐说话人判定谓词 `speaker_requires_media: Callable[[str], bool] | None = None`（`scene` / `bgm` 与命中 `CastingMap` 已绑皮套的角色仍强制校验 `sprite` 或 `vibe`；仅未绑定路人 NPC 与 `"？？？"` 放行省略/`"-1"`）。
   - `ai/llm/chat_loop.py` & `ai/llm/dialog_repair.py`：透传 `speaker_requires_media` 与已绑定演员名单至 `ChatLoop` 及 `repair_dialog_output()`，并在 `_repair_prompt()` 明确提示“哪些角色必须携带 `{media_field}`，未绑定的临时路人可省略”，防止已配置角色误漏立绘或 NPC 被修复循环死拦。
   - `application/chat/presentation/handlers/dialog_media.py` & `presentation.py`：`CharacterMediaHandler` 按「精确原名 → 别名表 → OpenCC 归一」匹配 `CastingMap`；命中时借用本地角色立绘与 TTS 音色（并支持原名/演员名展示模式及可选暗影剪影元数据），未绑定路人跳过语音与立绘推流、直接发出纯文本 `PresentationMessage` 且不占 3 个立绘槽。

2. **统一内部来源过滤谓词 & 单事务快照恢复协议**
   - `sdk/messages.py` & `core/chat_history/models.py`：定义 `CHUNK_FEED_SOURCE = "chunk_feed"` 与共享判定 `SYNTHETIC_INTERNAL_SOURCES = frozenset({"perception", COMPACT_SUMMARY_SOURCE, CHUNK_FEED_SOURCE})` 及 `is_synthetic_internal_source()` / `is_real_user_turn_message()`。
   - 收口全仓内部消费者（替代硬编码 `source == "perception"`）：
     - UI 与回放：`core/chat_history/models.py`（`render_messages_to_ui_history`）、`application/chat/host/history.py`（`_serialize_history_entries_from_messages`）及 `application/chat/history/replay.py` 跳过 `chunk_feed` 且不递增真人 `revertUserIndex`；
     - 屏幕感知与活跃度：`application/perception/hooks.py`（`prepare_turn`、`before_chat`、`message_added`）与 `application/chat/capabilities/perception.py` 禁止对 `chunk_feed` 附加视觉上下文且不计入 `from_user=True` 活跃度；`LLMManager.chat()` 对 `chunk_feed` 传 `include_local_time=False`；
     - 长期记忆：`ai/memory/hooks.py`、`ai/memory/rule_recall_planner.py` 与 `application/chat/capabilities/memory.py`（`_last_dialogue_turn_at`）统一排除 `chunk_feed`，文档剧场模式默认关闭自动长期记忆提取写入。
   - `core/chat_history/sqlite_session_store.py`、`core/chat_history/storage.py` & `application/chat/runtime/commands.py`：落地 `session_state_snapshots` 表、原子 `save_branch_state()`、`commit_behavior_turn()`、`behavior-turn-journal.json` 写前日志以及 Append / Fork / Switch / Rename / Truncate / Clear / 崩溃恢复全协议（见 4.3.C）。

3. **可定制压缩指令**
   - `sdk/hooks.py`：`BeforeCompactContext` 增加 `extra_instructions: list[str] = field(default_factory=list)` 与 `add_instruction(text: str)` 方法（保持向后兼容）。
   - `ai/llm/compact_manager.py`：在 `dispatch_before_compact()` 之后将 `extra_instructions` 去重拼入 `_create_compact_prompt()`。

4. **舞台完播回调、纯请求独立预取器与权威行为命令**
   - `application/chat/runtime/turn_wiring.py`、`session.py` & `commands.py`：监测 `dialog_queue` 与 `presentation_queue` 耗尽且最后一句语音/字幕播完后的 `playback_idle`；注册 `behavior-command` 权威处理入口。
   - **纯净独立预取器（无副作用 + 请求级取消）**：
     - 在 `ai/llm/` 新增纯生成函数 `run_speculative_dialog_generation(...)`：接收从 `ConversationHistory` 深拷贝并冻结的不可变消息列表与下一片 prompt，强制 `tools=None`、`stream=False`，**绝不调用 `LLMManager.chat()` / `ChatLoop`，不触发 `MessageJournal`、`MESSAGE_ADDED`、`CompactManager` 或 `ToolSession`**，仅调用纯函数 `repair_dialog_output(..., speaker_requires_media=...)` 校验输出。
     - 预取器持有独立创建的 `prefetch_adapter` 实例（单槽串行 `max_inflight = 1`），每次预取绑定独立 `PrefetchHandle(generation_token, expected_behavior_revision, cancel_event)`；跳章、回档、前台打断或关闭会话时仅取消 `prefetch_adapter` 与置位 `cancel_event`，**严禁调用前台 `LLMManager.llm_adapter.cancel()`**。
   - `frontend/src/features/chat-stage/`：`_chat_snapshot` 与 `behavior.state.replace` 携带 `BehaviorStateEnvelope`（含 `behaviorRevision`、`activeOptions` 与 `stagePolicy`）；`InputLayer.tsx` 根据 `stagePolicy.hideInputLayer` 隐藏输入框；点击最后一句或 Auto 结束时携带 `commandId`、`expectedBehaviorRevision` 与 `expectedChunkId` 下发 `behavior-command`（`kind="playback_completed"`）。

### Phase 2：构建共有文档摄取与共享仓库（`core/document/` & 应用层生命周期）

1. **`requirements-runtime-core.txt`**：引入轻量纯 Python PDF 解析依赖 `pypdf`（体积小、无 C++ 编译链负担，打包进 Tauri runtime 友好）。
2. **`core/document/ingest.py`**：
   - 复用 `core/knowledge/import_sources.py` 的 `_read_supported_text` 编码探测思路（UTF-8-SIG / UTF-16 / GB18030）；
   - 提取 PDF 逐页文本与目录书签（Outlines/TOC）；
   - 实现 **PDF 行尾硬回车断行合并预处理**（判定行尾非句末标点且下段非缩进/非章节标题时自动拼接，避免长行断裂影响语义与引号配对）；
   - 若检测到页数 > 0 但提取有效字符过少（纯扫描图片版 PDF），明确拦截并提示用户原因，不做静默空跑。
3. **`core/document/chunker.py` & `repository.py`（所有权与删除生命周期）**：
   - 章节识别：优先 PDF 书签映射，否则按中英文常见章节标题正则切分，无显式标题时按约 5,000 字自动生成虚拟分节供目录导航；
   - ~800 字（500～1,300 字）弹性切片 + 引号/连续对话保护 + 120 字 `lookahead` 生成；
   - **内容寻址存储与生命周期管理**：
     - 共享产物按 `data/documents/<doc_id>/`（含白名单文件 `manifest.json`、`chapters.json`、`chunks.jsonl`）经 `.ingest-<uuid>.tmp` 组装后 `os.replace` 原子落盘；导入/启动时自动清理残余过期 `.ingest-*.tmp` 目录；
     - 会话目录仅写入 `<session_dir>/document-binding.json`，并将 `document-binding.json` 与 `behavior-turn-journal.json` 纳入 `core/chat_history/storage.py` 的 `chat_history_storage_files()` 受管文件白名单；
     - 在应用层删除编排（扩展 `conversation_library` 并复用 `application/story/deletion_transaction.py` 的 `recoverable_deletion` 事务备份）中：删除会话后检查全局存活 `document-binding.json` 引用计数，引用归零时同一恢复事务内按白名单清理 `data/documents/<doc_id>/` 产物与空目录；`clear-history` 则保留 `document-binding.json` 以便原地重开。

### Phase 3：内部 `SessionBehavior` 协议与「📖 小说剧场」MVP 闭环

1. **`application/session_behavior/`**：定义 `SessionBehavior`、`BehaviorStateEnvelope`、`BehaviorCommand`、`CommandResolution`、`BehaviorTransition`、`CastBinding` 与会话能力适配器（对接 `SessionCapability` / `TurnContextProvider`）。
2. **`application/novel_theater/`**：
   - **角色初筛服务**：导入后抽样前 3～5 个切片交由作者 LLM 提取主要人物 JSON（标准名、别名列表、性别/特征简述、是否第一人称「我」），并与本地角色库自动做同名/特征初步推荐；
   - **导演提示词模板（`ai/llm/template/`）**：沿用普通模板 `dialog` JSON 输出契约（默认开启 `useNarration`、`useEffect`/`useBgm`，强制 `useChoice=False`），注入忠实原文转译、禁止提前演出 `lookahead`、神秘人输出 `"？？？"` 等指令；
   - **跳章与进出场控制**：通过 `behavior-command`（`kind="jump_chapter"` + 期望版本）跳转至目标章节首片，作废旧 `PrefetchHandle` 后继续演出。
3. **Bridge 路由与前端 UI**：
   - **`frontend_bridge_core/routes/`**：新增小说导入解析预览、人物提取、选角映射保存、小说剧场启动、文档删除回收及跳章路由。
   - **`frontend/src/features/chat-workspace/ChatWorkspacePage.tsx`**：在新建会话弹窗（`normal` / `story` 并列）新增 `novel`（「小说剧场」）卡片，提供极简三步创建流程：**选 TXT/PDF 看目录 → 确认主角绑皮套（可一键全跳过走纯对话/默认配置）→ 开演**。
   - **`frontend/src/features/chat-stage/`**：为小说剧场模式提供顶部轻量「章节目录与进度（第 X 章 · m/n 段）」抽屉，支持带版本号的跳章与状态 hydration。

### Phase 4：第二样板验证与公开插件 `sdk/` 升格（后续规划）

1. **「🎓 Galgame 讲堂」内置验证**：复用 Phase 1～3 全部共有底座，仅实现讲堂行为策略（`pick_actors` 选 1～2 名老师/学伴；`hideInputLayer = False`、`useChoice = True`、`useStat = True`；`NARR` 充当黑板展示公式/代码避免 TTS 误读；出题后 `phase="awaiting_input"` 并附稳定 `optionId`，`on_command` 校验 `expectedBehaviorRevision` 与选项身份，答对 `advance`，答错 `stay` 换例重讲；压缩摘要保留已学概念与错题薄弱项）。
2. **正式升格进 `sdk/`**：待上述双模式跑通并收敛接口变更后，将稳定的行为契约抽象进 `sdk/` 并在 `sdk/register.py`（`PluginCapabilityRegistry`）增加行为模式注册入口，同步更新 [`PLUGIN_DEVELOPER_GUIDE.md`](PLUGIN_DEVELOPER_GUIDE.md) 供社区插件作者使用。

---

## 6. 风险与应对措施

| 风险点 | 潜在问题 | 防御设计 |
| --- | --- | --- |
| **OpenCC 简繁转换冲突** | `CharacterMediaHandler` 对未直接命中的角色名会跑 OpenCC 转换，可能导致繁体原名小说或特定用字映射失配 | 选角映射查表与 `speaker_requires_media` 判定严格按 **「精确原名 → 别名表 → OpenCC 归一后名称」** 三级顺序执行，避免误转 |
| **跨 SQLite 与文件崩溃分裂** | 多步提交若在 `turns`、`session_state_snapshots` 与 `branches.json` 间中断，会导致游标与历史错位或重复演同一章 | 单事务 `commit_behavior_turn` + `behavior-turn-journal.json` 写前日志 + 原子 `os.replace` 投影 + 启动裁决修复孤立 turn/悬空快照（见 4.3.C） |
| **预取副作用与前台取消冲突** | 预取若走 `LLMManager.chat()` 会误写历史并触发钩子；共享 `llm_adapter.cancel()` 会意外终止前台回复 | 纯函数 `run_speculative_dialog_generation`（不可变消息、无工具/日志/钩子/压缩）+ 独立 `prefetch_adapter` 与请求级 `PrefetchHandle` |
| **PDF 排版硬回车与扫描件** | 排版 PDF 每 30 字自带 `\n` 导致句子碎裂、引号匹配失效；纯图扫描 PDF 提取为空文本 | `ingest.py` 内置行尾断行合并预处理；提取有效字符密度低于阈值时直接报错阻断并友好提示 |
| **孤儿文档残留或误删共享文档** | 会话目录若直接存放巨型切片会逃逸枚举清理；多会话复用同一文档时直接删除会破坏其他会话 | 共享内容寻址目录 `data/documents/<doc_id>/` + 会话受管 `document-binding.json` 白名单 + 全局引用计数归零后经 `recoverable_deletion` 清理 |

---

## 7. 验证计划

| 阶段 | 验证内容与覆盖目标 | 工具 / 用例位置 |
| --- | --- | --- |
| **架构边界回归** | 验证 `sdk/`、`core/document/`、`ai/`、`application/` 未引入任何逆向或越界导入 | `pytest test/unit/architecture/` |
| **文档、切片与生命周期单测** | 覆盖 UTF-8/UTF-16/GB18030 TXT、带书签与无书签 PDF、硬回车合并、未闭合引号顺延、`lookahead` 长度、扫描版报错、`.ingest-*.tmp` 崩溃清扫、引用计数归零清理与 `clear-history` 保留绑定 | 新增 `test/unit/core/document/` 与应用层文档删除测试 |
| **逐说话人校验与选角单测** | 覆盖 `speaker_requires_media` 放行未绑 NPC 同时拦截漏立绘的已绑主角、`_repair_prompt` 精准提示、别名/OpenCC 三级匹配、纯文本 `PresentationMessage` 不占 3 人立绘槽 | 新增 `test/unit/application/test_casting_and_npc.py` |
| **原子提交、内部源隔离与预取单测** | 覆盖 `is_synthetic_internal_source` 排除感知/记忆/UI/回放；单事务 `commit_behavior_turn`、Fork/Switch/Truncate/Clear 与崩溃自愈；`run_speculative_dialog_generation` 无历史/钩子/adapter 取消串扰；`behavior-command` OCC 版本拒绝与 `commandId` 幂等去重；`BeforeCompactContext` 自定义指令注入 | 新增 `test/unit/application/test_session_behavior_runtime.py` |
| **前端类型与组件测试** | 覆盖新建会话「小说剧场」流程、选角映射表、`InputLayer` 隐藏逻辑、版本化 `behavior-command` 下发与 hydration、以及舞台章节目录抽屉交互 | `pnpm lint:types`、`pnpm test` |
