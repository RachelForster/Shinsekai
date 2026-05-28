# React 前端解耦修改记录

日期：2026-05-29  
分支：`feat/react-frontend-refactor`

## 背景

根据 `docs/react_frontend_coupling_review.md` 中的 review 结论，本次修改重点处理 React 前端中的层级反向依赖和平台访问耦合问题。目标是让 `shared` 保持为底层共享层，让 feature/app 层通过 entity repository 或注入边界访问平台能力，而不是直接调用 `getPlatform()` 或依赖更高层业务类型。

## 已解决的问题

### 1. 平台契约从 entity 层下沉到 shared

原先 `shared/platform/types.ts` 依赖 `entities/config/types` 和 `entities/plugin/types`，导致底层 platform 契约反向依赖业务 entity。现在平台契约类型集中定义在 `frontend/src/shared/platform/types.ts`，包括：

- 角色、背景、精灵等媒体模型。
- API/System/App 配置模型。
- 插件、插件市场、插件 UI、MCP 配置模型。
- platform 各模块接口定义。

`entities/config/types.ts` 和 `entities/plugin/types.ts` 改为从 shared 契约 re-export 类型，保留原 import 路径兼容已有调用方。`entities/plugin/types.ts` 仍保留 `pluginSlotIds` 和 `isPluginSlotId` 这类运行时实体辅助逻辑。

### 2. 表单 schema 脱离 config entity

原先通用表单组件和插件 UI 配置复用了 `entities/config/types` 中的 `FormFieldSchema` 等类型，导致 UI 基础能力依赖配置实体。现在新增 `frontend/src/shared/ui/formSchema.ts`，统一定义：

- `FieldKind`
- `FormOption`
- `FormFieldSchema`
- `FormGroupSchema`

`entities/config/schema.ts`、`features/SchemaDrivenForm.tsx`、API 设置页和插件管理页改为使用 shared 表单 schema。这样表单 schema 成为共享 UI 契约，而不是 config entity 的附属类型。

### 3. AppState Provider 移入 shared app-state

原先 `app/providers/AppState.tsx` 存放应用状态 Context，但 feature 页面直接导入 app 层 provider，形成 feature 到 app 的反向依赖。现在新增 `frontend/src/shared/app-state/AppState.tsx`，承载：

- `AppStateProvider`
- `useAppState`
- `useAppConfigValue`

`frontend/src/app/providers/AppState.tsx` 改为兼容 re-export。`AppProviders`、API 设置页、系统设置页改为使用 shared app-state，降低 feature 对 app 层目录结构的依赖。

### 4. feature/app 层直接平台访问迁移到 repository 或 hook

新增 repository/hook 边界，集中封装原先散落在 feature/app 层的 `getPlatform()` 调用：

- `frontend/src/entities/chat/repository.ts`
  - `getChatSnapshot`
  - `getChatTheme`
  - `launchChat`
  - `resumeLastChat`
  - `sendChatCommand`
  - `subscribeChat`
  - `chatQueryKey`
- `frontend/src/entities/files/repository.ts`
  - `browseFiles`
  - `fileUrl`
  - `openExternal`
- `frontend/src/entities/music-cover/repository.ts`
  - `saveMusicCoverConfig`
  - `searchMusicCover`
  - `runMusicCover`
- `frontend/src/entities/plugin/hooks.ts`
  - `useAppUpdateInfo`

以下页面和组件已切换到 repository/hook 边界：

- `ChatLauncherPage`
- `ChatStagePage`
- `TemplateEditorPage`
- `MusicCoverPage`
- `ToolsPage`
- `BackgroundManagerPage`
- `CharacterEditorPage`
- `PluginManagerPage`
- `ApiSettingsPage`
- `BottomBar`

调整后，feature/app 层不再直接调用 `getPlatform()`。平台访问集中在 `shared/platform` 和各 entity repository 中，后续如果要替换 HTTP/preview platform 或引入 mock 边界，改动面会更小。

### 5. FileManager 改为注入文件浏览能力

原先 `shared/ui/FileManager.tsx` 直接调用 `getPlatform().files.browse()`，让 shared UI 组件依赖具体平台实现。现在 FileManager 支持两种注入方式：

- 通过 `onBrowse` prop 注入浏览行为。
- 通过 `FileBrowserProvider` 在上层统一提供浏览行为。

`AppProviders` 使用 `browseFiles` repository 注入默认文件浏览能力。对应测试也改为显式注入浏览函数，避免 UI 测试依赖全局 platform 单例。

### 6. 平台实现和测试同步调整

由于平台契约移动到 shared，`httpPlatform`、`browserPreviewPlatform`、`sampleData` 的类型 import 同步更新。`dialog.test.tsx` 和 `fileManager.test.tsx` 已按新的 FileManager 注入方式调整。

## 当前边界

本次解耦没有把所有 repository 改造成复杂的数据层；新增的 repository 多数仍是薄封装。这是有意保留的边界：先把 `getPlatform()` 从 feature/app/shared UI 中移出，统一收敛到 entity repository 和 platform 层，避免一次性引入过多缓存、状态管理或请求编排变更。

当前检查结果：

- `frontend/src/shared` 不再依赖 `entities`。
- `frontend/src/features` 和 `frontend/src/app` 不再直接调用 `getPlatform()`。
- `getPlatform()` 调用保留在 `shared/platform/platform.ts` 和 entity repository 层。

## 验证

已执行并通过：

- `pnpm lint:types`
- `pnpm format:check`
- `pnpm test`
- `git diff --check`

