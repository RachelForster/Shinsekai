# Live2D 集成试验（开发中）

本分支基于 PR 366，补齐模型文件受控访问、模型导入与手动状态保存、当前类型资源选择、语音所属角色路由，再实现独立的 `l2d` 文件 adapter 和前端模块。未实现 VRM、AI 自动设计或动态视觉采样；采样能力如实声明为 `none`。完整发布前还需要当前会话资源冻结、完整编辑器资源操作和发布矩阵验收。

## SDK 与样例

- 官方 Cubism SDK for Web **5-r.4**，固定使用有内置着色器的版本，避免运行时 CDN 依赖。
- 官方 SDK 下载包 SHA-256：`d78904d908bd232b800219e01732e4ea2f0562b5e9f35a2670742a1c16d22942`。
- [SDK 下载与许可](https://www.live2d.com/en/sdk/download/web/)、[发行许可](https://www.live2d.com/en/sdk/license/)。开源应用自身的许可不覆盖 Cubism Core 或用户模型。
- [Haru 免费样例](https://www.live2d.com/en/learn/sample/haru/)、[样例使用条件](https://www.live2d.com/en/learn/sample/model-terms/)。免费不等于公共领域。
- Core 与 Haru 仅用于已授权的本地集成试验。`frontend/public/live2d/.gitignore` 排除 Core 脚本与 models，不随此分支提交。
- Framework 的仓库分发方式待确认；目前 `frontend/vendor/.gitignore` 排除本地 Framework 产物。干净检出不能在缺少 Framework 的情况下构建，本分支尚未作为可发布 PR 推送。

本机 SDK 原始包和编译产物位于 `.tmp/l2d-sdk/r4/CubismSdkForWeb-5-r.4/`，实际本地前端试验文件位于 `frontend/vendor/cubism-framework/` 与 `frontend/public/live2d/`。不把这些路径当成发布安装方案。

## 模型与状态

角色先保存。导入必须明确选择 `model3.json` 入口，依赖逐个校验并复制到 `data/sprite/<sprite_prefix>/avatars/l2d/<包目录>/`。模型包外引用、网络 URL、路径穿越、缺失纹理等均拒绝。`/api/avatar/file` 沿用 bridge 媒体鉴权，仅开放已配置模型的声明依赖和保存的状态，不放宽 `/api/media` 的扩展名政策。

状态格式由 L2D 模块解释：

```json
{"parameters":{"ParamAngleX":12},"expressions":[],"motion":""}
```

参数与资源通过真实 SDK controls 校验；后端只验证文件/结构/有限数值，不假装能从 JSON 得知 moc3 参数范围。新条目以 `sprite_index=-1, path=""` 追加；覆盖同时核对模型路径、下标和原状态路径，保留条目语音。状态文件不覆盖旧文件，配置保存失败不改变原银行。

## 生命周期与嘴眼

- 同一模型实例反复 apply，换模型或离场才 dispose。
- `play` 播放所选动作一次；`restore` 不重播动作；`edit` 停用自动嘴眼和物理瞬态。
- 每帧从默认参数开始，按动作、基础参数/表情、自动眨眼、语音嘴型、物理的顺序处理。已有动作控制眼部时不叠加自动眨眼；基础闭眼保持闭眼；语音驱动不会改写微笑参数。
- `readState` 返回保存草稿副本，不捕获当前口型、眨眼或物理瞬态。
- WebAudio 只分析实际播放的 voice；队列保留 characterName，背景音乐/音效不驱动嘴型。暂停、等待缓冲、失败、跳过和结束撤去驱动。
- 帧循环、请求、纹理、GPU 上下文、观察器和事件监听随实例释放。R4 的 shader manager 没有单上下文移除 API，格式模块内有固定版本清理兼容代码，必须随 SDK 升级复核。

## 验证

共享状态 fixtures：`test/fixtures/avatar/l2d_states.json`，Python/TypeScript 均读取同一份。

本地真实模型冒烟页面：开发服务器下 `/e2e/fixtures/l2d-smoke.html`（不进入生产入口）。测试 Haru 实际渲染、嘴型开合、编辑状态读取、动作 play/restore 和重复销毁。本地截图在 `.tmp/l2d-evidence/`，不得作为模型再分发素材。

2026-09-29 本地验证：Edge WebGL 加载 Haru，识别 42 个参数、8 个表情、6 个动作；上述冒烟操作后无浏览器错误，重复销毁后 canvas 数量为 0。类型检查与格式检查通过。Python 全量结果为 2906 通过、9 跳过、1 个失败（现有 memory queue 测试遇到 Windows `os.replace` 权限错误）；单独重跑该测试文件 4 项通过。前端全量其余 1011 项通过，新增下拉框导致的 2 个旧选择器失败已修复，角色编辑器及页头 20 项重跑通过。并非完整的发布矩阵验收，也未验证真实 TTS 音频到模型的端到端链路。

后续待完成：SDK 依赖的干净检出/CI/打包路径；会话选择与资源列表冻结；动态条目完整增删、语音编辑与标签工作流；取消/多实例/受控 bridge 的端到端验收。不能把本地样例成功等同于全部设计验收通过。
