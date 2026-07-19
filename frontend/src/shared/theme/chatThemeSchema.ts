import type { MessageKey } from "../i18n";

export type ChatThemeEditorFieldKind = "asset" | "boolean" | "color" | "number" | "select" | "text";

export interface ChatThemeEditorFieldOption {
  label: string;
  value: string;
}

export interface ChatThemeEditorField {
  advanced?: boolean;
  kind: ChatThemeEditorFieldKind;
  labelKey: MessageKey;
  max?: number;
  min?: number;
  options?: ChatThemeEditorFieldOption[];
  path: string;
  step?: number;
  suffix?: string;
}

export interface ChatThemeEditorSection {
  advanced?: boolean;
  fields?: ChatThemeEditorField[];
  id: string;
  labelKey: MessageKey;
  path: string;
  sections?: ChatThemeEditorSection[];
}

const visualFields = (path: string, frame = false): ChatThemeEditorField[] => [
  { kind: "color", labelKey: "chat.theme.customizer.background", path: `${path}.background` },
  {
    advanced: true,
    kind: "asset",
    labelKey: "chat.theme.customizer.backgroundImage",
    path: `${path}.backgroundImage`,
  },
  { kind: "color", labelKey: "chat.theme.customizer.textColor", path: `${path}.color` },
  { kind: "color", labelKey: "chat.theme.customizer.borderColor", path: `${path}.borderColor` },
  { kind: "text", labelKey: "chat.theme.customizer.borderRadius", path: `${path}.borderRadius` },
  { advanced: true, kind: "text", labelKey: "chat.theme.customizer.boxShadow", path: `${path}.boxShadow` },
  {
    advanced: true,
    kind: "number",
    labelKey: "chat.theme.customizer.padding",
    max: 72,
    min: 8,
    path: `${path}.padding`,
    suffix: "px",
  },
  ...(frame
    ? [
        {
          advanced: true,
          kind: "asset" as const,
          labelKey: "chat.theme.customizer.frameImage" as MessageKey,
          path: `${path}.frameImage`,
        },
        {
          advanced: true,
          kind: "number" as const,
          labelKey: "chat.theme.customizer.frameSlice" as MessageKey,
          max: 200,
          min: 1,
          path: `${path}.frameSlice`,
        },
        {
          advanced: true,
          kind: "number" as const,
          labelKey: "chat.theme.customizer.frameWidth" as MessageKey,
          max: 96,
          min: 0,
          path: `${path}.frameWidthPx`,
          suffix: "px",
        },
        {
          advanced: true,
          kind: "number" as const,
          labelKey: "chat.theme.customizer.frameOutset" as MessageKey,
          max: 96,
          min: 0,
          path: `${path}.frameOutsetPx`,
          suffix: "px",
        },
      ]
    : []),
];

const textSize = (path: string, max = 64): ChatThemeEditorField => ({
  kind: "number",
  labelKey: "chat.theme.customizer.fontSize",
  max,
  min: 12,
  path,
  suffix: "px",
});

const textWeight = (path: string): ChatThemeEditorField => ({
  kind: "number",
  labelKey: "chat.theme.customizer.fontWeight",
  max: 900,
  min: 300,
  path,
  step: 100,
});

const logVisualSection = (id: string, labelKey: MessageKey, path: string, frame = false): ChatThemeEditorSection => ({
  fields: visualFields(path, frame).map((field) => ({ ...field, advanced: false })),
  id,
  labelKey,
  path,
});

const logSections: ChatThemeEditorSection[] = [
  logVisualSection("logs-page", "chat.theme.customizer.logsPage", "logs.page"),
  logVisualSection("logs-panel", "chat.theme.customizer.logsPanel", "logs.panel", true),
  logVisualSection("logs-toolbar", "chat.theme.customizer.logsToolbar", "logs.toolbar", true),
  logVisualSection("logs-sidebar", "chat.theme.customizer.logsSidebar", "logs.sidebar", true),
  logVisualSection("logs-source", "chat.theme.customizer.logsSource", "logs.source"),
  logVisualSection("logs-viewer", "chat.theme.customizer.logsViewer", "logs.viewer", true),
  {
    ...logVisualSection("logs-code", "chat.theme.customizer.logsCode", "logs.code"),
    fields: [
      ...visualFields("logs.code").map((field) => ({ ...field, advanced: false })),
      { kind: "text", labelKey: "chat.theme.customizer.fontFamily", path: "logs.code.fontFamily" },
    ],
  },
  {
    ...logVisualSection("logs-line", "chat.theme.customizer.logsLine", "logs.line"),
    sections: [
      logVisualSection("logs-line-hover", "chat.theme.customizer.stateHover", "logs.line.hover"),
      logVisualSection("logs-line-expanded", "chat.theme.customizer.stateExpanded", "logs.line.expanded"),
    ],
  },
  logVisualSection("logs-number", "chat.theme.customizer.logsNumber", "logs.number"),
  logVisualSection("logs-detail", "chat.theme.customizer.logsDetail", "logs.detail"),
  logVisualSection("logs-badge", "chat.theme.customizer.logsBadge", "logs.badge"),
  logVisualSection("logs-event", "chat.theme.customizer.logsEvent", "logs.event"),
  {
    ...logVisualSection("logs-file", "chat.theme.customizer.logsFile", "logs.fileItem"),
    sections: [
      logVisualSection("logs-file-hover", "chat.theme.customizer.stateHover", "logs.fileItem.hover"),
      logVisualSection("logs-file-active", "chat.theme.customizer.stateActive", "logs.fileItem.active"),
    ],
  },
  {
    id: "logs-levels",
    labelKey: "chat.theme.customizer.logsLevels",
    path: "logs.levels",
    sections: (["debug", "default", "info", "warn", "error"] as const).map((level) =>
      logVisualSection(`logs-level-${level}`, `chat.theme.customizer.level.${level}`, `logs.levels.${level}`),
    ),
  },
];

export const chatThemeEditorSections: ChatThemeEditorSection[] = [
  {
    fields: [
      { kind: "color", labelKey: "chat.theme.customizer.themeColor", path: "global.themeColor" },
      { kind: "text", labelKey: "chat.theme.customizer.fontFamily", path: "global.fontFamily" },
    ],
    id: "global",
    labelKey: "chat.theme.customizer.sectionGlobal",
    path: "global",
  },
  {
    fields: [
      ...visualFields("dialog", true),
      {
        kind: "select",
        labelKey: "chat.theme.customizer.chrome",
        options: [
          { label: "Panel", value: "panel" },
          { label: "None", value: "none" },
        ],
        path: "dialog.chrome",
      },
      {
        kind: "number",
        labelKey: "chat.theme.customizer.width",
        max: 100,
        min: 30,
        path: "dialog.widthPct",
        suffix: "%",
      },
      {
        kind: "number",
        labelKey: "chat.theme.customizer.height",
        max: 260,
        min: 96,
        path: "dialog.heightPx",
        suffix: "px",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.nameInputGap",
        max: 32,
        min: 12,
        path: "dialog.nameInputGapVh",
        suffix: "svh",
      },
      {
        kind: "number",
        labelKey: "chat.theme.customizer.offsetY",
        max: 240,
        min: -240,
        path: "dialog.offsetY",
        suffix: "px",
      },
      {
        kind: "select",
        labelKey: "chat.theme.customizer.align",
        options: [
          { label: "Left", value: "left" },
          { label: "Center", value: "center" },
        ],
        path: "dialog.textAlign",
      },
      { advanced: true, kind: "text", labelKey: "chat.theme.customizer.textShadow", path: "dialog.textShadow" },
      textSize("dialog.textSizePx"),
      textWeight("dialog.textWeight"),
    ],
    id: "dialog",
    labelKey: "chat.theme.customizer.sectionDialog",
    path: "dialog",
  },
  {
    fields: [
      ...visualFields("name", true),
      {
        kind: "select",
        labelKey: "chat.theme.customizer.align",
        options: [
          { label: "Left", value: "left" },
          { label: "Center", value: "center" },
        ],
        path: "name.align",
      },
      {
        kind: "select",
        labelKey: "chat.theme.customizer.decoration",
        options: [
          { label: "Accent", value: "accent" },
          { label: "Line dots", value: "line-dots" },
        ],
        path: "name.decoration",
      },
      { advanced: true, kind: "text", labelKey: "chat.theme.customizer.fontFamily", path: "name.fontFamily" },
      {
        advanced: true,
        kind: "boolean",
        labelKey: "chat.theme.customizer.hideAtStart",
        path: "name.hideWhenStartOption",
      },
      {
        kind: "number",
        labelKey: "chat.theme.customizer.overlap",
        max: 48,
        min: 0,
        path: "name.overlapPx",
        suffix: "px",
      },
      { advanced: true, kind: "text", labelKey: "chat.theme.customizer.textShadow", path: "name.textShadow" },
      textSize("name.textSizePx", 56),
      textWeight("name.textWeight"),
    ],
    id: "name",
    labelKey: "chat.theme.customizer.sectionName",
    path: "name",
  },
  {
    fields: [
      ...visualFields("input", true),
      {
        kind: "select",
        labelKey: "chat.theme.customizer.layout",
        options: [
          { label: "Default", value: "default" },
          { label: "Pill", value: "pill" },
        ],
        path: "input.layout",
      },
      {
        advanced: true,
        kind: "color",
        labelKey: "chat.theme.customizer.fieldBackground",
        path: "input.fieldBackground",
      },
      { advanced: true, kind: "text", labelKey: "chat.theme.customizer.fieldRadius", path: "input.fieldBorderRadius" },
      {
        kind: "number",
        labelKey: "chat.theme.customizer.maxWidth",
        max: 900,
        min: 320,
        path: "input.maxWidthPx",
        suffix: "px",
      },
      {
        advanced: true,
        kind: "select",
        labelKey: "chat.theme.customizer.sendPlacement",
        options: [
          { label: "Outside", value: "outside" },
          { label: "Inside", value: "inside" },
        ],
        path: "input.sendPlacement",
      },
    ],
    id: "input",
    labelKey: "chat.theme.customizer.sectionInput",
    path: "input",
  },
  {
    fields: [
      ...visualFields("options", true),
      { kind: "number", labelKey: "chat.theme.customizer.gap", max: 36, min: 0, path: "options.gap", suffix: "px" },
      {
        advanced: true,
        kind: "select",
        labelKey: "chat.theme.customizer.icon",
        options: [
          { label: "None", value: "none" },
          { label: "Chat", value: "chat" },
        ],
        path: "options.icon",
      },
      {
        kind: "select",
        labelKey: "chat.theme.customizer.placement",
        options: [
          { label: "Center", value: "center" },
          { label: "Right", value: "right" },
        ],
        path: "options.placement",
      },
      {
        kind: "select",
        labelKey: "chat.theme.customizer.widthMode",
        options: [
          { label: "Fixed", value: "fixed" },
          { label: "Content", value: "content" },
        ],
        path: "options.widthMode",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.width",
        max: 720,
        min: 260,
        path: "options.widthPx",
        suffix: "px",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.minWidth",
        max: 42,
        min: 12,
        path: "options.minWidthVw",
        suffix: "vw",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.maxWidth",
        max: 60,
        min: 20,
        path: "options.maxWidthVw",
        suffix: "vw",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.minHeight",
        max: 96,
        min: 36,
        path: "options.minHeightPx",
        suffix: "px",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.minHeightResponsive",
        max: 8,
        min: 3,
        path: "options.minHeightVh",
        step: 0.1,
        suffix: "svh",
      },
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.nameClearance",
        max: 12,
        min: 2,
        path: "options.nameClearanceVh",
        step: 0.1,
        suffix: "svh",
      },
      { advanced: true, kind: "text", labelKey: "chat.theme.customizer.textShadow", path: "options.textShadow" },
      textSize("options.textSizePx"),
      {
        advanced: true,
        kind: "number",
        labelKey: "chat.theme.customizer.fontSizeResponsive",
        max: 4,
        min: 1,
        path: "options.textSizeVh",
        step: 0.1,
        suffix: "svh",
      },
      textWeight("options.textWeight"),
    ],
    id: "options",
    labelKey: "chat.theme.customizer.sectionOptions",
    path: "options",
    sections: [
      {
        fields: visualFields("options.hover"),
        id: "options-hover",
        labelKey: "chat.theme.customizer.stateHover",
        path: "options.hover",
      },
      {
        fields: visualFields("options.active"),
        id: "options-active",
        labelKey: "chat.theme.customizer.stateActive",
        path: "options.active",
      },
    ],
  },
  {
    advanced: true,
    fields: [
      ...visualFields("toolbar", true).map((field) => ({ ...field, advanced: false })),
      {
        kind: "select",
        labelKey: "chat.theme.customizer.placement",
        options: [
          { label: "Dialog top", value: "dialog-top" },
          { label: "Input", value: "input" },
          { label: "Input top", value: "input-top" },
        ],
        path: "toolbar.placement",
      },
      {
        kind: "select",
        labelKey: "chat.theme.customizer.reveal",
        options: [
          { label: "Always", value: "always" },
          { label: "Hover", value: "hover" },
        ],
        path: "toolbar.reveal",
      },
    ],
    id: "toolbar",
    labelKey: "chat.theme.customizer.sectionToolbar",
    path: "toolbar",
  },
  {
    advanced: true,
    fields: visualFields("send"),
    id: "send",
    labelKey: "chat.theme.customizer.sectionSend",
    path: "send",
  },
  {
    fields: [
      {
        kind: "number",
        labelKey: "chat.theme.customizer.typewriterSpeed",
        max: 200,
        min: 1,
        path: "typewriter.cps",
        suffix: "cps",
      },
      { advanced: true, kind: "asset", labelKey: "chat.theme.customizer.typewriterSound", path: "typewriter.sound" },
    ],
    id: "typewriter",
    labelKey: "chat.theme.customizer.sectionTypewriter",
    path: "typewriter",
  },
  {
    advanced: true,
    id: "logs",
    labelKey: "chat.theme.customizer.sectionLogs",
    path: "logs",
    sections: logSections,
  },
];

function collectFieldPaths(sections: ChatThemeEditorSection[]): string[] {
  return sections.flatMap((section) => [
    ...(section.fields ?? []).map((field) => field.path),
    ...collectFieldPaths(section.sections ?? []),
  ]);
}

/** Used by contract tests to catch theme tokens that never become editable. */
// Fonts are edited as a structured list rather than a scalar field.
export const chatThemeEditorFieldPaths = [...collectFieldPaths(chatThemeEditorSections), "fonts"];
