import type { FrontendLanguage } from "../../shared/i18n/messages";

export type OnboardingStepId = "api" | "plugins" | "characters" | "backgrounds" | "complete";

export type OnboardingCopy = {
  actions: {
    add: string;
    api: string;
    backgrounds: string;
    chat: string;
    characters: string;
    create: string;
    fetchModels: string;
    import: string;
    install: string;
    installed: string;
    launch: string;
    next: string;
    plugins: string;
    previous: string;
    resume: string;
    retry: string;
    save: string;
    saved: string;
    stage: string;
    test: string;
    templates: string;
  };
  api: {
    apiKey: string;
    baseUrl: string;
    bundleButton: string;
    bundleDone: string;
    bundleHint: string;
    connected: string;
    description: string;
    model: string;
    provider: string;
    title: string;
    ttsPath: string;
    ttsProvider: string;
    ttsSpeed: string;
    voiceDescription: string;
    voiceTitle: string;
  };
  backgrounds: {
    description: string;
    empty: string;
    imageTags: string;
    imported: string;
    resourceBody: string;
    resourceLink: string;
    name: string;
    prefix: string;
    title: string;
    transparentBody: string;
    transparentTitle: string;
  };
  characters: {
    color: string;
    description: string;
    empty: string;
    imported: string;
    resourceBody: string;
    resourceLink: string;
    name: string;
    prefix: string;
    setting: string;
    tags: string;
    title: string;
  };
  common: {
    done: string;
    loading: string;
    selectPlaceholder: string;
  };
  complete: {
    bannerBody: string;
    bannerTitle: string;
    description: string;
    openTemplates: string;
    title: string;
  };
  plugins: {
    aiDependencyHint: string;
    browserBody: string;
    browserGuide: string;
    browserTitle: string;
    configReady: string;
    configure: string;
    dependencyStep: string;
    description: string;
    empty: string;
    installDone: string;
    installPending: string;
    installSelected: string;
    installedNoConfig: string;
    loading: string;
    marketplaceHint: string;
    noMatch: string;
    reloadFailed: string;
    reloadPending: string;
    selectedCount: string;
    title: string;
    visualBody: string;
    visualGuide: string;
    visualTitle: string;
    voiceBody: string;
    voiceGuide: string;
    voiceTitle: string;
  };
  finishLabel: string;
  optionalLabel: string;
  requiredLabel: string;
  stepLabel: string;
  title: string;
  toastFailed: string;
  toastSuccess: string;
};

export const onboardingCopy: Record<FrontendLanguage, OnboardingCopy> = {
  en: {
    actions: {
      add: "Add",
      api: "Configure API",
      backgrounds: "Backgrounds",
      chat: "Chat",
      characters: "Characters",
      create: "Create",
      fetchModels: "Fetch models",
      import: "Import",
      install: "Install",
      installed: "Ready",
      launch: "Launch",
      next: "Open next step",
      plugins: "Plugin market",
      previous: "Previous",
      resume: "Resume last chat",
      retry: "Retry",
      save: "Save",
      saved: "Saved",
      stage: "Chat stage",
      test: "Test",
      templates: "Templates",
    },
    api: {
      apiKey: "API key",
      baseUrl: "Base URL",
      bundleButton: "One-click download voice bundle",
      bundleDone: "Voice bundle is ready.",
      bundleHint:
        "The package may spend a long time extracting after download. That is normal; keep this page open until progress finishes.",
      connected: "Connection passed",
      description: "Save the LLM connection used by the rest of Shinsekai.",
      model: "Model ID",
      provider: "Provider",
      title: "API configuration",
      ttsPath: "TTS service path / URL",
      ttsProvider: "Voice provider",
      ttsSpeed: "Speech speed",
      voiceDescription: "Choose a voice provider and keep a practical speech speed.",
      voiceTitle: "Voice",
    },
    backgrounds: {
      description: "Import an existing background package, or skip this step and keep the stage transparent.",
      empty: "No backgrounds yet.",
      imageTags: "Image tags",
      imported: "Backgrounds imported",
      resourceBody: "Download example backgrounds and then import them here.",
      resourceLink: "Open resource library",
      name: "Background name",
      prefix: "Asset prefix",
      title: "Backgrounds",
      transparentBody:
        "Skipping background import is fine. With a transparent stage, Shinsekai can run like a desktop companion on top of your current screen.",
      transparentTitle: "Transparent desktop companion",
    },
    characters: {
      color: "Theme color",
      description: "Create a simple character profile or import one from a file.",
      empty: "No characters yet.",
      imported: "Characters imported",
      resourceBody: "Download example characters and then import the package here.",
      resourceLink: "Open resource library",
      name: "Character name",
      prefix: "Sprite prefix",
      setting: "Character setting",
      tags: "Emotion tags",
      title: "Characters",
    },
    common: {
      done: "Done",
      loading: "Loading",
      selectPlaceholder: "Select",
    },
    complete: {
      bannerBody:
        "Open the template page to choose characters and a chat template. You can generate, edit, launch, or quickly restart from there.",
      bannerTitle: "Setup complete. Time to chat.",
      description: "Everything important is ready. Continue in Templates for character and template selection.",
      openTemplates: "Open templates",
      title: "Ready",
    },
    plugins: {
      aiDependencyHint:
        "Visual and voice input plugins need AI dependencies. Installation can take a while, especially during package download and extraction.",
      browserBody: "Lets tools browse and operate webpages during chat.",
      browserGuide:
        "After installation, open plugin settings and turn off headless mode when you want to see browser actions.",
      browserTitle: "Browser plugin",
      configReady: "Installed and reloaded. Configuration is ready.",
      configure: "Configure",
      dependencyStep: "Install AI dependencies first, then download plugins.",
      description: "Install common extensions directly from the guide.",
      empty: "No plugin packages are available right now.",
      installDone: "Dependencies and selected plugins are installed. Plugins were reloaded and are ready to configure.",
      installPending: "Installing dependencies first, then downloading and installing the selected plugins.",
      installSelected: "One-click download",
      installedNoConfig: "Installed and reloaded. No separate plugin settings are needed.",
      loading: "Loading plugin catalog",
      marketplaceHint: "Find more plugins in Plugins > Discover.",
      noMatch: "No matching market plugin was found yet.",
      reloadFailed: "Dependencies and plugins were installed, but plugin reload failed",
      reloadPending: "Download finished. Reloading plugins so the new settings pages become available...",
      selectedCount: "{count} selected",
      title: "Common plugins",
      visualBody: "Gives the assistant visual understanding for screen and image workflows.",
      visualGuide: "After installation, enable active screen recognition in the visual plugin settings.",
      visualTitle: "Visual plugin",
      voiceBody: "Adds voice input support for hands-free chat.",
      voiceGuide: "After installation, configure voice input in the API page.",
      voiceTitle: "Voice input plugin",
    },
    finishLabel: "Open templates",
    optionalLabel: "Skippable",
    requiredLabel: "Required",
    stepLabel: "Step {current} of {total}",
    title: "First run guide",
    toastFailed: "Operation failed",
    toastSuccess: "Done",
  },
  ja: {
    actions: {
      add: "追加",
      api: "API 設定",
      backgrounds: "背景",
      chat: "チャット",
      characters: "キャラクター",
      create: "作成",
      fetchModels: "モデル取得",
      import: "インポート",
      install: "インストール",
      installed: "準備済み",
      launch: "起動",
      next: "次のステップへ",
      plugins: "プラグイン市場",
      previous: "戻る",
      resume: "前回のチャット",
      retry: "再試行",
      save: "保存",
      saved: "保存済み",
      stage: "チャットステージ",
      test: "テスト",
      templates: "テンプレート",
    },
    api: {
      apiKey: "API Key",
      baseUrl: "Base URL",
      bundleButton: "音声パックを一括ダウンロード",
      bundleDone: "音声パックの準備ができました。",
      bundleHint:
        "ダウンロード後の展開には時間がかかることがあります。これは正常です。進捗が終わるまでこのページを開いたままにしてください。",
      connected: "接続テスト成功",
      description: "Shinsekai 全体で使う LLM 接続を保存します。",
      model: "モデル ID",
      provider: "Provider",
      title: "API 設定",
      ttsPath: "TTS サービスパス / URL",
      ttsProvider: "音声プロバイダー",
      ttsSpeed: "話速",
      voiceDescription: "音声プロバイダーと実用的な話速を設定します。",
      voiceTitle: "音声",
    },
    backgrounds: {
      description: "既存の背景パッケージを導入します。透明背景のまま使う場合は、このステップをスキップできます。",
      empty: "背景はまだありません。",
      imageTags: "画像タグ",
      imported: "背景をインポートしました",
      resourceBody: "サンプル背景をダウンロードし、ここでインポートします。",
      resourceLink: "リソースを開く",
      name: "背景名",
      prefix: "素材プレフィックス",
      title: "背景",
      transparentBody:
        "背景を導入しなくても大丈夫です。透明背景のままなら、今の画面の上でデスクトップマスコットとして使えます。",
      transparentTitle: "透明背景でデスクトップマスコット",
    },
    characters: {
      color: "テーマカラー",
      description: "既存のキャラクターパッケージを導入します。おすすめリソースから始めるとすぐに会話へ進めます。",
      empty: "キャラクターはまだありません。",
      imported: "キャラクターをインポートしました",
      resourceBody: "サンプルキャラクターをダウンロードし、ここでインポートします。",
      resourceLink: "リソースを開く",
      name: "キャラクター名",
      prefix: "立ち絵プレフィックス",
      setting: "人物設定",
      tags: "感情タグ",
      title: "キャラクター",
    },
    common: {
      done: "完了",
      loading: "読み込み中",
      selectPlaceholder: "選択",
    },
    complete: {
      bannerBody:
        "テンプレートページでキャラクターとチャットテンプレートを選択できます。生成、編集、開始、クイック再起動はそこから行えます。",
      bannerTitle: "設定が完了しました。チャットできます。",
      description: "必要な準備は整いました。テンプレートページでキャラクターとテンプレートを選びましょう。",
      openTemplates: "テンプレートへ進む",
      title: "準備完了",
    },
    plugins: {
      aiDependencyHint:
        "視覚プラグインと音声入力プラグインは AI 依存関係をインストールします。ダウンロードや展開に時間がかかる場合があります。",
      browserBody: "チャット中に Web ページを閲覧・操作できるようにします。",
      browserGuide: "インストール後、動作を見たい場合はプラグイン設定で headless をオフにしてください。",
      browserTitle: "ブラウザプラグイン",
      configReady: "インストールと再読み込みが完了しました。設定できます。",
      configure: "設定へ",
      dependencyStep: "先に AI 依存関係を入れてから、プラグインをダウンロードします。",
      description: "よく使う拡張をガイドから直接インストールします。",
      empty: "現在利用できるプラグインがありません。",
      installDone: "依存関係と選択したプラグインのインストールが完了しました。プラグインも再読み込み済みです。",
      installPending: "先に依存関係をインストールし、その後プラグイン本体をダウンロードしてインストールします。",
      installSelected: "一括ダウンロード",
      installedNoConfig: "インストールと再読み込みが完了しました。追加設定は不要です。",
      loading: "プラグイン一覧を読み込み中",
      marketplaceHint: "その他のプラグインは「プラグイン」>「発見」にあります。",
      noMatch: "対応するマーケットプラグインがまだ見つかりません。",
      reloadFailed: "依存関係とプラグインはインストールされましたが、プラグイン再読み込みに失敗しました",
      reloadPending:
        "ダウンロードが完了しました。新しい設定ページを有効にするため、プラグインを再読み込みしています...",
      selectedCount: "{count} 件選択中",
      title: "よく使うプラグイン",
      visualBody: "画面や画像を理解するための視覚拡張です。",
      visualGuide: "インストール後、視覚プラグイン設定で画面の自動認識を有効にしてください。",
      visualTitle: "視覚プラグイン",
      voiceBody: "ハンズフリー会話のための音声入力を追加します。",
      voiceGuide: "インストール後、API ページで音声入力を設定してください。",
      voiceTitle: "音声入力プラグイン",
    },
    finishLabel: "テンプレートへ進む",
    optionalLabel: "スキップ可",
    requiredLabel: "必須",
    stepLabel: "{total} 中 {current} ステップ",
    title: "初回セットアップ",
    toastFailed: "操作に失敗しました",
    toastSuccess: "完了しました",
  },
  zh_CN: {
    actions: {
      add: "添加",
      api: "配置 API",
      backgrounds: "背景",
      chat: "聊天",
      characters: "人物",
      create: "创建",
      fetchModels: "获取模型",
      import: "导入",
      install: "一键安装",
      installed: "已就绪",
      launch: "启动",
      next: "打开下一步",
      plugins: "插件市场",
      previous: "上一步",
      resume: "恢复上次聊天",
      retry: "重试",
      save: "保存",
      saved: "已保存",
      stage: "聊天舞台",
      test: "测试",
      templates: "模板",
    },
    api: {
      apiKey: "API Key",
      baseUrl: "基础地址",
      bundleButton: "一键下载语音包",
      bundleDone: "语音包已准备好。",
      bundleHint: "下载完成后会进入解压阶段，耗时比较久是正常的。请保持页面打开，等进度结束后再继续。",
      connected: "连接测试通过",
      description: "保存 Shinsekai 后续会使用的 LLM 连接。",
      model: "模型 ID",
      provider: "服务商",
      title: "API 配置",
      ttsPath: "TTS 服务路径 / URL",
      ttsProvider: "语音服务商",
      ttsSpeed: "语速",
      voiceDescription: "需要本地语音能力时，直接下载推荐语音包即可。",
      voiceTitle: "语音",
    },
    backgrounds: {
      description: "导入已有背景包即可；如果想做桌宠，也可以不导入背景，保留透明舞台。",
      empty: "还没有背景。",
      imageTags: "图片标签",
      imported: "背景已导入",
      resourceBody: "先打开资源库下载示例背景包，然后在这里导入。",
      resourceLink: "打开资源库",
      name: "背景名称",
      prefix: "素材前缀",
      title: "背景",
      transparentBody: "背景不是必填项。不导入背景时，聊天舞台会保持透明，人物可以像桌宠一样悬浮在当前屏幕上。",
      transparentTitle: "也可以使用透明背景",
    },
    characters: {
      color: "主题色",
      description: "从资源库或本地文件导入人物包，让第一段对话更快开始。",
      empty: "还没有人物。",
      imported: "人物已导入",
      resourceBody: "先打开资源库下载示例人物包，然后在这里导入。",
      resourceLink: "打开资源库",
      name: "人物名称",
      prefix: "立绘前缀",
      setting: "人物设定",
      tags: "情绪标签",
      title: "人物",
    },
    common: {
      done: "已完成",
      loading: "正在加载",
      selectPlaceholder: "请选择",
    },
    complete: {
      bannerBody: "接下来到模板页选择人物和聊天模板。你可以在那里生成模板、编辑模板、启动聊天或快速重开。",
      bannerTitle: "已配置完成，可以聊天啦",
      description: "关键配置已经准备好，下一步去模板页选择人物和模板。",
      openTemplates: "前往模板页",
      title: "完成",
    },
    plugins: {
      aiDependencyHint: "视觉插件和语音输入插件需要安装 AI 依赖，下载和安装时间会比较久，请耐心等待。",
      browserBody: "让工具在聊天中浏览和操作网页。",
      browserGuide: "安装后进入插件设置，想看到浏览器操作时请取消勾选无头模式。",
      browserTitle: "浏览器插件",
      configReady: "已安装并重载，可以去配置。",
      configure: "去配置",
      dependencyStep: "会先安装 AI 相关依赖，再下载并安装插件。",
      description: "直接在引导页安装常见扩展。",
      empty: "暂时没有可用插件包。",
      installDone: "依赖和已选择的插件本体都已安装完成，插件服务也已重载，现在可以进入配置。",
      installPending: "正在先安装依赖，然后下载并安装已选择的插件本体。",
      installSelected: "一键下载",
      installedNoConfig: "已安装并重载，此插件无需单独配置。",
      loading: "正在读取插件市场",
      marketplaceHint: "更多插件可以在「插件」>「发现」里查看。",
      noMatch: "暂时没有在插件市场匹配到对应插件。",
      reloadFailed: "依赖和插件本体已安装，但插件服务重载失败",
      reloadPending: "下载已完成，正在重载插件服务，让新的设置页生效...",
      selectedCount: "已选择 {count} 项",
      title: "常见插件",
      visualBody: "让助手具备屏幕和图片理解能力。",
      visualGuide: "安装后进入视觉插件设置，勾选主动识别屏幕。",
      visualTitle: "视觉插件",
      voiceBody: "为聊天增加语音输入能力。",
      voiceGuide: "安装后请到 API 页面勾选并配置语音输入。",
      voiceTitle: "语音输入插件",
    },
    finishLabel: "进入模板页",
    optionalLabel: "可跳过",
    requiredLabel: "必做",
    stepLabel: "第 {current} / {total} 步",
    title: "首次使用引导",
    toastFailed: "操作失败",
    toastSuccess: "操作完成",
  },
};
