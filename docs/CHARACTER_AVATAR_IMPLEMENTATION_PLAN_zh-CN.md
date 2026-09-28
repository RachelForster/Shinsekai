Shinsekai 多形态人物形象实现方案（简化版）

日期：2026-09-27。本文替换此前的统一演出预设方案，按“一个角色选择一种形象，各类型独立编号、独立标注”设计。目前仅完成方案，未实施运行代码。

本文说明需求、资源结构与用户操作；adapter 的完整签名、前后端命令、能力标志和并行协作边界以 [高层设计与协作契约](CHARACTER_AVATAR_HIGH_LEVEL_DESIGN_zh-CN.md) 为准。

核心是复用 Character 和 Sprite：人物仍以 character_name 唯一识别（对应现有 Character.name），角色卡在 `static` 与已注册的模型格式（首期 l2d、vrm）之间选择；每种类型有自己的资源列表和 emotion_tags。运行时只使用当前选中类型的列表。静态的 3 号与 L2D 的 3 号没有对应关系，也不要求它们表达相同情绪。

关键复用决策：**格式是数据而不是字段**。Character 只加 `avatar_type` 和一个 `avatars` 键控映射，每个格式不再占一个字段；新增格式 = 一个目录 + 一行注册（见第 8 节配方）。首期 l2d / vrm 只是“同一配方跑两次”的两个实例。

1. 最小的数据改动

角色顶层只增加两个字段：

| 字段 | 用途 |
|---|---|
| avatar_type | 当前选择：static 或已注册格式 id（首期 l2d / vrm）；旧角色默认 static |
| avatars | 格式 id → ModelSprites（model_path + 该格式自己的 sprites、emotion_tags） |

原有 name、sprite_prefix、sprites、emotion_tags、sprite_scale、角色设定和语音配置继续使用。根级 sprites / emotion_tags 始终属于 static；不把当前类型的数据来回复制到根级，也不新增 static 容器。sprite_prefix 继续只是现有资源目录名，人物查找仍使用 name。

动态类型使用同一种小结构；列表条目直接复用现有 Sprite：

```ts
type AvatarFormatId = string;

interface ModelSprites {
  model_path: string;
  sprites: Sprite[];
  emotion_tags: string;
}

// 在现有 Character 上增加这两个字段，其他字段沿用。
interface CharacterAvatarFields {
  avatar_type: AvatarFormatId;
  avatars: Record<AvatarFormatId, ModelSprites>;
}
```

新增字段不用问号或 Optional。后端加载旧角色时通过默认值补齐：avatar_type 为 static，avatars 为空映射。未导入模型的格式在角色卡中显示“未配置”，不能直接启用。不建立额外的版本迁移框架。

配置文件里出现本版本不认识的格式 id（未来版本保存）时，加载保留该键、UI 标记“不可用”、保存回写不丢弃；`avatar_type` 指向未知 id 时显示不可用占位并保留选择，用户可以切回 static；不自动套用静态同编号资源。这是向前 / 向后兼容的固定行为，不是格式实现各自决定。

配置片段如下，其他已有角色字段在示例中省略展示：

```yaml
name: Alice
avatar_type: l2d

# 原静态配置，完全保留
sprites:
  - path: assets/sprites/alice/smile.png
  - path: assets/sprites/alice/angry.png
emotion_tags: |
  立绘 1：微笑
  立绘 2：生气

# 每种格式在 avatars 下占一个键，键名即格式 id
avatars:
  l2d:
    model_path: assets/l2d/alice/alice.model3.json
    sprites:
      - path: assets/l2d/alice/states/look_away.json
      - path: assets/l2d/alice/states/nod.json
    emotion_tags: |
      立绘 1：侧头，移开视线
      立绘 2：点头，赞同
  vrm:
    model_path: assets/vrm/alice/alice.vrm
    sprites:
      - path: assets/vrm/alice/states/greeting.json
    emotion_tags: |
      立绘 1：挥手，打招呼
```

标签文本暂时沿用“立绘 N：”格式，以直接复用 tag_contents / numbered_tags 和旧编号规则；界面可以显示“L2D 资源 N”“VRM 资源 N”。既有 Sprite 的 voice_path / voice_text / voice_type 仍可使用，示例未设置时沿用原有语音行为，不新增语音绑定系统。

不增加人物、模型、动作条目的业务 ID；不建立跨类型 target 映射、统一预设目录、编号保留表或 tombstone。模型库本身的参数名、骨骼名，以及系统已有的 playbackId 等播放标识继续按原用途使用。

2. 动态资源就是“保存好的表情动作条目”

静态 Sprite.path 指向图片；L2D / VRM 的 Sprite.path 指向应用保存的状态 JSON。模型路径每种格式只保存一次，状态文件只记录这个模型应该怎样表现。当前每个角色每种格式配置一个模型，不提前设计多模型版本管理。

L2D 状态文件示例：

```json
{
  "parameters": {"ParamAngleX": 12, "ParamEyeBallX": -0.3},
  "expressions": ["expressions/smile.exp3.json"],
  "motion": "motions/nod.motion3.json"
}
```

VRM 状态文件示例：

```json
{
  "expressions": {"happy": 0.7},
  "bones": {"head": [0, 0, 0, 1]},
  "motion": "motions/greeting.vrma"
}
```

这些是编辑器 / 程序保存的内部资源文件，不是新增的 LLM 输出 schema。每种文件的字段均必填：没有表情或骨骼调整使用空集合，没有动作使用空字符串。状态结构对共享层不透明，由各格式模块在自己的目录里定义（L2DState、VrmState 等）并校验；平台层只看到 `unknown`（前端）与 `object`（后端）。模型类型由所属 `avatars` 键确定，不给每个条目重复增加类型和模型路径。

VRM bones 使用规范人形骨骼名称与相对父骨骼的局部旋转四元数；编辑器通过加载器的人形骨骼接口读写。资源内的表情和动作路径相对 model_path 所在目录解析，并限制在已导入目录内。示例参数、表情和动作只有模型实际存在时才能保存；缺少绑定的模型不能凭空生成动作。

编辑器流程：

1. 在角色卡选择类型，首次使用时导入模型。
2. 预览模型，调节真实参数、表情权重、姿态，或选择模型已有动作。
3. 点击“保存为新资源”，写入状态 JSON，并向该类型 sprites 追加一项。
4. 为新条目填写 tag；也可以覆盖当前条目，修改后保存。
5. 资源按当前列表从 1 编号，上传、删除、重新编号沿用现有立绘规则。

文件名只表示文件路径，不是新增业务 ID，也不要求删除资源后重命名剩余文件。列表位置决定编号，标签行跟着列表同步处理。缩略图从预览生成缓存，不要求再给每个 Sprite 添加 thumbnail 字段。

保存的是用户编辑的基础状态，不把某一帧的随机眨眼、说话嘴型或物理抖动一起保存。编辑时暂停这些自动驱动；状态切换先恢复基础值，再应用保存的参数，防止上一个状态残留。涉及同一参数 / 骨骼的静态姿态和动作需有固定覆盖顺序，基础版可以直接提示冲突并让用户选择保留哪一项。

更换模型时，原状态不保证适用。保留旧文件供用户处理，校验参数和路径，只有当前模型兼容的条目才加入候选；不自动把旧表情映射到新模型，更不映射到其他形象类型。临时排除无效候选时保留原列表位置对应的编号，不能过滤后重新枚举，导致“3 号”意外指向另一项；真正删除时才按现有规则重新编号并同步标签。

3. 最大程度复用现在的选择、标注和语音流程

只增加一个统一取当前类型资源的入口，代替分散读取 character.sprites / character.emotion_tags：

```python
def get_character_assets(character, avatar_type: str) -> ModelSprites:
    if avatar_type == "static":
        return ModelSprites(
            model_path="",
            sprites=character.sprites,
            emotion_tags=character.emotion_tags,
        )
    return character.avatars[avatar_type]  # 边界已校验，未知 id 不会到这里
```

这个入口返回现有列表和标签的视图，不复制或改写角色数据。对应保存入口按同一 avatar_type 写回 `avatars` 对应键；异步导入 / AI 标注提交时记录 name 和 avatar_type，即使用户切换编辑页，也只写回任务启动时的类型。

| 当前模块 | 需要的改动 |
|---|---|
| config/schema.py、character_config.py | 加入两个字段（avatar_type、avatars 映射）和完整默认值；旧角色直接可用 |
| config/character_manager.py | 动态资源操作沿用列表增删和标签同步逻辑；静态删除只删除静态文件 |
| config/character_assets.py | 新增：`get_character_assets` 及按类型的写回小工具 |
| sdk/adapters/avatar.py、registry.py | 新增：ModelAssetAdapter、能力标志、按 id 注册 / 查找 |
| core/media/avatar/{l2d,vrm,...}.py | 各格式的 inspect / parse_state / state_files |
| dialog_media/resolver/sprite.py | 从当前类型构造候选、解析 path，并从同一类型读取条目语音 |
| dialog_media/catalogs.py | 索引当前类型资源；scope 区分角色名与类型，防止多套 tags 混检 |
| ai/llm/template/dialog/sections/character.py | 提供当前类型的资源数量和 emotion_tags |
| application/media/auto_annotation.py | 静态仍看图片；动态按能力标志看状态预览，再写入对应类型 emotion_tags |
| application/characters/management.py、tools/file_util.py | 保存 / 导入导出完整角色，复制动态模型依赖和状态文件 |

现有 AssetCandidate、AssetResolver、direct / semantic lookup、ResolvedSpriteAsset、TtsGenerationRequest 和 TTS 生成策略继续使用。动态状态 JSON 也是一个有 path 的资源，不需要先拆成新的演出对象和语音对象。尤其要修改 SpriteAssetResolver._read_voice_config：不能动态资源选中第 2 项，却仍然去根级静态 sprites[1] 读取音频；动态条目从 `avatars[avatar_type].sprites` 对应项读取。

运行链路就是：

```text
character_name 查找角色
  → 读取本次聊天选择的 avatar_type
  → get_character_assets 取这一类型的 sprites 和 emotion_tags
  → 现有编号 / vibe 查找
  → 选中这一列表的第 N 项
  → static 显示图片；动态格式按注册表加载该状态
```

LLM 输出 schema、别名、必填性、外层包络和插件扩展全部保持现状。编号模式仍输出 sprite，内部仍使用 asset_id；语义模式仍输出自然语言 vibe，检索无结果时仍按当前实现回退编号。不要求 LLM 输出模型类型、参数或动作字段。

例如 LLM 仍输出既有消息条目：

```json
{
  "character_name": "Alice",
  "speech": "嗯，我同意。",
  "sprite": 2
}
```

角色卡选择 l2d 时，它选的是 avatars.l2d.sprites[1]，提示词也只提供 l2d 的标签。选择 static 时，它选的是根级 sprites[1]，提示词提供静态标签。它们无需表达相同情绪；LLM 根据各自的实际标签重新选择编号。语义模式也只检索当前类型。

首版让角色卡的选择在下一次启动聊天时生效，本次会话保持启动时选中的类型和资源列表，避免生成途中切换后把同一个数字解释为另一套资源。资源选择、提示词和条目语音都读取这份会话内列表，不能又按修改后的 YAML 下标读取另一个条目的语音。没有复杂目录版本机制；后续若需要聊天中立即切换，可在当前回复结束、清空待播内容并刷新提示词之后整体切换。切类型后以新模型默认状态启动，不跨类型重放历史资源编号；原聊天文字保留。

4. 前端只扩展角色显示方式

复用 SpriteLayer 的槽位、缩放、位移和发言高亮，里面按 avatar_type 选择 img 或注册表里的模型组件。三个角色可以分别使用不同类型同场显示，但同一个角色当前只显示角色卡选中的一种。

槽位与格式无关：`slot` 仍是 character → 0/1/2 的舞台位置（后端 `_get_or_create_sprite_slot` LRU，前端 `upsertChatStageSprite` 稳定槽位），`<figure>` 上的轴心、偏移、缩放、发言高亮全部照旧。改造点只有一处——`SpriteLayer` 里硬编码的 `<img>` 换成 `CharacterVisual`：static 分支走原 `<img>`，模型格式分支按注册表把 module 挂进容器。adapter 通过 `resize(width, height)` 拿到槽位盒子布局 CSS 尺寸（不乘外层 transform）并在内部 contain 适配，不拥有 slot / x / y / scale。

继续使用现有 sprite.show / sprite.remove，不增加新的事件族。为使前端知道如何加载，在 sprite.show 及其舞台快照中增加两个必要字段：avatarType、modelUrl（对应 Character.avatar_type）；原 url 在静态模式指向图片，在动态模式指向状态 JSON。

新增两个字段在规范化后的事件类型中必填。静态发送 avatarType=static、modelUrl=""；既有旧事件由入口补齐这两个静态值。复用原 characterName、seq、slot、scale 和音频 playbackId，不新增演出身份体系或协议版本框架。LLM 输出与这些内部 UI 字段无关。

前端接口只覆盖模型创建、状态应用 / 读取、嘴型输入、尺寸变化和销毁，完整定义见 [高层设计](CHARACTER_AVATAR_HIGH_LEVEL_DESIGN_zh-CN.md)。每个格式实现相同的生命周期与各自的编辑控件，并导出自己的 `adapters/<format>/format.ts` 轻量描述符，由应用入口注册；load() 动态加载 SDK 和实现；静态继续使用现有 img。控制参数扫描和编辑由各自适配器提供，不先建立通用能力数据库。只有切换模型才重载，切换状态只应用参数 / 动作。卸载时取消动画循环并释放 GPU 资源；连续异步切状态以最后一次请求为准。

沿用现有资源鉴权与文件服务，为各模型格式的相对依赖提供包目录寻址或加载器 URL 重写；只允许访问导入包范围。状态 JSON 不送入图片缩略图接口，交给模型预览生成截图缓存。

模型加载失败时显示该类型的错误 / 占位，允许用户切回 static；不拿“同编号静态图”冒充这个动态表情，也不创建跨类型的自动标签映射。未知格式 id 渲染“不可用”占位。

5. 口型和眨眼

基础口型直接接在已有 SoundPlayer：分析实际播放的 voice 音量，平滑后驱动当前 characterName 对应的模型。把 tts.play 中现有的 characterName 保留到语音队列项，避免队列里的旧语音驱动最新对白角色。BGM 和音效不参与嘴型分析。**只有当前模型的 `session.capabilities.mouth` 为真才接开合量**；不支持的格式照常显示但不驱动嘴型。

继续使用现有 playbackId、rendererId、分句状态与播放回执。实际开始播放才动嘴，暂停、缓冲、跳过、结束、失败时恢复嘴部基础状态。同一句后续音频片段不重新发起整个肢体动作；沿用现有分句处理判断首段，不新增动作编号或时间轴 ID。

L2D 使用模型的嘴眼参数，VRM 使用已有嘴型 / 眨眼 expression；自动眨眼在各适配器中实现（由 `session.capabilities.blink` 决定是否启用）。已有表情或动作控制闭眼时，应暂停 / 混合自动眨眼；嘴型与微笑等表情按模型规则混合，不简单互相覆盖。人工保存状态时排除自动驱动参数。

基础版先做音量口型；精细音素口型后续再加。没有嘴眼绑定时照常显示模型，并在角色卡说明该能力不可用。Python 和 React state 不参与逐帧参数传输。

6. LLM 自动设计与独立标注

两种能力都只作用于用户正在编辑的那一类型：

- 已有资源自动标注：加载该状态，采样截图；有动作时取多个时间点。复用当前视觉标注能力，写入这一类型的 emotion_tags。不会改另一类型标签。
- 自动设计新资源：读取当前模型实际可用的参数、表情和动作，结合受限的点头 / 视线 / 歪头模板构造候选；LLM 沿用既有编号 / vibe 契约选择符合描述的候选，程序保存成与手动编辑相同的状态 JSON，追加到当前 sprites，再自动标注。

采样能力由实例的 `session.capabilities.sampling` 声明：`none` 表示该格式不提供动态视觉标注，不声称完成；`single` / `multi` 决定采样帧数。不修改 LLM 输出 schema，也不把新 JSON 隐藏在 speech 或 effect 中。AI 和人工最终操作同一种状态文件；用户可以继续手动调整 AI 生成的条目并保存。新文件通过范围、参数存在性和预览检查后入库；不覆盖已编辑资源。

这一版可以组合模型已有表情、动作和有界参数模板。模型不存在的形变、复杂走路 / 跳舞动作不能靠文本 LLM 凭空产生；需要另接动作生成服务时再扩展。无论如何，不要求这些表现与 static 的表情集合一致。

7. 总体文件架构：在原模块接入，少建新层

下面只列本功能相关文件。带“新增”的文件按实现需要建立，不创建空壳 Service、Repository 或独立 SDK 契约包。遵守现有 [项目依赖边界](PROJECT_STRUCTURE.md)。注意“每个格式一个目录 + 一行注册”是稳定形态，新增格式只往 `core/media/avatar/` 与 `adapters/` 下加目录，不动共享文件。

```text
Shinsekai/
├─ config/
│  ├─ schema.py                         两个字段与 ModelSprites
│  ├─ character_config.py               旧角色配置 / 导入导出适配
│  ├─ character_manager.py              按类型读写资源与标签
│  └─ character_assets.py               新增：统一资源选择与写回小工具
├─ core/media/
│  ├─ asset_tags.py                     复用原编号标签工具
│  └─ avatar/                          新增：注册表及格式 adapter
│     ├─ registry.py                    id → adapter 注册 / 查找
│     ├─ l2d.py                         L2D 资源检查、状态解析（注册一行）
│     └─ vrm.py                         VRM 资源检查、状态解析（注册一行）
├─ sdk/adapters/avatar.py              共享文件能力 ABC 与能力声明
├─ application/
│  ├─ characters/management.py          复用角色保存与资源操作
│  ├─ characters/model_assets.py        新增：模型导入、状态保存、预览采样用例
│  ├─ characters/generate_model_states.py 新增：AI 候选选择、保存与标注流程
│  ├─ media/auto_annotation.py          扩展到当前类型的预览标注（按能力标志）
│  ├─ chat/dialog_media/catalogs.py     当前类型的候选和检索 scope
│  ├─ chat/dialog_media/resolver/sprite.py 当前类型资源与语音解析
│  ├─ chat/ui_updates.py                原 sprite.show 增加加载类型和模型地址
│  └─ runtime/event_sink.py             保存对应舞台状态
├─ ai/llm/template/dialog/sections/
│  └─ character.py                     当前类型数量和标签；输出 schema 不动
├─ frontend_bridge_core/
│  ├─ routes/character_routes.py        在现有角色路由接入模型操作
│  ├─ routes/file_transport.py          模型子资源寻址和原有鉴权
│  └─ chat_stream.py                    原媒体事件路径处理适配
├─ tools/file_util.py                  .char 打包模型及其依赖、状态、语音
└─ frontend/src/
   ├─ app/avatarFormats.ts              启动时注册随构建交付的 format.ts 描述符
   ├─ shared/platform/types.ts          Character 和内部舞台类型的小幅扩展
   ├─ shared/platform/httpPlatform.ts   角色模型操作 API
   ├─ entities/character-visual/        新增：聊天和预览共用
   │  ├─ contracts.ts / registry.ts     共享实例接口与 id → 模块注册
   │  ├─ CharacterVisual.tsx            按类型选择显示组件
   │  ├─ adapters/l2d/                  L2D 描述符、加载、状态、嘴眼和参数编辑
   │  └─ adapters/vrm/                  VRM 描述符、加载、状态、嘴眼和姿态编辑
   ├─ features/character-editor/
   │  ├─ CharacterEditorPage.tsx        增加形象类型选择（读注册表）
   │  ├─ CharacterSpritesSection.tsx   复用画廊、编号、标签、条目语音
   │  ├─ SpriteTagsDialog.tsx           对选中类型进行标签编辑
   │  └─ ModelStateEditor.tsx           新增：模型参数调整与保存
   └─ features/chat-stage/
      ├─ components/StageLayers.tsx    现有布局内嵌 CharacterVisual
      ├─ state/                       保留原 reducer，补充类型和模型地址
      └─ audio/soundPlayer.ts          语音所属角色和音量分析（按能力标志路由嘴型）
```

Python 继续负责文件、配置、LLM 和聊天编排；前端负责模型加载、渲染和参数预览。新功能直接复用现有 platform / bridge / 任务机制。模型配置留在角色卡内，实际文件存入对应类型目录，沿用 sprite_prefix 组织，不另建人物身份目录。

后端只需要少量新增用例，接口用角色名、格式 id 和现有列表下标定位：

```python
def import_character_model(name, avatar_type, source_path): ...
def save_model_state(name, avatar_type, model_path, sprite_index, path, state, tags): ...
def generate_model_states(name, avatar_type, description): ...
def annotate_model_sprites(name, avatar_type): ...
```

sprite_index 沿用内部从 0 开始的列表下标；保存时 -1 表示追加且 path 为空，其他值表示覆盖已有条目。model_path 与 path 复用编辑时已加载的字段，用来检查模型和下标是否仍指向原对象，不增加持久化身份字段。LLM 和界面显示的资源编号仍从 1 开始，只在入口做一次转换。模型导入、保存、生成需要新请求时，直接加在现有 character 路由；标签、语音等能复用原操作的继续复用，内部补充明确的目标类型（格式 id）。

8. 分步骤 / PR 大纲与“加格式”配方

本 PR 0 先落注册与宿主 API 基础，不包含真实 renderer、模型导入 / 保存 / 导出与 AI 流程；已实现和待接通范围见 [高层设计](CHARACTER_AVATAR_HIGH_LEVEL_DESIGN_zh-CN.md)。后续首版收敛成四个实现 PR。每个 PR 自带对应测试和 .char 往返检查，首个发布包含前四个；不再先搭建完整的统一演出平台。

“新增一个格式”是固定配方，任何格式（gltf、spine、live3d……）都照此办理：

```
新增格式 X：
  后端  core/media/avatar/x.py       实现 ModelAssetAdapter（format_id、capabilities、inspect/parse_state/state_files）
  前端  entities/character-visual/adapters/x/  实现 AvatarModule<S,C> 与 Editor（含自己的 S/C、fixtures）
  注册  后端 registry.register_adapter(...) 一行；前端导出 adapters/x/format.ts，由应用启动入口统一注册
  测试  双方 fixtures / tests（接受与拒绝边界、资源释放、.char 往返）
  不改  Character schema、get_character_assets、编号/标签/语音、事件、命令、LLM、共享 UI
```

| PR | 主要内容 | 验收 |
|---|---|---|
| 1 / A：共享基础 | 两个字段、默认值、统一取资源入口、角色卡选择、tags / 提示词 / 语音查找、adapter 契约、注册表、能力标志、平台命令、媒体寻址、舞台字段与语音桥 | 旧角色仍为 static；不同类型编号和标签互不影响；LLM schema 原样；静态回归和 adapter 测试替身通过；只加一个测试替身格式即可跑通注册、导入 / 保存 / 选中 / 应用 / 导出 |
| 2 / B：Live2D 与手动状态编辑 | L2D 后端文件 adapter、前端实例 / Editor、状态 fixtures、SDK 依赖和注册；复用基础的导入 / 保存 / 语音能力 | 手调保存为第 N 项后，LLM 可选中；动作表情切换不重载模型；停止语音收口；模型包可导入导出 |
| 3 / C：VRM 与手动状态编辑 | VRM 后端文件 adapter、前端实例 / Editor、VRMA、状态 fixtures、渲染依赖和注册 | 与 L2D 无实现依赖；各自选各自的编号；VRM 表情与嘴眼可同时工作 |
| 4：AI 自动设计和标注 | 当前模型候选、AI 选择、保存新条目、预览采样（按能力标志）、自动 tags、继续手动编辑 | 只操作指定类型；不会生成不存在的参数；标注失败保留成功项；静态标签不受影响 |

依赖顺序：1 →（2 与 3 并行）→ 4，对应高层设计的 A →（B 与 C）→ D。共享基础先落契约、注册表与接入点，两个格式独立开发自己的目录；每种格式先用一个真实模型跑通显示与嘴眼，再扩展编辑功能。每次修改共享音频、资源导入或角色保存时，回归现有静态行为。

Blender 放到后续独立 PR：先支持 Blender 导出的 VRM；需要通用 GLB 时按“加格式”配方添加 gltf 类型和对应 ModelSprites，结构完全一样，不碰 Character 与共享代码。直接导入 .blend 则是导入阶段调用 Blender 导出，运行时仍加载导出文件，不给 Character 增加 Blender 工程元数据。

需要重点防止的几个问题：动态标签误写静态标签；动态条目读取了静态同编号语音；删图时误删整个模型目录；模型包导出漏纹理 / 动作；异步编辑或标注写回了切换后的类型；TTS 排队时嘴型跟错角色；未知格式 id 被静默丢弃或在旧版本崩溃。

9. 可行性依据与边界

Live2D 使用官方 Cubism SDK for Web，已有 [口型控制](https://docs.live2d.com/en/cubism-sdk-manual/lipsync/) 和 [自动眨眼](https://docs.live2d.com/en/cubism-sdk-manual/autoeyeblink/)；VRM 可以使用 [three-vrm](https://github.com/pixiv/three-vrm) 和 [VRMA](https://vrm.dev/en/vrma/)。状态编辑只是把加载器支持的参数 / 姿态保存下来，再按编号读取。

模型必须有相应绑定，不能保证每个文件都有嘴型、眨眼或肢体动作；能力标志如实声明，共享层据此降级而不是假设。Live2D 用户模型导入与 SDK 分发在接入时核对 [官方发行许可](https://www.live2d.com/en/sdk/license/)。Blender 源工程并非任意内容都能无损转换；以导出的模型实际能力为准。
