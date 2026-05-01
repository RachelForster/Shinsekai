# EasyAIDesktopAssistant — `ui/settings_ui`

本目录为 **PySide6 设置窗口**（原 Gradio WebUI 迁移）。根目录文件按职责分层如下：

| 路径 | 说明 |
|------|------|
| `main.py` | 主窗口装配：`Ui_MainWindow`、侧栏与 stacked 页面挂载 |
| `window.py` | 对外入口：`SettingsWindow`、`create_default_context`、窗口度量 |
| `context.py` | `SettingsUIContext` / `WebUIContext`，注入 ConfigManager 与各业务路径 |
| `feedback.py` | Toast / `QMessageBox` 反馈封装 |
| `utils.py` | 画廊路径、缩略图尺寸等共用工具 |
| `qt_mm.py` | QtMultimedia 惰性封装 |
| `ai_progress.py` / `ai_field_translate.py` | AI 进度条与字段翻译辅助 |
| `apply_qt_material.py` | 主题材质应用 |
| **`tabs/`** | 各设置页：`ApiSettingsTab`、`CharacterSettingsTab`、`BackgroundSettingsTab`、`TemplateSettingsTab`、`ToolsSettingsTab`、`MusicCoverSettingsTab` |
| **`services/`** | 无 Qt 或弱耦合逻辑：聊天模板读写与启动（`chat_template_handlers`）、模板页会话快照（`template_tab_session`） |
| **`tts/`** | TTS 离线包下载对话框、后台线程、运行环境探测 |
| **`modules/`** | PyDracula 壳：编译后的 `main.ui`、`resources_rc`、`UIFunctions` 等 |
| **`widgets/`** | 自定义控件（如窗口缩放 grip） |
| **`themes/`** | `.qss` / Python 主题定义 |

以下为原版 PyDracula 模板说明（捐赠链接、编译命令等），与上层应用共存：

---

# PyDracula - Modern GUI (PySide6)
# 

> ## :gift: **//// DONATE ////**
> ## 🔗 Donate (Gumroad): https://gum.co/mHsRC
> This interface is free for any use, but if you are going to use it commercially, consider helping to maintain this project and others with a donation by Gumroado at the link above. This helps to keep this and other projects active.

> **Warning**: this project was created using PySide6 and Python 3.9, using previous versions can cause compatibility problems.

# YouTube - Presentation And Tutorial
Presentation and tutorial video with the main functions of the user interface.
> 🔗 https://youtu.be/9DnaHg4M_AM

# Multiple Themes
![PyDracula_Default_Dark](https://user-images.githubusercontent.com/60605512/112993874-0b647700-9140-11eb-8670-61322d70dbe3.png)
![PyDracula_Light](https://user-images.githubusercontent.com/60605512/112993918-18816600-9140-11eb-837c-e7a7c3d2b05e.png)

# High DPI
> Qt Widgets is an old technology and does not have a good support for high DPI settings, making these images look distorted when your system has DPI applied above 100%.
You can minimize this problem using a workaround by applying this code below in "main.py" just below the import of the Qt modules.
```python
# ADJUST QT FONT DPI FOR HIGHT SCALE
# ///////////////////////////////////////////////////////////////
from modules import *
from widgets import *
os.environ["QT_FONT_DPI"] = "96"
```

# Running
> Inside your preferred terminal run the commands below depending on your system, remembering before installing Python 3.9> and PySide6 "pip install PySide6".
> ## **Windows**:
```console
python main.py
```
> ## **MacOS and Linux**:
```console
python3 main.py
```
# Compiling
> ## **Windows**:
```console
python setup.py build
```

# Project Files And Folders
> **main.py**: application initialization file.

> **main.ui**: Qt Designer project.

> **resouces.qrc**: Qt Designer resoucers, add here your resources using Qt Designer. Use version 6 >

> **setup.py**: cx-Freeze setup to compile your application (configured for Windows).

> **themes/**: add here your themes (.qss).

> **modules/**: module for running PyDracula GUI.

> **modules/app_funtions.py**: add your application's functions here.
Up
> **modules/app_settings.py**: global variables to configure user interface.

> **modules/resources_rc.py**: "resource.qrc" file compiled for python using the command: ```pyside6-rcc resources.qrc -o resources_rc.py```.

> **modules/ui_functions.py**: add here only functions related to the user interface / GUI.

> **modules/ui_main.py**: file related to the user interface exported by Qt Designer. You can compile it manually using the command: ```pyside6-uic main.ui> ui_main.py ```.
After expoting in .py and change the line "import resources_rc" to "from. Resoucers_rc import *" to use as a module.

> **images/**: put all your images and icons here before converting to Python (resources_re.py) ```pyside6-rcc resources.qrc -o resources_rc.py```.

# Projects Created Using PyDracula
**See the projects that were created using PyDracula.**
> To participate create a "Issue" with the name beginning with "#pydracula_project", leaving the link of your project on Github, name of the creator and what is its functionality. Your project will be added and this list will be deleted from "Issue".
**Malicious programs will not be added**!



