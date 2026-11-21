# 文档驱动舞台底座与会话行为 SDK（SessionBehavior）设计方案

> 状态：草案
> 日期：2026-11-21
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

### 2.1 缺口 ①：缺少舞台真实完播回调（`on_playback_idle`）与无脏数据预取机制

- **现状**：`sdk/hooks.py` 中的 `MESSAGE_ADDED`（`MessageAddedContext`）在 LLM 刚吐完一轮 JSON、消息写入 `ConversationHistory` 时即刻触发；此时 `dialog_queue` 与 `presentation_queue` 才刚开始向前端舞台送出第 1 句台词与 TTS 音频。
- **痛点**：
  - 若在 `message_added` 中立即触发下一段生成，会直接打断当前排队朗读的台词或导致队列顺序冲突；
  - 若等全部播完后再请求 LLM 生成下一段，用户读完每段最后一句都会卡住干等 5～15 秒。

### 2.2 缺口 ②：角色绑定强校验与无立绘路人（NPC）通道阻断

- **现状**：
  - `core/messaging/dialog_output.py` 的 `has_valid_dialog_output()` 强制校验：除 `CG` / `CHOICE` / `COT` / `NARR` / `STAT` 等系统关键字外，所有条目都必须携带 `sprite`（indexed 模式）或 `vibe`（semantic 模式）。
  - `application/chat/presentation/handlers/dialog_media.py` 的 `CharacterMediaHandler.handle()` 在 `rt.config.get_character_by_name(name_s)` 返回 `None` 时直接抛出 `ValueError(f"未找到角色配置: {name_s}")`。
  - 实际上，下游 `application/chat/presentation/handlers/presentation.py` 的 `CharacterDialogUiHandler.handle()` **已经具备兜底显示能力**（找不到 `character_config` 时会跳过立绘并用 `#84C2D5` 默认色渲染对话框），只是消息在更早的校验层和媒体层就被拦截了。
- **已敲定的美术与交互决策（明确不生成四张“无脸黑衣人”预设立绘）**：
  - 经过方案评估，决定**不采用“成男 / 成女 / 萝莉 / 正太四张无脸黑衣人预设图”**作为未匹配角色的替身，原因有三：
    1. **立绘槽位挤占**：舞台立绘池上限仅为 3 个 LRU 槽位（`frontend/src/features/chat-stage/state/sprites.ts` 中 `CHAT_STAGE_SPRITE_SLOT_COUNT = 3`），路人甲、店小二频繁上台会直接把正在对戏的男女主真立绘挤出舞台；
    2. **表现割裂**：静态黑衣人无法做微表情反应，且与角色揭晓真身后的实际发型/体型/服饰轮廓前后不一致；
    3. **维护冗余**：引入无意义静态占位资源不如复用正统视觉小说的克制做法。
  - **最终采用方案**：
    1. **未绑定本地皮套的纯龙套 / 路人 NPC**（如“店小二”“路人甲”）：走**纯对话框演出通道**——对话框正常显示路人名称与台词，不占用 3 人立绘槽、不切换场上主角立绘、不触发 TTS 语音；
    2. **已绑定本地皮套但原文尚未揭晓身份的角色**（如 `？？？` / `神秘少女` 初登场，作为可选增强）：直接复用其对应本地角色的真实立绘/Live2D 资源，并在前端渲染层叠加暗影剪影滤镜（如低亮度暗影效果），揭晓真名时撤除滤镜——保证剪影轮廓与动作变化和本人 100% 一致。

### 2.3 缺口 ③：缺少随聊天回档 / 分支自动同步的会话状态槽

- **现状**：如 [`PLUGIN_DEVELOPER_GUIDE.md`](PLUGIN_DEVELOPER_GUIDE.md) 所述，当前插件内部状态通常自行读写 `data/plugins/` 下的文件。
- **痛点**：当用户在聊天历史中执行回溯（`ChatCommandDispatcher._revert_history` / `revert_chat_history`）或切换对话分支时，`core/chat_history/sqlite_session_store.py` 管理的 `history.db` 回退了对话轮次，但插件外部文件中的状态（如小说当前演到第几段、RPG 血量金币、人格情绪值）仍停留在未来时间点，造成时空错乱。

### 2.4 缺口 ④：压缩钩子不可定制、文档摄取缺少 PDF 支持、新建会话入口封闭

- **现状**：
  - `sdk/hooks.py` 的 `BeforeCompactContext` 仅暴露只读快照字段（`messages`、`older_messages`、`recent_messages`、`session_id`、`up_to_seq`），`ai/llm/compact_manager.py` 的 `_create_compact_prompt()` 使用固定通用闲聊总结提示词，行为模式或插件无法声明“压缩早期历史时必须保留人物别名表 / 错题薄弱点 / 核心人格参数”。
  - `core/knowledge/import_sources.py` 已实现 UTF-8 / UTF-16 / GB18030 自动编码探测，但仅支持 `.txt` 与 `.json`；`requirements-runtime-core.txt` 尚未引入 PDF 解析依赖。
  - 现有 `application/story/generation.py` 面向 `MAX_SYNOPSIS_CHARS = 20_000` 字的梗概进行三阶段浓缩建图与自由发挥，无法直接承接几十万字长篇原文的忠实逐段演出。
  - `frontend/src/features/chat-workspace/ChatWorkspacePage.tsx` 当前仅硬编码 `"normal"` 与 `"story"` 两种新建会话形态。

---

## 3. 分层架构：6 项共有内核 vs 4 大行为策略协议

### 3.1 依赖方向

严格遵守 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) 与 `test/unit/architecture/test_import_boundaries.py` 守护的单向依赖规则，不新增任何架构例外：

```text
frontend (新建向导 / 选角映射表 / 舞台章节目录抽屉 / 无输入连播控制)
   │
   ▼
frontend_bridge_core (文档上传解析预览路由 / 启动载荷 / 跳章与推进命令转发)
   │
   ▼
application (SessionBehavior 内部编排 / 演员与 NPC 路由 / 预取缓冲 / 游标回档同步)
   ├──▶ ai (CompactManager 可扩展压缩提示 / 人物抽取与导演提示词模板)
   ├──▶ plugin_system (后续开放插件行为注册接入)
   ├──▶ core (core/document 切片 / history.db 状态快照表 / dialog 校验放宽)
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
| 1 | **文档摄取与弹性切片仓库** | TXT 多编码解码、PDF 文本与书签 TOC 提取、PDF 硬回车修复、扫描版空文本拦截、按段落与引号边界切成 ~800 字切片并提供随机索引/目录查询 | `core/document/` |
| 2 | **隐藏喂料消息与状态快照存储** | 定义 `source="chunk_feed"` 内部输入来源（对 LLM 与压缩器可见，在 `render_messages_to_ui_history` 与 `replay.py` 中隐藏）；在 `history.db` 中按 `(branch_id, up_to_seq, namespace)` 存取 JSON 状态快照并与回档/切分支原子联动 | `core/chat_history/models.py`、`sqlite_session_store.py`、`commands.py` |
| 3 | **选角与别名路由表（`CastingMap`）** | 维护 `小说角色名 / 别名表 → 本地角色 ID` 的映射与「显示原名 / 替换本地角色名」开关；在 OpenCC 简繁转换前先按原始名与别名归一匹配 | `application/` |
| 4 | **无立绘 NPC 放行与剪影态** | 放宽非注册说话人的 `sprite`/`vibe` 必填校验；`CharacterMediaHandler` 对未绑皮套说话人跳过语音与立绘推流，仅推送纯文本对话展示；支持已绑定角色的暗影剪影状态标记 | `core/messaging/dialog_output.py`、`dialog_media.py` |
| 5 | **真实完播回调与只读预取缓冲** | 监测舞台字幕/TTS 真正播完的 `playback_idle` 时机；**基于 `ConversationHistory` 只读副本**在后台内存预跑下一片 LLM 回复（绝不提前落盘），真正推进时再原子提交；响应 `stagePolicy` 控制舞台是否隐藏底部输入框及播完动作 | `application/chat/runtime/`、`frontend/src/features/chat-stage/` |
| 6 | **Token 计数与压缩执行骨架** | 复用 `CompactManager` 精确计算上下文 Token、保护最近 `recent_message_limit` 条消息、调度 `BeforeCompactContext` 收集自定义指令并写入 `compact_checkpoints` | `ai/llm/compact_manager.py`、`sdk/hooks.py` |

### 3.3 什么是「行为定义的」？（四大策略接口与形态对比）

任何文档驱动玩法或导演型会话模式，本质上只需通过 `SessionBehavior` 实现 4 个策略接口：

| 策略接口 | 核心职责 | 📖 小说剧场（Phase 3 MVP） | 🎓 Galgame 讲堂（Phase 4） | 🎲 TRPG 跑团 DM（远期） |
| --- | --- | --- | --- | --- |
| **1. `CastingPolicy`<br>选角策略** | 声明开局如何建立演员与本地角色的绑定关系 | **`extract_and_map`**：抽样前几片提取主要角色 + 别名表 + 第一人称「我」，供用户映射本地皮套；未映射角色走无立绘 NPC | **`pick_actors`**：直接从本地角色库挑选 1 名「主讲老师」+ 可选 1 名「捧哏学伴」 | **混合选角**：1 名角色或旁白任 DM + 1～N 名本地角色任 AI 队友 / 玩家角色，模组 NPC 走无立绘通道 |
| **2. `InteractionPolicy`<br>交互策略** | 声明舞台界面开关与播完后的默认行为 | • `hideInputLayer = True`<br>• `useChoice = False`<br>• `useNarration = True`<br>• `playbackEndAction = "auto_advance"`（点屏幕/Auto 自动演下一片） | • `hideInputLayer = False`（允许随时打断提问）<br>• `useChoice = True`（出题选项）<br>• `useStat = True`（掌握度）<br>• `playbackEndAction = "wait_user"` | • `hideInputLayer = False`<br>• `useChoice` 可选、`useStat = True`（HP/SAN/线索）<br>• 支持注册 `@tool`（如真随机投骰、模组切片检索） |
| **3. `ProgressionPolicy`<br>推进策略** | 决定每片如何喂给 LLM（`build_turn_input`），以及播完后停驻/推进/跳转（`evaluate_turn`） | • `build_turn_input`：注入本片 800 字正文 + 120 字后文 `lookahead` 提示<br>• `evaluate_turn`：只要回复合法，**100% 确定性返回 `Advance(prefetch=True)`**（零额外裁判 LLM 请求） | • `build_turn_input`：指令将教材揉成讲解对话，规定**核心公式/代码/题干放入 `NARR` 黑板**避免 TTS 念错，口语讲解后出题<br>• `evaluate_turn`：出题后 `Stay`；玩家答对返回 `Advance`，答错返回 `Stay` 留堂换例重讲；支持 `Jump` 复习 | • 开局注入模组总纲隐藏背景；玩家提交行动后 DM 依场景按需 `Jump(chunk_id)` 或调检索工具翻阅对应地点/NPC 切片<br>• 输入契约预留可选 `player_id / display_name` 以兼容多真人同回合攒批 |
| **4. `CompactionPolicy`<br>压缩策略** | 通过 `BeforeCompactContext` 注入总结必须保留的域内记忆 | 要求压缩摘要完整保留：**已登场人物标准名与外号/称呼映射、第一人称「我」身份、人物关系与主线进展** | 要求压缩摘要保留：**已掌握的核心概念清单、玩家答错或反复追问过的薄弱知识点** | 要求压缩摘要保留：**调查员当前状态、关键持有线索、已触发事件与 NPC 态度** |

> **远期多人联机安全边界（TRPG 备忘）**：
> 当前 `frontend_bridge_core/transport/mobile_access.py` 中的 `MobileAccessTransport` 会通过 URL 参数携带高权限宿主凭证 `shinsekai_bridge_token`（仅供房主本人手机使用）。未来若开放跨网络网友联机跑团，**严禁向外部访客分发 `shinsekai_bridge_token`**，必须独立提供绑定单端口与单会话作用域的低权限 `room_invite_token`（访客仅能接收当前舞台演出事件与以指定角色身份提交行动）。

---

## 4. 长篇小说上下文与跨段指代消解设计

### 4.1 放弃“全书梗概浓缩”，采用“原生多轮切片 + 达阈值自动压缩”

针对几十万字小说，核心设计原则是不在导入期用 LLM 把全书压缩成几十字节点要求，而是：

1. **原汁原味喂料**：将小说切成 ~800 字切片后，按顺序以 `source="chunk_feed"` 的内部消息追加进原生 `ConversationHistory`，由常规对话大模型逐片演译成标准 `dialog` JSON。
2. **达阈值自然压缩 + 近期原文无缝衔接**：
   - 每轮切片（约 800 字原文 + 对应 `dialog` JSON ≈ 2,000～2,500 tokens）顺次进入历史，按默认 `128k` 上下文与 `0.4` 压缩阈值估算，可连续演出约 20 轮（~1.6 万字）才触发一次 `CompactManager.auto_compact_if_needed()`。
   - 压缩触发时，早期历史在 `CompactionPolicy` 指导下提炼成包含**全人物别名映射与主线**的摘要，同时 `CompactManager` **完整保留最近 `recent_message_limit`（默认 20 条）消息（约最近 8,000 字的原文与已消解说话人的 `dialog`）**，跨压缩边界的代词指代与语气绝不断档。
3. **命中 Prefix KV Cache**：由于只向历史末尾追加新切片而不反复拼接/改写前文系统提示词或上下文块，前面几十轮消息前缀完全稳定，在主流 LLM 接口上可稳定命中前缀缓存，显著降低延迟与输入成本。

### 4.2 切口指代消解三保险

为彻底解决切分边界处的“他/她”指代丢失、先出引号后写说话人（倒装提示语）以及悬疑藏名问题，增加三道轻量防御：

1. **弹性引号保护切分**：目标切片长度为 800 字（允许弹性区间 500～1,300 字）。遇到空行/场景分隔线优先切分；若到达 800 字附近时仍处于未闭合引号内或连续对白段落中（上下相邻段均以引号开头），切分器自动向后顺延至该段连续对话结束后的叙述段再落刀。
2. **向后只读偷看窗（`lookahead`）**：喂给 LLM 当前切片 `chunk.text` 时，附带下一片开头约 120 字作为只读预览 `chunk.lookahead`，Prompt 明确标注 **“仅供确认末尾倒装署名与代词指代，严禁在本轮提前演出”**。
3. **悬疑角色 `？？？` 规范与不可编造约束**：Prompt 明确规定“忠实还原原文情节点与核心台词，不得提前剧透或编造后续剧情”；对于原文刻意隐瞒身份的初登场声音或黑影，统一输出 `character_name: "？？？"`（或原文称谓如 `"门外的男声"`），待演到揭晓段落再切换回标准名与绑定皮套。

### 4.3 核心数据模型与协议草案

#### A. 文档与切片模型（`core/document/models.py`）

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
    doc_id: str
    title: str
    source_type: Literal["txt", "pdf"]
    total_chars: int
    chapters: tuple[DocumentChapter, ...]
    chunks: tuple[DocumentChunk, ...]
```

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

#### C. 随分支与 `seq` 同步的状态快照表（`core/chat_history/sqlite_session_store.py`）

```sql
CREATE TABLE IF NOT EXISTS session_state_snapshots (
    branch_id TEXT NOT NULL DEFAULT 'main',
    up_to_seq INTEGER NOT NULL,
    namespace TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (branch_id, up_to_seq, namespace)
);
```

- 每次行为推进提交回合时，写入当前 `branch_id` 对应最新 `turn.seq` 的状态快照（如 `namespace = "novel_theater"`、`state_json = {"chunk_index": 12, "chapter_id": "ch-2"}`）。
- 用户执行回档 `truncate_to_seq` 或切换分支时，直接删除大于目标 `seq` 的快照行并恢复该时刻之前最新一条 `state_json`，实现对话历史、分支树与阅读进度的绝对原子同步。

#### D. 内部行为契约草案（Phase 1～3 位于 `application/session_behavior/protocol.py`）

```python
@dataclass(frozen=True, slots=True)
class InteractionPolicy:
    hide_input_layer: bool = False
    use_choice: bool = True
    use_stat: bool = False
    use_narration: bool = True
    playback_end_action: Literal["wait_user", "auto_advance"] = "wait_user"

@dataclass(frozen=True, slots=True)
class TurnAdvanceDecision:
    action: Literal["stay", "advance", "jump", "end"]
    next_chunk_index: int | None = None
    prefetch_next: bool = False

class SessionBehavior(Protocol):
    behavior_id: str

    def interaction_policy(self, state: Mapping[str, Any]) -> InteractionPolicy: ...

    def build_turn_input(
        self,
        *,
        chunk: DocumentChunk | None,
        state: Mapping[str, Any],
        actor_id: str = "",          # 预留字段：单人为空，多人联机时标识发言玩家
        display_name: str = "",      # 预留字段：玩家显示名
    ) -> str: ...

    def evaluate_turn(
        self,
        *,
        assistant_message: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> TurnAdvanceDecision: ...

    def compaction_instructions(self, state: Mapping[str, Any]) -> Sequence[str]: ...
```

---

## 5. 分阶段实施路线与模块清单

### Phase 1：补齐 4 项宿主共有底座原语

1. **无立绘 NPC 放行与演员皮套映射路由**
   - `core/messaging/dialog_output.py`：`has_valid_dialog_output()` 增加 `allow_unconfigured_speakers: bool = False` 参数（未配置角色放行 `sprite`/`vibe` 校验）。
   - `application/chat/presentation/handlers/dialog_media.py`：在 `CharacterMediaHandler` 接入会话级 `CastingMap`；优先匹配原始名/别名再 fallback 到 OpenCC 简繁转换；若说话人未绑定本地角色且允许无立绘 NPC，直接发出 `asset_id="-1"`、无音频的 `PresentationMessage`，不抛异常。
   - `application/chat/presentation/handlers/presentation.py`：确认无配置角色仅刷新对话框且不驱逐现有 3 个立绘槽；预留角色剪影状态元数据支持（供已绑定但暂隐去真名的 `？？？` 使用）。

2. **隐藏喂料来源 & 分支回档安全的状态快照槽**
   - `sdk/messages.py` & `core/chat_history/models.py`：确立 `source="chunk_feed"` 喂料消息来源；`is_real_user_turn_message()`、`render_messages_to_ui_history()` 与 `application/chat/history/replay.py` 跳过该内部来源，仅保留其参与 LLM 上下文与 `CompactManager` 摘要。
   - `core/chat_history/sqlite_session_store.py` & `application/chat/runtime/commands.py`：落地 `session_state_snapshots` 表及其读写/按 `seq` 截断/分支克隆方法；在 `_revert_history()` 与分支切换中联动恢复状态快照。

3. **可定制压缩指令**
   - `sdk/hooks.py`：`BeforeCompactContext` 增加 `extra_instructions: list[str] = field(default_factory=list)` 与 `add_instruction(text: str)` 方法（保持向后兼容）。
   - `ai/llm/compact_manager.py`：在 `dispatch_before_compact()` 之后将 `extra_instructions` 去重拼入 `_create_compact_prompt()`。

4. **舞台真实完播回调、无脏数据预取器与舞台交互策略**
   - `application/chat/runtime/turn_wiring.py` / `session.py` / 播放控制管线：当生成结束且 `dialog_queue` 与 `presentation_queue` 耗尽并完成最后一句音频/字幕等待时，发射受控的 `playback_idle` 信号。
   - **无脏数据预取器**：第 `N` 片开始播放时，基于 `ConversationHistory` 的只读快照副本异步生成第 `N+1` 片的 `dialog` 文本并暂存于内存缓冲槽（不调用 `add_message`、不写 `history.db`、不争抢 `tts_manager` 锁）；当收到 `advance-chunk` 时将第 `N+1` 片的 `chunk_feed` 与预取结果原子提交并推入媒体管线；跳章、回档或中断时立即作废缓冲槽并取消在途请求。
   - `frontend/src/features/chat-stage/`：会话快照下发 `stagePolicy`（`hideInputLayer`、`playbackEndAction`）；`InputLayer.tsx` 据此隐藏输入框；当 `playbackEndAction === "auto_advance"` 且用户点击最后一句（或 Auto 播放结束）时，自动下发 `advance-chunk` 命令（或无缝读取缓冲切换下一段）。

### Phase 2：构建共有文档摄取与切片模块（`core/document/`）

1. **`requirements-runtime-core.txt`**：引入轻量纯 Python PDF 解析依赖 `pypdf`（体积小、无 C++ 编译链负担，打包进 Tauri runtime 友好）。
2. **`core/document/ingest.py`**：
   - 复用 `core/knowledge/import_sources.py` 的 `_read_supported_text` 编码探测思路（UTF-8-SIG / UTF-16 / GB18030）；
   - 提取 PDF 逐页文本与目录书签（Outlines/TOC）；
   - 实现 **PDF 行尾硬回车断行合并预处理**（判定行尾非句末标点且下段非缩进/非章节标题时自动拼接，避免长行断裂影响语义与引号配对）；
   - 若检测到页数 > 0 但提取有效字符过少（纯扫描图片版 PDF），明确拦截并提示用户原因，不做静默空跑。
3. **`core/document/chunker.py`**：
   - 章节识别：优先 PDF 书签映射，否则按中英文常见章节标题正则切分，无显式标题时按约 5,000 字自动生成虚拟分节供目录导航；
   - ~800 字（500～1,300 字）弹性切片 + 引号/连续对话保护 + 120 字 `lookahead` 生成；
   - 提供 `ChunkRepository` 持久化（如落盘到会话目录或 `data/documents/<doc_id>/`）与 `get` / `next` / `first_of_chapter` / `search` 查询能力。

### Phase 3：内部 `SessionBehavior` 协议与「📖 小说剧场」MVP 闭环

1. **`application/session_behavior/`**：定义 `SessionBehavior` 协议、`InteractionPolicy`、`TurnAdvanceDecision`、`CastBinding` 与会话能力适配器（对接 `SessionCapability` / `TurnContextProvider`）。
2. **`application/novel_theater/`**：
   - **角色初筛服务**：导入后抽样前 3～5 个切片交由作者 LLM 提取主要人物 JSON（标准名、别名列表、性别/特征简述、是否第一人称「我」），并与本地角色库自动做同名/特征初步推荐；
   - **导演提示词模板（`ai/llm/template/`）**：沿用普通模板 `dialog` JSON 输出契约（默认开启 `useNarration`、`useEffect`/`useBgm`，强制 `useChoice=False`），注入忠实原文转译、禁止提前演出 `lookahead`、神秘人输出 `"？？？"` 等指令；
   - **跳章与进出场控制**：支持跳转到指定章节首片，清理内存预取槽后继续演出。
3. **Bridge 路由与前端 UI**：
   - **`frontend_bridge_core/routes/`**：新增小说上传/本地文件选择解析预览、人物提取、选角映射保存、小说剧场启动与跳章路由。
   - **`frontend/src/features/chat-workspace/ChatWorkspacePage.tsx`**：在新建会话弹窗（`normal` / `story` 并列）新增 `novel`（「小说剧场」）卡片，提供极简三步创建流程：**选 TXT/PDF 看目录 → 确认主角绑皮套（可一键全跳过走纯对话/默认配置）→ 开演**。
   - **`frontend/src/features/chat-stage/`**：为小说剧场模式提供顶部轻量「章节目录与进度（第 X 章 · m/n 段）」抽屉，支持点选跳章。

### Phase 4：第二样板验证与公开插件 `sdk/` 升格（后续规划）

1. **「🎓 Galgame 讲堂」内置验证**：复用 Phase 1～3 全部共有底座，仅实现讲堂行为策略（`pick_actors` 选 1～2 名老师/学伴；`hideInputLayer = False`、`useChoice = True`、`useStat = True`；`NARR` 充当黑板展示公式/代码避免 TTS 误读；出题后 `Stay`，答对 `Advance`，答错 `Stay` 换例重讲；压缩摘要保留已学概念与错题薄弱项）。
2. **正式升格进 `sdk/`**：待上述双模式跑通并收敛接口变更后，将稳定的行为契约抽象进 `sdk/` 并在 `sdk/register.py`（`PluginCapabilityRegistry`）增加行为模式注册入口，同步更新 [`PLUGIN_DEVELOPER_GUIDE.md`](PLUGIN_DEVELOPER_GUIDE.md) 供社区插件作者使用。

---

## 6. 风险与应对措施

| 风险点 | 潜在问题 | 防御设计 |
| --- | --- | --- |
| **OpenCC 简繁转换冲突** | `CharacterMediaHandler` 对未直接命中的角色名会跑 OpenCC 转换，可能导致繁体原名小说或特定用字映射失配 | 选角映射查表严格按 **「精确原名 → 别名表 → OpenCC 归一后名称」** 三级顺序执行，避免误转 |
| **PDF 排版硬回车与扫描件** | 排版 PDF 每 30 字自带 `\n` 导致句子碎裂、引号匹配失效；纯图扫描 PDF 提取为空文本 | `ingest.py` 内置行尾断行合并预处理；提取有效字符密度低于阈值时直接报错阻断并友好提示 |
| **预取并发竞争与脏数据** | 用户在预取进行中点击跳章、回档或退出会话，若预取结果晚到可能覆盖新位置；提前 TTS 会抢占当前台词合成锁 | 预取附带 `(doc_id, expected_chunk_index, generation_token)` 校验且只读快照运行，不落盘、不提前跑 TTS；位置变化时立即丢弃过期结果 |
| **超长篇目录与文件体积** | 导入数十 MB 的巨型 TXT 导致前端目录列表渲染卡顿或内存飙升 | 切片仓库独立存储于会话/文档目录，前端目录接口仅返回轻量 `chapters` 摘要元数据，不整本传给前端 |

---

## 7. 验证计划

| 阶段 | 验证内容与覆盖目标 | 工具 / 用例位置 |
| --- | --- | --- |
| **架构边界回归** | 验证 `sdk/`、`core/document/`、`ai/`、`application/` 未引入任何逆向或越界导入 | `pytest test/unit/architecture/` |
| **文档与切片单测** | 覆盖 UTF-8/UTF-16/GB18030 TXT、带书签与无书签 PDF、硬回车合并、未闭合引号顺延、`lookahead` 长度与扫描版报错 | 新增 `test/unit/core/document/` |
| **NPC 与选角映射单测** | 覆盖 `allow_unconfigured_speakers` 校验放行、别名/OpenCC 匹配顺序、未绑定路人纯文本 `PresentationMessage` 输出与不占立绘槽 | 新增 `test/unit/application/test_casting_and_npc.py` |
| **推进、预取与回档单测** | 覆盖 `source="chunk_feed"` 不进 UI 历史与回放、预取不污染未提交历史、跳章作废旧预取、回档同步恢复 `session_state_snapshots`、`BeforeCompactContext` 自定义指令注入 | 新增 `test/unit/application/test_session_behavior_runtime.py` |
| **前端类型与组件测试** | 覆盖新建会话「小说剧场」流程、选角映射表、`InputLayer` 隐藏逻辑及舞台章节目录抽屉交互 | `pnpm lint:types`、`pnpm test` |
