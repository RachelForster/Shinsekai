# Live2D 集成试验（开发中）

本分支基于 PR 366，补齐模型文件受控访问、模型导入与手动状态保存、当前类型资源选择、语音所属角色路由，再实现独立的 `l2d` 文件 adapter 和前端模块。未实现 VRM、AI 自动设计或动态视觉采样；采样能力如实声明为 `none`。完整发布前还需要当前会话资源冻结、完整编辑器资源操作和发布矩阵验收。

## SDK 与样例

- 官方 Cubism SDK for Web **5-r.4**，固定使用有内置着色器的版本，避免运行时 CDN 依赖。
- 官方 SDK 下载包 SHA-256：`d78904d908bd232b800219e01732e4ea2f0562b5e9f35a2670742a1c16d22942`。
- [SDK 下载与许可](https://www.live2d.com/en/sdk/download/web/)、[发行许可](https://www.live2d.com/en/sdk/license/)。开源应用自身的许可不覆盖 Cubism Core 或用户模型。
- [Haru 免费样例](https://www.live2d.com/en/learn/sample/haru/)、[样例使用条件](https://www.live2d.com/en/learn/sample/model-terms/)。免费不等于公共领域。
- Core 与 Haru 仅用于已授权的本地集成试验。`frontend/public/live2d/.gitignore` 排除 Core 脚本与 models，不随此分支提交。
- SDK 是显式准备的可选本地运行时，源码和类型检查不再引用被忽略的 vendor 产物。干净检出可以构建及运行单元测试；未安装 SDK 时加载 L2D 会明确报错，静态立绘不受影响。Core / Framework 的发布分发方案仍需单独许可审查。

本机 SDK 原始包位于 `.tmp/l2d-sdk/r4/CubismSdkForWeb-5-r.4/`。用户先阅读并接受 SDK 的 Framework / Core 许可，然后显式运行（不会自动下载 SDK 或复制模型）：

```powershell
cd frontend
pnpm prepare:l2d --sdk-dir ../.tmp/l2d-sdk/r4/CubismSdkForWeb-5-r.4 --accept-sdk-license
```

脚本核对 SDK 的 CHANGELOG 首个版本为 `5-r.4`，使用已声明的 Vite 依赖将官方 Framework 和本项目的窄桥接模块编译成 `public/live2d/cubism-sdk.js`，同时复制 Core 与许可说明；这些生成文件均被忽略，不随 PR 分发。应用仅按需加载同源本地资源，没有运行时 CDN。`sdk.ts` 定义本应用所需的窄运行时接口，不引用或分发 Core 的专有类型文件。升级 SDK 必须复核桥接模块，不能仅修改版本字符串。

## 模型与状态

角色先保存。导入必须明确选择 `model3.json` 入口，依赖逐个校验并复制到 `data/sprite/<sprite_prefix>/avatars/l2d/<包目录>/`。模型包外引用、网络 URL、路径穿越、缺失纹理等均拒绝。`/api/avatar/file` 沿用 bridge 媒体鉴权，仅开放已配置模型的声明依赖和保存的状态，不放宽 `/api/media` 的扩展名政策。

静态“删除全部立绘”保留 `avatars/` 模型子目录及各类型配置。显式替换模型会清空该类型的活动状态和标签，旧模型及状态文件保留在旧包目录供手动恢复，不再进入提示词、聊天资源候选或编辑器活动列表；在新模型上重新保存的状态才可用，不自动迁移旧编号。`.char` 导入后的模型、状态和语音使用绝对项目路径，导出仅在配置副本中转换为包内相对路径。配置通过同目录临时文件及原子替换提交，写入失败向上传播，模型导入或状态保存回滚新增文件与内存银行。

状态格式由 L2D 模块解释：

角色编辑器复用 `shared/ui` 的 `Select`、`FilePicker`、`TextInput`、`Button` / `AsyncButton` 和 `Switch`，沿用角色编辑页的 section / field-row 布局及中英日 i18n。Live2D 描述符声明 `.model3.json` 入口过滤，文件选择沿用桌面原生对话框与浏览器降级机制，并保留手输路径。角色导入 / 保存走既有 character repository，模型 URL 和不透明状态读取分别归 files / character/modelStateRepository；格式专属 Editor 与状态类型仍留在设计指定的 adapter 目录。

模型导入成功时将该类型与资源银行一并持久化，失败同时回滚，不再因刷新返回静态立绘。默认查看区复用 `ImageAssetGallery` 的编号 / 标签卡片、既有 inspector 布局与 `CharacterVisual` 的真实模型预览；卡片不伪造动态缩略图。点击“新建状态”（或已有条目的“编辑状态”）才挂载临时编辑实例，复用 `Dialog`，桌面左侧滚动参数、右侧固定模型预览，窄屏改为上下排列。只有保存成功才提交并选中对应条目；取消释放实例、不保存草稿，保存失败保留草稿供重试。

```json
{"parameters":{"ParamAngleX":12},"expressions":[],"motion":""}
```

参数与资源通过真实 SDK controls 校验；后端只验证文件/结构/有限数值，不假装能从 JSON 得知 moc3 参数范围。新条目以 `sprite_index=-1, path=""` 追加；覆盖同时核对模型路径、下标和原状态路径，保留条目语音。状态文件不覆盖旧文件，配置保存失败不改变原银行。

## 格式扩展与共享边界

- 前端渲染已独立到 `modules/character-visual`：契约、注册表、公共宿主与格式 adapter 不依赖角色实体或业务页面；业务消费者经 `index.ts` 使用渲染 API，`app/avatarFormats.ts` 统一发现格式。`entities/character` 只承担资源银行规则与状态 repository，默认资源银行不再由格式描述符创建。
- 前端 architecture 测试禁止实体/共享层依赖渲染、渲染反向依赖业务层、公共代码直连具体格式、格式间交叉依赖及描述符提前加载 SDK；移除 L2D 注册后，独立 `demo` 格式仍可使用通用编辑器完成选择、导入、新建及保存不透明状态。
- 该分层调整已通过 434 项相关前端回归、类型检查和生产构建；新目录下真实 Haru 冒烟测试保持连续中间姿态、采样帧无空白、资源重载 0 次及销毁后 canvas 为 0。不修改后端协议、角色配置结构或状态文件格式。
- `config.character_assets.get_character_assets(character)` 默认读取当前形象银行；静态图片保留原存储结构。初始资源选择、对话资源解析均复用此入口。识别旧启动路径时可遍历所有银行，但非当前银行的路径只用于判断失效，不能作为当前状态下标使用。
- `application.chat.character_visual.resolve_character_visual` 是舞台资源投影入口。初始快照与实时事件共用它；事件累计出的重连快照保留同一组形象字段。共享层只处理模型入口和状态引用，不解释具体格式的状态内容。
- `application.media.resource_urls.ResourceUrls` 是独立于事件发送的资源地址接口，通过运行时组装注入展示层。`BridgeResourceUrls` 统一实现鉴权、普通媒体地址及模型目录内的资源地址；HTTP bridge 和 WebSocket producer 复用同一实现。传输类原有 URL 方法仅作兼容委托。
- `StreamingUIUpdateManager` 明确要求完整的资源地址接口，不再用 `hasattr` 将缺失的模型能力静默降为图片 URL。尚未组装传输的默认地址实现只支持本地静态图片，模型请求会明确报错。
- 前端 `entities/character/assets.ts` 负责通用银行选择，启动路径检查、模型查看与编辑弹窗共用它；`CharacterVisual` 与通用状态编辑器继续通过 registry 加载格式模块。

在现有模型包、JSON 状态及能力契约内增加格式，需要实现后端 `ModelAssetAdapter` 并在内置或插件组装入口注册，前端添加 `adapters/<format>/format.ts` 及其模块（由 `app/avatarFormats.ts` 自动发现）。无需修改舞台、事件传输、通用编辑器或资源路由。若格式引入契约尚未表达的能力，再单独扩展契约。

回归验证包含一个 `demo` 格式，其状态为 `{"pose":[1,2,3]}`，复用模型导入、状态保存、初始显示、实时事件、重连快照和受控资源读取；不依赖 Cubism 的参数、动作或表情字段。

本次共享边界重构验证：`shinsekai` conda 环境下应用层、配置、bridge、core 和架构边界测试共 1659 项通过、5 项跳过；前端形象模块、角色编辑器、聊天启动及舞台测试 407 项通过，类型检查与生产构建通过。本地包内 Python 的 `desktop-core` 启动自检通过；未完成更新后运行实例的鉴权模型请求及真实舞台渲染复验。

## 生命周期与嘴眼

- 同一模型实例反复 apply，换模型或离场才 dispose。
- 舞台使用角色身份而非快照的资源 ID 作为组件 key，避免初始快照（例如 `Alice-0`）与实时事件（`Alice`）切换时销毁同一模型。
- 首次应用、`restore` 与 `edit` 立即恢复目标状态；后续 `play` 用 300ms `smoothstep` 混合上一次实际显示的基础姿态与本帧目标参数。连续切换从当前中间姿态接续，不从旧目标或默认值重新开始；遵循系统减少动态效果设置。过渡在 L2D adapter 内完成，不新增共享状态字段或渲染依赖。
- 过渡覆盖参数及 Add / Multiply / Overwrite 表情的计算结果，结束时精确落到新状态；被新状态移除的参数回到默认值，不累积残留。自动眨眼、语音和物理在混合之后计算，不进入过渡起点或 `readState`；普通表情切换也不重置眨眼计时与部件透明度。
- `play` 播放所选动作一次；`restore` 不重播动作；`edit` 停用自动嘴眼和物理瞬态。
- 每帧从默认参数开始，按动作、基础参数/表情、自动眨眼、语音嘴型、物理的顺序处理。已有动作控制眼部时不叠加自动眨眼；基础闭眼保持闭眼；语音驱动不会改写微笑参数。
- `readState` 返回保存草稿副本，不捕获当前口型、眨眼或物理瞬态。
- WebAudio 只分析实际播放的 voice；队列保留 characterName，背景音乐/音效不驱动嘴型。暂停、等待缓冲、失败、跳过和结束撤去驱动。
- 帧循环、请求、纹理、GPU 上下文、观察器和事件监听随实例释放。R4 的 shader manager 没有单上下文移除 API，本地编译的 `scripts/l2d-sdk-bridge.mjs` 含固定版本清理兼容代码，必须随 SDK 升级复核。

## 验证

共享状态 fixtures：`test/fixtures/avatar/l2d_states.json`，Python/TypeScript 均读取同一份。

本地真实模型冒烟页面：开发服务器下 `/e2e/fixtures/l2d-smoke.html`（不进入生产入口）。测试 Haru 实际渲染、嘴型开合、编辑状态读取、动作 play/restore 和重复销毁。本地截图在 `.tmp/l2d-evidence/`，不得作为模型再分发素材。

2026-09-29 本地验证：Edge WebGL 加载 Haru，识别 42 个参数、8 个表情、6 个动作；上述冒烟操作后无浏览器错误，重复销毁后 canvas 数量为 0。类型检查与格式检查通过。Python 全量结果为 2906 通过、9 跳过、1 个失败（现有 memory queue 测试遇到 Windows `os.replace` 权限错误）；单独重跑该测试文件 4 项通过。前端全量其余 1011 项通过，新增下拉框导致的 2 个旧选择器失败已修复，角色编辑器及页头 20 项重跑通过。并非完整的发布矩阵验收，也未验证真实 TTS 音频到模型的端到端链路。

PR 368 合并 main 后的追加验证：不含 Core / Framework 产物的 Git 源码快照通过强制类型检查和生产构建；前端完整覆盖率检查通过，行和语句覆盖率均为 90.28%（门槛保持 85%）。本地 SDK 改为显式编译后，Edge 再次实际渲染 Haru（51,422 个非透明像素、42 个参数），编辑读回、动作 play / restore、三次创建与释放无浏览器错误，最终 canvas 数量为 0。SDK 的动态入口使用同源绝对 URL，避免开发服务器把可选 public 资源改写为 `?import` 而加载失败。这些结果仍不包含真实 TTS 到模型的端到端验收。

后续待完成：SDK 的发布许可/打包分发方案；会话选择与资源列表冻结；动态条目完整增删、语音编辑与标签工作流；取消/多实例/受控 bridge 的端到端验收。不能把本地样例成功等同于全部设计验收通过。

表情过渡追加验证：形象模块与聊天舞台相关单元测试 321 项通过，类型检查及生产构建通过。使用本地已授权 Haru 样例与真实 Cubism 5-r.4，在无头 Edge WebGL 中观察到角度 0 → 25 的连续中间值，快速反向切换后到达最新目标；采样帧最少 16795 个非透明像素，模型资源重载 0 次，销毁后 canvas 为 0，无浏览器错误。该检查使用独立本地样例页，不代表当前用户聊天实例或真实 TTS 链路的端到端验收。
