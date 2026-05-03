[中文版](https://github.com/RachelForster/Shinsekai/blob/main/README.md) | [English](https://github.com/RachelForster/Shinsekai/blob/main/docs/README_EN.md)

# Shinsekai

A desktop assistant for **visual-novel / otome / story-driven RPG** play: let a large language model drive character dialogue, **keep sprites in sync with emotion**, and plug in **speech synthesis**, **speech recognition**, and extensions like **vision and tools**—configure everything in the local Settings app while the chat window stays focused on the scene.

---

## Why Shinsekai

- **One pipeline for performance**: templates, session history, sprite swaps and moods, TTS/ASR, and input plumbing are wired so you spend less time context-switching between tools.  
- **Two-window design**: the **Settings** app (`webui.py` / bundle) holds API, characters, and plugins; the **chat** window stays focused on dialogue and stage direction.  
- **Swap models and engines**: connect mainstream LLMs and OpenAI-compatible endpoints under **API settings**; **TTS** spans GPT-SoVITS, Genie TTS, CosyVoice, and lighter stacks without a discrete GPU; **image gen** can target ComfyUI-style backends on the same page.  
- **Listen and speak**: optional mic **ASR** (e.g. Vosk; more via **plugins**) and line **TTS**, or turn synthesis off and rely on per-sprite bundled audio only.  
- **More than plain chat**: built-in / plugin **LLM tools** plus **MCP** bring search, automation, and other services into the same turn.  
- **Extensible & themeable**: the **plugin SDK** adds adapters, settings pages, and chat chrome; UI language, fonts, and chat styling can be tuned via config and plugins (e.g. `chat_ui_theme`).  
- **Local-first data**: defaults live under **`data/`** (`api.yaml`, `system_config.yaml`, characters, history)—easy to back up or fork for your own project.  
- **Open source**: start from git or a [release bundle](https://github.com/RachelForster/Shinsekai/releases); optional plugins are listed in [Shinsekai-Plugin-Registry](https://github.com/RachelForster/Shinsekai-Plugin-Registry).

---

## Preview

![In-game example](../assets/present_example.png)

[![](https://img.shields.io/badge/Bilibili-Full_demo_I-00A1D6?logo=bilibili&logoColor=white)](https://www.bilibili.com/video/BV1V4H7z5Ez7/)
[![](https://img.shields.io/badge/Bilibili-Full_demo_II-00A1D6?logo=bilibili&logoColor=white)](https://www.bilibili.com/video/BV1Hp4y1c7TU/?share_source=copy_web&vd_source=4641a345db4563ba087d0ed0ba8bdf85)

**Walkthrough (Chinese audio/UI):** [API setup and importing a character pack](https://www.bilibili.com/video/BV1V4H7z5Ez7/)

---

## Feature snapshot

| Area | What you get |
|------|----------------|
| **Characters & templates** | Create / import-export character packs (`.char`); AI-assisted bios; **chat templates** for multi-character setups; **history** load/save, rewind, and archives. |
| **Sprites & staging** | Multi-image sprite sets; **0–3×** scale; per-image **emotion tags** tied to dialog mood commands; template-dependent CG / effect fields. |
| **Voice** | **TTS**: GPT-SoVITS, Genie TTS, CosyVoice, etc.—pick an engine under **API settings** and point at your server paths/URLs; choose “off” to play **per-sprite line audio** only. **ASR**: mic recognition defaults to **Vosk**; Whisper-class engines via **plugins**. |
| **LLM & tools** | Configure provider, **model id**, keys, and base URL under **API settings**; **streaming** and **tool calls**; tools from built-in / plugin **`@tool`** plus **MCP** (`data/config/mcp.yaml`). |
| **Text-to-image (T2I)** | **API settings** for **ComfyUI** (endpoint, workflow, node ids); other **T2I adapters** can be added via plugins. |
| **Settings & system** | **PySide** Settings for **API** (`data/config/api.yaml`) and **system** (`data/config/system_config.yaml`): UI language, ASR backend, theme tint, font size, and more. |
| **Plugins** | `data/config/plugins.yaml` manifest; **Plugins** tab to discover/install and toggle; extends LLM/TTS/ASR/T2I, tools, **Settings / Tools / chat** surfaces. |
| **MCP** | **Plugins → MCP** or YAML to attach SSE/stdio servers; tools registered into the in-process LLM tool list. |
| **Vision & other extensions** | Vision, theme editors, etc. ship as **official or community plugins** (see `plugins/`); capabilities vary by package README. |

---

## Quick start (~5 minutes)

### 1. Get the app

**From source:**

```bash
git clone https://github.com/RachelForster/Shinsekai
cd Shinsekai
```

**Bundle:** download and extract from [Releases](https://github.com/RachelForster/Shinsekai/releases) (`install.bat` / `start.bat` included).

### 2. Install dependencies

Bundle users: run `install.bat`.

Developers (Python 3.10 recommended):

```bash
conda create -n shinsekai python=3.10
conda activate shinsekai
pip install -r requirements.txt
```

### 3. Open Settings

Bundle: `start.bat`. From source:

```bash
python webui_qt.py
```

### 4. First conversation

1. Open **API settings**, configure your LLM (e.g. DeepSeek or any OpenAI-compatible endpoint), and save.  
2. Under **Character management**, import a pack (example: [nanami.char](https://github.com/RachelForster/Shinsekai/releases/download/v1.0.4/nanami.char)).  
3. Open **Chat template**, select the character, and generate a template.  
4. Click **Start chat**; send messages in the main window and watch sprites and replies.

### Optional: spoken lines

For synthesized dialogue audio, deploy [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS). On weaker hardware or without a dedicated GPU, prefer **Genie TTS** or similar in API settings.

---

## Plugin system

List plugins in **`data/config/plugins.yaml`**; source lives under **`plugins/<package>/`**. The host merges **LLM / TTS / ASR / T2I** adapters, **tools**, and contributions to **Settings**, the **tools area**, and the **chat window**.

- **UI**: Settings → **Plugins** — enable/disable, discover & download from the index, run `pip install -r requirements.txt` with the same interpreter as the app.  
- **Index:** [Shinsekai-Plugin-Registry](https://github.com/RachelForster/Shinsekai-Plugin-Registry)  
- **Scaffold:** `python -m sdk.cli create --package your_plugin_name`  
- **Developer guide:** [PLUGIN_DEVELOPER_GUIDE.md](PLUGIN_DEVELOPER_GUIDE.md)

Restart the app after changing the manifest so plugins reload.

---

## MCP (Model Context Protocol)

Expose [MCP](https://modelcontextprotocol.io/) servers to the **in-process LLM tool list**. Supported transports include **SSE** and **stdio**.

1. Install: `pip install mcp`  
2. Configure **`data/config/mcp.yaml`**, or use Settings → **Plugins** → **MCP** for a visual editor.  
3. **Save & apply** reconnects servers and registers remote tools for the current process (use a name **prefix** per server to avoid clashes).

Independent of the plugin system: you can wire external capabilities through YAML alone—no `PluginBase` required.

---

## Docs & links

| Topic | Link |
|------|------|
| Chinese README | [README.md](https://github.com/RachelForster/Shinsekai/blob/main/README.md) |
| GUI user guide (Chinese, non-technical) | [GUI_USER_GUIDE_zh-CN.md](GUI_USER_GUIDE_zh-CN.md) |
| Plugin developer guide | [PLUGIN_DEVELOPER_GUIDE.md](PLUGIN_DEVELOPER_GUIDE.md) |
| Repository | [github.com/RachelForster/Shinsekai](https://github.com/RachelForster/Shinsekai) |

Issues and PRs are welcome. If you redistribute character or voice assets, follow each author’s license.
