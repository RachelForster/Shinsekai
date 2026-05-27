export type FrontendLanguage = "zh_CN" | "en" | "ja";

export type MessageKey =
  | "app.brandSubtitle"
  | "app.preview"
  | "app.shellMeta"
  | "app.title"
  | "api.description"
  | "api.error.saveFallback"
  | "api.links.help"
  | "api.links.link1"
  | "api.links.link2"
  | "api.links.link3"
  | "api.links.link4"
  | "api.links.link5"
  | "api.links.title"
  | "api.language.field"
  | "api.language.hint"
  | "api.language.title"
  | "api.llm.apiKey"
  | "api.llm.baseUrl"
  | "api.llm.connectionTitle"
  | "api.llm.fetchDone"
  | "api.llm.fetchEmpty"
  | "api.llm.fetchFailed"
  | "api.llm.fetchMissing"
  | "api.llm.fetchModels"
  | "api.llm.fetchTitle"
  | "api.llm.fetching"
  | "api.llm.model"
  | "api.llm.modelCustom"
  | "api.llm.modelPlaceholder"
  | "api.llm.provider"
  | "api.llm.reasoningEffort"
  | "api.llm.required"
  | "api.llm.streaming"
  | "api.llm.thinkingEnabled"
  | "api.llm.thinkingUnsupported"
  | "api.loading"
  | "api.resume.btn"
  | "api.resume.tip"
  | "api.resume.title"
  | "api.tts.bundleDone"
  | "api.tts.bundleDownload"
  | "api.tts.bundleFailed"
  | "api.tts.bundleGenie"
  | "api.tts.bundleGptSovits"
  | "api.tts.bundleGptSovits50"
  | "api.tts.bundleHint"
  | "api.tts.bundlePick"
  | "api.tts.bundleTitle"
  | "api.title"
  | "api.toast.saved"
  | "background.delete.confirmBody"
  | "background.delete.confirmTitle"
  | "background.description"
  | "background.emptyBody"
  | "background.emptyTitle"
  | "background.error.deleteFallback"
  | "background.error.exportFallback"
  | "background.error.importFallback"
  | "background.error.saveFallback"
  | "background.error.translateFallback"
  | "background.field.bgTags"
  | "background.field.bgmTags"
  | "background.field.name"
  | "background.field.spritePrefix"
  | "background.groupListTitle"
  | "background.loading"
  | "background.resource.backgroundImage"
  | "background.resource.bgm"
  | "background.resource.count"
  | "background.resource.description"
  | "background.resource.imageCount"
  | "background.resource.source"
  | "background.resource.type"
  | "background.action.aiTranslate"
  | "background.action.community"
  | "background.action.saveBgmTags"
  | "background.action.saveImageTags"
  | "background.action.uploadContribution"
  | "background.asset.addBgm"
  | "background.asset.addImage"
  | "background.asset.clearBgm"
  | "background.asset.clearImages"
  | "background.asset.deleteSelectedBgm"
  | "background.asset.emptyBgm"
  | "background.asset.emptyImages"
  | "background.asset.filename"
  | "background.asset.index"
  | "background.asset.noSelectedBgm"
  | "background.asset.path"
  | "background.asset.preview"
  | "background.asset.select"
  | "background.asset.selectBgm"
  | "background.asset.selectImages"
  | "background.asset.selectedFiles"
  | "background.asset.tag"
  | "background.asset.uploadBgm"
  | "background.asset.uploadError"
  | "background.asset.uploadImages"
  | "background.section.assets"
  | "background.section.bgm"
  | "background.section.images"
  | "background.section.info"
  | "background.section.tags"
  | "background.title"
  | "background.toast.deleted"
  | "background.toast.exportComplete"
  | "background.toast.importComplete"
  | "background.toast.saved"
  | "background.validation.nameRequired"
  | "bottom.ready"
  | "bottom.author"
  | "bottom.saving"
  | "bottom.syncing"
  | "bottom.transport"
  | "character.delete.confirmBody"
  | "character.delete.confirmTitle"
  | "character.description"
  | "character.emptyBody"
  | "character.emptyTitle"
  | "character.error.deleteFallback"
  | "character.error.aiFallback"
  | "character.error.exportFallback"
  | "character.error.importFallback"
  | "character.error.saveFallback"
  | "character.error.translateFallback"
  | "character.action.aiTranslate"
  | "character.action.aiWrite"
  | "character.action.community"
  | "character.action.pickColor"
  | "character.action.uploadContribution"
  | "character.field.characterSetting"
  | "character.field.color"
  | "character.field.emotionTags"
  | "character.field.gptModel"
  | "character.field.name"
  | "character.field.promptLang"
  | "character.field.promptText"
  | "character.field.pronunciationMap"
  | "character.field.referAudio"
  | "character.field.sovitsModel"
  | "character.field.speechSpeed"
  | "character.field.speechVolume"
  | "character.field.spritePrefix"
  | "character.field.spriteScale"
  | "character.import.noFile"
  | "character.listTitle"
  | "character.loading"
  | "character.memory.add"
  | "character.memory.count"
  | "character.memory.delete"
  | "character.memory.empty"
  | "character.memory.error"
  | "character.memory.loading"
  | "character.memory.nameRequired"
  | "character.memory.placeholder"
  | "character.memory.refresh"
  | "character.memory.section"
  | "character.row.current"
  | "character.section.basic"
  | "character.section.personality"
  | "character.section.sprites"
  | "character.section.voice"
  | "character.sprite.add"
  | "character.sprite.clear"
  | "character.sprite.empty"
  | "character.sprite.imageError"
  | "character.sprite.path"
  | "character.sprite.saveScale"
  | "character.sprite.saveTags"
  | "character.sprite.selectImages"
  | "character.sprite.selectedFiles"
  | "character.sprite.deleteVoice"
  | "character.sprite.saveVoiceText"
  | "character.sprite.uploadVoice"
  | "character.sprite.uploadImages"
  | "character.sprite.voiceError"
  | "character.sprite.voiceHint"
  | "character.sprite.voicePath"
  | "character.sprite.voiceText"
  | "character.sprite.voiceUploadPath"
  | "character.title"
  | "character.toast.deleted"
  | "character.toast.exportComplete"
  | "character.toast.importComplete"
  | "character.toast.saved"
  | "character.validation.gptModelExt"
  | "character.validation.nameRequired"
  | "character.validation.noQuotedPaths"
  | "character.validation.sovitsModelExt"
  | "character.validation.spritePrefixAscii"
  | "character.validation.spritePrefixRequired"
  | "chat.clear.confirmAction"
  | "chat.clear.confirmBody"
  | "chat.clear.confirmTitle"
  | "chat.emptyDialog"
  | "chat.error.commandFallback"
  | "chat.error.loadFallback"
  | "chat.input.micDenied"
  | "chat.input.micError"
  | "chat.input.micStart"
  | "chat.input.micStop"
  | "chat.input.micUnsupported"
  | "chat.input.placeholder"
  | "chat.input.send"
  | "chat.toast.historyCleared"
  | "chat.toast.historyCopied"
  | "chat.toast.historyOpened"
  | "chat.toolbar.clearHistory"
  | "chat.toolbar.copyHistory"
  | "chat.toolbar.openHistory"
  | "chat.toolbar.pauseAsr"
  | "chat.toolbar.reroll"
  | "chat.toolbar.skipSpeech"
  | "common.author"
  | "common.add"
  | "common.cancel"
  | "common.chooseFile"
  | "common.chooseFolder"
  | "common.close"
  | "common.delete"
  | "common.deleteFailed"
  | "common.description"
  | "common.edit"
  | "common.entry"
  | "common.name"
  | "common.no"
  | "common.open"
  | "common.refresh"
  | "common.remove"
  | "common.retry"
  | "common.save"
  | "common.saveFailed"
  | "common.saveApply"
  | "common.export"
  | "common.exportFailed"
  | "common.import"
  | "common.importFailed"
  | "common.new"
  | "common.yes"
  | "common.operationFailed"
  | "common.status"
  | "common.subpages"
  | "common.validationFailed"
  | "common.fixInvalidFields"
  | "form.jsonInvalid"
  | "filePicker.address"
  | "filePicker.empty"
  | "filePicker.hidden"
  | "filePicker.loading"
  | "filePicker.modified"
  | "filePicker.name"
  | "filePicker.parent"
  | "filePicker.roots"
  | "filePicker.selectCurrent"
  | "filePicker.selectFile"
  | "filePicker.size"
  | "filePicker.type"
  | "filePicker.typeDirectory"
  | "filePicker.typeFile"
  | "launch.background"
  | "launch.character"
  | "launch.description"
  | "launch.emptyBody"
  | "launch.emptyTitle"
  | "launch.history"
  | "launch.historyHelp"
  | "launch.historyPlaceholder"
  | "launch.start"
  | "launch.template"
  | "launch.title"
  | "launch.toast.failed"
  | "launch.toast.started"
  | "launch.validation.historyJson"
  | "mcp.action.openYaml"
  | "mcp.action.previewTools"
  | "mcp.action.saveServer"
  | "mcp.defaultTimeout"
  | "mcp.delete.confirmBody"
  | "mcp.delete.confirmTitle"
  | "mcp.description"
  | "mcp.dialog.addTitle"
  | "mcp.dialog.editTitle"
  | "mcp.enabled"
  | "mcp.field.args"
  | "mcp.field.callTimeout"
  | "mcp.field.command"
  | "mcp.field.connection"
  | "mcp.field.env"
  | "mcp.field.group"
  | "mcp.field.headers"
  | "mcp.field.prefix"
  | "mcp.field.registeredName"
  | "mcp.field.transport"
  | "mcp.field.toolName"
  | "mcp.field.url"
  | "mcp.globalEnable"
  | "mcp.importJson"
  | "mcp.importJson.hint"
  | "mcp.importJson.noServers"
  | "mcp.importJson.okBody"
  | "mcp.importJson.title"
  | "mcp.installHint"
  | "mcp.preview.empty"
  | "mcp.preview.emptyBody"
  | "mcp.preview.loading"
  | "mcp.server.emptyBody"
  | "mcp.server.emptyTitle"
  | "mcp.server.title"
  | "mcp.status.disabled"
  | "mcp.status.enabled"
  | "mcp.status.no"
  | "mcp.status.yes"
  | "mcp.toast.importFailed"
  | "mcp.toast.importSuccess"
  | "mcp.toast.opened"
  | "mcp.toast.operationFailed"
  | "mcp.toast.previewSuccess"
  | "mcp.toast.saveSuccess"
  | "mcp.tools.title"
  | "mcp.validation.argsArray"
  | "mcp.validation.defaultTimeout"
  | "mcp.validation.envObject"
  | "mcp.validation.headersObject"
  | "mcp.validation.needCommand"
  | "mcp.validation.needUrl"
  | "nav.api"
  | "nav.background"
  | "nav.character"
  | "nav.launch"
  | "nav.musicCover"
  | "nav.plugins"
  | "nav.secondary"
  | "nav.settingsCenter"
  | "nav.system"
  | "nav.template"
  | "nav.tools"
  | "plugin.action.install"
  | "plugin.action.installed"
  | "plugin.action.openGitHub"
  | "plugin.action.register"
  | "plugin.action.uninstall"
  | "plugin.action.update"
  | "plugin.action.viewConfig"
  | "plugin.appUpdate.button"
  | "plugin.appUpdate.confirm"
  | "plugin.appUpdate.failed"
  | "plugin.appUpdate.ref"
  | "plugin.appUpdate.refHead"
  | "plugin.appUpdate.refLatest"
  | "plugin.appUpdate.repo"
  | "plugin.appUpdate.success"
  | "plugin.appUpdate.tagInvalid"
  | "plugin.appUpdate.tagsEmpty"
  | "plugin.appUpdate.tagsLoading"
  | "plugin.appUpdate.title"
  | "plugin.appUpdate.version"
  | "plugin.appUpdate.versionUnknown"
  | "plugin.appUpdate.warning"
  | "plugin.author"
  | "plugin.catalog.emptyBody"
  | "plugin.catalog.emptyTitle"
  | "plugin.catalog.errorBody"
  | "plugin.catalog.errorTitle"
  | "plugin.catalog.loading"
  | "plugin.catalog.title"
  | "plugin.description"
  | "plugin.directory"
  | "plugin.detail.back"
  | "plugin.detail.errorBody"
  | "plugin.detail.errorTitle"
  | "plugin.detail.kindSettings"
  | "plugin.detail.kindTools"
  | "plugin.detail.loading"
  | "plugin.detail.noUi"
  | "plugin.detail.pages"
  | "plugin.detail.pyqtNotice"
  | "plugin.detail.save"
  | "plugin.detail.saveFailed"
  | "plugin.detail.saveSuccess"
  | "plugin.detail.settingsPages"
  | "plugin.detail.title"
  | "plugin.detail.toolsTabs"
  | "plugin.disable.confirmBody"
  | "plugin.disable.confirmTitle"
  | "plugin.error.installFallback"
  | "plugin.error.toggleFallback"
  | "plugin.error.uninstallFallback"
  | "plugin.id"
  | "plugin.install.entryHelp"
  | "plugin.install.entryLabel"
  | "plugin.install.placeholder"
  | "plugin.install.title"
  | "plugin.installRef.title"
  | "plugin.installed.emptyBody"
  | "plugin.installed.emptyTitle"
  | "plugin.installed.count"
  | "plugin.installed.loading"
  | "plugin.installed.title"
  | "plugin.loadError.unavailable"
  | "plugin.permissions"
  | "plugin.plugin"
  | "plugin.toggle.disable"
  | "plugin.toggle.enable"
  | "plugin.status.downloaded"
  | "plugin.status.disabled"
  | "plugin.status.enabled"
  | "plugin.status.installed"
  | "plugin.status.notInstalled"
  | "plugin.status.unavailable"
  | "plugin.status.updating"
  | "plugin.table.actionHeader"
  | "plugin.table.slots"
  | "plugin.toast.disabled"
  | "plugin.toast.enabled"
  | "plugin.toast.installFailed"
  | "plugin.toast.installSuccess"
  | "plugin.toast.operationFailed"
  | "plugin.toast.restartHint"
  | "plugin.toast.uninstalled"
  | "plugin.uninstall.confirmBody"
  | "plugin.uninstall.confirmTitle"
  | "plugin.version"
  | "system.asr.computeAuto"
  | "system.asr.computeType"
  | "system.asr.device"
  | "system.asr.deviceAuto"
  | "system.asr.followUi"
  | "system.asr.hint"
  | "system.asr.langEn"
  | "system.asr.langJa"
  | "system.asr.langYue"
  | "system.asr.langZh"
  | "system.asr.language"
  | "system.asr.modelCustom"
  | "system.asr.modelCustomPlaceholder"
  | "system.asr.provider"
  | "system.asr.title"
  | "system.asr.voskHint"
  | "system.asr.voskModelPath"
  | "system.asr.voskModels"
  | "system.asr.whisperModel"
  | "system.description"
  | "system.error.saveFallback"
  | "system.loading"
  | "system.title"
  | "system.toast.saved"
  | "template.action.selectAllCharacters"
  | "template.action.launch"
  | "template.action.quickRestart"
  | "template.defaultName"
  | "template.description"
  | "template.emptyBody"
  | "template.emptySelection"
  | "template.emptyTitle"
  | "template.error.generateFailed"
  | "template.error.generateFallback"
  | "template.error.launchFailed"
  | "template.error.saveFallback"
  | "template.field.background"
  | "template.field.characters"
  | "template.field.content"
  | "template.field.historyFile"
  | "template.field.initSprite"
  | "template.field.maxDialogItems"
  | "template.field.maxSpeechChars"
  | "template.field.name"
  | "template.field.path"
  | "template.field.scenario"
  | "template.field.system"
  | "template.field.templateName"
  | "template.field.useCg"
  | "template.field.useChoice"
  | "template.field.useCot"
  | "template.field.useEffect"
  | "template.field.useNarration"
  | "template.field.useStat"
  | "template.field.useTranslation"
  | "template.field.voiceLanguage"
  | "template.listTitle"
  | "template.loading"
  | "template.mode.edit"
  | "template.mode.generate"
  | "template.quickRestart.body"
  | "template.quickRestart.title"
  | "template.section.content"
  | "template.section.generate"
  | "template.section.load"
  | "template.section.run"
  | "template.section.scenario"
  | "template.section.system"
  | "template.toast.launched"
  | "template.transparentBackground"
  | "template.title"
  | "template.toast.generated"
  | "template.toast.saved"
  | "template.validation.backgroundRequired"
  | "template.validation.charactersRequired"
  | "template.validation.nameRequired"
  | "top.chatStage"
  | "tools.browse"
  | "tools.character"
  | "tools.cropBtn"
  | "tools.cropInput"
  | "tools.cropOutput"
  | "tools.cropRatio"
  | "tools.cropTitle"
  | "tools.description"
  | "tools.galleryEmpty"
  | "tools.galleryLabel"
  | "tools.gemBox"
  | "tools.gemHint"
  | "tools.genPromptsBtn"
  | "tools.genSpritesBtn"
  | "tools.h2Sprites"
  | "tools.msgGenFailed"
  | "tools.msgGenOk"
  | "tools.msgNoPrompts"
  | "tools.msgRefInvalid"
  | "tools.msgSelectChar"
  | "tools.msgTitleGen"
  | "tools.msgTitlePrompts"
  | "tools.outputDirPlaceholder"
  | "tools.promptLine"
  | "tools.promptsGenerated"
  | "tools.promptsPlaceholder"
  | "tools.refDialogTitle"
  | "tools.refLabel"
  | "tools.refPlaceholder"
  | "tools.rmbgBtn"
  | "tools.rmbgFirst"
  | "tools.rmbgInput"
  | "tools.rmbgOutput"
  | "tools.rmbgTitle"
  | "tools.spriteCount"
  | "tools.tabMain";

export const frontendMessages: Record<FrontendLanguage, Record<MessageKey, string>> = {
  en: {
    "app.brandSubtitle": "AI RPG Tools",
    "app.preview": "Settings",
    "app.shellMeta": "AI RPG Tools",
    "app.title": "Shinsekai",
    "api.description":
      "Configure LLM, TTS, voice input, and ComfyUI. API settings are written to api.yaml; microphone recognition settings are written to system_config.yaml.",
    "api.error.saveFallback": "Check the configuration fields.",
    "api.links.help":
      "Extract and point the TTS service startup path to that folder. GPT SoVITS needs about 11GB; Genie TTS about 4GB.",
    "api.links.link1": "GPT-SoVITS on GitHub",
    "api.links.link2": "ModelScope: GPT-SoVITS v2pro package",
    "api.links.link3": "ModelScope: RTX 50-series bundle",
    "api.links.link4": "Genie TTS for CPU-friendly inference",
    "api.links.link5": "ModelScope: Genie TTS Server bundle",
    "api.links.title": "Resources & links",
    "api.language.field": "Interface language",
    "api.language.hint": "Takes effect immediately. Standalone desktop chat windows apply it after the next launch.",
    "api.language.title": "Interface language",
    "api.llm.apiKey": "LLM API Key",
    "api.llm.baseUrl": "LLM base URL",
    "api.llm.connectionTitle": "LLM API",
    "api.llm.fetchDone": "Fetched {count} models.",
    "api.llm.fetchEmpty": "No available models were returned.",
    "api.llm.fetchFailed": "Failed to fetch models.",
    "api.llm.fetchMissing": "Fill in the LLM base URL and API key first.",
    "api.llm.fetchModels": "Fetch available models",
    "api.llm.fetchTitle": "Model list",
    "api.llm.fetching": "Fetching models",
    "api.llm.model": "Model ID",
    "api.llm.modelCustom": "Custom model ID...",
    "api.llm.modelPlaceholder": "Model ID",
    "api.llm.provider": "Provider",
    "api.llm.reasoningEffort": "Reasoning effort",
    "api.llm.required": "Provider, base URL, API key, and model ID are required.",
    "api.llm.streaming": "Streaming response",
    "api.llm.thinkingEnabled": "Thinking mode",
    "api.llm.thinkingUnsupported": "This model does not support thinking mode.",
    "api.loading": "Loading API settings",
    "api.resume.btn": "Resume last chat & launch",
    "api.resume.tip":
      "Uses the newest chat history JSON and the last launch template cache, then starts chat with transparent background and ComfyUI disabled.",
    "api.resume.title": "Launch chat",
    "api.tts.bundleDone": "TTS bundle is ready: {path}",
    "api.tts.bundleDownload": "Download",
    "api.tts.bundleFailed": "TTS bundle download failed.",
    "api.tts.bundleGenie": "Genie TTS Server",
    "api.tts.bundleGptSovits": "GPT-SoVITS v2pro",
    "api.tts.bundleGptSovits50": "GPT-SoVITS v2pro for RTX 50",
    "api.tts.bundleHint": "Downloads and extracts the same integrated TTS packages as the PySide settings window.",
    "api.tts.bundlePick": "Package",
    "api.tts.bundleTitle": "TTS integrated package",
    "api.title": "API Configuration",
    "api.toast.saved": "API settings saved",
    "background.delete.confirmBody": "Delete background group “{name}”?",
    "background.delete.confirmTitle": "Delete background",
    "background.description": "Maintain background groups, image tags, and BGM tags for templates and chat launch.",
    "background.emptyBody": "Create a background group before using it in templates.",
    "background.emptyTitle": "No backgrounds",
    "background.error.deleteFallback": "The background group was not deleted.",
    "background.error.exportFallback": "The background package was not exported.",
    "background.error.importFallback": "The background package was not imported.",
    "background.error.saveFallback": "Background fields did not pass validation.",
    "background.error.translateFallback": "AI translation failed.",
    "background.field.bgTags": "Image tags",
    "background.field.bgmTags": "BGM tags",
    "background.field.name": "Name",
    "background.field.spritePrefix": "Resource directory",
    "background.groupListTitle": "Background groups",
    "background.loading": "Loading backgrounds",
    "background.resource.backgroundImage": "Background images",
    "background.resource.bgm": "BGM",
    "background.resource.count": "Count",
    "background.resource.description":
      "The React layer edits resource declarations; upload, copy, and validation stay in the platform adapter.",
    "background.resource.imageCount": "{count} images",
    "background.resource.source": "Source",
    "background.resource.type": "Type",
    "background.action.aiTranslate": "AI translate",
    "background.action.community": "Community backgrounds",
    "background.action.saveBgmTags": "Save BGM description",
    "background.action.saveImageTags": "Save image description",
    "background.action.uploadContribution": "Upload contribution",
    "background.asset.addBgm": "Add BGM row",
    "background.asset.addImage": "Add image row",
    "background.asset.clearBgm": "Delete all BGM",
    "background.asset.clearImages": "Delete all images",
    "background.asset.deleteSelectedBgm": "Delete selected BGM",
    "background.asset.emptyBgm": "No BGM entries",
    "background.asset.emptyImages": "No background images",
    "background.asset.filename": "File name",
    "background.asset.index": "Index",
    "background.asset.noSelectedBgm": "Select BGM rows first.",
    "background.asset.path": "Path",
    "background.asset.preview": "Preview",
    "background.asset.select": "Select",
    "background.asset.selectBgm": "Select BGM files",
    "background.asset.selectImages": "Select image files",
    "background.asset.selectedFiles": "{count} files selected",
    "background.asset.tag": "Tag",
    "background.asset.uploadBgm": "Upload listed BGM",
    "background.asset.uploadError": "Resource upload failed.",
    "background.asset.uploadImages": "Upload listed images",
    "background.section.assets": "Resources",
    "background.section.bgm": "Background music",
    "background.section.images": "Background images",
    "background.section.info": "Background info",
    "background.section.tags": "Tags",
    "background.title": "Backgrounds",
    "background.toast.deleted": "Background deleted",
    "background.toast.exportComplete": "Export complete",
    "background.toast.importComplete": "Imported {count} background groups",
    "background.toast.saved": "Background saved",
    "background.validation.nameRequired": "Background name is required.",
    "bottom.ready": "Ready",
    "bottom.author": "By: 不二咲爱笑",
    "bottom.saving": "Saving",
    "bottom.syncing": "Syncing",
    "bottom.transport": "Components communicate through repositories, queries, and platform adapters",
    "character.delete.confirmBody": "Delete character “{name}”?",
    "character.delete.confirmTitle": "Delete character",
    "character.description": "Edit character profile, sprites, emotion tags, and TTS parameters.",
    "character.emptyBody": "Import a character package or create a character.",
    "character.emptyTitle": "No characters",
    "character.error.aiFallback": "AI writing failed.",
    "character.error.deleteFallback": "The character was not deleted.",
    "character.error.exportFallback": "The character package was not exported.",
    "character.error.importFallback": "The character package was not imported.",
    "character.error.saveFallback": "Character fields did not pass validation.",
    "character.error.translateFallback": "AI translation failed.",
    "character.action.aiTranslate": "AI translate",
    "character.action.aiWrite": "AI write",
    "character.action.community": "Community characters",
    "character.action.pickColor": "Pick color",
    "character.action.uploadContribution": "Upload contribution",
    "character.field.characterSetting": "Character setting",
    "character.field.color": "Name color",
    "character.field.emotionTags": "Emotion tags (per upload / order)",
    "character.field.gptModel": "GPT model path",
    "character.field.name": "Character name",
    "character.field.promptLang": "Language (en/ja/zh)",
    "character.field.promptText": "Reference line text",
    "character.field.pronunciationMap": "Pronunciation map",
    "character.field.referAudio": "Reference audio",
    "character.field.sovitsModel": "SoVITS model",
    "character.field.speechSpeed": "TTS Speed",
    "character.field.speechVolume": "TTS Volume",
    "character.field.spritePrefix": "Upload directory name (ASCII)",
    "character.field.spriteScale": "Display scale",
    "character.import.noFile": "No file selected",
    "character.listTitle": "Characters",
    "character.loading": "Loading characters",
    "character.memory.add": "Add memory",
    "character.memory.count": "{count} memories",
    "character.memory.delete": "Delete",
    "character.memory.empty": "No memories",
    "character.memory.error": "Memory operation failed.",
    "character.memory.loading": "Loading memories",
    "character.memory.nameRequired": "Enter or select a character name to manage memories.",
    "character.memory.placeholder": "Memory content",
    "character.memory.refresh": "Refresh",
    "character.memory.section": "Long-term memory",
    "character.row.current": "Current character",
    "character.section.basic": "Basic info",
    "character.section.personality": "Character setting",
    "character.section.sprites": "Sprites",
    "character.section.voice": "Voice reference (SoVITS, optional)",
    "character.sprite.add": "Add sprite row",
    "character.sprite.clear": "Delete all sprites",
    "character.sprite.empty": "No sprites",
    "character.sprite.imageError": "Sprite image operation failed.",
    "character.sprite.path": "Sprite path",
    "character.sprite.saveScale": "Save scale",
    "character.sprite.saveTags": "Upload tags",
    "character.sprite.selectImages": "Choose images...",
    "character.sprite.selectedFiles": "{count} files selected",
    "character.sprite.deleteVoice": "Delete voice",
    "character.sprite.saveVoiceText": "Save text",
    "character.sprite.uploadVoice": "Upload voice",
    "character.sprite.uploadImages": "Upload",
    "character.sprite.voiceError": "Sprite voice operation failed.",
    "character.sprite.voiceHint": "Voice path and text are stored per sprite, matching the PySide sprite voice panel.",
    "character.sprite.voicePath": "Voice path",
    "character.sprite.voiceText": "Voice text",
    "character.sprite.voiceUploadPath": "Voice upload file",
    "character.title": "Characters",
    "character.toast.deleted": "Character deleted",
    "character.toast.exportComplete": "Export complete",
    "character.toast.importComplete": "Imported {count} characters",
    "character.toast.saved": "Character saved",
    "character.validation.gptModelExt": "GPT model path must end with .ckpt.",
    "character.validation.nameRequired": "Character name is required.",
    "character.validation.noQuotedPaths": "Model and reference audio paths must not be wrapped in quotes.",
    "character.validation.sovitsModelExt": "SoVITS model path must end with .pth.",
    "character.validation.spritePrefixAscii": "Sprite directory must contain ASCII characters only.",
    "character.validation.spritePrefixRequired": "Sprite directory is required.",
    "chat.clear.confirmAction": "Clear",
    "chat.clear.confirmBody": "Clear the current conversation history? This also deletes the linked history file.",
    "chat.clear.confirmTitle": "Clear history",
    "chat.emptyDialog": "Waiting for the conversation to start.",
    "chat.error.commandFallback": "The chat command was not completed.",
    "chat.error.loadFallback": "Could not load chat state",
    "chat.input.micDenied": "Microphone permission was denied.",
    "chat.input.micError": "Speech recognition could not start.",
    "chat.input.micStart": "Start microphone",
    "chat.input.micStop": "Stop microphone",
    "chat.input.micUnsupported":
      "This browser does not support speech recognition. Use Chrome/Edge on the local React bridge.",
    "chat.input.placeholder": "Enter dialogue",
    "chat.input.send": "Send",
    "chat.toast.historyCleared": "History cleared",
    "chat.toast.historyCopied": "History copied",
    "chat.toast.historyOpened": "History opened",
    "chat.toolbar.clearHistory": "Clear history",
    "chat.toolbar.copyHistory": "Copy history",
    "chat.toolbar.openHistory": "Open history",
    "chat.toolbar.pauseAsr": "Pause ASR",
    "chat.toolbar.reroll": "Retry reply",
    "chat.toolbar.skipSpeech": "Skip",
    "common.add": "Add",
    "common.author": "Author",
    "common.cancel": "Cancel",
    "common.chooseFile": "Choose file",
    "common.chooseFolder": "Choose folder",
    "common.close": "Close",
    "common.delete": "Delete",
    "common.deleteFailed": "Delete failed",
    "common.description": "Description",
    "common.edit": "Edit",
    "common.entry": "Entry",
    "common.name": "Name",
    "common.no": "No",
    "common.open": "Open",
    "common.refresh": "Refresh",
    "common.remove": "Remove",
    "common.retry": "Retry",
    "common.save": "Save",
    "common.saveFailed": "Save failed",
    "common.saveApply": "Save and apply",
    "common.export": "Export",
    "common.exportFailed": "Export failed",
    "common.import": "Import",
    "common.importFailed": "Import failed",
    "common.new": "New",
    "common.yes": "Yes",
    "common.operationFailed": "Operation failed",
    "common.status": "Status",
    "common.subpages": "Subpages",
    "common.validationFailed": "Validation failed",
    "common.fixInvalidFields": "Fix the highlighted fields first.",
    "form.jsonInvalid": "Invalid JSON. Fix it before saving.",
    "filePicker.address": "Path",
    "filePicker.empty": "This folder is empty.",
    "filePicker.hidden": "Show hidden files",
    "filePicker.loading": "Loading folder...",
    "filePicker.modified": "Modified",
    "filePicker.name": "Name",
    "filePicker.parent": "Parent folder",
    "filePicker.roots": "Locations",
    "filePicker.selectCurrent": "Select folder",
    "filePicker.selectFile": "Select file",
    "filePicker.size": "Size",
    "filePicker.type": "Type",
    "filePicker.typeDirectory": "Folder",
    "filePicker.typeFile": "File",
    "launch.background": "Background",
    "launch.character": "Characters",
    "launch.description": "Launch parameters combine a template, characters, background, and optional history file.",
    "launch.emptyBody": "Create at least one template first.",
    "launch.emptyTitle": "Launch data is incomplete",
    "launch.history": "History",
    "launch.historyHelp": "Multiple characters are sent to the launch payload in this selection order.",
    "launch.historyPlaceholder": "./data/chat_history/...",
    "launch.start": "Launch",
    "launch.template": "Template",
    "launch.title": "Launch chat",
    "launch.toast.failed": "Launch failed",
    "launch.toast.started": "Chat launched",
    "launch.validation.historyJson": "History path must point to a .json file.",
    "mcp.action.openYaml": "Open YAML",
    "mcp.action.previewTools": "Preview tools",
    "mcp.action.saveServer": "Save server",
    "mcp.defaultTimeout": "Default call timeout",
    "mcp.delete.confirmBody": "Remove this MCP server from the draft list?",
    "mcp.delete.confirmTitle": "Delete MCP server",
    "mcp.description": "MCP servers are stored in data/config/mcp.yaml and applied through the bridge.",
    "mcp.dialog.addTitle": "Add MCP server",
    "mcp.dialog.editTitle": "Edit MCP server",
    "mcp.enabled": "Enabled",
    "mcp.field.args": "Args JSON",
    "mcp.field.callTimeout": "Call timeout",
    "mcp.field.command": "Command",
    "mcp.field.connection": "Connection",
    "mcp.field.env": "Env JSON",
    "mcp.field.group": "Tool group",
    "mcp.field.headers": "Headers JSON",
    "mcp.field.prefix": "Name prefix",
    "mcp.field.registeredName": "Registered name",
    "mcp.field.transport": "Transport",
    "mcp.field.toolName": "Tool",
    "mcp.field.url": "URL",
    "mcp.globalEnable": "Enable MCP tools",
    "mcp.importJson": "Import JSON",
    "mcp.importJson.hint": "Paste a JSON object with mcpServers.",
    "mcp.importJson.noServers": "No mcpServers field found or empty.",
    "mcp.importJson.okBody": "Imported {count} MCP server(s). Click Save & Apply to activate.",
    "mcp.importJson.title": "Import MCP JSON",
    "mcp.installHint": "Install the Python mcp package before connecting real servers.",
    "mcp.preview.empty": "No tools returned.",
    "mcp.preview.emptyBody": "Check enabled servers, network, or command.",
    "mcp.preview.loading": "Loading MCP config",
    "mcp.server.emptyBody": "Add an SSE, Streamable HTTP, or stdio server.",
    "mcp.server.emptyTitle": "No MCP servers",
    "mcp.server.title": "MCP servers",
    "mcp.status.disabled": "Disabled",
    "mcp.status.enabled": "Enabled",
    "mcp.status.no": "No",
    "mcp.status.yes": "Yes",
    "mcp.toast.importFailed": "Import failed",
    "mcp.toast.importSuccess": "MCP servers imported",
    "mcp.toast.opened": "Config file opened",
    "mcp.toast.operationFailed": "MCP operation failed",
    "mcp.toast.previewSuccess": "MCP tools refreshed",
    "mcp.toast.saveSuccess": "MCP config saved",
    "mcp.tools.title": "Enabled tools preview",
    "mcp.validation.argsArray": "Args must be a JSON array.",
    "mcp.validation.defaultTimeout": "Default timeout must be greater than 0.",
    "mcp.validation.envObject": "Env must be a JSON object.",
    "mcp.validation.headersObject": "Headers must be a JSON object.",
    "mcp.validation.needCommand": "Command is required for stdio servers.",
    "mcp.validation.needUrl": "URL is required for HTTP MCP servers.",
    "nav.api": "API",
    "nav.background": "Backgrounds",
    "nav.character": "Characters",
    "nav.launch": "Launch chat",
    "nav.musicCover": "Music cover",
    "nav.plugins": "Plugins",
    "nav.secondary": "Secondary navigation",
    "nav.settingsCenter": "Settings navigation",
    "nav.system": "System",
    "nav.template": "Templates",
    "nav.tools": "Tools",
    "tools.browse": "Browse",
    "tools.character": "Character",
    "tools.cropBtn": "Run crop",
    "tools.cropInput": "Input folder",
    "tools.cropOutput": "Output folder (optional)",
    "tools.cropRatio": "Keep top fraction of height",
    "tools.cropTitle": "Batch crop sprites",
    "tools.description":
      "Sprite generation, crop, and background removal use the same tool flow as the PySide settings window.",
    "tools.galleryEmpty": "No generated sprites",
    "tools.galleryLabel": "Output previews",
    "tools.gemBox": "Batch-generate sprites (requires Gemini API key)",
    "tools.gemHint": "A Gemini API key is required. You can also use the official free web UI.",
    "tools.genPromptsBtn": "Generate prompt lines",
    "tools.genSpritesBtn": "Batch-generate",
    "tools.h2Sprites": "Sprite tools",
    "tools.msgGenFailed": "Generation failed.",
    "tools.msgGenOk": "Generated {n} file(s) (output: {dir})",
    "tools.msgNoPrompts": "Enter at least one prompt",
    "tools.msgRefInvalid": "Choose a valid reference image",
    "tools.msgSelectChar": "Select a character",
    "tools.msgTitleGen": "Generate",
    "tools.msgTitlePrompts": "Prompts",
    "tools.outputDirPlaceholder": "Output directory (optional)",
    "tools.promptLine": "Sprite {n}: {text}",
    "tools.promptsGenerated": "Generated {n} prompt line(s).",
    "tools.promptsPlaceholder": "One prompt per line",
    "tools.refDialogTitle": "Reference image",
    "tools.refLabel": "Reference image",
    "tools.refPlaceholder": "Reference image path",
    "tools.rmbgBtn": "Run",
    "tools.rmbgFirst": "The first run may download models; it can take a while.",
    "tools.rmbgInput": "Input folder",
    "tools.rmbgOutput": "Output folder (optional)",
    "tools.rmbgTitle": "Remove background (batch)",
    "tools.spriteCount": "Number of sprites to generate",
    "tools.tabMain": "Sprites & batch tools",
    "plugin.action.install": "Install",
    "plugin.action.installed": "Installed",
    "plugin.action.openGitHub": "GitHub",
    "plugin.action.register": "Register",
    "plugin.action.uninstall": "Uninstall",
    "plugin.action.update": "Update",
    "plugin.action.viewConfig": "Plugin settings",
    "plugin.appUpdate.button": "Update app",
    "plugin.appUpdate.confirm": "Update",
    "plugin.appUpdate.failed": "App update failed.",
    "plugin.appUpdate.ref": "Version",
    "plugin.appUpdate.refHead": "Default branch tip (HEAD)",
    "plugin.appUpdate.refLatest": "Latest release",
    "plugin.appUpdate.repo": "Repository: {repo}",
    "plugin.appUpdate.success": "App updated",
    "plugin.appUpdate.tagInvalid": "Pick a tag or use Latest release / HEAD.",
    "plugin.appUpdate.tagsEmpty": "No tags were returned; Latest release and HEAD are still available.",
    "plugin.appUpdate.tagsLoading": "Loading tags...",
    "plugin.appUpdate.title": "Update application",
    "plugin.appUpdate.version": "Current version: {version}",
    "plugin.appUpdate.versionUnknown": "Current version: unknown",
    "plugin.appUpdate.warning":
      "This downloads a GitHub source archive and merges it into the current install directory, skipping data and plugins. This cannot be undone automatically.",
    "plugin.author": "Author",
    "plugin.catalog.emptyBody": "Refresh the catalog to show community plugins.",
    "plugin.catalog.emptyTitle": "No plugins found",
    "plugin.catalog.errorBody": "Check the network and try again.",
    "plugin.catalog.errorTitle": "Could not load plugin catalog",
    "plugin.catalog.loading": "Loading plugin catalog",
    "plugin.catalog.title": "Discover",
    "plugin.description":
      "Plugins contribute only to fixed slots and are installed, enabled, or disabled through the platform layer.",
    "plugin.directory": "Directory",
    "plugin.detail.back": "Back to plugins",
    "plugin.detail.errorBody": "The plugin page metadata could not be loaded.",
    "plugin.detail.errorTitle": "Could not load plugin settings",
    "plugin.detail.kindSettings": "Settings page",
    "plugin.detail.kindTools": "Tools tab",
    "plugin.detail.loading": "Loading plugin settings",
    "plugin.detail.noUi": "This plugin has no settings page contribution.",
    "plugin.detail.pages": "Plugin pages",
    "plugin.detail.pyqtNotice":
      "This plugin still contributes a PyQt widget and does not expose a React config schema.",
    "plugin.detail.save": "Save settings",
    "plugin.detail.saveFailed": "Plugin settings were not saved.",
    "plugin.detail.saveSuccess": "Plugin settings saved",
    "plugin.detail.settingsPages": "Settings pages",
    "plugin.detail.title": "{title} settings",
    "plugin.detail.toolsTabs": "Tools tabs",
    "plugin.disable.confirmBody": "Disable “{title}” on the next app start?",
    "plugin.disable.confirmTitle": "Disable plugin",
    "plugin.error.installFallback": "Check the plugin ID or network status.",
    "plugin.error.toggleFallback": "Plugin status was not updated.",
    "plugin.error.uninstallFallback": "Plugin was not removed.",
    "plugin.id": "Plugin ID",
    "plugin.install.entryHelp":
      "Manifest entries are supported. GitHub repositories download sources, install dependencies, and try to register automatically.",
    "plugin.install.entryLabel": "Plugin ID",
    "plugin.install.placeholder": "plugins.xxx.plugin:Plugin or owner/repo",
    "plugin.install.title": "Install",
    "plugin.installRef.title": "Choose plugin version",
    "plugin.installed.emptyBody": "Installed plugins will appear here.",
    "plugin.installed.emptyTitle": "No plugins",
    "plugin.installed.count": "{count} plugins",
    "plugin.installed.loading": "Loading plugins",
    "plugin.installed.title": "Installed",
    "plugin.loadError.unavailable":
      "Configured in plugins.yaml, but the plugin code is not installed or failed to import.",
    "plugin.permissions": "Permissions",
    "plugin.plugin": "Plugin",
    "plugin.toggle.disable": "Disable",
    "plugin.toggle.enable": "Enable",
    "plugin.status.downloaded": "Downloaded",
    "plugin.status.disabled": "Disabled",
    "plugin.status.enabled": "Enabled",
    "plugin.status.installed": "Installed",
    "plugin.status.notInstalled": "Not installed",
    "plugin.status.unavailable": "Not loaded",
    "plugin.status.updating": "Updating",
    "plugin.table.actionHeader": "Actions",
    "plugin.table.slots": "Slots",
    "plugin.toast.disabled": "Plugin disabled",
    "plugin.toast.enabled": "Plugin enabled",
    "plugin.toast.installFailed": "Install failed",
    "plugin.toast.installSuccess": "Plugin installed",
    "plugin.toast.operationFailed": "Operation failed",
    "plugin.toast.restartHint": "Restart the app for plugin changes to take effect.",
    "plugin.toast.uninstalled": "Plugin uninstalled",
    "plugin.uninstall.confirmBody": "Remove “{title}” from the manifest and delete its plugin folder when safe?",
    "plugin.uninstall.confirmTitle": "Uninstall plugin",
    "plugin.version": "Version",
    "system.asr.computeAuto": "Auto (follow device)",
    "system.asr.computeType": "Compute precision",
    "system.asr.device": "Device",
    "system.asr.deviceAuto": "Auto",
    "system.asr.followUi": "Follow interface language",
    "system.asr.hint":
      "Recognition language applies to every engine. Whisper model, device, and precision appear only for Whisper engines; Vosk keeps only its model path.",
    "system.asr.langEn": "English",
    "system.asr.langJa": "Japanese",
    "system.asr.langYue": "Cantonese",
    "system.asr.langZh": "Chinese",
    "system.asr.language": "Recognition language",
    "system.asr.modelCustom": "Custom (local path or Hugging Face id)",
    "system.asr.modelCustomPlaceholder": "Local folder or full model id",
    "system.asr.provider": "Engine",
    "system.asr.title": "Voice input (ASR)",
    "system.asr.voskHint":
      "Download a Vosk model, extract it, and paste the folder path into the Vosk model path field.",
    "system.asr.voskModelPath": "Vosk model path",
    "system.asr.voskModels": "Vosk models",
    "system.asr.whisperModel": "Whisper model",
    "system.description": "Base interface, media paths, and live room settings.",
    "system.error.saveFallback": "Check the system configuration.",
    "system.loading": "Loading system settings",
    "system.title": "System",
    "system.toast.saved": "System settings saved",
    "template.action.launch": "Launch chat",
    "template.action.quickRestart": "Quick restart",
    "template.action.selectAllCharacters": "Select all characters",
    "template.defaultName": "New template",
    "template.description":
      "Template editing and generation reuse character and background queries, then refresh chat launch after saving.",
    "template.emptyBody": "Generate a template first.",
    "template.emptySelection": "No template selected",
    "template.emptyTitle": "No templates",
    "template.error.generateFailed": "Generate failed",
    "template.error.generateFallback": "Check the selected characters and background.",
    "template.error.launchFailed": "Launch failed",
    "template.error.saveFallback": "Template content was not saved.",
    "template.field.background": "Background",
    "template.field.characters": "Characters",
    "template.field.content": "Content",
    "template.field.historyFile": "History file",
    "template.field.initSprite": "Initial sprite",
    "template.field.maxDialogItems": "Max dialog items",
    "template.field.maxSpeechChars": "Max speech chars",
    "template.field.name": "Name",
    "template.field.path": "Path",
    "template.field.scenario": "Scenario",
    "template.field.system": "System template",
    "template.field.templateName": "Template name",
    "template.field.useCg": "Use ComfyUI",
    "template.field.useChoice": "Choice rules",
    "template.field.useCot": "COT prompt",
    "template.field.useEffect": "Visual effects",
    "template.field.useNarration": "Narration rules",
    "template.field.useStat": "Stat rules",
    "template.field.useTranslation": "LLM translation",
    "template.field.voiceLanguage": "Voice target language",
    "template.listTitle": "Templates",
    "template.loading": "Loading templates",
    "template.mode.edit": "Edit",
    "template.mode.generate": "Generate",
    "template.quickRestart.body": "Clear the selected/default chat history and launch a fresh chat?",
    "template.quickRestart.title": "Quick restart",
    "template.section.content": "Template content",
    "template.section.generate": "Generate template",
    "template.section.load": "Load from file",
    "template.section.run": "Save and launch",
    "template.section.scenario": "User scenario",
    "template.section.system": "System template",
    "template.title": "Templates",
    "template.toast.generated": "Template generated",
    "template.toast.launched": "Chat launched",
    "template.toast.saved": "Template saved",
    "template.transparentBackground": "透明场景",
    "template.validation.backgroundRequired": "Choose a background.",
    "template.validation.charactersRequired": "Choose at least one character.",
    "template.validation.nameRequired": "Template name is required.",
    "top.chatStage": "Chat stage",
  },
  ja: {
    "app.brandSubtitle": "AI RPG Tools",
    "app.preview": "設定",
    "app.shellMeta": "AI RPG Tools",
    "app.title": "新世界プログラム",
    "api.description":
      "大規模言語モデル、TTS、音声入力、ComfyUI を設定します。API 関連は api.yaml、マイク認識は system_config.yaml に保存します。",
    "api.error.saveFallback": "設定項目を確認してください。",
    "api.links.help":
      "展開先を TTS サービス起動パスに指定してください。GPT SoVITS は約 11GB、Genie TTS は約 4GB 必要です。",
    "api.links.link1": "GitHub: GPT-SoVITS",
    "api.links.link2": "ModelScope: GPT-SoVITS v2pro",
    "api.links.link3": "ModelScope: RTX 50 系向け",
    "api.links.link4": "Genie TTS（CPU 向け軽量推論）",
    "api.links.link5": "ModelScope: Genie TTS Server 統合包",
    "api.links.title": "リソース",
    "api.language.field": "インターフェース言語",
    "api.language.hint": "即時反映されます。単独実行中のデスクトップチャット窓には次回起動時に適用されます。",
    "api.language.title": "インターフェース言語",
    "api.llm.apiKey": "LLM API Key",
    "api.llm.baseUrl": "LLM ベース URL",
    "api.llm.connectionTitle": "LLM API",
    "api.llm.fetchDone": "{count} 件のモデルを取得しました。",
    "api.llm.fetchEmpty": "利用可能なモデルを取得できませんでした。",
    "api.llm.fetchFailed": "モデル一覧の取得に失敗しました。",
    "api.llm.fetchMissing": "LLM ベース URL と API Key を先に入力してください。",
    "api.llm.fetchModels": "利用可能なモデルを取得",
    "api.llm.fetchTitle": "モデル一覧",
    "api.llm.fetching": "モデルを取得中",
    "api.llm.model": "モデル ID",
    "api.llm.modelCustom": "カスタムモデル ID...",
    "api.llm.modelPlaceholder": "モデル ID",
    "api.llm.provider": "プロバイダー",
    "api.llm.reasoningEffort": "推論強度",
    "api.llm.required": "プロバイダー、ベース URL、API Key、モデル ID は必須です。",
    "api.llm.streaming": "ストリーミング応答",
    "api.llm.thinkingEnabled": "思考モード",
    "api.llm.thinkingUnsupported": "このモデルは思考モードに対応していません。",
    "api.loading": "API 設定を読み込み中",
    "api.resume.btn": "最後のチャットを読み込んで起動",
    "api.resume.tip":
      "最新のチャット履歴 JSON と前回起動テンプレートを使い、透明背景・ComfyUI 無効でチャットを開始します。",
    "api.resume.title": "チャット起動",
    "api.tts.bundleDone": "TTS 統合パッケージの準備ができました: {path}",
    "api.tts.bundleDownload": "ダウンロード",
    "api.tts.bundleFailed": "TTS 統合パッケージのダウンロードに失敗しました。",
    "api.tts.bundleGenie": "Genie TTS Server",
    "api.tts.bundleGptSovits": "GPT-SoVITS v2pro",
    "api.tts.bundleGptSovits50": "RTX 50 系向け GPT-SoVITS v2pro",
    "api.tts.bundleHint": "PySide 設定画面と同じ TTS 統合パッケージをダウンロードして展開します。",
    "api.tts.bundlePick": "パッケージ",
    "api.tts.bundleTitle": "TTS 統合パッケージ",
    "api.title": "API 設定",
    "api.toast.saved": "API 設定を保存しました",
    "background.delete.confirmBody": "背景グループ「{name}」を削除しますか？",
    "background.delete.confirmTitle": "背景を削除",
    "background.description": "テンプレートとチャット開始で使う背景グループ、画像タグ、BGM タグを管理します。",
    "background.emptyBody": "テンプレートで使う前に背景グループを作成してください。",
    "background.emptyTitle": "背景がありません",
    "background.error.deleteFallback": "背景グループを削除できませんでした。",
    "background.error.exportFallback": "背景パッケージを書き出せませんでした。",
    "background.error.importFallback": "背景パッケージを取り込めませんでした。",
    "background.error.saveFallback": "背景項目の検証に失敗しました。",
    "background.error.translateFallback": "AI 翻訳に失敗しました。",
    "background.field.bgTags": "画像タグ",
    "background.field.bgmTags": "BGM タグ",
    "background.field.name": "名前",
    "background.field.spritePrefix": "リソースディレクトリ",
    "background.groupListTitle": "背景グループ",
    "background.loading": "背景を読み込み中",
    "background.resource.backgroundImage": "背景画像",
    "background.resource.bgm": "BGM",
    "background.resource.count": "数",
    "background.resource.description":
      "React 層はリソース宣言のみ編集し、アップロード、コピー、検証は platform adapter に任せます。",
    "background.resource.imageCount": "{count} 枚",
    "background.resource.source": "出所",
    "background.resource.type": "種類",
    "background.action.aiTranslate": "AI 翻訳",
    "background.action.community": "コミュニティ背景",
    "background.action.saveBgmTags": "BGM 説明を保存",
    "background.action.saveImageTags": "背景説明を保存",
    "background.action.uploadContribution": "投稿フォーム",
    "background.asset.addBgm": "BGM 行を追加",
    "background.asset.addImage": "画像行を追加",
    "background.asset.clearBgm": "BGM をすべて削除",
    "background.asset.clearImages": "画像をすべて削除",
    "background.asset.deleteSelectedBgm": "選択した BGM を削除",
    "background.asset.emptyBgm": "BGM がありません",
    "background.asset.emptyImages": "背景画像がありません",
    "background.asset.filename": "ファイル名",
    "background.asset.index": "番号",
    "background.asset.noSelectedBgm": "先に BGM 行を選択してください。",
    "background.asset.path": "パス",
    "background.asset.preview": "再生",
    "background.asset.select": "選択",
    "background.asset.selectBgm": "BGM ファイルを選択",
    "background.asset.selectImages": "画像ファイルを選択",
    "background.asset.selectedFiles": "{count} 件を選択中",
    "background.asset.tag": "タグ",
    "background.asset.uploadBgm": "一覧の BGM をアップロード",
    "background.asset.uploadError": "リソースのアップロードに失敗しました。",
    "background.asset.uploadImages": "一覧の画像をアップロード",
    "background.section.assets": "リソース",
    "background.section.bgm": "BGM",
    "background.section.images": "背景画像",
    "background.section.info": "背景情報",
    "background.section.tags": "タグ",
    "background.title": "背景管理",
    "background.toast.deleted": "背景を削除しました",
    "background.toast.exportComplete": "書き出し完了",
    "background.toast.importComplete": "{count} 件の背景グループを取り込みました",
    "background.toast.saved": "背景を保存しました",
    "background.validation.nameRequired": "背景名は必須です。",
    "bottom.ready": "待機中",
    "bottom.author": "By: 不二咲爱笑",
    "bottom.saving": "保存中",
    "bottom.syncing": "同期中",
    "bottom.transport": "コンポーネントは repository、query、platform adapter で通信",
    "character.delete.confirmBody": "キャラクター「{name}」を削除しますか？",
    "character.delete.confirmTitle": "キャラクターを削除",
    "character.description": "キャラクター設定、立ち絵、感情タグ、TTS パラメータを編集します。",
    "character.emptyBody": "キャラクターパッケージを取り込むか、新規作成してください。",
    "character.emptyTitle": "キャラクターがありません",
    "character.error.aiFallback": "AI 生成に失敗しました。",
    "character.error.deleteFallback": "キャラクターを削除できませんでした。",
    "character.error.exportFallback": "キャラクターパッケージを書き出せませんでした。",
    "character.error.importFallback": "キャラクターパッケージを取り込めませんでした。",
    "character.error.saveFallback": "キャラクター項目の検証に失敗しました。",
    "character.error.translateFallback": "AI 翻訳に失敗しました。",
    "character.action.aiTranslate": "AI 翻訳",
    "character.action.aiWrite": "AI 生成",
    "character.action.community": "コミュニティキャラ",
    "character.action.pickColor": "色を選択",
    "character.action.uploadContribution": "投稿フォーム",
    "character.field.characterSetting": "人物設定",
    "character.field.color": "名前色",
    "character.field.emotionTags": "情緒タグ（アップロード/順序に対応）",
    "character.field.gptModel": "GPT モデルパス",
    "character.field.name": "キャラクター名",
    "character.field.promptLang": "言語 (en/ja/zh)",
    "character.field.promptText": "参照テキスト",
    "character.field.pronunciationMap": "読みマップ",
    "character.field.referAudio": "参照音声",
    "character.field.sovitsModel": "SoVITS モデル",
    "character.field.speechSpeed": "TTS 速度",
    "character.field.speechVolume": "TTS 音量",
    "character.field.spritePrefix": "アップロード用ディレクトリ名（英字）",
    "character.field.spriteScale": "表示倍率",
    "character.import.noFile": "ファイル未選択",
    "character.listTitle": "キャラクター",
    "character.loading": "キャラクターを読み込み中",
    "character.memory.add": "記憶を追加",
    "character.memory.count": "{count} 件",
    "character.memory.delete": "削除",
    "character.memory.empty": "記憶がありません",
    "character.memory.error": "記憶操作に失敗しました。",
    "character.memory.loading": "記憶を読み込み中",
    "character.memory.nameRequired": "記憶を管理するにはキャラクター名を入力または選択してください。",
    "character.memory.placeholder": "記憶内容",
    "character.memory.refresh": "更新",
    "character.memory.section": "長期記憶",
    "character.row.current": "現在のキャラクター",
    "character.section.basic": "基本情報",
    "character.section.personality": "キャラ設定",
    "character.section.sprites": "立ち絵",
    "character.section.voice": "声の参照（SoVITS 等・任意）",
    "character.sprite.add": "立ち絵行を追加",
    "character.sprite.clear": "立ち絵をすべて削除",
    "character.sprite.empty": "立ち絵がありません",
    "character.sprite.imageError": "立ち絵画像の操作に失敗しました。",
    "character.sprite.path": "立ち絵パス",
    "character.sprite.saveScale": "倍率を保存",
    "character.sprite.saveTags": "タグをアップロード",
    "character.sprite.selectImages": "画像を選択...",
    "character.sprite.selectedFiles": "{count} 件を選択中",
    "character.sprite.deleteVoice": "音声を削除",
    "character.sprite.saveVoiceText": "テキスト保存",
    "character.sprite.uploadVoice": "音声をアップロード",
    "character.sprite.uploadImages": "アップロード",
    "character.sprite.voiceError": "立ち絵音声の操作に失敗しました。",
    "character.sprite.voiceHint": "音声パスとテキストは PySide の立ち絵音声パネルと同じく立ち絵ごとに保存されます。",
    "character.sprite.voicePath": "音声パス",
    "character.sprite.voiceText": "音声テキスト",
    "character.sprite.voiceUploadPath": "アップロード音声",
    "character.title": "キャラクター",
    "character.toast.deleted": "キャラクターを削除しました",
    "character.toast.exportComplete": "書き出し完了",
    "character.toast.importComplete": "{count} 件のキャラクターを取り込みました",
    "character.toast.saved": "キャラクターを保存しました",
    "character.validation.gptModelExt": "GPT モデルのパスは .ckpt で終わる必要があります。",
    "character.validation.nameRequired": "キャラクター名は必須です。",
    "character.validation.noQuotedPaths": "モデルと参照音声のパスを引用符で囲まないでください。",
    "character.validation.sovitsModelExt": "SoVITS モデルのパスは .pth で終わる必要があります。",
    "character.validation.spritePrefixAscii": "立ち絵ディレクトリは ASCII 文字のみ使用できます。",
    "character.validation.spritePrefixRequired": "立ち絵ディレクトリは必須です。",
    "chat.clear.confirmAction": "消去",
    "chat.clear.confirmBody": "現在の会話履歴を消去しますか？関連する履歴ファイルも削除されます。",
    "chat.clear.confirmTitle": "履歴を消去",
    "chat.emptyDialog": "会話の開始を待っています。",
    "chat.error.commandFallback": "チャットコマンドを実行できませんでした。",
    "chat.error.loadFallback": "チャット状態を読み込めません",
    "chat.input.micDenied": "マイクの権限が拒否されました。",
    "chat.input.micError": "音声認識を開始できませんでした。",
    "chat.input.micStart": "マイクを開始",
    "chat.input.micStop": "マイクを停止",
    "chat.input.micUnsupported":
      "このブラウザは音声認識に対応していません。ローカルの React bridge で Chrome/Edge を使用してください。",
    "chat.input.placeholder": "台詞を入力",
    "chat.input.send": "送信",
    "chat.toast.historyCleared": "履歴を消去しました",
    "chat.toast.historyCopied": "履歴をコピーしました",
    "chat.toast.historyOpened": "履歴を開きました",
    "chat.toolbar.clearHistory": "履歴を消去",
    "chat.toolbar.copyHistory": "履歴をコピー",
    "chat.toolbar.openHistory": "履歴を開く",
    "chat.toolbar.pauseAsr": "ASR を一時停止",
    "chat.toolbar.reroll": "返答を再生成",
    "chat.toolbar.skipSpeech": "スキップ",
    "common.add": "追加",
    "common.author": "作者",
    "common.cancel": "キャンセル",
    "common.chooseFile": "ファイルを選択",
    "common.chooseFolder": "フォルダを選択",
    "common.close": "閉じる",
    "common.delete": "削除",
    "common.deleteFailed": "削除失敗",
    "common.description": "説明",
    "common.edit": "編集",
    "common.entry": "Entry",
    "common.name": "名前",
    "common.no": "いいえ",
    "common.open": "開く",
    "common.refresh": "更新",
    "common.remove": "削除",
    "common.retry": "再試行",
    "common.save": "保存",
    "common.saveFailed": "保存失敗",
    "common.saveApply": "保存して適用",
    "common.export": "書き出し",
    "common.exportFailed": "書き出し失敗",
    "common.import": "取り込み",
    "common.importFailed": "取り込み失敗",
    "common.new": "新規",
    "common.yes": "はい",
    "common.operationFailed": "操作失敗",
    "common.status": "状態",
    "common.subpages": "サブページ",
    "common.validationFailed": "検証失敗",
    "common.fixInvalidFields": "赤い項目を先に修正してください。",
    "form.jsonInvalid": "JSON が不正です。保存前に修正してください。",
    "filePicker.address": "パス",
    "filePicker.empty": "このフォルダは空です。",
    "filePicker.hidden": "隠しファイルを表示",
    "filePicker.loading": "フォルダを読み込み中...",
    "filePicker.modified": "更新日時",
    "filePicker.name": "名前",
    "filePicker.parent": "親フォルダ",
    "filePicker.roots": "場所",
    "filePicker.selectCurrent": "フォルダを選択",
    "filePicker.selectFile": "ファイルを選択",
    "filePicker.size": "サイズ",
    "filePicker.type": "種類",
    "filePicker.typeDirectory": "フォルダ",
    "filePicker.typeFile": "ファイル",
    "launch.background": "背景",
    "launch.character": "キャラクター",
    "launch.description": "テンプレート、キャラクター、背景、履歴ファイルを組み合わせて開始します。",
    "launch.emptyBody": "先にテンプレートを 1 つ以上作成してください。",
    "launch.emptyTitle": "開始に必要なデータが不足しています",
    "launch.history": "履歴",
    "launch.historyHelp": "複数キャラクターはこの選択順で起動 payload に入ります。",
    "launch.historyPlaceholder": "./data/chat_history/...",
    "launch.start": "開始",
    "launch.template": "テンプレート",
    "launch.title": "チャット開始",
    "launch.toast.failed": "起動失敗",
    "launch.toast.started": "チャットを起動しました",
    "launch.validation.historyJson": "履歴パスは .json ファイルを指定してください。",
    "mcp.action.openYaml": "YAML を開く",
    "mcp.action.previewTools": "ツールを確認",
    "mcp.action.saveServer": "サーバーを保存",
    "mcp.defaultTimeout": "既定の呼び出しタイムアウト",
    "mcp.delete.confirmBody": "この MCP サーバーを下書きから削除しますか？",
    "mcp.delete.confirmTitle": "MCP サーバーを削除",
    "mcp.description": "MCP サーバーは data/config/mcp.yaml に保存され、bridge 経由で適用されます。",
    "mcp.dialog.addTitle": "MCP サーバーを追加",
    "mcp.dialog.editTitle": "MCP サーバーを編集",
    "mcp.enabled": "有効",
    "mcp.field.args": "引数 JSON",
    "mcp.field.callTimeout": "呼び出しタイムアウト",
    "mcp.field.command": "コマンド",
    "mcp.field.connection": "接続",
    "mcp.field.env": "環境変数 JSON",
    "mcp.field.group": "ツールグループ",
    "mcp.field.headers": "ヘッダー JSON",
    "mcp.field.prefix": "名前プレフィックス",
    "mcp.field.registeredName": "登録名（LLM）",
    "mcp.field.transport": "転送",
    "mcp.field.toolName": "ツール名",
    "mcp.field.url": "URL",
    "mcp.globalEnable": "MCP ツールを有効化",
    "mcp.importJson": "JSON から取り込み",
    "mcp.importJson.hint": "mcpServers を含む JSON を貼り付けます。",
    "mcp.importJson.noServers": "mcpServers フィールドが見つからないか空です。",
    "mcp.importJson.okBody": "{count} 件の MCP サーバーを取り込みました。「保存して適用」を押して反映してください。",
    "mcp.importJson.title": "MCP JSON を取り込み",
    "mcp.installHint": "実サーバーに接続する前に Python の mcp パッケージを入れてください。",
    "mcp.preview.empty": "ツールは返されませんでした。",
    "mcp.preview.emptyBody": "有効化・ネットワーク・コマンドを確認してください。",
    "mcp.preview.loading": "MCP 設定を読み込み中",
    "mcp.server.emptyBody": "SSE、Streamable HTTP、または stdio サーバーを追加してください。",
    "mcp.server.emptyTitle": "MCP サーバーなし",
    "mcp.server.title": "MCP サーバー",
    "mcp.status.disabled": "無効",
    "mcp.status.enabled": "有効",
    "mcp.status.no": "いいえ",
    "mcp.status.yes": "はい",
    "mcp.toast.importFailed": "取り込み失敗",
    "mcp.toast.importSuccess": "MCP サーバーを取り込みました",
    "mcp.toast.opened": "設定ファイルを開きました",
    "mcp.toast.operationFailed": "MCP 操作失敗",
    "mcp.toast.previewSuccess": "MCP ツールを更新しました",
    "mcp.toast.saveSuccess": "MCP 設定を保存しました",
    "mcp.tools.title": "有効ツールのプレビュー",
    "mcp.validation.argsArray": "引数は JSON 配列にしてください。",
    "mcp.validation.defaultTimeout": "既定のタイムアウトは 0 より大きくしてください。",
    "mcp.validation.envObject": "環境変数は JSON オブジェクトにしてください。",
    "mcp.validation.headersObject": "ヘッダーは JSON オブジェクトにしてください。",
    "mcp.validation.needCommand": "stdio サーバーにはコマンドが必要です。",
    "mcp.validation.needUrl": "HTTP MCP サーバーには URL が必要です。",
    "nav.api": "API",
    "nav.background": "背景管理",
    "nav.character": "キャラクター",
    "nav.launch": "チャット開始",
    "nav.musicCover": "音楽カバー",
    "nav.plugins": "プラグイン",
    "nav.secondary": "サブナビゲーション",
    "nav.settingsCenter": "設定ナビゲーション",
    "nav.system": "システム",
    "nav.template": "チャットテンプレート",
    "nav.tools": "ツール",
    "tools.browse": "参照",
    "tools.character": "キャラ",
    "tools.cropBtn": "実行",
    "tools.cropInput": "入力フォルダ",
    "tools.cropOutput": "出力フォルダ（空欄可）",
    "tools.cropRatio": "上側の残し比率",
    "tools.cropTitle": "一括トリミング",
    "tools.description": "立ち絵生成、トリミング、背景除去は PySide 設定画面と同じツールフローを使います。",
    "tools.galleryEmpty": "生成済み立ち絵はありません",
    "tools.galleryLabel": "生成プレビュー",
    "tools.gemBox": "一括で立ち絵生成（Gemini API キーが必要）",
    "tools.gemHint": "Gemini API キーが必要です。公式の無料 Web 版も利用できます。",
    "tools.genPromptsBtn": "プロンプト行を生成",
    "tools.genSpritesBtn": "一括生成",
    "tools.h2Sprites": "立ち絵ツール",
    "tools.msgGenFailed": "生成に失敗しました。",
    "tools.msgGenOk": "{n} 枚生成しました（出力: {dir}）",
    "tools.msgNoPrompts": "プロンプトを入力してください",
    "tools.msgRefInvalid": "有効な参考画像を指定してください",
    "tools.msgSelectChar": "キャラを選んでください",
    "tools.msgTitleGen": "生成",
    "tools.msgTitlePrompts": "プロンプト",
    "tools.outputDirPlaceholder": "出力先（空欄可）",
    "tools.promptLine": "立ち絵 {n}：{text}",
    "tools.promptsGenerated": "{n} 行のプロンプトを生成しました。",
    "tools.promptsPlaceholder": "1 行 1 プロンプト",
    "tools.refDialogTitle": "参考画像",
    "tools.refLabel": "参考画像",
    "tools.refPlaceholder": "参考画像のパス",
    "tools.rmbgBtn": "実行",
    "tools.rmbgFirst": "初回はモデル取得で時間がかかる場合があります。",
    "tools.rmbgInput": "入力フォルダ",
    "tools.rmbgOutput": "出力フォルダ（空欄可）",
    "tools.rmbgTitle": "一括で背景除去",
    "tools.spriteCount": "生成枚数",
    "tools.tabMain": "立ち絵・一括処理",
    "plugin.action.install": "インストール",
    "plugin.action.installed": "インストール済み",
    "plugin.action.openGitHub": "GitHub",
    "plugin.action.register": "登録",
    "plugin.action.uninstall": "アンインストール",
    "plugin.action.update": "更新",
    "plugin.action.viewConfig": "プラグイン設定",
    "plugin.appUpdate.button": "本体を更新",
    "plugin.appUpdate.confirm": "更新",
    "plugin.appUpdate.failed": "本体の更新に失敗しました。",
    "plugin.appUpdate.ref": "バージョン",
    "plugin.appUpdate.refHead": "デフォルトブランチ最新（HEAD）",
    "plugin.appUpdate.refLatest": "最新リリース",
    "plugin.appUpdate.repo": "リポジトリ：{repo}",
    "plugin.appUpdate.success": "本体を更新しました",
    "plugin.appUpdate.tagInvalid": "タグを選ぶか、最新リリース / HEAD を使ってください。",
    "plugin.appUpdate.tagsEmpty": "タグは取得できませんでした。最新リリースと HEAD は利用できます。",
    "plugin.appUpdate.tagsLoading": "タグを読み込み中...",
    "plugin.appUpdate.title": "本体プログラムの更新",
    "plugin.appUpdate.version": "現在のバージョン：{version}",
    "plugin.appUpdate.versionUnknown": "現在のバージョン：不明",
    "plugin.appUpdate.warning":
      "GitHub のソース ZIP をダウンロードし、現在のインストール先にマージします（data と plugins は除外）。元に戻せません。",
    "plugin.author": "作者",
    "plugin.catalog.emptyBody": "索引を更新するとコミュニティプラグインが表示されます。",
    "plugin.catalog.emptyTitle": "表示できるプラグインがありません",
    "plugin.catalog.errorBody": "ネットワークを確認して再試行してください。",
    "plugin.catalog.errorTitle": "プラグイン索引を読み込めません",
    "plugin.catalog.loading": "プラグイン索引を読み込み中",
    "plugin.catalog.title": "発見",
    "plugin.description": "プラグインは固定 slot にのみ貢献し、platform 層を通じてインストール、有効化、無効化します。",
    "plugin.directory": "場所",
    "plugin.detail.back": "プラグイン一覧へ戻る",
    "plugin.detail.errorBody": "プラグインページのメタデータを読み込めませんでした。",
    "plugin.detail.errorTitle": "プラグイン設定を読み込めません",
    "plugin.detail.kindSettings": "設定ページ",
    "plugin.detail.kindTools": "ツールタブ",
    "plugin.detail.loading": "プラグイン設定を読み込み中",
    "plugin.detail.noUi": "このプラグインには設定ページがありません。",
    "plugin.detail.pages": "プラグインページ",
    "plugin.detail.pyqtNotice":
      "このプラグインはまだ PyQt ウィジェットとして提供されており、React の設定 schema は公開されていません。",
    "plugin.detail.save": "設定を保存",
    "plugin.detail.saveFailed": "プラグイン設定を保存できませんでした。",
    "plugin.detail.saveSuccess": "プラグイン設定を保存しました",
    "plugin.detail.settingsPages": "設定ページ",
    "plugin.detail.title": "{title} 設定",
    "plugin.detail.toolsTabs": "ツールタブ",
    "plugin.disable.confirmBody": "次回起動時に「{title}」を無効化しますか？",
    "plugin.disable.confirmTitle": "プラグインを無効化",
    "plugin.error.installFallback": "プラグイン ID またはネットワーク状態を確認してください。",
    "plugin.error.toggleFallback": "プラグイン状態を更新できませんでした。",
    "plugin.error.uninstallFallback": "プラグインを削除できませんでした。",
    "plugin.id": "プラグイン ID",
    "plugin.install.entryHelp":
      "manifest entry に対応。GitHub リポジトリはソース取得、依存関係のインストール、自動登録を試みます。",
    "plugin.install.entryLabel": "プラグイン ID",
    "plugin.install.placeholder": "plugins.xxx.plugin:Plugin または owner/repo",
    "plugin.install.title": "インストール",
    "plugin.installRef.title": "プラグインのバージョンを選択",
    "plugin.installed.emptyBody": "インストール後ここに表示されます。",
    "plugin.installed.emptyTitle": "プラグインなし",
    "plugin.installed.count": "{count} 件のプラグイン",
    "plugin.installed.loading": "プラグインを読み込み中",
    "plugin.installed.title": "インストール済み",
    "plugin.loadError.unavailable":
      "plugins.yaml には設定されていますが、プラグインコードが未インストールか、インポートに失敗しました。",
    "plugin.permissions": "権限",
    "plugin.plugin": "プラグイン",
    "plugin.toggle.disable": "無効化",
    "plugin.toggle.enable": "有効化",
    "plugin.status.downloaded": "ダウンロード済み",
    "plugin.status.disabled": "無効",
    "plugin.status.enabled": "有効",
    "plugin.status.installed": "インストール済み",
    "plugin.status.notInstalled": "未インストール",
    "plugin.status.unavailable": "未読み込み",
    "plugin.status.updating": "更新中",
    "plugin.table.actionHeader": "操作",
    "plugin.table.slots": "Slots",
    "plugin.toast.disabled": "プラグインを無効化しました",
    "plugin.toast.enabled": "プラグインを有効化しました",
    "plugin.toast.installFailed": "インストール失敗",
    "plugin.toast.installSuccess": "プラグインをインストールしました",
    "plugin.toast.operationFailed": "操作失敗",
    "plugin.toast.restartHint": "プラグイン変更を反映するにはアプリを再起動してください。",
    "plugin.toast.uninstalled": "プラグインをアンインストールしました",
    "plugin.uninstall.confirmBody":
      "「{title}」を manifest から削除し、安全な場合はプラグインフォルダーも削除しますか？",
    "plugin.uninstall.confirmTitle": "プラグインをアンインストール",
    "plugin.version": "バージョン",
    "system.asr.computeAuto": "自動（デバイスに合わせる）",
    "system.asr.computeType": "計算精度 (compute_type)",
    "system.asr.device": "推論デバイス",
    "system.asr.deviceAuto": "自動",
    "system.asr.followUi": "表示言語に合わせる",
    "system.asr.hint":
      "認識言語は全エンジン共通です。Whisper モデル、デバイス、精度は Whisper 系エンジン選択時のみ表示し、Vosk ではモデルパスだけを扱います。",
    "system.asr.langEn": "English",
    "system.asr.langJa": "日本語",
    "system.asr.langYue": "粵語",
    "system.asr.langZh": "中文",
    "system.asr.language": "認識言語",
    "system.asr.modelCustom": "カスタム（ローカルパスまたは HF 名）",
    "system.asr.modelCustomPlaceholder": "ローカルフォルダまたはモデル ID",
    "system.asr.provider": "認識エンジン",
    "system.asr.title": "音声入力（ASR）",
    "system.asr.voskHint": "Vosk モデルをダウンロードして解凍し、フォルダパスを Vosk model path に入力してください。",
    "system.asr.voskModelPath": "Vosk model path",
    "system.asr.voskModels": "Vosk モデル",
    "system.asr.whisperModel": "Whisper モデル",
    "system.description": "基本インターフェース、メディアパス、配信ルーム設定。",
    "system.error.saveFallback": "システム設定を確認してください。",
    "system.loading": "システム設定を読み込み中",
    "system.title": "システム",
    "system.toast.saved": "システム設定を保存しました",
    "template.action.launch": "チャット開始",
    "template.action.quickRestart": "クイック再起動",
    "template.action.selectAllCharacters": "全キャラクターを選択",
    "template.defaultName": "新規テンプレート",
    "template.description":
      "テンプレート編集と生成はキャラクター、背景 query を再利用し、保存後にチャット開始を更新します。",
    "template.emptyBody": "まずテンプレートを生成してください。",
    "template.emptySelection": "テンプレートが選択されていません",
    "template.emptyTitle": "テンプレートがありません",
    "template.error.generateFailed": "生成失敗",
    "template.error.generateFallback": "キャラクターと背景の選択を確認してください。",
    "template.error.launchFailed": "起動失敗",
    "template.error.saveFallback": "テンプレート内容を保存できませんでした。",
    "template.field.background": "背景",
    "template.field.characters": "キャラクター",
    "template.field.content": "内容",
    "template.field.historyFile": "履歴ファイル",
    "template.field.initSprite": "初期立ち絵",
    "template.field.maxDialogItems": "最大会話数",
    "template.field.maxSpeechChars": "最大台詞文字数",
    "template.field.name": "名前",
    "template.field.path": "パス",
    "template.field.scenario": "ユーザーシナリオ",
    "template.field.system": "システムテンプレート",
    "template.field.templateName": "テンプレート名",
    "template.field.useCg": "ComfyUI を使う",
    "template.field.useChoice": "選択肢ルール",
    "template.field.useCot": "COT プロンプト",
    "template.field.useEffect": "演出効果",
    "template.field.useNarration": "ナレーションルール",
    "template.field.useStat": "ステータスルール",
    "template.field.useTranslation": "LLM 翻訳",
    "template.field.voiceLanguage": "音声目標言語",
    "template.listTitle": "テンプレート",
    "template.loading": "テンプレートを読み込み中",
    "template.mode.edit": "編集",
    "template.mode.generate": "生成",
    "template.quickRestart.body": "選択中または既定のチャット履歴を削除し、新しいチャットを開始しますか？",
    "template.quickRestart.title": "クイック再起動",
    "template.section.content": "テンプレート内容",
    "template.section.generate": "テンプレート生成",
    "template.section.load": "ファイルから読み込み",
    "template.section.run": "保存と起動",
    "template.section.scenario": "ユーザーシナリオ",
    "template.section.system": "システムテンプレート",
    "template.title": "チャットテンプレート",
    "template.toast.generated": "テンプレートを生成しました",
    "template.toast.launched": "チャットを起動しました",
    "template.toast.saved": "テンプレートを保存しました",
    "template.transparentBackground": "透明场景",
    "template.validation.backgroundRequired": "背景を選択してください。",
    "template.validation.charactersRequired": "キャラクターを 1 人以上選択してください。",
    "template.validation.nameRequired": "テンプレート名は必須です。",
    "top.chatStage": "チャットステージ",
  },
  zh_CN: {
    "app.brandSubtitle": "AI RPG Tools",
    "app.preview": "设置",
    "app.shellMeta": "AI RPG Tools",
    "app.title": "新世界程序",
    "api.description":
      "配置大语言模型、TTS、语音输入与 ComfyUI；API 相关写入 api.yaml，麦克风识别选项写入 system_config.yaml。",
    "api.error.saveFallback": "请检查配置字段。",
    "api.links.help": "解压后请将目录填到 TTS 服务启动路径。GPT SoVITS 建议至少 11GB 磁盘，Genie TTS 约 4GB。",
    "api.links.link1": "GPT-SOVITS github 源地址",
    "api.links.link2": "点击下载 GPT-SOVITS 整合包 (ModelScope)",
    "api.links.link3": "50 系显卡整合包 (ModelScope)",
    "api.links.link4": "Genie TTS（适用于 CPU 的轻量推理）",
    "api.links.link5": "下载 Genie TTS Server 整合包（ModelScope .7z）",
    "api.links.title": "资源与说明",
    "api.language.field": "界面语言",
    "api.language.hint": "立即生效。独立运行的桌面主窗口在下次启动时应用。",
    "api.language.title": "界面语言",
    "api.llm.apiKey": "LLM API Key",
    "api.llm.baseUrl": "LLM API 基础网址",
    "api.llm.connectionTitle": "LLM API 配置",
    "api.llm.fetchDone": "已获取 {count} 个模型。",
    "api.llm.fetchEmpty": "未获取到可用模型。",
    "api.llm.fetchFailed": "获取模型列表失败。",
    "api.llm.fetchMissing": "请先填写 LLM 基础地址和 API Key。",
    "api.llm.fetchModels": "获取可用模型",
    "api.llm.fetchTitle": "模型列表",
    "api.llm.fetching": "正在获取模型",
    "api.llm.model": "模型 ID",
    "api.llm.modelCustom": "自定义模型 ID...",
    "api.llm.modelPlaceholder": "模型 ID",
    "api.llm.provider": "服务商",
    "api.llm.reasoningEffort": "思考强度",
    "api.llm.required": "服务商、基础地址、API Key 和模型 ID 都需要填写。",
    "api.llm.streaming": "流式响应",
    "api.llm.thinkingEnabled": "思考模式",
    "api.llm.thinkingUnsupported": "该模型不支持思考模式。",
    "api.loading": "正在读取 API 设定",
    "api.resume.btn": "加载上次聊天并启动",
    "api.resume.tip":
      "使用 data/chat_history 下最近修改的聊天记录和上次启动模板缓存，以透明背景、不启用 ComfyUI 的方式启动聊天。",
    "api.resume.title": "启动聊天",
    "api.tts.bundleDone": "TTS 整合包已就绪：{path}",
    "api.tts.bundleDownload": "下载",
    "api.tts.bundleFailed": "TTS 整合包下载失败。",
    "api.tts.bundleGenie": "Genie TTS Server",
    "api.tts.bundleGptSovits": "GPT-SoVITS v2pro",
    "api.tts.bundleGptSovits50": "50 系显卡 GPT-SoVITS v2pro",
    "api.tts.bundleHint": "下载并解压与 PySide 设置窗口相同的 TTS 整合包。",
    "api.tts.bundlePick": "整合包",
    "api.tts.bundleTitle": "TTS 整合包",
    "api.title": "API 配置",
    "api.toast.saved": "API 设定已保存",
    "background.delete.confirmBody": "确认删除背景组「{name}」？",
    "background.delete.confirmTitle": "删除背景",
    "background.description": "背景组、图片标签和 BGM 标签在这里维护，供模板与聊天启动复用。",
    "background.emptyBody": "新建背景组后可在模板中引用。",
    "background.emptyTitle": "暂无背景",
    "background.error.deleteFallback": "背景未删除。",
    "background.error.exportFallback": "背景包未导出。",
    "background.error.importFallback": "背景包未导入。",
    "background.error.saveFallback": "背景字段未通过校验。",
    "background.error.translateFallback": "AI 翻译失败。",
    "background.field.bgTags": "图片标签",
    "background.field.bgmTags": "BGM 标签",
    "background.field.name": "名称",
    "background.field.spritePrefix": "资源目录",
    "background.groupListTitle": "背景组",
    "background.loading": "正在读取背景",
    "background.resource.backgroundImage": "背景图片",
    "background.resource.bgm": "BGM",
    "background.resource.count": "数量",
    "background.resource.description": "当前 React 层只维护资源声明；实际图片上传、复制和校验由平台适配层实现。",
    "background.resource.imageCount": "{count} 图",
    "background.resource.source": "来源",
    "background.resource.type": "类型",
    "background.action.aiTranslate": "AI 翻译",
    "background.action.community": "社区背景",
    "background.action.saveBgmTags": "保存背景音乐描述",
    "background.action.saveImageTags": "保存背景说明到当前组",
    "background.action.uploadContribution": "上传投稿",
    "background.asset.addBgm": "添加 BGM 行",
    "background.asset.addImage": "添加图片行",
    "background.asset.clearBgm": "删除所有背景音乐",
    "background.asset.clearImages": "删除所有背景图片",
    "background.asset.deleteSelectedBgm": "批量删除已选 BGM",
    "background.asset.emptyBgm": "暂无 BGM",
    "background.asset.emptyImages": "暂无背景图片",
    "background.asset.filename": "文件名",
    "background.asset.index": "序号",
    "background.asset.noSelectedBgm": "请先勾选要删除的音乐条。",
    "background.asset.path": "路径",
    "background.asset.preview": "试听",
    "background.asset.select": "选择",
    "background.asset.selectBgm": "选择 BGM 文件",
    "background.asset.selectImages": "选择背景图片",
    "background.asset.selectedFiles": "已选择 {count} 个文件",
    "background.asset.tag": "标签描述",
    "background.asset.uploadBgm": "上传列表中的 BGM",
    "background.asset.uploadError": "资源上传失败。",
    "background.asset.uploadImages": "上传列表中的图片",
    "background.section.assets": "资源",
    "background.section.bgm": "背景音乐",
    "background.section.images": "背景图片",
    "background.section.info": "背景信息",
    "background.section.tags": "标签",
    "background.title": "背景管理",
    "background.toast.deleted": "背景已删除",
    "background.toast.exportComplete": "导出完成",
    "background.toast.importComplete": "导入 {count} 个背景组",
    "background.toast.saved": "背景已保存",
    "background.validation.nameRequired": "背景名称不能为空。",
    "bottom.ready": "就绪",
    "bottom.author": "By: 不二咲爱笑",
    "bottom.saving": "正在保存",
    "bottom.syncing": "正在同步",
    "bottom.transport": "组件通过 repository、query 和 platform adapter 通信",
    "character.delete.confirmBody": "确认删除角色「{name}」？",
    "character.delete.confirmTitle": "删除角色",
    "character.description": "角色资料、立绘、情绪标签和 TTS 参数集中编辑。",
    "character.emptyBody": "导入角色包或新建角色。",
    "character.emptyTitle": "暂无角色",
    "character.error.aiFallback": "AI 帮写失败。",
    "character.error.deleteFallback": "角色未删除。",
    "character.error.exportFallback": "角色包未导出。",
    "character.error.importFallback": "角色包未导入。",
    "character.error.saveFallback": "角色字段未通过校验。",
    "character.error.translateFallback": "AI 翻译失败。",
    "character.action.aiTranslate": "AI 翻译",
    "character.action.aiWrite": "AI 帮写",
    "character.action.community": "社区角色",
    "character.action.pickColor": "选择颜色",
    "character.action.uploadContribution": "上传投稿",
    "character.field.characterSetting": "人物设定",
    "character.field.color": "名字颜色",
    "character.field.emotionTags": "标注立绘情绪关键字（与上传/排序对应）",
    "character.field.gptModel": "GPT 模型路径",
    "character.field.name": "角色名",
    "character.field.promptLang": "语言 (en/ja/zh)",
    "character.field.promptText": "参考音频文字内容",
    "character.field.pronunciationMap": "读音映射",
    "character.field.referAudio": "参考音频",
    "character.field.sovitsModel": "SoVITS 模型",
    "character.field.speechSpeed": "TTS 语速",
    "character.field.speechVolume": "TTS 语音音量",
    "character.field.spritePrefix": "上传数据目录名（英文）",
    "character.field.spriteScale": "立绘显示缩放",
    "character.import.noFile": "未选择文件",
    "character.listTitle": "角色",
    "character.loading": "正在读取角色",
    "character.memory.add": "添加记忆",
    "character.memory.count": "{count} 条记忆",
    "character.memory.delete": "删除",
    "character.memory.empty": "暂无记忆",
    "character.memory.error": "记忆操作失败。",
    "character.memory.loading": "正在读取记忆",
    "character.memory.nameRequired": "输入或选择角色名后管理长期记忆。",
    "character.memory.placeholder": "记忆内容",
    "character.memory.refresh": "刷新",
    "character.memory.section": "长期记忆",
    "character.row.current": "当前角色",
    "character.section.basic": "基础信息",
    "character.section.personality": "角色设定",
    "character.section.sprites": "立绘管理",
    "character.section.voice": "语音模型参考（SoVITS 等，可选）",
    "character.sprite.add": "添加立绘行",
    "character.sprite.clear": "删除所有立绘",
    "character.sprite.empty": "暂无立绘",
    "character.sprite.imageError": "立绘图片操作失败。",
    "character.sprite.path": "立绘路径",
    "character.sprite.saveScale": "保存缩放",
    "character.sprite.saveTags": "上传立绘标注",
    "character.sprite.selectImages": "选择立绘图片...",
    "character.sprite.selectedFiles": "已选择 {count} 个文件",
    "character.sprite.deleteVoice": "删除语音",
    "character.sprite.saveVoiceText": "保存文本",
    "character.sprite.uploadVoice": "上传语音",
    "character.sprite.uploadImages": "上传图片",
    "character.sprite.voiceError": "立绘语音操作失败。",
    "character.sprite.voiceHint": "语音路径与文本按立绘逐条保存，对齐 PySide 的当前立绘语音区域。",
    "character.sprite.voicePath": "语音路径",
    "character.sprite.voiceText": "语音文本",
    "character.sprite.voiceUploadPath": "待上传语音",
    "character.title": "人物设定",
    "character.toast.deleted": "角色已删除",
    "character.toast.exportComplete": "导出完成",
    "character.toast.importComplete": "导入 {count} 个角色",
    "character.toast.saved": "角色已保存",
    "character.validation.gptModelExt": "GPT 模型路径后缀应为 .ckpt。",
    "character.validation.nameRequired": "角色名不能为空。",
    "character.validation.noQuotedPaths": "模型与参考音频路径不要用双引号包裹。",
    "character.validation.sovitsModelExt": "SoVITS 模型路径后缀应为 .pth。",
    "character.validation.spritePrefixAscii": "立绘目录只能包含英文、数字和英文标点。",
    "character.validation.spritePrefixRequired": "立绘目录不能为空。",
    "chat.clear.confirmAction": "清空",
    "chat.clear.confirmBody": "确认清空当前会话历史？这个操作会删除已关联的历史文件。",
    "chat.clear.confirmTitle": "清空历史",
    "chat.emptyDialog": "等待对话开始。",
    "chat.error.commandFallback": "聊天命令未执行。",
    "chat.error.loadFallback": "无法读取聊天状态",
    "chat.input.micDenied": "麦克风权限被拒绝。",
    "chat.input.micError": "语音识别未能启动。",
    "chat.input.micStart": "启动麦克风",
    "chat.input.micStop": "停止麦克风",
    "chat.input.micUnsupported": "当前浏览器不支持语音识别。请在本地 React bridge 中使用 Chrome/Edge。",
    "chat.input.placeholder": "输入对白",
    "chat.input.send": "发送",
    "chat.toast.historyCleared": "历史已清空",
    "chat.toast.historyCopied": "历史已复制",
    "chat.toast.historyOpened": "历史已打开",
    "chat.toolbar.clearHistory": "清空历史",
    "chat.toolbar.copyHistory": "复制历史",
    "chat.toolbar.openHistory": "打开历史",
    "chat.toolbar.pauseAsr": "暂停识别",
    "chat.toolbar.reroll": "重试回复",
    "chat.toolbar.skipSpeech": "跳过",
    "common.add": "添加",
    "common.author": "作者",
    "common.cancel": "取消",
    "common.chooseFile": "选择文件",
    "common.chooseFolder": "选择文件夹",
    "common.close": "关闭",
    "common.delete": "删除",
    "common.deleteFailed": "删除失败",
    "common.description": "说明",
    "common.edit": "编辑",
    "common.entry": "Entry",
    "common.name": "名称",
    "common.no": "否",
    "common.open": "打开",
    "common.refresh": "刷新",
    "common.remove": "移除",
    "common.retry": "重试",
    "common.save": "保存",
    "common.saveFailed": "保存失败",
    "common.saveApply": "保存并应用",
    "common.export": "导出",
    "common.exportFailed": "导出失败",
    "common.import": "导入",
    "common.importFailed": "导入失败",
    "common.new": "新建",
    "common.yes": "是",
    "common.operationFailed": "操作失败",
    "common.status": "状态",
    "common.subpages": "子页面",
    "common.validationFailed": "校验失败",
    "common.fixInvalidFields": "请先修正标红字段。",
    "form.jsonInvalid": "JSON 格式无效，修正后再保存。",
    "filePicker.address": "路径",
    "filePicker.empty": "这个文件夹为空。",
    "filePicker.hidden": "显示隐藏文件",
    "filePicker.loading": "正在读取文件夹...",
    "filePicker.modified": "修改时间",
    "filePicker.name": "名称",
    "filePicker.parent": "上级文件夹",
    "filePicker.roots": "位置",
    "filePicker.selectCurrent": "选择文件夹",
    "filePicker.selectFile": "选择文件",
    "filePicker.size": "大小",
    "filePicker.type": "类型",
    "filePicker.typeDirectory": "文件夹",
    "filePicker.typeFile": "文件",
    "launch.background": "背景",
    "launch.character": "角色",
    "launch.description": "启动参数由模板、角色、背景和历史记录组成，提交给聊天运行态。",
    "launch.emptyBody": "请先创建至少一个模板。",
    "launch.emptyTitle": "启动资料不完整",
    "launch.history": "历史记录",
    "launch.historyHelp": "多角色模板会按这里的选择顺序进入启动 payload。",
    "launch.historyPlaceholder": "./data/chat_history/...",
    "launch.start": "启动",
    "launch.template": "模板",
    "launch.title": "启动聊天",
    "launch.toast.failed": "启动失败",
    "launch.toast.started": "聊天已启动",
    "launch.validation.historyJson": "历史记录路径必须指向 .json 文件。",
    "mcp.action.openYaml": "打开 YAML",
    "mcp.action.previewTools": "刷新工具列表",
    "mcp.action.saveServer": "保存服务",
    "mcp.defaultTimeout": "默认调用超时",
    "mcp.delete.confirmBody": "从草稿列表中移除此 MCP 服务？",
    "mcp.delete.confirmTitle": "删除 MCP 服务",
    "mcp.description": "MCP 服务配置保存在 data/config/mcp.yaml，并通过 bridge 保存、预览和应用。",
    "mcp.dialog.addTitle": "添加 MCP 服务",
    "mcp.dialog.editTitle": "编辑 MCP 服务",
    "mcp.enabled": "启用",
    "mcp.field.args": "参数 JSON",
    "mcp.field.callTimeout": "调用超时",
    "mcp.field.command": "命令",
    "mcp.field.connection": "连接",
    "mcp.field.env": "环境变量 JSON",
    "mcp.field.group": "工具分组",
    "mcp.field.headers": "请求头 JSON",
    "mcp.field.prefix": "名称前缀",
    "mcp.field.registeredName": "注册名（LLM）",
    "mcp.field.transport": "传输",
    "mcp.field.toolName": "工具名",
    "mcp.field.url": "URL",
    "mcp.globalEnable": "启用 MCP 工具",
    "mcp.importJson": "从 JSON 导入",
    "mcp.importJson.hint": "粘贴包含 mcpServers 的 JSON 配置。",
    "mcp.importJson.noServers": "未找到 mcpServers 字段或为空。",
    "mcp.importJson.okBody": "已导入 {count} 个 MCP 服务。请点「保存并应用」生效。",
    "mcp.importJson.title": "导入 MCP JSON",
    "mcp.installHint": "连接真实服务前，请在当前 Python 环境安装 mcp 包。",
    "mcp.preview.empty": "未获取到工具。",
    "mcp.preview.emptyBody": "请检查服务是否启用、网络或命令。",
    "mcp.preview.loading": "正在读取 MCP 配置",
    "mcp.server.emptyBody": "添加 SSE、Streamable HTTP 或 stdio 服务。",
    "mcp.server.emptyTitle": "暂无 MCP 服务",
    "mcp.server.title": "MCP 服务",
    "mcp.status.disabled": "停用",
    "mcp.status.enabled": "启用",
    "mcp.status.no": "否",
    "mcp.status.yes": "是",
    "mcp.toast.importFailed": "导入失败",
    "mcp.toast.importSuccess": "MCP 服务已导入",
    "mcp.toast.opened": "配置文件已打开",
    "mcp.toast.operationFailed": "MCP 操作失败",
    "mcp.toast.previewSuccess": "MCP 工具列表已刷新",
    "mcp.toast.saveSuccess": "MCP 配置已保存",
    "mcp.tools.title": "已启用服务的工具预览",
    "mcp.validation.argsArray": "参数必须是 JSON 数组。",
    "mcp.validation.defaultTimeout": "默认超时必须大于 0。",
    "mcp.validation.envObject": "环境变量必须是 JSON 对象。",
    "mcp.validation.headersObject": "请求头必须是 JSON 对象。",
    "mcp.validation.needCommand": "stdio 服务需要填写命令。",
    "mcp.validation.needUrl": "HTTP MCP 服务需要填写 URL。",
    "nav.api": "API 设定",
    "nav.background": "背景管理",
    "nav.character": "人物设定",
    "nav.launch": "启动聊天",
    "nav.musicCover": "音乐翻唱",
    "nav.plugins": "插件",
    "nav.secondary": "辅助导航",
    "nav.settingsCenter": "设置中心导航",
    "nav.system": "系统",
    "nav.template": "聊天模板",
    "nav.tools": "小工具",
    "tools.browse": "浏览",
    "tools.character": "角色",
    "tools.cropBtn": "确认裁剪",
    "tools.cropInput": "输入目录",
    "tools.cropOutput": "输出目录（可空）",
    "tools.cropRatio": "保留上半部分比例",
    "tools.cropTitle": "批量裁剪立绘",
    "tools.description": "立绘生成、裁剪和抠图沿用 PySide 设置窗口的小工具流程。",
    "tools.galleryEmpty": "暂无已生成立绘",
    "tools.galleryLabel": "已生成的立绘",
    "tools.gemBox": "批量自动生成立绘（需配置 Gemini API Key）",
    "tools.gemHint": "需要 Gemini API Key。也可使用官方免费界面生成。",
    "tools.genPromptsBtn": "生成立绘提示词",
    "tools.genSpritesBtn": "批量生成立绘",
    "tools.h2Sprites": "立绘处理",
    "tools.msgGenFailed": "生成失败。",
    "tools.msgGenOk": "已生成 {n} 张（输出目录: {dir}）",
    "tools.msgNoPrompts": "请输入提示词",
    "tools.msgRefInvalid": "请选择有效的参考图片",
    "tools.msgSelectChar": "请选择角色",
    "tools.msgTitleGen": "生成",
    "tools.msgTitlePrompts": "提示词",
    "tools.outputDirPlaceholder": "输出目录，默认可留空",
    "tools.promptLine": "立绘 {n}：{text}",
    "tools.promptsGenerated": "已生成 {n} 条提示词。",
    "tools.promptsPlaceholder": "立绘提示词，一行一个",
    "tools.refDialogTitle": "参考图片",
    "tools.refLabel": "参考图片",
    "tools.refPlaceholder": "参考图片路径",
    "tools.rmbgBtn": "确认处理",
    "tools.rmbgFirst": "首次可能自动下载模型，耗时较长。",
    "tools.rmbgInput": "输入目录",
    "tools.rmbgOutput": "输出目录（可空）",
    "tools.rmbgTitle": "批量抠出立绘",
    "tools.spriteCount": "生成立绘数量",
    "tools.tabMain": "立绘与批处理",
    "plugin.action.install": "安装",
    "plugin.action.installed": "已安装",
    "plugin.action.openGitHub": "GitHub",
    "plugin.action.register": "登记",
    "plugin.action.uninstall": "卸载",
    "plugin.action.update": "更新",
    "plugin.action.viewConfig": "插件设置",
    "plugin.appUpdate.button": "更新主程序",
    "plugin.appUpdate.confirm": "更新",
    "plugin.appUpdate.failed": "主程序更新失败。",
    "plugin.appUpdate.ref": "版本",
    "plugin.appUpdate.refHead": "默认分支最新源码（HEAD）",
    "plugin.appUpdate.refLatest": "最新发布",
    "plugin.appUpdate.repo": "仓库：{repo}",
    "plugin.appUpdate.success": "主程序已更新",
    "plugin.appUpdate.tagInvalid": "请选择一个 tag，或改用最新发布 / HEAD。",
    "plugin.appUpdate.tagsEmpty": "未获取到 tag；仍可使用最新发布和 HEAD。",
    "plugin.appUpdate.tagsLoading": "正在读取 tags...",
    "plugin.appUpdate.title": "更新主程序",
    "plugin.appUpdate.version": "当前版本：{version}",
    "plugin.appUpdate.versionUnknown": "当前版本：未知",
    "plugin.appUpdate.warning":
      "将从 GitHub 下载源码归档并合并覆盖到当前程序目录（会跳过 data 和 plugins）。此操作不可自动撤销。",
    "plugin.author": "作者",
    "plugin.catalog.emptyBody": "刷新索引后会显示社区插件。",
    "plugin.catalog.emptyTitle": "暂无可发现插件",
    "plugin.catalog.errorBody": "检查网络后可重新刷新。",
    "plugin.catalog.errorTitle": "插件索引读取失败",
    "plugin.catalog.loading": "正在读取插件索引",
    "plugin.catalog.title": "发现",
    "plugin.description": "插件只能贡献到固定 slot，并通过平台层安装、启用和停用。",
    "plugin.directory": "位置",
    "plugin.detail.back": "返回插件列表",
    "plugin.detail.errorBody": "插件页面元数据读取失败。",
    "plugin.detail.errorTitle": "无法读取插件设置",
    "plugin.detail.kindSettings": "设置页",
    "plugin.detail.kindTools": "工具页",
    "plugin.detail.loading": "正在读取插件设置",
    "plugin.detail.noUi": "该插件没有设置页贡献。",
    "plugin.detail.pages": "插件页面",
    "plugin.detail.pyqtNotice": "该插件仍以 PyQt Widget 形式贡献设置页，尚未暴露 React 可渲染的配置 schema。",
    "plugin.detail.save": "保存设置",
    "plugin.detail.saveFailed": "插件设置未保存。",
    "plugin.detail.saveSuccess": "插件设置已保存",
    "plugin.detail.settingsPages": "设置页",
    "plugin.detail.title": "{title} 设置",
    "plugin.detail.toolsTabs": "工具页标签",
    "plugin.disable.confirmBody": "确认在下次启动时停用「{title}」？",
    "plugin.disable.confirmTitle": "停用插件",
    "plugin.error.installFallback": "检查插件 ID 或网络状态。",
    "plugin.error.toggleFallback": "插件状态未更新。",
    "plugin.error.uninstallFallback": "插件未卸载。",
    "plugin.id": "插件 ID",
    "plugin.install.entryHelp": "支持 manifest entry；GitHub 仓库会下载源码、安装依赖并尝试自动登记。",
    "plugin.install.entryLabel": "插件 ID",
    "plugin.install.placeholder": "plugins.xxx.plugin:Plugin 或 owner/repo",
    "plugin.install.title": "安装",
    "plugin.installRef.title": "选择插件版本",
    "plugin.installed.emptyBody": "安装后会显示在这里。",
    "plugin.installed.emptyTitle": "暂无插件",
    "plugin.installed.count": "{count} 个插件",
    "plugin.installed.loading": "正在读取插件",
    "plugin.installed.title": "已安装",
    "plugin.loadError.unavailable": "plugins.yaml 已配置该插件，但插件代码未安装或导入失败。",
    "plugin.permissions": "权限",
    "plugin.plugin": "插件",
    "plugin.toggle.disable": "停用",
    "plugin.toggle.enable": "启用",
    "plugin.status.downloaded": "已下载",
    "plugin.status.disabled": "已停用",
    "plugin.status.enabled": "已启用",
    "plugin.status.installed": "已安装",
    "plugin.status.notInstalled": "未安装",
    "plugin.status.unavailable": "未加载",
    "plugin.status.updating": "正在更新",
    "plugin.table.actionHeader": "操作",
    "plugin.table.slots": "Slot",
    "plugin.toast.disabled": "插件已停用",
    "plugin.toast.enabled": "插件已启用",
    "plugin.toast.installFailed": "安装失败",
    "plugin.toast.installSuccess": "插件已安装",
    "plugin.toast.operationFailed": "操作失败",
    "plugin.toast.restartHint": "重启应用后插件变更生效。",
    "plugin.toast.uninstalled": "插件已卸载",
    "plugin.uninstall.confirmBody": "确认将「{title}」从 manifest 移除，并在安全时删除对应插件目录？",
    "plugin.uninstall.confirmTitle": "卸载插件",
    "plugin.version": "版本",
    "system.asr.computeAuto": "自动（跟随设备）",
    "system.asr.computeType": "计算精度",
    "system.asr.device": "推理设备",
    "system.asr.deviceAuto": "自动",
    "system.asr.followUi": "跟随界面语言",
    "system.asr.hint":
      "识别语言对所有引擎共用；Whisper 模型、推理设备与计算精度仅在选用 Whisper 引擎时显示，Vosk 只保留模型目录字段。",
    "system.asr.langEn": "English",
    "system.asr.langJa": "日本語",
    "system.asr.langYue": "粵語",
    "system.asr.langZh": "中文",
    "system.asr.language": "识别语言",
    "system.asr.modelCustom": "自定义（本地目录或 Hugging Face 名）",
    "system.asr.modelCustomPlaceholder": "填写本地模型目录或完整模型 ID",
    "system.asr.provider": "识别引擎",
    "system.asr.title": "语音输入（ASR）",
    "system.asr.voskHint": "下载 Vosk 模型并解压后，将目录路径填入 Vosk model path 字段。",
    "system.asr.voskModelPath": "Vosk model path",
    "system.asr.voskModels": "Vosk 模型",
    "system.asr.whisperModel": "Whisper 模型",
    "system.description": "基础界面、媒体路径和直播配置。",
    "system.error.saveFallback": "请检查系统配置。",
    "system.loading": "正在读取系统设置",
    "system.title": "系统",
    "system.toast.saved": "系统设置已保存",
    "template.action.launch": "启动聊天",
    "template.action.quickRestart": "快速重开",
    "template.action.selectAllCharacters": "全选角色",
    "template.defaultName": "新模板",
    "template.description": "模板编辑与生成功能复用角色、背景 query，保存后刷新启动聊天页。",
    "template.emptyBody": "先生成一个模板。",
    "template.emptySelection": "未选择模板",
    "template.emptyTitle": "暂无模板",
    "template.error.generateFailed": "生成失败",
    "template.error.generateFallback": "请检查角色与背景选择。",
    "template.error.launchFailed": "启动失败",
    "template.error.saveFallback": "模板内容未保存。",
    "template.field.background": "背景",
    "template.field.characters": "角色",
    "template.field.content": "内容",
    "template.field.historyFile": "历史记录",
    "template.field.initSprite": "初始立绘",
    "template.field.maxDialogItems": "最大对话条数",
    "template.field.maxSpeechChars": "最大台词字数",
    "template.field.name": "名称",
    "template.field.path": "路径",
    "template.field.scenario": "用户情景",
    "template.field.system": "系统模板",
    "template.field.templateName": "模板名",
    "template.field.useCg": "启用 ComfyUI",
    "template.field.useChoice": "选择规则",
    "template.field.useCot": "思维链提示",
    "template.field.useEffect": "演出效果",
    "template.field.useNarration": "旁白规则",
    "template.field.useStat": "数值状态规则",
    "template.field.useTranslation": "LLM 翻译",
    "template.field.voiceLanguage": "语音目标语言",
    "template.listTitle": "模板",
    "template.loading": "正在读取模板",
    "template.mode.edit": "编辑",
    "template.mode.generate": "生成",
    "template.quickRestart.body": "清空当前/默认聊天记录并启动一局新聊天？",
    "template.quickRestart.title": "快速重开",
    "template.section.content": "模板内容",
    "template.section.generate": "生成模板",
    "template.section.load": "从文件加载",
    "template.section.run": "保存与启动",
    "template.section.scenario": "用户情景",
    "template.section.system": "系统模板",
    "template.title": "聊天模板",
    "template.toast.generated": "模板已生成",
    "template.toast.launched": "聊天已启动",
    "template.toast.saved": "模板已保存",
    "template.transparentBackground": "透明场景",
    "template.validation.backgroundRequired": "请选择背景。",
    "template.validation.charactersRequired": "请至少选择一个角色。",
    "template.validation.nameRequired": "模板名不能为空。",
    "top.chatStage": "聊天舞台",
  },
};
