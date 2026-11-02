import type { ReleaseHighlight } from "../types";

export const release230: ReleaseHighlight = {
  version: "2.3.0",
  content: {
    zh_CN: {
      title: "Chat UI 现在可以自己设计了",
      summary: "从主题管理页创建自己的聊天界面，并在保存前直接查看真实效果。",
      actionLabel: "打开主题编辑器",
      actionTo: "/settings/system/chat-themes/customize",
      features: [
        {
          icon: "palette",
          title: "可视化主题配置",
          description: "调整对话框、姓名标签、输入框、选项、字体、颜色和打字速度。",
        },
        {
          icon: "preview",
          title: "真实组件实时预览",
          description: "编辑时直接预览对话、选项和输入区域，不需要反复进入聊天页面。",
        },
        {
          icon: "copy",
          title: "安全地从内置主题开始",
          description: "内置主题会复制为独立的用户主题，原始主题和资源不会被覆盖。",
        },
      ],
    },
    en: {
      title: "Design your own Chat UI",
      summary: "Create a custom chat theme from Theme Management and preview the real result before saving.",
      actionLabel: "Open theme editor",
      actionTo: "/settings/system/chat-themes/customize",
      features: [
        {
          icon: "palette",
          title: "Visual theme controls",
          description: "Tune dialogs, name labels, inputs, options, typography, colors, and typewriter speed.",
        },
        {
          icon: "preview",
          title: "Live preview with real components",
          description: "Preview dialogs, options, and the input area without repeatedly opening a chat session.",
        },
        {
          icon: "copy",
          title: "Start safely from a built-in theme",
          description: "Built-in themes are copied into user-owned themes, leaving the originals and assets untouched.",
        },
      ],
    },
    ja: {
      title: "Chat UI を自分でデザイン",
      summary: "テーマ管理からオリジナルのチャットテーマを作成し、保存前に実際の表示を確認できます。",
      actionLabel: "テーマエディターを開く",
      actionTo: "/settings/system/chat-themes/customize",
      features: [
        {
          icon: "palette",
          title: "ビジュアルテーマ設定",
          description: "ダイアログ、名前ラベル、入力欄、選択肢、フォント、色、表示速度を調整できます。",
        },
        {
          icon: "preview",
          title: "実際のコンポーネントでライブプレビュー",
          description: "チャットを開き直さずに、ダイアログ、選択肢、入力欄をその場で確認できます。",
        },
        {
          icon: "copy",
          title: "内蔵テーマから安全に開始",
          description: "内蔵テーマはユーザーテーマとして複製され、元のテーマや素材は変更されません。",
        },
      ],
    },
  },
};
