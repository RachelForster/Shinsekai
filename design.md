# Shinsekai Design Standard

本文档定义 Shinsekai 当前前端的视觉与交互标准，适用于 React 设置中心、聊天演出窗口、插件贡献页和后续前端重写。目标是在保留现有风格识别度的前提下，让新增页面、组件和主题扩展保持一致。

## 1. 设计定位

Shinsekai 是面向 Galgame、乙女、剧情向 RPG 的桌面助手。界面应同时满足两种体验：

- **设置中心**：偏工具型，信息密度高、层级清晰、适合反复配置。
- **聊天主窗**：偏演出型，强调角色、立绘、对白、选项和沉浸感。

整体风格为 **暗色桌面工具外壳 + 半透明叙事浮层 + 柔和紫粉强调色**。不要做成营销落地页、网页仪表盘或过度装饰的卡片布局。

## 2. React 技术栈

默认技术栈：

- **语言与框架**：React + TypeScript。
- **构建工具**：Vite。
- **桌面容器**：需要桌面分发时使用 Tauri 或 Electron；React 层不得直接散落调用容器 API，应通过 `platform` / `ipc` 适配层访问。
- **样式系统**：CSS variables + CSS Modules 或普通 CSS 分层文件。若引入 Tailwind，只能消费同一套 design tokens，不另起颜色体系。
- **图标**：优先使用 `lucide-react`，缺失时再使用项目资源图标。
- **路由**：设置中心页面使用 React Router 或等价路由层；聊天主窗可作为独立 route 或独立 window entry。
- **数据请求与缓存**：异步数据、插件列表、下载状态、远端索引等使用 query/cache 层管理。
- **本地 UI 状态**：使用 React state、`useReducer` 或轻量 store；不要把表单临时态写进全局配置。
- **表单**：使用 schema-driven form。字段定义、校验规则、默认值和保存 payload 应由同一份 schema 派生。
- **测试**：组件交互用 Testing Library，业务纯函数用单元测试，关键页面和聊天舞台用 Playwright 截图回归。

推荐目录：

```text
frontend/
  src/
    app/
      routes/
      providers/
      shell/
    shared/
      ui/
      icons/
      theme/
      i18n/
      platform/
      async/
    entities/
      config/
      character/
      background/
      plugin/
      template/
    features/
      api-settings/
      character-editor/
      background-manager/
      template-editor/
      plugin-manager/
      chat-launcher/
      chat-stage/
```

React 实现边界：

- `components` 只负责展示和基础交互，不直接读写 YAML、文件系统或后端状态。
- `features` 负责业务行为、表单提交、异步任务和页面级状态。
- `entities` 保存领域类型、schema、序列化和 repository。
- `shared/theme` 输出 CSS variables，所有页面只能引用 token，不硬编码主题色。
- 插件贡献 UI 必须通过注册表渲染到固定 slot，不能直接改写 App shell。

## 3. 视觉原则

### 3.1 暗色优先

默认使用深色背景。界面不使用大面积纯黑，而使用带蓝灰倾向的深色层级。

| Token | CSS Variable | 用途 | 当前值 |
| --- | --- | --- | --- |
| `bg.app` | `--color-bg-app` | 设置中心主背景 | `#282c34` / `rgb(40,44,52)` |
| `bg.sidebar` | `--color-bg-sidebar` | 左侧导航、菜单背景 | `#21252b` / `rgb(33,37,43)` |
| `bg.panel` | `--color-bg-panel` | 抽屉、底栏、分隔区域 | `#2c313a` / `rgb(44,49,58)` |
| `bg.input` | `--color-bg-input` | 输入框深色底 | `#1b1d23` / `rgb(27,29,35)` |
| `border.default` | `--color-border` | 分隔线、控件边框 | `#343b48` / `rgb(52,59,72)` |
| `border.hover` | `--color-border-hover` | 悬停边框 | `#404758` / `rgb(64,71,88)` |
| `text.primary` | `--color-text-primary` | 主文字 | `#dddddd` |
| `text.muted` | `--color-text-muted` | 次级文字 | `#717e95` |
| `accent.primary` | `--color-accent-primary` | 主要强调色 | `#bd93f9` |
| `accent.secondary` | `--color-accent-secondary` | 选择/高亮辅助色 | `#ff79c6` |
| `chat.surface` | `--color-chat-surface` | 聊天对白底 | `rgba(50,50,50,0.78)` |
| `chat.toolbar` | `--color-chat-toolbar` | 聊天工具栏底 | `rgba(50,50,50,0.59)` |

### 3.2 层级清楚，不堆装饰

- 设置中心用侧栏、顶部栏、内容区和底栏建立层级。
- 页面内部优先使用分组、表单行、表格、分段导航，不使用嵌套卡片。
- 聊天主窗允许半透明浮层、边框图、立绘和背景图，设置页不使用演出化装饰。
- 不使用渐变球、背景光斑、纯装饰插画。

### 3.3 角色与内容优先

聊天窗口里，立绘、对白和选项是第一视觉重点。工具按钮、输入栏、状态提示应保持可用但不抢戏。

## 4. 字体

### 4.1 设置中心

- 默认字体遵循当前 PyDracula 体系：`Segoe UI`。
- 中文环境下通过全局 CSS font stack 使用微软雅黑，页面不要为单个组件随意指定不同中文字体。
- 基础字号以当前窗口缩放逻辑为准，避免在页面内硬编码大号标题。

### 4.2 聊天主窗

聊天窗使用：

```text
'Microsoft YaHei', 'SimHei', 'Arial'
```

规则：

- 对白字号随窗口缩放，不按视口宽度直接线性缩放。
- 对白行高保持宽松，当前标准为约 `150%` 到 `200%`。
- 不使用负字距。聊天对白可保留轻微正字距，但不要影响可读性。

## 5. 布局标准

### 5.1 设置中心布局

设置中心采用固定 shell：

```text
AppShell = SidebarNav + TopBar + ContentOutlet + BottomBar
```

页面内容规则：

- 主内容放入可滚动区域，避免窗口变小时控件被截断。
- 表单使用标签 + 控件的稳定行结构。
- 复杂功能拆成分组：配置、路径、模型参数、高级选项、操作区。
- 页面底部的主要操作按钮靠近相关内容，不悬浮遮挡表单。
- 长列表和表格需要固定表头、明确选择态和空状态。

React 组件建议：

```text
<AppShell>
  <SidebarNav />
  <TopBar />
  <ContentOutlet />
  <BottomBar />
</AppShell>
```

### 5.2 聊天主窗布局

聊天主窗采用舞台式布局：

```text
Background / Sprite Layer
Dialog Layer
Options Layer
Input Layer
Toolbar Layer
```

规则：

- 背景和立绘优先占据窗口主体。
- 对话框位于底部或偏底部，不能遮挡角色脸部的主要区域。
- 选项列表与对白区同属叙事层，样式保持一致。
- 输入栏贴近底部，透明窗模式下要避开窗口边缘和系统安全区。
- 工具栏使用半透明背景，按钮以图标或短文本为主。

React 组件建议：

```text
<ChatStage>
  <BackgroundLayer />
  <SpriteLayer />
  <DialogLayer />
  <OptionsLayer />
  <InputLayer />
  <FloatingToolbar />
</ChatStage>
```

## 6. 组件规范

### 6.1 按钮

设置页按钮：

- 背景：`#343b48`
- Hover：`#394150`
- Pressed：`#232831`
- 圆角：`5px`
- 边框：`2px solid #343b48`

聊天窗按钮：

- 发送按钮使用主题色 `theme_color`。
- 工具按钮使用半透明白底和白色边框。
- 跳过语音等轻量按钮允许透明背景，仅在 hover 时显示反馈。
- 危险操作必须有确认弹窗，不只依赖颜色表达风险。

React 组件命名：

- `Button`
- `IconButton`
- `AsyncButton`
- `DangerButton`
- `ToolbarButton`

按钮必须支持 `disabled`、`loading`、`focus-visible` 和 tooltip。

### 6.2 输入框

设置页输入框：

- 背景：`#21252b` 或 `#1b1d23`
- 边框默认与背景接近，hover/focus 时提高对比。
- Focus 边框：`#5b657c`
- 文本选择色：`#ff79c6`

聊天输入框：

- 背景：`rgba(50,50,50,0.78)`
- 文字：白色
- 圆角：`5px`
- Padding：约 `8px 10px`

React 组件命名：

- `TextInput`
- `TextArea`
- `Select`
- `FilePicker`
- `NumberInput`
- `ColorInput`

表单组件必须支持错误态、说明文本、禁用态和受控/非受控边界。

### 6.3 分段导航

分段导航用于同一功能内的子页切换，替代复杂的多级标签页：

- 未选中：透明背景、白字。
- 选中：强调色文字 + 底部 `2px` 强调线。
- Hover：轻微半透明白色背景。
- 子页只有一个时隐藏导航条。

React 组件命名：`SegmentedTabs`。

### 6.4 表格与列表

- 表格背景保持透明或深色，不使用亮色表格。
- 选中态使用 `#bd93f9` 或 `#404758`。
- 行内操作按钮保持短标签，批量操作放到表格上方或下方。
- 空列表应显示简短空状态和一个明确操作入口。

React 组件命名：

- `DataTable`
- `ListView`
- `EmptyState`
- `InlineActions`

### 6.5 Toast 与弹窗

- 成功、普通提示使用 Toast。
- 失败、校验错误、破坏性操作使用 `Dialog` 或 `AlertDialog`。
- Toast 最大宽度约 `420px`，圆角约 `12px`，展示时间约 `4500ms`。

## 7. 聊天主题扩展

聊天窗允许通过 `data/chat_ui_theme.json` 或配置路径覆盖局部外观。主题扩展只能影响视觉声明，不应改变布局稳定性。

允许：

- 背景色、边框色、边框图、阴影感、圆角。
- 对话框、数值信息、选项、输入栏、忙碌提示、麦克风按钮外观。
- `dialog_offset_y`、`dialog_width_pct`、`dialog_padding`、`options_gap` 这类受控布局参数。

禁止：

- 直接覆盖 `width`、`height`、`min-width`、`max-width`、`position`、`left`、`right`、`top`、`bottom`、`font-size` 等破坏布局和缩放的 CSS。
- 用主题文件覆盖整套控件结构。
- 让主题依赖绝对屏幕尺寸。

React 实现：

- 主题 JSON 进入 `theme/chatChromeTheme.ts` 解析。
- 解析结果转成 CSS variables 或受控 style object。
- 所有用户主题字段必须经过 allowlist 过滤。
- 组件只读取 theme token，不拼接任意 CSS 字符串。

## 8. 交互标准

### 8.1 状态反馈

每个会耗时的操作都需要明确状态：

- 保存配置：成功 Toast，失败弹窗。
- 导入/导出：显示文件结果或错误原因。
- 下载/安装插件：显示进度、完成、失败和重试入口。
- 启动聊天：失败时说明缺少历史、模板或可执行文件。

### 8.2 异步任务

- 不在 React 渲染路径中执行网络、模型、下载、安装、生成图片等耗时任务。
- 异步任务期间禁用相关按钮或显示 busy 状态。
- 任务完成后恢复原控件状态。

React 实现：

- 用 `useMutation` 或等价 mutation 封装保存、导入、安装、生成等命令。
- mutation 状态必须映射到按钮 `loading`、表单 `disabled`、Toast/Dialog。
- 长任务需要进度事件，进度从 IPC/WebSocket/SSE 或轮询进入 store。

### 8.3 选择与确认

- 删除角色、覆盖文件、禁用插件、清空历史等操作必须确认。
- 文件选择控件应显示当前路径，并提供重新选择入口。
- 路径错误、URL 错误、空值错误应在提交前阻断。

## 9. 状态管理标准

### 9.1 页面状态

- 表单草稿态保存在页面组件或表单库中。
- 当前选中 tab、展开分组、临时过滤条件保存在 route query 或页面局部状态。
- 全局主题、语言、用户偏好保存在 app store。

### 9.2 领域状态

- 配置、角色、背景、插件、模板等数据通过 repository/query 层读取。
- 保存成功后刷新对应 query，避免手动同步多份副本。
- 聊天运行态使用明确状态机：`idle`、`listening`、`generating`、`streaming`、`speaking`、`paused`、`error`。

### 9.3 插件 UI

- 插件只能贡献到固定 slot：设置页扩展、工具页扩展、聊天工具栏扩展、聊天输出扩展。
- 插件贡献必须声明 id、title、icon、权限、渲染组件和配置 schema。
- 插件 UI 不能直接修改全局 CSS，也不能替换 AppShell。

## 10. 文案标准

- 设置中心文案要短、明确、工具化。
- 按钮使用动词：保存、导入、导出、删除、生成、启动。
- 错误信息说明原因和下一步，不只写“失败”。
- 不在界面上解释过多功能原理，复杂说明放到文档或 tooltip。
- 中文和英文之间保留空格，例如 `LLM 模型`、`API Key`。

## 11. 图标与资源

- 设置中心优先使用 `lucide-react`，必要时沿用现有资源图标体系。
- 图标作为导航和按钮辅助，不单独承担不可理解的含义。
- 图标按钮必须有 tooltip。
- 聊天窗视觉资源优先展示真实背景、立绘、CG 或边框图，不使用抽象占位图长期替代。
- 图片加载失败时要有明确降级样式，不能出现空白控件。

## 12. 可访问性与稳定性

- 文本和背景必须保持足够对比度。
- 控件最小点击区域不低于 `32px`，主要操作建议不低于 `36px`。
- 所有文字必须在窗口缩放后仍可读，不应被按钮边界裁切。
- 页面应支持窗口缩小后的滚动，不靠隐藏关键控件解决拥挤。
- 所有交互控件必须有 `focus-visible` 状态。
- Dialog、Menu、Select、Popover 必须支持键盘操作和焦点管理。

## 13. 重写约束

后续重写前端时，应遵循以下边界：

- 保留设置中心与聊天主窗的体验分工。
- 设置中心继续走工具型高密度布局，不做大面积营销式 hero。
- 聊天主窗继续以角色演出为中心，控件浮层服从立绘和对白。
- 业务逻辑、配置读写、插件注册不要写进 React 组件层。
- 新组件优先沉淀到共享组件库，再进入具体页面。
- 新主题能力必须通过受控 token 或 schema 暴露，不能让插件任意破坏主布局。

## 14. 新页面验收清单

新增或重写页面前，检查：

- 是否符合暗色 token 和强调色体系。
- 是否使用统一按钮、输入框、分段导航、toast 和弹窗行为。
- 是否有 loading、success、failure、empty、disabled 状态。
- 是否能在小窗口中滚动使用。
- 是否避免嵌套卡片和无意义装饰。
- 是否把文件读写、网络请求、插件操作放到 repository、service、mutation 或 platform adapter。
- 是否支持 i18n 文案刷新。
- 是否没有硬编码绝对屏幕尺寸和不可控字号。
- 是否有键盘焦点态和基础可访问性属性。
- 是否为关键流程补充组件测试或 Playwright 回归截图。
