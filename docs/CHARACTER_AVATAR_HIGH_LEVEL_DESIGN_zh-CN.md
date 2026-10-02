Shinsekai 多形态角色：高层设计与协作契约

状态：本 PR 交付 PR 0 共享 API 基础与设计契约，不宣称运行时已支持 L2D / VRM。需求与示例见 [实现方案](CHARACTER_AVATAR_IMPLEMENTATION_PLAN_zh-CN.md)，目录依赖遵守 [项目结构](PROJECT_STRUCTURE.md)。本文确定 adapter、前后端边界和协作接口；具体 SDK 参数处理由各格式实现维护。

设计原则：角色负责选择使用哪套资源，资源列表负责编号和标签，格式 adapter 负责解释某种格式。共享层理解“选择第几项”，不理解“这个参数怎样让角色微笑”。

本次已实现：Character 的两个字段与旧配置默认值、资源选择函数、SDK / 宿主注册、前端描述符启动入口与懒加载、模型宿主生命周期、sprite.show 元数据和静态舞台兼容。测试使用替身格式，仓库尚无真实模型 renderer。

PR A 仍需接通角色卡类型选择及保存 / .char 往返、提示词与语义索引 / 条目语音的当前类型路由、受控模型文件服务、语音驱动、聊天快照 restore 与首段 play 的区分。模型 JSON / 二进制依赖不得通过全局放宽原媒体接口扩展名来开放；按导入后的包范围授权。PR B / C 再加入真实格式及编辑器，PR D 完成 AI 流程。下文是这些 PR 的目标契约，不能把 SDK 注册成功视为完整格式可用。


本文的复用目标很具体：**新增一个立绘 / 模型格式，只新增格式目录并接入既定注册入口；不改 Character 数据模型、不改取资源入口、不改编号 / 标签 / 语音、不改事件与命令。** 下面第 0 节说明这套可复用结构，其余各节都在同一结构下展开。

0. 可复用核心：一个注册表 + 一个键控映射

旧思路按格式加字段（l2d、vrm 各占 Character 一个字段、AvatarType 枚举加一个值、StateByType 加一种状态），每加一个格式要改十处共享代码。本文改为四点：

- 格式 id 是开放字符串；`static` 是内置保留 id，不在动态映射里。
- Character 只存两个字段：`avatar_type`（当前选择）和 `avatars`（格式 id → 该格式资源）。不再为每个格式新增字段。
- 前后端各有一个注册表：格式 id → adapter / 渲染编辑模块。注册表是唯一“知道有哪些格式”的地方。
- 状态文件对共享层不透明（`unknown` / `dict`），只有该格式的 adapter 校验并解释。

因此新增一个格式（例如 `gltf`）的完整清单是：

1. 后端 `core/media/avatar/gltf.py`：实现 `ModelAssetAdapter`，注册一行。
2. 前端 `modules/character-visual/adapters/gltf/`：实现 `AvatarModule` 与 Editor，导出轻量 `format.ts` 描述符，由应用启动入口统一注册。
3. 各自 fixtures / tests。

**不修改**：Character schema、`get_character_assets`、编号 / 标签 / 语音查找、舞台事件、命令路由、LLM schema、共享画廊 / 标签 / 语音 UI。

因为共享层不感知具体格式，它改用**能力标志**（嘴型、眨眼、动作、采样）而不是格式名来决定行为。格式多了之后，新增能力标志只影响用到该能力的共享点，不影响已有格式。

1. 数据契约：键控映射 + 开放格式 id

- 人物唯一标识仍是 Character.name，对外沿用 character_name / 现有请求的 name，不引入人物或模型业务 ID。
- Character 只增加 `avatar_type`、`avatars` 两个字段；`static` 继续使用根级 sprites / emotion_tags，不进入 `avatars` 映射。每个动态格式在 `avatars` 中持有一个 `model_path` 和自己的 sprites / emotion_tags。
- Sprite 保持现有结构。静态 path 是图片，动态 path 是状态文件；条目语音继续用 voice_path / voice_text / voice_type。
- 各类型独立编号、独立标注。编号由列表位置计算，不建立跨类型语义映射。
- LLM 输出 schema、编号 / vibe 选择顺序和插件字段规则保持不变。新接口的字段均必填；已建立但未配置模型的格式在 `avatars` 中保留 `model_path=""`、`sprites=[]`、`emotion_tags=""` 的空值，旧角色在配置入口补齐默认值。
- 当前会话使用启动时选定的类型和资源列表；编辑角色卡影响下次启动。首版不实现中途换类型的会话重编排。

共享数据契约（Sprite 使用现有定义）：

```ts
export type AvatarFormatId = string;
export const STATIC_AVATAR_TYPE = "static" as const;

export interface ModelSprites {
  model_path: string;
  sprites: Sprite[];
  emotion_tags: string;
}

export interface CharacterAvatarFields {
  avatar_type: AvatarFormatId;                // "static" 或已注册格式 id
  avatars: Record<AvatarFormatId, ModelSprites>; // 格式 id → 该格式资源
}
```

```python
# config/schema.py（增量）
class ModelSprites(BaseModel):
    model_path: str = ""
    sprites: List[Sprite] = Field(default_factory=list)
    emotion_tags: str = ""

class Character(BaseModel):
    ...
    avatar_type: str = "static"
    avatars: Dict[str, ModelSprites] = Field(default_factory=dict)
```

`model_path` 是普通字符串（未配置时为空；导入前文件可能尚不存在），动态条目的 `Sprite.path` 继续沿用 `FilePath`（指向已存在的状态 JSON）。

唯一的资源选择函数为 `get_character_assets(character, avatar_type)`。`static` 返回根级列表及空 model_path，动态类型按 id 查 `avatars`：

```python
def get_character_assets(character, avatar_type: str) -> ModelSprites:
    if avatar_type == "static":
        return ModelSprites(
            model_path="",
            sprites=character.sprites,
            emotion_tags=character.emotion_tags,
        )
    return character.avatars[avatar_type]  # 边界已校验，未知 id 不会到达这里
```

提示词、语义索引、资源解析、条目语音、标签编辑全部经过这个入口。写操作由现有 CharacterUseCase / character manager 按 `avatar_type` 更新 `avatars` 对应项，不建立第二个持久化入口。

未知格式的向前 / 向后兼容是复用的一部分，必须明确：

- 配置文件里出现当前版本不认识的格式 id（未来版本保存的配置）时，**保留不丢弃**，加载后标记“不可用”，在 UI 中不可选择；保存回写时原样保留该键，不做静默删除。
- `avatar_type` 指向未知 id 时，显示“不可用”占位并保留选择，允许用户切回 static；不能把动态编号套到静态列表。
- 格式 id 统一 trim + lowercase；static 保留、空键和规范化后的重复键报错。配置加载保留未知格式的数据，命令入口另查注册状态及该角色是否配置了对应资源，不将“注册过”当成“已导入”。

编号模式把现有 sprite / asset_id 解析为当前列表的第 N 项；语义模式只检索当前类型的 tags。索引 scope 使用现有角色名与类型组成，例如 `sprite:Alice:l2d`，仅是检索分区，不是新业务身份。无效条目可以从候选中排除，但保留原列表下标对应的编号；真正删除时仍按现有规则重新编号。

2. 后端格式注册表与 adapter 边界

| 边界 | 共享代码负责 | 格式 adapter 负责 |
|---|---|---|
| 后端模型文件 | 鉴权、导入暂存、任务、文件提交、角色配置更新、编号与标签、角色包 | 找到模型入口、列出依赖、解析状态结构与文件引用 |
| 前端模型实例 | DOM 容器、类型分发、资源获取、请求取消、舞台布局、语音路由、保存与标签 UI | SDK 加载、渲染、状态应用、嘴眼混合、参数控件和资源释放 |

static 继续使用原图片实现；只有动态格式实现模型 adapter。注册表按 id 索引，**新增格式加一行注册**，不建立插件发现、全局模型管理器或通用参数语言。

后端 adapter 是无角色、无会话状态的文件能力。公共 ABC 与数据类型从 `sdk.adapters` 导出（实现见 [SDK 契约](../sdk/adapters/avatar.py)），内置实现放在 `core/media/avatar/`。这些类型不写入 Character，也不新增 manifest；注册表可以复用无状态 adapter 实例：

```python
from dataclasses import dataclass
from pathlib import Path
from abc import ABC, abstractmethod
from typing import ClassVar

@dataclass(frozen=True)
class ModelFiles:
    entry: Path
    files: tuple[Path, ...]

@dataclass(frozen=True)
class ModelCapabilities:
    mouth: bool = False       # 语音音量可驱动嘴型
    blink: bool = False       # 支持自动眨眼
    motion: bool = False      # 支持一次性动作
    sampling: str = "none"    # none | single | multi（预览采样）

class ModelAssetAdapter(ABC):
    format_id: ClassVar[str] = ""
    capabilities: ClassVar[ModelCapabilities] = ModelCapabilities()

    @abstractmethod
    def inspect(self, source: Path) -> ModelFiles:
        """识别一个模型入口，并列出导入时需要的完整依赖。"""
        ...

    @abstractmethod
    def parse_state(self, model: Path, value: object) -> dict:
        """校验结构、有限数值和文件引用，返回规范化状态。"""
        ...

    @abstractmethod
    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        """列出状态额外引用的动作、表情等文件，供角色包打包。"""
        ...
```

注册实现见 [后端注册表](../core/media/avatar/registry.py) 与 [SDK 注册入口](../sdk/register.py)。注册名是唯一依据；adapter 的 format_id 必须与其规范化后相同，不一致时记录错误并跳过该贡献，不能改名注册。SDK 拒绝重复注册；宿主合并时保留首个有效贡献、报告冲突，内置格式优先。一个插件失败不能阻断其他格式。priority 只用于贡献排序，不授权覆盖同名格式。

内置 adapter 必须在运行时组合入口显式 import / 注册，不依赖从未加载的模块副作用。Python 插件由已有 PluginManager 初始化，宿主调用 configure_registered_formats；工厂在这一步创建轻量 adapter，耗时模型加载留给操作。后端注册只提供文件能力，不会把 React 渲染代码装进浏览器。

格式 capabilities 是支持上限，前端 session.capabilities 才描述当前模型实际的嘴眼绑定与动作 / 采样能力。无嘴眼绑定的模型仍可加载；UI、语音和采样按实例实际能力降级。后端不能凭格式标志承诺当前模型具备某个参数。

inspect 不复制文件，parse_state 不保存文件，adapter 不修改角色。application 按 ModelFiles 暂存 / 提交依赖，并调用现有配置保存逻辑。包中有多个模型入口时要求明确选择，不猜测。所有依赖解析限制在已选中或导入的资源范围，错误不能通过扩大文件权限解决。

后端校验结构、引用与数值有效性；真实 SDK 参数存在性和取值范围由前端实例检查。尤其不能假设 Python 仅凭 model3.json 就能证明所有 moc3 参数有效。保存前在当前模型预览中验证，运行时 apply 再次验证；不支持的参数返回错误，不静默忽略成另一个表情。

3. 前端格式注册表与 adapter：加载一次，重复应用状态

公共模型生命周期与格式专属编辑信息分开。泛型 S 是状态文件内容，C 是该格式的临时编辑描述；C 不进入数据库、会话快照或 LLM 消息。每个格式先声明一个描述符，再提供渲染 / 编辑模块：

```ts
export type ApplyMode = "play" | "restore" | "edit";

export interface AvatarCapabilities {
  mouth: boolean;                       // 语音音量驱动嘴型
  blink: boolean;                       // 自动眨眼
  motion: boolean;                      // 一次性动作
  sampling: "none" | "single" | "multi"; // 预览采样
}

export interface AvatarMount {
  element: HTMLElement;
  modelUrl: string;
  assetUrl(relativePath: string): string;
  reportError(error: Error): void;
}

export interface AvatarSession<S, C> {
  readonly capabilities: AvatarCapabilities; // 当前模型实际可用的能力
  readonly controls: C;
  apply(state: S, mode: ApplyMode, signal: AbortSignal): Promise<void>;
  readState(): S;
  setMouthOpen(value: number): void;
  setSpeechLevel?(value: number): void;   // 可选语音瞬态，与是否有嘴型绑定无关
  resize(width: number, height: number): void;
  dispose(): void;
}

export interface AvatarEditorProps<S, C> {
  session: AvatarSession<S, C>;
  value: S;
  onChange(value: S): void;
}

export interface AvatarModule<S, C> {
  create(mount: AvatarMount, signal: AbortSignal): Promise<AvatarSession<S, C>>;
  Editor: import("react").ComponentType<AvatarEditorProps<S, C>>;
}

export interface AvatarFormat<S, C> {
  id: AvatarFormatId;
  label: string;
  modelExtensions?: string[];          // 共享文件选择器的入口后缀过滤，省略则不过滤
  capabilities: AvatarCapabilities;
  load(): Promise<AvatarModule<S, C>>;  // 按需加载渲染与编辑代码
}
```

注册表按规范化 id 存描述符，拒绝空值、static 与同名覆盖。因为 S/C 因格式而异，注册表内部擦除泛型；格式模块负责从 unknown 校验成自己的 S，共享层不解释状态。实现见 [前端注册表](../frontend/src/modules/character-visual/registry.ts)。

领域层与渲染模块独立：`entities/character/assets.ts` 创建和选择通用资源银行，`entities/character/modelStateRepository.ts` 负责状态地址与读取。`AvatarFormat` 不再提供 `createEmpty()`，渲染契约不依赖 `Character` / `ModelSprites`；格式只提供元数据与模块加载。业务页面通过 `modules/character-visual/index.ts` 消费公开渲染接口，由 `app` 注册具体实现。公共模块不反向依赖业务层，也不直接引入任何具体 SDK；各格式只依赖公共契约和自己的实现。

应用启动时，[avatarFormats.ts](../frontend/src/app/avatarFormats.ts) 收集 `adapters/*/format.ts` 的 default export 并统一注册。format.ts 只含轻量元数据，类型使用 type import，load() 内使用动态 import 加载 SDK / renderer / Editor。注册本身不触发 load；并发 load 共用 Promise，失败清除缓存，后续创建可以重试。这个入口只包含随当前前端构建交付的格式；第三方 Python 插件若没有对应前端描述符，应显示不可用。运行时分发第三方 JS 不属于本 PR 的插件承诺。

L2D 模块提供 L2DState、参数 / 动作编辑描述与自己的 Editor；VRM 模块提供 VrmState、表情 / 人形骨骼编辑描述与自己的 Editor；未来格式同理。共享 ModelStateEditor 只管理“当前编号、草稿、保存、标签”，等待 load() 后通过 `module.Editor` 展示格式专属控件。编辑描述 C 不强求一致，避免为了统一滑条把各模型的能力都压成一种格式。

共享编辑器与格式 Editor 复用已有 shared/ui 控件和 i18n；文件选择复用 FilePicker 的桌面原生 / 浏览器降级路径。入口后缀从描述符的 modelExtensions 读取，不在共享层硬编码 l2d / vrm；后缀过滤只辅助选择，不代替后端 adapter 校验。角色导入 / 保存经 character repository，模型 URL 经 files repository，状态读取经 character/modelStateRepository，领域类型沿用 entities/config/types 的出口。

接口行为必须一致：

| 操作 | 共同约定 |
|---|---|
| create | 创建独立实例、加载模型并建立中性基础状态；失败或取消须清理已分配资源；模型无嘴眼绑定时仍可创建 |
| apply(..., play) | 从模型基础值应用该资源并播放所选动作一次；不同条目不能累积残留值 |
| apply(..., restore) | 恢复持续姿态 / 表情，不重新播放一次性动作；用于快照恢复 |
| apply(..., edit) | 展示可编辑基础状态，暂停自动眨眼、语音嘴型与会污染编辑结果的瞬态驱动 |
| readState | 返回当前可保存的基础状态及所选动作引用的副本；不捕获当前眨眼、嘴型或物理瞬态 |
| setMouthOpen | 接收 0–1 的语音开合量；0 表示撤去语音驱动并回到基础嘴部表现，不强制抹去微笑 |
| resize | 适应给定 CSS 宽高；设备像素比在实现内限幅；舞台位置 / 缩放仍由外层 CSS 管理 |
| dispose | 可重复调用，取消加载和帧循环，释放纹理 / GPU / 监听器；之后不再回调宿主 |

adapter 自己持有一个帧循环，并按固定顺序混合动作、基础表情、自动眨眼、嘴型和物理。宿主不读写 SDK 参数，也不逐帧 setState。被中止的 apply 不能在新请求之后覆盖状态；宿主取消上一次请求，adapter 在异步边界和提交前检查 signal。

CharacterVisual 的分发只有一处：static 渲染现有 img；动态类型按注册表懒加载模块。实例由组件持有，模型 URL 不变时只 apply，新模型或卸载才 dispose。加载与 apply 使用独立的 AbortController，晚到的实例立即 dispose，晚到的状态响应不得提交；HTTP 失败不能作为状态应用。错误以覆盖层展示，保留挂载容器，换模型或下一次有效状态可恢复。预览和聊天各有实例，互不改变状态。未知格式 id（本版本未注册）渲染占位并允许切回 static。

4. 状态文件属于各格式，对共享层不透明

共享层把状态当作与 `avatar_type` 对应的不透明 JSON；前端按格式解析后交给 adapter，后端按格式 `parse_state`，两端用相同 JSON fixtures 验证接受和拒绝的边界。**共享契约不再声明 `L2DState` / `VrmState` / `StateByType` 这类硬编码联合**，状态结构由各格式模块在自己的目录里定义并导出，作为 `AvatarModule<S, C>` 的 S：

```ts
// 各格式目录内自定，例如 l2d
export interface L2DState {
  parameters: Record<string, number>;
  expressions: string[];
  motion: string;
}

// 各格式目录内自定，例如 vrm
export interface VrmState {
  expressions: Record<string, number>;
  bones: Record<string, [number, number, number, number]>;
  motion: string;
}
```

空集合表示无覆盖，空 motion 表示无动作。状态内资源路径相对模型入口目录；SDK 的参数名、表情名、人形骨骼名本来就是该格式控制接口，不额外翻译成应用 ID。VRM 骨骼四元数按加载器规范人形骨骼的局部坐标读写。

不要把多种格式拼成一个带大量空字段的万能状态。平台边界处状态是 `unknown`（前端）与 `object`/`dict`（后端），格式模块在入口解析并校验后得到自己的 S，之后才进入 apply / 保存；共享层不解析、不比较、不重排状态字段。

5. 前端接口与后端命令

延续 getPlatform() → HTTP bridge → CharacterUseCase 的现有链路。后端命令是现有 CharacterOperation 的增量，HTTP 仍放在 character_routes.py；没有独立消息总线。所有 name 都指向 Character.name，`avatar_type` 是格式 id（`static` 或注册表内的模型格式），明确指出操作哪个类型，不依赖服务器此刻的“当前选择”。

| 命令 / 平台方法 | 请求中的必要数据 | 结果 / 行为 |
|---|---|---|
| 既有 SAVE / saveCharacter | 现有完整 Character，含两个新字段 | 返回保存后的 Character；角色卡类型选择走此入口 |
| IMPORT_MODEL / importCharacterModel | name、avatar_type、source_path | 返回既有 TaskSnapshot；任务成功结果是完整 Character；可导入未选中的类型 |
| SAVE_MODEL_STATE / saveModelState | name、avatar_type、model_path、sprite_index、path、state、tags | 校验后写状态文件、更新对应 Sprite 和标签，返回完整 Character |
| GENERATE_MODEL_STATES / generateModelStates | name、avatar_type、description | 返回既有 TaskSnapshot；生成条目追加到任务指定类型 |
| 既有增删、标签、条目语音操作 | 现有字段，加明确 avatar_type | 更新指定类型；静态旧入口固定归一化为 static |
| 既有自动标注任务 | name、avatar_type、当前列表 | 静态使用图片；动态使用前端渲染的采样图；结果写入指定类型的 emotion_tags |

动态导入 / 状态操作只接受注册表内的模型格式；static 继续原图片上传。新 HTTP 路由建议为 POST /api/characters/model/import、POST /api/characters/model/state、POST /api/characters/model/generate；其余优先扩展已有路由。preview 是前端本地实例，不新增后端“启动渲染器”命令。

保存请求中 model_path 和 path 复用编辑时已加载的字段，分别用于检查模型是否已更换、所选下标是否还指向同一资源；不是新增持久化字段或身份体系。新增条目用 sprite_index=-1、path=""；覆盖用 0 起始下标和当前 Sprite.path。检查不符返回冲突并要求刷新，不能悄悄覆盖另一个条目。界面与 LLM 的 N 号只在入口转换为 N-1。

平台类型示意（Character、TaskSnapshot 沿用现有类型）。state 在平台边界是 `unknown`，格式模块在保存前解析校验：

```ts
export interface SaveModelStateInput {
  name: string;
  avatar_type: AvatarFormatId;   // 已注册模型格式 id，非 static
  model_path: string;
  sprite_index: number;
  path: string;
  state: unknown;                // 由格式模块解析为 S 后再调用
  tags: string;
}

export interface CharacterModelPlatform {
  importCharacterModel(input: {
    name: string;
    avatar_type: AvatarFormatId;
    source_path: string;
  }): Promise<TaskSnapshot>;
  saveModelState(input: SaveModelStateInput): Promise<Character>;
  generateModelStates(input: {
    name: string;
    avatar_type: AvatarFormatId;
    description: string;
  }): Promise<TaskSnapshot>;
}
```

这是现有 ShinsekaiPlatform 的方法组，不创建第二个客户端。model_path / path 是角色包内由后端认可的资源路径，source_path 必须来自既有上传 / 文件选择许可范围，前端不能让后端任意读取本机文件。后端文件访问复用现有安全路径工具。

命令执行遵循一个简单规则：先准备文件和校验，成功后再提交资源列表与标签；失败保留旧配置。对同一角色的配置提交串行化，耗时导入 / AI 推理在提交锁之外；提交前重新读取并核对当前名称、类型、模型路径与目标资源。重命名 / 更换模型后的旧任务报冲突，不创建同名新角色或写进另一套列表。

更换模型沿用实现方案的显式用户操作，保留旧状态待校验，不能重解释旧编号。overwrite 保留该 Sprite 的语音字段；append 沿用现有 Sprite 的语音默认值。删除状态只移除该文件及对应标签行，不删除被其他条目引用的共享动作或模型。

6. 沿用舞台事件和播放时序

sprite.show 只增加 avatarType 和 modelUrl 两个事件字段；其余 characterName、url、scale、slot、seq 等沿用。avatarType 是格式 id（`static` 或注册表内格式，对应 Character.avatar_type）。url 仍是选中资源的位置：静态为图片，动态为状态 JSON。

| 当前类型 | avatarType | modelUrl | url |
|---|---|---|---|
| static | static | 空字符串 | 图片 URL |
| 某模型格式（如 L2D） | 该格式 id | 模型入口 URL | 当前状态 URL |

新增字段在规范化后的事件和快照中必填。旧事件仅在现有入口补齐 static 与空 modelUrl；不增加事件族或协议版本框架。后端 ui_updates、event_sink、chat_stream 与前端 reducer / snapshot 由共享基础维护者一次性接通，格式开发者不分别改一套。

**槽位与格式正交，avatar 重构不改变槽位语义：**

- slot 仍由共享层拥有：后端 `_get_or_create_sprite_slot` 按 character → 0..N-1 做 LRU 分配；前端 `upsertChatStageSprite` / `resolvedChatStageSpriteSlot` 负责槽位稳定、轴心补偿与重连修复。格式 adapter 不读也不写 slot。
- SpriteLayer 的 `<figure>` 仍是布局单元：`data-slot`、`--sprite-axis-center`、`--sprite-offset-x/y`、`--sprite-scale`、发言高亮 `data-speaking` / `data-dim` 全部照旧，作用于整个槽位，与内容无关。
- 唯一变化是 figure 内部：从硬编码 `<img>` 换成 CharacterVisual 分发——static 渲染现有 img，模型格式按注册表把 module 挂进一个容器。adapter 只负责“把模型放进这个盒子”（contain 适配、内部取景），不负责盒子在哪、多大、排第几。
- sprite.scale / sprite_scale 继续缩放这个盒子（CSS transform）；adapter 通过 resize(width, height) 拿到布局 CSS 像素尺寸（未乘外层 transform），并在实现内限幅设备像素比。模型自身的取景（画布尺寸、相机 FOV、中心对齐）属于格式能力，不属于槽位。

模型资源使用现有媒体鉴权，补充包内相对寻址。AvatarMount.assetUrl 由共享加载器提供；各格式内部 loader 所有外部依赖也必须经该规则转换和检查，不能只有状态文件受限而纹理直接访问任意 URL。

SoundPlayer 保留已有 characterName 到实际语音队列项，从 voice 支路采样并平滑开合量，以真正播放的 characterName 路由到实例。**是否路由嘴型由当前模型的 `session.capabilities.mouth` 决定**；不支持嘴型的格式不接开合量。继续使用已有 playbackId / rendererId；BGM、音效不驱动嘴型。停止、失败、缓冲和失去播放权时撤去语音驱动，不增加新的播放身份字段。

媒体 worker 可以提前准备资源，舞台更新仍由既有有序呈现链执行。首段触发状态 / 动作，后续分句只继续音频；使用现有分句判断与事件 seq 去重。恢复快照使用 restore，新消息使用 play，不因重连重播动作。切换形象类型后的新会话不复用其他类型的历史资源编号。

7. 人工编辑与 AI 使用同一个保存出口

人工流程：模块 Editor 修改草稿 → session.apply(..., edit) 预览 → readState → 格式模块解析校验 → saveModelState → 获得更新后的 Character → 刷新当前类型画廊。只有保存成功才更新正式条目，预览实例不影响聊天。

AI 流程：格式模块根据真实 controls 构造有界候选 → 现有编号 / vibe 契约选择候选 → 程序得到对应状态 → 同样校验和保存 → 预览采样 → 复用标签生成流程。LLM 不返回新的状态 JSON schema，也不在 speech / effect 隐藏动作指令。

动态采样需要真正的前端模型实例，**是否可采样由 `session.capabilities.sampling` 决定**：`none` 表示该格式不提供动态视觉标注（不声称完成）；`single` 采样所选状态一帧；`multi` 对有动作的状态按时间点顺序采样。共享编辑器顺序采样所选状态，使用既有图片上传和任务机制交给视觉标注用例。需要捕获 / 时间定位时，由各格式模块提供编辑期采样辅助函数，不把它变成聊天渲染器的必需方法。关闭预览、取消任务或模型失效时明确取消这一批；没有可用渲染客户端时不声称后端已完成动态视觉标注。

参数缺失、数值越界、文件引用无效都不能写成可用条目。后端不能验证的 SDK 能力在前端保存前和运行时检查；错误返回当前编辑器。批量任务只追加成功项，失败项保留原因，绝不跨类型修改标签。

8. 文件所有权：格式自包含，共享层不感知具体格式

| 维护范围 | 文件 / 目录 | 稳定边界 |
|---|---|---|
| 共享基础 | config/schema.py、config/character_assets.py、现有 character manager / use case / routes、sprite resolver / catalogs、原舞台事件与音频 | 角色结构（两个新字段）、取资源入口、平台命令、事件字段、能力标志和语音输入 |
| 共享前端 | modules/character-visual/contracts.ts、registry.ts、CharacterVisual.tsx、features/character-editor/ModelStateEditor.tsx、shared/platform/types.ts | AvatarFormat / Session 与平台类型；static 保留原 img |
| 共享后端 | sdk/adapters/avatar.py、core/media/avatar/registry.py、application/characters/model_assets.py | ModelAssetAdapter、能力标志、导入 / 状态提交、文件安全与配置更新 |
| 每个格式（如 L2D） | core/media/avatar/l2d.py、modules/character-visual/adapters/l2d/、各自 fixtures / tests | 该格式依赖、状态解析、加载与编辑、嘴眼和资源释放 |
| 每个格式（如 VRM） | core/media/avatar/vrm.py、modules/character-visual/adapters/vrm/、各自 fixtures / tests | 该格式依赖、状态解析、加载与编辑、嘴眼和资源释放 |
| AI 整合 | application/characters/generate_model_states.py、application/media/auto_annotation.py、编辑器批量操作 | 接受格式候选 / 采样结果，复用保存和标签流程 |

后端公共契约位于 sdk/adapters/avatar.py，沿用现有插件能力注册；core 只持有运行时注册快照。前端 shared/platform 不反向依赖具体 adapter：平台层只看到 `avatar_type: string` 和 `state: unknown`，具体状态类型由格式模块在自己的目录导出；临时 C 类型只由格式模块导出。Python adapter 的状态解析模型留在格式目录，config 不导入 core。

注册表采用固定 id → 轻量描述符 / adapter 的入口，前端实现按需加载。基础 PR 先声明契约、共享宿主和一个**测试替身格式**，未就绪格式在 UI 中不可选择；每个格式 PR 再添加自己的目录与一行注册。双方都不复制或改写 CharacterVisual、SoundPlayer、character_routes.py 的通用逻辑。

9. 新增格式的清单与 PR 顺序

“加一个新格式”是可重复的配方，作为文档的一部分固定下来：

```
新增格式 X：
  后端  core/media/avatar/x.py       实现 ModelAssetAdapter（format_id、capabilities、inspect/parse_state/state_files）
  前端  modules/character-visual/adapters/x/  实现 AvatarModule<S,C> 与 Editor（含自己的 S/C 类型、fixtures）
  注册  后端 registry.register_adapter(...) 一行；前端导出 adapters/x/format.ts（应用启动入口自动注册）
  测试  双方 fixtures / tests（接受与拒绝边界、资源释放、.char 往返）
  不改  Character schema、get_character_assets、编号/标签/语音、事件、命令、LLM、共享 UI
```

| PR | 内容 | 谁依赖它 |
|---|---|---|
| A：共享基础 | 两个角色字段、默认值、资源选择、命令和 adapter 契约、注册表、能力标志、舞台宿主、音频桥、static 回归；用测试替身格式验注册与生命周期 | L2D / VRM 都从 A 开始 |
| B：L2D | 仅 L2D adapter、Editor、模型 / 状态 fixtures、所需 SDK 依赖、注册接入 | 不依赖 C |
| C：VRM | 仅 VRM adapter、Editor、模型 / 状态 fixtures、所需渲染依赖、注册接入 | 不依赖 B |
| D：创作与发布整合 | 当前类型 AI 设计 / 标注、混合舞台、完整 .char 往返、跨平台检查 | 可先接入已完成的一个格式，发布验证覆盖两者 |

协作主线是 A → (B 与 C 同时开发) → D。B、C 本质上是“同一配方跑两次”，互不依赖也互不改共享代码。所有共享接口修改集中回 A 或一个单独的共享修订提交，两条格式分支同步它；不要在 B、C 分别发明同名不同义的参数或能力标志。依赖包和锁文件的合并冲突由集成人统一重新生成，不手工拼接锁文件。

双方交付相同的行为验收：

1. 用真实的最小模型加载，应用两条状态，切换后无参数残留且没有重复加载模型。
2. apply / readState 往返保留用户编辑与动作选择，自动嘴眼 / 物理不进入保存文件。
3. play 触发动作，restore 不重播动作，edit 可稳定调整；取消旧 apply 不覆盖新状态。
4. 语音暂停 / 结束恢复基础嘴部状态，模型无嘴眼绑定时能正常显示并给出可见说明；`capabilities.mouth=false` 的格式不接开合量。
5. 关闭预览、离场与重复 dispose 后无帧循环 / GPU / 事件监听泄漏。
6. 状态文件和依赖可随 .char 导出再导入；动态标签 / 条目语音不会读写 static 或另一种动态类型。
7. 提供有效状态、越界 / 未知控制、缺失文件、取消加载样例，Python 与 TypeScript 对状态结构的判断一致。
8. **复用冒烟**：只新增一个测试替身格式（新目录 + 后端注册 + 前端描述符），不改任何共享文件，即能在 UI 出现、能导入 / 保存 / 选中 / 应用 / 导出；这验证“加格式”配方成立。

共享基础另外验证 LLM 输出 schema 不变、旧角色默认 static、原编号 / vibe 行为、条目删除重排、保存下标冲突、角色重命名后的旧任务、语音排队不串角色，以及未知格式 id 的保留、不可用提示和手动切回 static。只验证共享契约所需行为，不要求 L2D 和 VRM 具有相同表情集合或相同可编辑参数。
