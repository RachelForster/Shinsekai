Shinsekai 多形态角色：高层设计与协作契约

状态：待实施的设计契约。本 PR 提交文档，不宣称运行时已支持 L2D / VRM。需求与示例见 [实现方案](CHARACTER_AVATAR_IMPLEMENTATION_PLAN_zh-CN.md)，目录依赖遵守 [项目结构](PROJECT_STRUCTURE.md)。本文确定 adapter、前后端边界和协作接口；具体 SDK 参数处理由各格式实现维护。

设计原则：角色负责选择使用哪套资源，资源列表负责编号和标签，adapter 负责解释某种格式。共享层理解“选择第几项”，不理解“这个参数怎样让角色微笑”。

1. 保持既有业务模型

- 人物唯一标识仍是 Character.name，对外沿用 character_name / 现有请求的 name，不引入人物或模型业务 ID。
- Character 只增加 avatar_type、l2d、vrm 三个字段；static 继续使用根级 sprites / emotion_tags。每种动态类型持有一个 model_path 和自己的 sprites / emotion_tags。
- Sprite 保持现有结构。静态 path 是图片，动态 path 是状态文件；条目语音继续用 voice_path / voice_text / voice_type。
- 各类型独立编号、独立标注。编号由列表位置计算，不建立跨类型语义映射。
- LLM 输出 schema、编号 / vibe 选择顺序和插件字段规则保持不变。新接口的字段均必填；未配置模型使用空字符串和空列表，旧角色在配置入口补齐默认值。
- 当前会话使用启动时选定的类型和资源列表；编辑角色卡影响下次启动。首版不实现中途换类型的会话重编排。

共享数据契约只保留这些信息（Sprite 使用现有定义）：

```ts
export type AvatarType = "static" | "l2d" | "vrm";
export type ModelAvatarType = Exclude<AvatarType, "static">;

export interface ModelSprites {
  model_path: string;
  sprites: Sprite[];
  emotion_tags: string;
}

export interface CharacterAvatarFields {
  avatar_type: AvatarType;
  l2d: ModelSprites;
  vrm: ModelSprites;
}
```

唯一的资源选择函数为 get_character_assets(character, avatar_type)。对 static 返回根级列表及空 model_path，对动态类型返回对应配置。提示词、语义索引、资源解析、条目语音、标签编辑全部经过这个入口。写操作由现有 CharacterUseCase / character manager 更新对应位置，不建立第二个持久化入口。

编号模式把现有 sprite / asset_id 解析为当前列表的第 N 项；语义模式只检索当前类型的 tags。索引 scope 使用现有角色名与类型组成，例如 sprite:Alice:l2d，仅是检索分区，不是新业务身份。无效条目可以从候选中排除，但保留原列表下标对应的编号；真正删除时仍按现有规则重新编号。

2. 两个 adapter 边界

| 边界 | 共享代码负责 | 格式 adapter 负责 |
|---|---|---|
| 后端模型文件 | 鉴权、导入暂存、任务、文件提交、角色配置更新、编号与标签、角色包 | 找到模型入口、列出依赖、解析状态结构与文件引用 |
| 前端模型实例 | DOM 容器、类型分发、资源获取、请求取消、舞台布局、语音路由、保存与标签 UI | SDK 加载、渲染、状态应用、嘴眼混合、参数控件和资源释放 |

static 继续使用原图片实现；只有 l2d / vrm 实现模型 adapter。注册表是明确的两项映射，不建立插件发现、全局模型管理器或通用参数语言。

后端 adapter 是无角色、无会话状态的文件能力，放在 core/media/avatar/。下面的对象仅在一次调用中存在，不写入 Character 或新增 manifest：

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

ModelAvatarType = Literal["l2d", "vrm"]

@dataclass(frozen=True)
class ModelFiles:
    entry: Path
    files: tuple[Path, ...]

class ModelAssetAdapter(Protocol):
    avatar_type: ModelAvatarType

    def inspect(self, source: Path) -> ModelFiles:
        """识别一个模型入口，并列出导入时需要的完整依赖。"""
        ...

    def parse_state(self, model: Path, value: object) -> dict[str, object]:
        """校验结构、有限数值和文件引用，返回规范化状态。"""
        ...

    def state_files(self, model: Path, state: dict[str, object]) -> tuple[Path, ...]:
        """列出状态额外引用的动作、表情等文件，供角色包打包。"""
        ...
```

inspect 不复制文件，parse_state 不保存文件，adapter 不修改角色。application 按 ModelFiles 暂存 / 提交依赖，并调用现有配置保存逻辑。包中有多个模型入口时要求明确选择，不猜测。所有依赖解析限制在已选中或导入的资源范围，错误不能通过扩大文件权限解决。

后端校验结构、引用与数值有效性；真实 SDK 参数存在性和取值范围由前端实例检查。尤其不能假设 Python 仅凭 model3.json 就能证明所有 moc3 参数有效。保存前在当前模型预览中验证，运行时 apply 再次验证；不支持的参数返回错误，不静默忽略成另一个表情。

3. 前端 adapter：加载一次，重复应用状态

公共模型生命周期与格式专属编辑信息分开。泛型 S 是状态文件内容，C 是该格式的临时编辑描述；C 不进入数据库、会话快照或 LLM 消息。

```ts
export type ApplyMode = "play" | "restore" | "edit";

export interface AvatarMount {
  element: HTMLElement;
  modelUrl: string;
  assetUrl(relativePath: string): string;
  reportError(error: Error): void;
}

export interface AvatarSession<S, C> {
  readonly controls: C;
  apply(state: S, mode: ApplyMode, signal: AbortSignal): Promise<void>;
  readState(): S;
  setMouthOpen(value: number): void;
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
```

L2D 模块提供 L2DState、参数 / 动作编辑描述与自己的 Editor；VRM 模块提供 VrmState、表情 / 人形骨骼编辑描述与自己的 Editor。共享 ModelStateEditor 只管理“当前编号、草稿、保存、标签”，通过模块的 Editor 展示格式专属控件。编辑描述 C 不强求一致，避免为了统一滑条把两种模型的能力都压成一种格式。

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

CharacterVisual 的分发只有一处：static 渲染现有 img；动态类型按注册表懒加载模块。实例由组件持有，模型 URL 不变时只 apply，新模型或卸载才 dispose。预览和聊天各有实例，互不改变状态。

4. 状态文件属于各格式

```ts
export interface L2DState {
  parameters: Record<string, number>;
  expressions: string[];
  motion: string;
}

export interface VrmState {
  expressions: Record<string, number>;
  bones: Record<string, [number, number, number, number]>;
  motion: string;
}

export interface StateByType {
  l2d: L2DState;
  vrm: VrmState;
}
```

空集合表示无覆盖，空 motion 表示无动作。状态内资源路径相对模型入口目录；SDK 的参数名、表情名、人形骨骼名本来就是该格式控制接口，不额外翻译成应用 ID。VRM 骨骼四元数按加载器规范人形骨骼的局部坐标读写。

共享层把状态当作与 avatar_type 对应的文件内容。前端按类型解析后交给 adapter，后端按类型 parse_state；两端用相同 JSON fixtures 验证接受和拒绝的边界。不要把两种文件拼成一个带大量空字段的万能状态。

5. 前端接口与后端命令

延续 getPlatform() → HTTP bridge → CharacterUseCase 的现有链路。后端命令是现有 CharacterOperation 的增量，HTTP 仍放在 character_routes.py；没有独立消息总线。所有 name 都指向 Character.name，avatar_type 明确指出操作哪个类型，不依赖服务器此刻的“当前选择”。

| 命令 / 平台方法 | 请求中的必要数据 | 结果 / 行为 |
|---|---|---|
| 既有 SAVE / saveCharacter | 现有完整 Character，包含三个新字段 | 返回保存后的 Character；角色卡类型选择走此入口 |
| IMPORT_MODEL / importCharacterModel | name、avatar_type、source_path | 返回既有 TaskSnapshot；任务成功结果是完整 Character；可导入未选中的类型 |
| SAVE_MODEL_STATE / saveModelState | name、avatar_type、model_path、sprite_index、path、state、tags | 校验后写状态文件、更新对应 Sprite 和标签，返回完整 Character |
| GENERATE_MODEL_STATES / generateModelStates | name、avatar_type、description | 返回既有 TaskSnapshot；生成条目追加到任务指定类型 |
| 既有增删、标签、条目语音操作 | 现有字段，加明确 avatar_type | 更新指定类型；静态旧入口固定归一化为 static |
| 既有自动标注任务 | name、avatar_type、当前列表 | 静态使用图片；动态使用前端渲染的采样图；结果写入指定类型的 emotion_tags |

动态导入 / 状态操作只接受 l2d、vrm；static 继续原图片上传。新 HTTP 路由建议为 POST /api/characters/model/import、POST /api/characters/model/state、POST /api/characters/model/generate；其余优先扩展已有路由。preview 是前端本地实例，不新增后端“启动渲染器”命令。

保存请求中 model_path 和 path 复用编辑时已加载的字段，分别用于检查模型是否已更换、所选下标是否还指向同一资源；不是新增持久化字段或身份体系。新增条目用 sprite_index=-1、path=""；覆盖用 0 起始下标和当前 Sprite.path。检查不符返回冲突并要求刷新，不能悄悄覆盖另一个条目。界面与 LLM 的 N 号只在入口转换为 N-1。

平台类型示意（Character、TaskSnapshot 沿用现有类型）：

```ts
export type SaveModelStateInput = {
  [K in ModelAvatarType]: {
    name: string;
    avatar_type: K;
    model_path: string;
    sprite_index: number;
    path: string;
    state: StateByType[K];
    tags: string;
  };
}[ModelAvatarType];

export interface CharacterModelPlatform {
  importCharacterModel(input: {
    name: string;
    avatar_type: ModelAvatarType;
    source_path: string;
  }): Promise<TaskSnapshot>;
  saveModelState(input: SaveModelStateInput): Promise<Character>;
  generateModelStates(input: {
    name: string;
    avatar_type: ModelAvatarType;
    description: string;
  }): Promise<TaskSnapshot>;
}
```

这是现有 ShinsekaiPlatform 的方法组，不创建第二个客户端。model_path / path 是角色包内由后端认可的资源路径，source_path 必须来自既有上传 / 文件选择许可范围，前端不能让后端任意读取本机文件。后端文件访问复用现有安全路径工具。

命令执行遵循一个简单规则：先准备文件和校验，成功后再提交资源列表与标签；失败保留旧配置。对同一角色的配置提交串行化，耗时导入 / AI 推理在提交锁之外；提交前重新读取并核对当前名称、类型、模型路径与目标资源。重命名 / 更换模型后的旧任务报冲突，不创建同名新角色或写进另一套列表。

更换模型沿用实现方案的显式用户操作，保留旧状态待校验，不能重解释旧编号。overwrite 保留该 Sprite 的语音字段；append 沿用现有 Sprite 的语音默认值。删除状态只移除该文件及对应标签行，不删除被其他条目引用的共享动作或模型。

6. 沿用舞台事件和播放时序

sprite.show 只增加 avatar_type 和 model_url；其余 characterName、url、scale、slot、seq 等沿用。url 仍是选中资源的位置：静态为图片，动态为状态 JSON。

| 当前类型 | avatar_type | model_url | url |
|---|---|---|---|
| static | static | 空字符串 | 图片 URL |
| L2D | l2d | model3.json 入口 URL | 当前 L2D 状态 URL |
| VRM | vrm | VRM 入口 URL | 当前 VRM 状态 URL |

新增字段在规范化后的事件和快照中必填。旧事件仅在现有入口补齐 static 与空 model_url；不增加事件族或协议版本框架。后端 ui_updates、event_sink、chat_stream 与前端 reducer / snapshot 由共享基础维护者一次性接通，格式开发者不分别改一套。

模型资源使用现有媒体鉴权，补充包内相对寻址。AvatarMount.assetUrl 由共享加载器提供；L2D / VRM 内部 loader 所有外部依赖也必须经该规则转换和检查，不能只有状态文件受限而纹理直接访问任意 URL。

SoundPlayer 保留已有 characterName 到实际语音队列项，从 voice 支路采样并平滑开合量，以真正播放的 characterName 路由到实例。继续使用已有 playbackId / rendererId；BGM、音效不驱动嘴型。停止、失败、缓冲和失去播放权时撤去语音驱动，不增加新的播放身份字段。

媒体 worker 可以提前准备资源，舞台更新仍由既有有序呈现链执行。首段触发状态 / 动作，后续分句只继续音频；使用现有分句判断与事件 seq 去重。恢复快照使用 restore，新消息使用 play，不因重连重播动作。切换形象类型后的新会话不复用其他类型的历史资源编号。

7. 人工编辑与 AI 使用同一个保存出口

人工流程：模块 Editor 修改草稿 → session.apply(..., edit) 预览 → readState → saveModelState → 获得更新后的 Character → 刷新当前类型画廊。只有保存成功才更新正式条目，预览实例不影响聊天。

AI 流程：格式模块根据真实 controls 构造有界候选 → 现有编号 / vibe 契约选择候选 → 程序得到对应状态 → 同样校验和保存 → 预览采样 → 复用标签生成流程。LLM 不返回新的状态 JSON schema，也不在 speech / effect 隐藏动作指令。

动态采样需要真正的前端模型实例。共享编辑器顺序采样所选状态，使用既有图片上传和任务机制交给视觉标注用例；动作使用有顺序的多帧采样。需要捕获 / 时间定位时，由各格式模块提供编辑期采样辅助函数，不把它变成聊天渲染器的必需方法。关闭预览、取消任务或模型失效时明确取消这一批；没有可用渲染客户端时不声称后端已完成动态视觉标注。

参数缺失、数值越界、文件引用无效都不能写成可用条目。后端不能验证的 SDK 能力在前端保存前和运行时检查；错误返回当前编辑器。批量任务只追加成功项，失败项保留原因，绝不跨类型修改标签。

8. 文件所有权让两个格式独立开发

| 维护范围 | 文件 / 目录 | 稳定边界 |
|---|---|---|
| 共享基础 | config/schema.py、config/character_assets.py、现有 character manager / use case / routes、sprite resolver / catalogs、原舞台事件与音频 | 角色结构、取资源入口、平台命令、事件字段和语音输入 |
| 共享前端 | entities/character-visual/contracts.ts、registry.ts、CharacterVisual.tsx、features/character-editor/ModelStateEditor.tsx、shared/platform/types.ts | AvatarModule / Session 与平台类型；static 保留原 img |
| 共享后端 | core/media/avatar/contracts.py、registry.py、application/characters/model_assets.py | ModelAssetAdapter、导入 / 状态提交、文件安全与配置更新 |
| L2D | core/media/avatar/l2d.py、entities/character-visual/adapters/l2d/、各自 fixtures / tests | Cubism 依赖、状态解析、加载与编辑、嘴眼和资源释放 |
| VRM | core/media/avatar/vrm.py、entities/character-visual/adapters/vrm/、各自 fixtures / tests | VRM / VRMA 依赖、状态解析、加载与编辑、嘴眼和资源释放 |
| AI 整合 | application/characters/generate_model_states.py、application/media/auto_annotation.py、编辑器批量操作 | 接受格式候选 / 采样结果，复用保存和标签流程 |

共享契约位于宿主已有模块，不创建新的 sdk/avatar.py；本期 adapter 是内部实现边界。前端 shared/platform 不反向依赖具体 adapter：传输用状态类型放在 shared/platform 的既有契约模块，格式实现消费它；临时 C 类型只由格式模块导出。Python adapter 的状态解析模型留在格式目录，config 不导入 core。

注册表采用固定的 l2d / vrm 懒加载入口。基础 PR 可以先声明契约、共享宿主和未接入占位，未就绪类型在 UI 中不可选择；每个格式 PR 再添加自己的目录与一行注册。双方都不复制或改写 CharacterVisual、SoundPlayer、character_routes.py 的通用逻辑。

9. PR 顺序与交付契约

| PR | 内容 | 谁依赖它 |
|---|---|---|
| A：共享基础 | 三个角色字段、默认值、资源选择、命令和 adapter 契约、舞台宿主、音频桥、static 回归；用测试替身验 adapter 生命周期 | L2D / VRM 都从 A 开始 |
| B：L2D | 仅 L2D adapter、Editor、模型 / 状态 fixtures、所需 SDK 依赖、注册接入 | 不依赖 C |
| C：VRM | 仅 VRM adapter、Editor、模型 / 状态 fixtures、所需渲染依赖、注册接入 | 不依赖 B |
| D：创作与发布整合 | 当前类型 AI 设计 / 标注、混合舞台、完整 .char 往返、跨平台检查 | 可先接入已完成的一个格式，发布验证覆盖两者 |

协作主线是 A → (B 与 C 同时开发) → D。所有共享接口修改集中回 A 或一个单独的共享修订提交，两条格式分支同步它；不要在 B、C 分别发明同名不同义的参数。依赖包和锁文件的合并冲突由集成人统一重新生成，不手工拼接锁文件。

双方交付相同的行为验收：

1. 用真实的最小模型加载，应用两条状态，切换后无参数残留且没有重复加载模型。
2. apply / readState 往返保留用户编辑与动作选择，自动嘴眼 / 物理不进入保存文件。
3. play 触发动作，restore 不重播动作，edit 可稳定调整；取消旧 apply 不覆盖新状态。
4. 语音暂停 / 结束恢复基础嘴部状态，模型无嘴眼绑定时能正常显示并给出可见说明。
5. 关闭预览、离场与重复 dispose 后无帧循环 / GPU / 事件监听泄漏。
6. 状态文件和依赖可随 .char 导出再导入；动态标签 / 条目语音不会读写 static 或另一种动态类型。
7. 提供有效状态、越界 / 未知控制、缺失文件、取消加载样例，Python 与 TypeScript 对状态结构的判断一致。

共享基础另外验证 LLM 输出 schema 不变、旧角色默认 static、原编号 / vibe 行为、条目删除重排、保存下标冲突、角色重命名后的旧任务、语音排队不串角色。只验证共享契约所需行为，不要求 L2D 和 VRM 具有相同表情集合或相同可编辑参数。
