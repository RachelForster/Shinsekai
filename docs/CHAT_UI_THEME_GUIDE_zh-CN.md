# 聊天皮肤定义与制作指南

本文定义 Shinsekai 聊天皮肤的目录结构、`theme.json` 字段、资源规则、SVG 九宫格边框以及校验和安装流程。

代码中使用的正式名称是“聊天主题”（chat UI theme）；本文中的“皮肤”和“主题”含义相同。当前清单版本为 `schema: 1`，权威校验实现位于 [`sdk/chat_ui_theme.py`](../sdk/chat_ui_theme.py)。若文档与校验器出现差异，以当前版本的校验器为准。

## 1. 设计边界

一个主题只能包含 JSON 和静态资源，不能包含 JavaScript、CSS 文件或其它可执行代码。主题可以改变：

- 对话框、姓名框、选项、输入框、工具条和发送按钮的视觉；
- 日志页的面板、列表、代码区和日志级别配色；
- 字体、背景图、打字速度和打字音效；
- 受控的尺寸、位置和布局枚举；
- 支持边框层的组件所使用的独立 SVG 或位图九宫格边框。

主题不能替换 React 组件结构，也不能注入任意 CSS 声明。没有填写的字段继续使用宿主基础样式，因此主题可以只覆盖自己需要的部分。

## 2. 最快上手

### 2.1 目录结构

建议把静态资源放进 `assets/`，但资源只要位于主题根目录内即可：

```text
my-theme/
  theme.json
  preview.png
  assets/
    frame-dialog.svg
    frame-name.svg
    background.webp
    font.woff2
    type.wav
```

所有资源路径都相对于 `theme.json` 所在目录。例如：

```json
{
  "preview": "preview.png",
  "tokens": {
    "dialog": {
      "frameImage": "assets/frame-dialog.svg"
    }
  }
}
```

### 2.2 最小合法主题

```json
{
  "schema": 1,
  "id": "my-theme",
  "name": {
    "zh_CN": "我的皮肤"
  },
  "tokens": {}
}
```

### 2.3 一个可直接修改的主题

下面的示例只给对话框配置不规则 SVG。输入框、选项和工具条仍使用各自的普通 CSS 边框，不会跟随对话框变形。

```json
{
  "schema": 1,
  "id": "my-neon-theme",
  "name": {
    "zh_CN": "我的霓虹皮肤",
    "en": "My Neon Theme"
  },
  "author": "Your Name",
  "version": "1.0.0",
  "description": {
    "zh_CN": "对话框使用不规则 SVG，其他控件保持圆角。"
  },
  "preview": "preview.png",
  "tokens": {
    "global": {
      "themeColor": "#00f5ff",
      "fontFamily": "Segoe UI, sans-serif"
    },
    "dialog": {
      "background": "rgba(2, 8, 20, 0.92)",
      "borderColor": "rgba(0, 245, 255, 0.12)",
      "borderRadius": "4px",
      "color": "#e9fbff",
      "frameImage": "assets/frame-dialog.svg",
      "frameSlice": 28,
      "frameWidthPx": 28,
      "frameOutsetPx": 2,
      "padding": 24,
      "widthPct": 84
    },
    "options": {
      "background": "rgba(3, 12, 28, 0.92)",
      "borderColor": "rgba(0, 245, 255, 0.72)",
      "borderRadius": "999px",
      "color": "#e9fbff"
    },
    "input": {
      "background": "rgba(2, 8, 20, 0.94)",
      "borderColor": "rgba(0, 245, 255, 0.72)",
      "borderRadius": "999px",
      "layout": "pill"
    },
    "toolbar": {
      "background": "rgba(3, 10, 24, 0.88)",
      "borderColor": "rgba(0, 245, 255, 0.5)",
      "borderRadius": "999px",
      "placement": "input-top",
      "reveal": "hover"
    },
    "typewriter": {
      "cps": 40
    }
  }
}
```

## 3. 校验、打包和安装

在仓库根目录执行：

```bash
python -m sdk.chat_ui_theme validate ./my-theme
python -m sdk.chat_ui_theme pack ./my-theme -o ./dist/my-theme.zip
```

`validate` 输出 `OK` 表示字段契约通过；`[warn]` 表示主题仍可使用，但应在发布前修复。当前版本中，资源文件不存在只会产生警告，不会让校验或打包失败。

生成的 ZIP 可以从聊天窗口的调色板按钮打开主题选择器，再选择“上传主题”安装。压缩包只支持以下两种结构：

```text
theme.zip
  theme.json
  ...
```

或：

```text
theme.zip
  my-theme/
    theme.json
    ...
```

第二种结构中只能有一个顶层主题目录。安装后的用户主题位于 `data/chat_ui_themes/<id>/`。本地开发时也可以把目录直接放到这里，再在主题选择器中刷新。

目录名应与 `theme.json` 的 `id` 一致。宿主直接扫描目录时，目录名是实际使用的主题 ID。上传相同 ID 的主题不会默认覆盖；可先删除旧主题再重新安装。

## 4. `theme.json` 顶层字段

| 字段 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- |
| `schema` | 是 | `1` | 当前只接受整数 `1`。 |
| `id` | 是 | string | 1–64 个字符；匹配 `[a-z0-9][a-z0-9_-]{0,63}`。只使用小写字母、数字、`-` 和 `_`。 |
| `name` | 是 | object | 多语言名称，如 `{ "zh_CN": "夜城", "en": "Night City" }`；至少一个值非空。 |
| `tokens` | 是 | object | 主题令牌，允许的顶层块见后文。 |
| `author` | 否 | string | 作者或组织名。 |
| `version` | 否 | string | 建议使用 SemVer，例如 `1.2.0`。 |
| `description` | 否 | object | 多语言主题说明。 |
| `preview` | 否 | string | 预览图的主题内相对路径。 |

显示名称按“当前界面语言 → `zh_CN` → `en` → `id`”回退。安装时清单会被规整，未列出的顶层字段可能被移除；不要依赖自定义顶层字段或不存在的 `$schema` 文件。

## 5. 资源和 CSS 值规则

### 5.1 资源路径

`preview`、`backgroundImage`、`frameImage`、字体 `src` 和打字音效 `sound` 必须使用主题目录内的相对路径。

允许：

```text
preview.png
assets/frame-dialog.svg
assets/fonts/my-font.woff2
```

禁止：

```text
../shared/frame.svg
C:\images\frame.svg
/home/me/frame.svg
https://example.com/frame.svg
file:///frame.svg
data:image/svg+xml,...
```

路径统一建议使用 `/`。发布前必须处理所有“引用的资源不存在”警告，否则对应图片、字体或声音在运行时不会生效。

### 5.2 CSS 值

主题字段填写的是单个 CSS 属性值，不是 CSS 声明。例如：

```json
{
  "background": "linear-gradient(135deg, rgba(2,8,20,0.94), rgba(19,3,27,0.9))",
  "boxShadow": "0 0 24px rgba(0,245,255,0.2)",
  "borderRadius": "12px"
}
```

字符串值不能包含：

- `{`、`}` 或 `;`；
- `url(...)`；图片必须通过 `backgroundImage` 或 `frameImage` 引用；
- `width:`、`height:`、`min-width:`、`max-width:`、`min-height:`、`max-height:`；
- `position:`、`left:`、`right:`、`top:`、`bottom:`、`font-size:`。

需要调整尺寸和布局时，使用规范中对应的数字字段或枚举字段。

## 6. 通用视觉字段

普通视觉块 `VisualBlock` 支持以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `background` | string | 背景颜色或渐变。 |
| `backgroundImage` | string | 主题内背景图路径。 |
| `borderColor` | string | 普通 CSS 边框颜色。 |
| `borderRadius` | string | 普通 CSS 圆角。 |
| `boxShadow` | string | 外阴影或内阴影。 |
| `color` | string | 文本或图标颜色。 |
| `padding` | number | 内边距，范围 `8–72` px。 |

`dialog`、`options`、`input`、`toolbar`、`send`、`name` 以及多数 `logs` 子块都继承这些字段。状态块如 `options.hover`、`options.active` 也是普通 `VisualBlock`。

## 7. 独立 SVG 九宫格边框

### 7.1 支持位置

SVG 边框不是全局皮肤层，每个组件单独配置：

| 配置块 | 实际作用位置 |
| --- | --- |
| `tokens.dialog` | 对话框外壳。 |
| `tokens.name` | 姓名框。 |
| `tokens.options` | 每一个选项按钮；所有选项共享该定义。 |
| `tokens.input` | 输入区外壳。 |
| `tokens.toolbar` | 当前显示的工具条外壳。 |
| `tokens.logs.panel` | 日志工具条、侧栏和查看器的公共边框回退。 |
| `tokens.logs.toolbar` | 单独覆盖日志工具条。 |
| `tokens.logs.sidebar` | 单独覆盖日志侧栏。 |
| `tokens.logs.viewer` | 单独覆盖日志查看器。 |

`send`、`options.active`、`options.hover`、日志行和徽章等高密度元素没有独立边框层。不要在这些块上配置 SVG frame。

为兼容早期 `schema: 1` 主题，校验器可能仍接受不支持位置上的 `frameImage` 和 `frameSlice`，但前端不会渲染它们；`frameWidthPx` 和 `frameOutsetPx` 则会直接被拒绝。应始终以本节表格列出的支持位置为准。

如果某个组件没有填写 `frameImage`，它的 SVG 边框层不可见，普通 `borderColor` 和 `borderRadius` 仍然生效。因此只给 `dialog` 填写 `frameImage`，不会影响 `input`、`options` 或 `toolbar`。

### 7.2 Frame 字段

支持边框层的块是 `FrameVisualBlock`，比普通视觉块多四个字段：

| 字段 | 类型和范围 | 默认行为 |
| --- | --- | --- |
| `frameImage` | 相对路径 | SVG 或位图九宫格素材；省略时不显示边框层。 |
| `frameSlice` | `1–200` | 素材坐标系中的切片值；存在图片时默认 `32`。 |
| `frameWidthPx` | `0–96` | 屏幕上的九宫格边框带宽，决定角块显示尺寸和素材缩放；省略时回退为最终 `frameSlice`。 |
| `frameOutsetPx` | `0–96` | 向组件外绘制的距离；默认 `0`，不参与布局。 |

建议总是显式填写 `frameWidthPx`。它不是 SVG 线条的 stroke 粗细，而是九宫格角块在屏幕上的目标宽高。若希望素材按 1:1 比例显示并避免角块压缩，可让它与 `frameSlice` 使用相同数值；需要整体缩放边框时再按比例调整。

边框运行时是覆盖在组件上的绝对定位透明层：`inset: 0`、`pointer-events: none`、`border-image-repeat: stretch`。中间边条会拉伸到组件边缘之间，不会重复平铺装饰片段。它不会改变文本、按钮或输入框的位置。SVG 可以形成不规则的视觉轮廓，但组件的布局盒和点击区域仍是原来的矩形。`frameOutsetPx` 也不占布局空间，值过大时可能与相邻组件重叠，或被祖先容器裁切。

### 7.3 SVG 制作建议

推荐使用方形或接近方形的 `viewBox`，例如 `128 × 128`：

```svg
<svg xmlns="http://www.w3.org/2000/svg"
     width="128" height="128" viewBox="0 0 128 128"
     preserveAspectRatio="none">
  <path
    d="M28 4H100L124 28V100L108 124H28L4 100V28Z"
    fill="none"
    stroke="#69f9ff"
    stroke-width="2" />
</svg>
```

对应配置：

```json
{
  "frameImage": "assets/frame-dialog.svg",
  "frameSlice": 28,
  "frameWidthPx": 28,
  "frameOutsetPx": 2
}
```

制作时注意：

- `frameSlice` 按 SVG 的 `viewBox` 坐标计算，而不是屏幕像素；
- 切片值应小于素材宽高的一半，确保四角之间仍有可重复的边段；
- 把关键切角和装饰放在四角切片内，把可拉伸的连续线条放在边段；
- 中心区域不会作为面板内容填充，面板底色应写在 `background`；
- 建议使用 `preserveAspectRatio="none"`，并在不同宽高比下预览；
- 线条、辉光和外伸装饰应留出安全边距，避免裁切；
- 不同形态的组件应使用不同素材。对话框素材通常不适合直接复用于输入框或胶囊选项。

当前赛博朋克主题可作为参考：

- [`frame-dialog.svg`](../assets/chat_ui_themes/neon-night-city/frame-dialog.svg)：`128 × 128`，`slice 28 / width 28 / outset 2`；
- [`frame-name.svg`](../assets/chat_ui_themes/neon-night-city/frame-name.svg)：`96 × 64`，`slice 16 / width 16 / outset 2`；
- [`frame-panel.svg`](../assets/chat_ui_themes/neon-night-city/frame-panel.svg)：`96 × 96`，`slice 24 / width 24 / outset 2`。

## 8. Token 定义

`tokens` 顶层只允许：

```text
global, fonts, dialog, options, input, toolbar, send, name, logs, typewriter
```

### 8.1 `global`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `themeColor` | string | 主题强调色。 |
| `fontFamily` | string | 聊天区默认字体族；可引用 `fonts` 中声明的字体。 |

### 8.2 `fonts`

`fonts` 是自定义字体数组，每项会生成一个带 `font-display: swap` 的 `@font-face`：

```json
{
  "fonts": [
    {
      "family": "My Theme Font",
      "src": "assets/fonts/my-theme.woff2",
      "weight": "400 800",
      "style": "normal"
    }
  ],
  "global": {
    "fontFamily": "My Theme Font, sans-serif"
  }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `family` | 是 | 字体族名称。 |
| `src` | 是 | 主题内字体文件路径。 |
| `weight` | 否 | CSS 字体粗细值或范围。 |
| `style` | 否 | CSS 字体样式，如 `normal`、`italic`。 |

### 8.3 `dialog`

`dialog` 是 `FrameVisualBlock`，并支持：

| 字段 | 类型或范围 | 说明 |
| --- | --- | --- |
| `chrome` | `panel \| none` | `panel` 为面板模式；`none` 为字幕布局。字幕主题通常同时使用透明背景并省略 frame。 |
| `widthPct` | `30–100` | 对话框视口宽度百分比，上限仍受宿主安全宽度约束。 |
| `heightPx` | `96–260` | 对话区固定高度。`chrome: none` 且省略时，当前运行时使用 156 px。 |
| `nameInputGapVh` | `12–32` | 姓名装饰中心线到输入区顶部的目标距离，单位 `svh`。 |
| `offsetY` | `-240–240` | 对话框垂直偏移，单位 px。 |
| `textAlign` | `left \| center` | 正文对齐方式。 |
| `textShadow` | string | 正文文字阴影。 |
| `textSizePx` | `12–64` | 正文字号。 |
| `textWeight` | `300–900` | 正文字重。 |

### 8.4 `options`

`options` 是 `FrameVisualBlock`。frame 会应用到每一个选项按钮。

| 字段 | 类型或范围 | 说明 |
| --- | --- | --- |
| `active` | `VisualBlock` | 当前激活或选中状态。 |
| `hover` | `VisualBlock` | 鼠标悬停状态。 |
| `gap` | `0–36` | 选项间距，单位 px。 |
| `icon` | `none \| chat` | 是否显示聊天图标。 |
| `placement` | `center \| right` | 选项组居中或靠右。 |
| `widthMode` | `fixed \| content` | 固定宽度或按内容宽度。 |
| `widthPx` | `260–720` | `fixed` 模式宽度。 |
| `minWidthVw` | `12–42` | `content` 模式最小宽度。 |
| `maxWidthVw` | `20–60` | `content` 模式最大宽度。 |
| `minHeightPx` | `36–96` | 选项最小高度，单位 px。 |
| `minHeightVh` | `3–8` | 响应式最小高度，单位 `svh`。 |
| `nameClearanceVh` | `2–12` | 选项与姓名区域的安全距离。 |
| `textSizePx` | `12–64` | 选项文字固定字号。 |
| `textSizeVh` | `1–4` | 选项文字响应式字号。 |
| `textWeight` | `300–900` | 选项字重。 |
| `textShadow` | string | 选项文字阴影。 |

如果同时填写 `minHeightPx` 与 `minHeightVh`，响应式的 `minHeightVh` 最终生效；`textSizeVh` 同样会覆盖 `textSizePx` 对应的最终 CSS 变量。

### 8.5 `input`

`input` 是 `FrameVisualBlock`，作用于整个输入区外壳。

| 字段 | 类型或范围 | 说明 |
| --- | --- | --- |
| `layout` | `default \| pill` | 默认布局或一体式胶囊布局。 |
| `maxWidthPx` | `320–900` | 输入区最大宽度；`pill` 省略时使用 640 px。 |
| `sendPlacement` | `outside \| inside` | 默认布局中发送按钮在输入区外或内。`pill` 自带提交面，不使用 `inside` 变体。 |
| `fieldBackground` | string | 内层文本输入面的背景。 |
| `fieldBorderRadius` | string | 内层文本输入面的圆角。 |

布局预设先应用，显式填写的通用视觉字段、`fieldBackground`、`fieldBorderRadius` 和 `maxWidthPx` 后应用，因此显式字段优先。

### 8.6 `toolbar`

`toolbar` 是 `FrameVisualBlock`。

| 字段 | 可选值 | 说明 |
| --- | --- | --- |
| `placement` | `dialog-top \| input \| input-top` | 工具条位于对话框顶部、输入区内或输入区顶部。 |
| `reveal` | `always \| hover` | 总是显示或悬停时显示。 |

只有填写有效 `placement` 时才会启用对应的定位预设；此时省略 `reveal` 按 `always` 处理。

### 8.7 `send`

`send` 只接受普通 `VisualBlock`，用于发送按钮。它没有独立 SVG frame 层。

### 8.8 `name`

`name` 是 `FrameVisualBlock`。

| 字段 | 类型或范围 | 说明 |
| --- | --- | --- |
| `align` | `left \| center` | 姓名框对齐方式。 |
| `decoration` | `accent \| line-dots` | 强调装饰或两侧线点装饰。 |
| `fontFamily` | string | 姓名单独使用的字体族，优先于 `global.fontFamily`。 |
| `hideWhenStartOption` | boolean | 起始选项出现时隐藏姓名。 |
| `textShadow` | string | 姓名文字阴影。 |
| `textSizePx` | `12–56` | 当前前端有效字号范围。SDK 校验兼容到 64，但运行时上限为 56。 |
| `textWeight` | `300–900` | 姓名字重。 |

### 8.9 `logs`

日志子块同样使用通用视觉字段：

| 子块 | 类型 | 作用 |
| --- | --- | --- |
| `page` | `VisualBlock` | 日志页整体。 |
| `panel` | `FrameVisualBlock` | 日志主面板样式，也是 toolbar/sidebar/viewer 的公共 frame 回退。 |
| `toolbar` | `FrameVisualBlock` | 日志工具条，可覆盖 panel frame。 |
| `sidebar` | `FrameVisualBlock` | 日志文件侧栏，可覆盖 panel frame。 |
| `viewer` | `FrameVisualBlock` | 日志查看器，可覆盖 panel frame。 |
| `source` | `VisualBlock` | 日志来源标签。 |
| `code` | `VisualBlock + fontFamily` | 代码或原始内容区。 |
| `line` | `VisualBlock + hover + expanded` | 日志行及其状态。 |
| `number` | `VisualBlock` | 行号。 |
| `detail` | `VisualBlock` | 日志详情。 |
| `badge` | `VisualBlock` | 普通徽章。 |
| `event` | `VisualBlock` | 事件徽章。 |
| `fileItem` | `VisualBlock + hover + active` | 文件列表项及其状态。 |
| `levels` | object | `debug`、`default`、`error`、`info`、`warn`，每项为 `VisualBlock`。 |

`logs.panel.frame*` 本身不是第四个独立可见边框；它给日志工具条、侧栏和查看器提供公共默认值。需要三个不同外形时，在 `logs.toolbar`、`logs.sidebar`、`logs.viewer` 中分别覆盖。

没有显式填写日志样式时，宿主会从聊天主题中派生一部分普通视觉值，但不会把聊天组件的 SVG frame 带进日志页：

| 日志块 | 普通视觉回退来源 |
| --- | --- |
| `page` | `dialog.color` |
| `panel` | `toolbar`，没有时使用 `dialog` |
| `toolbar` | `toolbar` |
| `sidebar` | `toolbar`，没有时使用 `input` |
| `source`、`event` | `options` 的背景和边框，加 `name.color` 或 `global.themeColor` |
| `viewer` | `dialog` |
| `code` | `input.fieldBackground`、`input.background` 或 `dialog.background`；颜色来自 `input` 或 `dialog` |
| `detail` | `input` |
| `badge` | `options.color` 或 `dialog.color` |

`line`、`number`、`fileItem` 和 `levels` 没有聊天 token 回退，省略时使用日志页基础 CSS。

### 8.10 `typewriter`

| 字段 | 类型或范围 | 说明 |
| --- | --- | --- |
| `cps` | `1–200` | 每秒显示字符数；省略时为 40。 |
| `sound` | string | 主题内打字音效相对路径。 |

## 9. 数值范围总表

越界数字会被收敛到允许范围，而不是让主题任意撑破布局。

| 字段 | 范围 |
| --- | --- |
| `padding` | `8–72` |
| `dialog.widthPct` | `30–100` |
| `dialog.heightPx` | `96–260` |
| `dialog.nameInputGapVh` | `12–32` |
| `dialog.offsetY` | `-240–240` |
| `options.gap` | `0–36` |
| `typewriter.cps` | `1–200` |
| `frameSlice` | `1–200` |
| `frameWidthPx`、`frameOutsetPx` | `0–96` |
| `options.minHeightPx` | `36–96` |
| `options.minHeightVh` | `3–8` |
| `options.minWidthVw` | `12–42` |
| `options.maxWidthVw` | `20–60` |
| `input.maxWidthPx` | `320–900` |
| `options.nameClearanceVh` | `2–12` |
| `options.textSizeVh` | `1–4` |
| `textSizePx` | 通常 `12–64`；`name` 当前有效上限为 `56` |
| `textWeight` | `300–900` |
| `options.widthPx` | `260–720` |

## 10. 回退和优先级

- 主题可以是局部定义；省略字段时，不会自动复制另一个主题的同名字段，而是继续使用宿主基础 CSS。
- 布局预设先应用，显式视觉字段后应用，显式字段优先。
- 没有 `frameImage` 时，`frameSlice`、`frameWidthPx` 或 `frameOutsetPx` 单独存在也不会产生可见边框。
- 聊天组件的 frame 相互独立，不会跨组件继承。
- 日志的普通视觉值有上一节所述回退；聊天 frame 会被移除。只有 `logs.panel.frame*` 会作为三个日志容器的公共 frame 回退。
- 当前活动主题无法读取时，应用会尝试内置默认主题 `windborne-adventure`；仍不可用时回退到宿主基础样式。

## 11. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 所有框都变成同一个形状 | 在多个块中重复填写了同一个 `frameImage`。只在需要的组件上配置，或分别提供素材。 |
| 边框整体过大或过小 | `frameWidthPx` 与期望的素材显示比例不匹配。1:1 显示时让它与 `frameSlice` 相同，再按比例微调。 |
| 边线分成重复小节 | 使用了会平铺边段的旧版 `round` 渲染。升级到使用 `stretch` 的版本，并确保边段只包含可连续拉伸的线条。 |
| 四角被拉扯或边线错位 | `frameSlice` 与素材 `viewBox` 不匹配。根据角区实际尺寸调整，并保证切片小于宽高的一半。 |
| SVG 没显示 | 检查相对路径、文件是否存在、配置块是否支持 frame，以及 `frameWidthPx` 是否为 0。 |
| 选项按钮全部出现边框 | `tokens.options` 定义的是每一个选项的共同外观，这是预期行为。 |
| 外伸装饰被裁切 | 减小 `frameOutsetPx`，或把装饰向素材内部移动。outset 不会申请额外布局空间。 |
| `background` 中的图片被拒绝 | 不能写 `url(...)`；改用 `backgroundImage`。 |
| 校验为 `OK` 但图片不显示 | 缺失资源当前只产生 warning。修复所有 warning 后再发布。 |
| ZIP 提示找不到 `theme.json` | 把清单放到 ZIP 根目录，或唯一的一层顶级目录内。 |
| 上传提示主题已存在 | 用户主题默认不覆盖同 ID 目录；先删除旧主题，或在本地开发目录中替换后刷新。 |

## 12. 完整参考主题

- 赛博朋克与独立 SVG frame：[`assets/chat_ui_themes/neon-night-city/theme.json`](../assets/chat_ui_themes/neon-night-city/theme.json)
- 无 SVG frame 的 ADV 主题：[`assets/chat_ui_themes/windborne-adventure/theme.json`](../assets/chat_ui_themes/windborne-adventure/theme.json)
- 前端类型与运行时解析：[`frontend/src/shared/theme/chatTheme.ts`](../frontend/src/shared/theme/chatTheme.ts)
- 权威校验与打包工具：[`sdk/chat_ui_theme.py`](../sdk/chat_ui_theme.py)

发布主题前，至少执行一次 `validate`，在宽屏和窄屏中分别查看对话框、长姓名、多行输入和多选项场景，并确认所有资源警告已经处理。
