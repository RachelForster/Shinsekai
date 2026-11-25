<p align="center">
  <img src="../assets/system/picture/shinsekai-github-banner.png" alt="Shinsekai GitHub Banner" width="100%">
</p>

[中文版](https://github.com/RachelForster/Shinsekai/blob/main/README.md) | [English](https://github.com/RachelForster/Shinsekai/blob/main/docs/README_EN.md)

# Shinsekai

A source-available desktop companion and interactive performance platform for **visual-novel / otome / story-driven RPG** play: let large language models drive character dialogue and story staging with **multi-format visuals (static/animated sprites, MMD, Live2D)**, **outfit groups and emotion sync**, **speech synthesis and lip-sync**, **long-term memory and knowledge retrieval**, **real-time screen perception**, a **built-in desktop agent**, and **plugin / MCP extensions**—managed centrally in the React / Tauri Settings app while the chat stage stays focused on immersion.

---

## Why Shinsekai

- **Fast setup & full visual-novel staging**: a **5-step onboarding wizard** gets LLM, voice, and characters running quickly; dialogue automatically switches **backgrounds & BGM**, presents **branching choices & live affinity/stat changes**, triggers **sound & visual effects**, and can generate **custom CGs on the fly** via **ComfyUI**.
- **Screen-aware companion & desktop pet**: **real-time screen sharing + local RapidOCR** lets characters react to gameplay, watch videos/anime with subtitle awareness, and adapt pacing for video calls, reading, or idle moments; supports **LAN mobile QR companion** and a draggable, edge-docking **circular mini-avatar mode** (with global input shortcut).
- **Static, transparent video, and 3D / 2D avatars**: supports images, **MP4 / WebM** transparent animated sprites, built-in **MMD (PMX)** models with auto breathing, breeze, gaze, and VPD / VMD motions, and experimental **Live2D** support—plus **lip-sync & speaking blinks** and **outfit groups with story-driven auto-switching**.
- **Full expression sets & matting studio**: built-in LLM prompt planning, T2I generation, optional **MiniMax H3** image-to-video (generate expressive sprite sets from a single reference, 22-frame directional transitions, and transparent animated sprites), and **ToonOut / ISNet** matting.
- **One-sentence character creation & AI branching story canvas**: ask the built-in **desktop agent (Pi runtime)** to research info, draft character bios, generate/import sprites, and prepare voices end-to-end; use **Story Mode** to turn a premise into an editable **branching node canvas**, run **multi-character ensemble scenes**, and export replays as **MP4 / WebM videos**.
- **Everyday assistant & system tray reminders**: the desktop agent can search guides online (via browser plugins), read/write local files, organize folders, and save notes into your knowledge base; desktop builds support **system tray residency, autostart, and scheduled character voice reminders**.
- **Structured long-term memory, worldbooks & relationships**: powered by a local **SQLite + FTS5 + ONNX** hybrid engine with **Ebbinghaus retention decay**, **per-save memory isolation**, a built-in **self-persona**, **character relationship graphs**, and a separate **knowledge base (RAG)** for worldbooks and TXT lore imports.
- **Themes, voice & plugin ecosystem**: includes **5 built-in Galgame chat themes** (plus a **visual theme customizer**), community character packs, **GPT-SoVITS / Genie TTS / CosyVoice**, **Vosk / Whisper**, **plugin SDK**, and **MCP (SSE / stdio)**, with local-first data under `data/`.

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
| **Onboarding & desktop tray** | **5-step guided setup** (API / plugins / characters / backgrounds); unified React / Tauri Settings app with **system tray minimization**, OS autostart, and **scheduled character voice reminders**. |
| **Characters, relations & self-persona** | Create / import-export character packs (`.char`), AI-assisted bios & translation, or one-sentence agent creation; visual **character relationship graphs** with affinity (-10 to +10) injected into dialogue context; built-in **self-persona** for global player identity. |
| **Sprites, outfits & dynamic models** | Images, MP4 / WebM transparent video, **MMD (PMX + VPD/VMD)**, and experimental **Live2D**; unified full / half / close-up framing; **outfit groups** (smart auto-grouping, manual switch/lock, story auto-switching); **lip-sync & speaking blinks**; smooth crossfade fallback without transition clips. |
| **AI sprite studio** | Centered workspace: LLM prompt & Chinese tag planning, reference-preserving T2I (generate multi-expression sprite sets from one image), optional **MiniMax H3** frame picking / transparent animation / 22-frame directional transitions (with chat-history recommendations) and ToonOut / ISNet matting. |
| **Stage, replay & mini avatar** | Auto-switching **backgrounds, BGM & SFX/visual effects**, **branching options & affinity/stat updates**, and live **ComfyUI CG generation**; single-timeline compaction & 4-in-1 revert cascade; multi-select history **stage replay** (with optional voice completion), **copy / PNG screenshot / MP4·WebM video recording**; **circular mini-avatar widget** and **LAN mobile QR access**. |
| **AI story & node canvas** | Turn a premise and cast into a playable story with a visual **branching node graph** (drag-and-drop editing + LLM-assisted graph revisions), **multi-character scenes**, deterministic path validation, and versioned saves. |
| **Long-term memory & worldbooks** | Local **SQLite + FTS5 + ONNX** hybrid engine (zero PyTorch memory dependency); canon facts & Ebbinghaus retention decay, 3 save-isolation modes, and TXT/JSON history extraction; separate **knowledge manager** for worldbook/TXT imports with per-character bindings. |
| **Screen perception & desktop agent** | **Screen sharing + local RapidOCR** (subtitles / full screen / region) and shared-audio detection across 7 adaptive scenes (gaming, co-watching, video calls, reading, idle, etc.); **desktop agent (Pi runtime)** supporting web lookup, local file/folder tools, character setup, diagnostics, and plugin skills. |
| **Voice (TTS / ASR)** | **TTS**: GPT-SoVITS, Genie TTS, CosyVoice, etc., with optional voice archiving, per-sprite line audio fallback, and `characters.voice.prepare` automated voice pipeline; **ASR**: Vosk / Whisper with F8 hold-to-talk. |
| **Themes, plugins & MCP** | **5 built-in Galgame themes** and **visual theme customizer**; **ComfyUI** & T2I plugins; `data/config/plugins.yaml` + **Plugin Manager** ([Shinsekai-Plugin-Registry](https://github.com/RachelForster/Shinsekai-Plugin-Registry)); **MCP (SSE / stdio)** external tool integration. |

---

## Quick start (~5 minutes)

### 1. Get the app

**From source:**

```bash
git clone https://github.com/RachelForster/Shinsekai
cd Shinsekai
```

**Portable Bundle:** download and extract from [Releases](https://github.com/RachelForster/Shinsekai/releases). On Windows portable bundles, double-click `shinsekai.exe` directly.

### 2. Install dependencies

Source script users: run `scripts\install.bat` (Windows) or `scripts/install.command` (macOS).

Developers (Python 3.10 recommended):

```bash
conda create -n shinsekai python=3.10
conda activate shinsekai
pip install -r requirements.txt
```

Linux source users may also run `./scripts/install-linux.sh`. If a Python 3.10 non-`base` conda environment is active, the script installs dependencies into that environment; otherwise it prefers `uv` to create `.venv`, and falls back to a system `python3.10`.

### 3. Open Settings

Portable bundle (Windows): double-click `shinsekai.exe`. From source, use the platform launch script under `scripts/`:

```bash
./scripts/start.sh
```

Windows and macOS provide `scripts\start.bat` (plus `scripts\start-tauri.bat`) and `scripts/start.command`. Source builds require building the React frontend once (`cd frontend && pnpm install && pnpm build`). The retired Qt settings and chat windows are no longer available.

For Tauri desktop development:

```bash
cd frontend
pnpm install
pnpm tauri:dev
```

Before releasing, update the root `VERSION` file and run `pnpm sync:version` inside `frontend/` to sync `package.json`, Tauri Cargo manifests, and `runtime_manifest.json`.

### 4. First conversation

1. Open **API settings**, configure your LLM (e.g. DeepSeek or any OpenAI-compatible endpoint), test the connection, and save.  
2. Under **Character management**, import a pack (example: [nanami.char](https://github.com/RachelForster/Shinsekai/releases/download/v1.0.4/nanami.char); more packs at [Community Resources](https://rachelforster.github.io/Shinsekai/resources.html)), or open the **Assistant** in the bottom-left sidebar to help create one.  
3. Open **Chat template**, select characters (plus optional player character and initial outfits), and generate a template.  
4. Click **Start chat**; send messages on the stage and watch sprites, models, and voices respond.

### Optional: spoken lines

For synthesized dialogue audio, use **API settings → Voice** to download the recommended **GPT-SoVITS** or lightweight **Genie TTS** bundle (or deploy [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) manually), or let the desktop assistant prepare character voice references automatically.

---

## Plugin system

List plugins in **`data/config/plugins.yaml`**; source lives under **`plugins/<package>/`**. The host merges **LLM / TTS / ASR / T2I** adapters, **tools**, and contributions to **Settings**, the **tools area**, the **chat workspace**, and the **chat stage**.

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
|-------|------|
| Chinese README | [README.md](https://github.com/RachelForster/Shinsekai/blob/main/README.md) |
| Changelog & latest release notes | [CHANGELOG.md](../CHANGELOG.md) · [2.7.0 Release notes](releases/2.7.0.md) |
| GUI user guide (Chinese, non-technical) | [GUI_USER_GUIDE_zh-CN.md](GUI_USER_GUIDE_zh-CN.md) |
| Chat UI theme guide (Chinese) | [CHAT_UI_THEME_GUIDE_zh-CN.md](CHAT_UI_THEME_GUIDE_zh-CN.md) |
| Plugin developer guide | [PLUGIN_DEVELOPER_GUIDE.md](PLUGIN_DEVELOPER_GUIDE.md) |
| Repository | [github.com/RachelForster/Shinsekai](https://github.com/RachelForster/Shinsekai) |

Issues and PRs are welcome. If you redistribute character or voice assets, follow each author’s license.

---

## License Notice

Shinsekai is a source-available project licensed under the **PolyForm Strict License 1.0.0** with **Shinsekai Additional Permissions and Contribution Terms**. You may inspect, build, and modify the source code locally for personal noncommercial use and study, and maintain GitHub forks for learning, discussion, and submitting pull requests. Commercial use and redistribution (including modified copies, release builds, installers, portable bundles, standalone mirrors, or app/game store distribution) are not permitted without prior written permission. See [LICENSE](../LICENSE).
