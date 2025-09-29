[中文版](README.md) | [English Version](docs/README_EN.md)

# Shinsekai Program

> AI-powered galgame/otome game/RPG engine with large language model integration, automatic sprite switching, and voice synthesis support

## Core Features

### AI Character Management
- **Character Creation & Configuration**
  - Custom character sprites, voices, and settings
  - AI-assisted generation of character backstories and personalities
  - Character import/export for easy sharing

### Sprite System
- **Visual Presentation**
  - Upload and manage multiple character sprites
  - Sprite scaling adjustment (0-3x)

- **Emotion Tagging**
  - Label emotional keywords for each sprite
  - Intelligent emotion-sprite matching

### Voice System
- **Dual Mode Support**
  - **Full Voice Mode**: Real-time voice generation for every line (requires GPT-SoVITS)
  - **Preset Voice Mode**: Play pre-uploaded voice files

![Wellerman-Uri](assets/present_example.png)

[![](https://img.shields.io/badge/-Full_Demo_Ⅰ-EEE?logo=bilibili)](https://www.bilibili.com/video/BV15H4y1o73x/?share_source=copy_web&vd_source=4641a345db4563ba087d0ed0ba8bdf85)
[![](https://img.shields.io/badge/-Full_Demo_Ⅱ-EEE?logo=bilibili)](https://www.bilibili.com/video/BV1Hp4y1c7TU/?share_source=copy_web&vd_source=4641a345db4563ba087d0ed0ba8bdf85)

**Video Tutorial: Coming Soon...0.0**

## Quick Start

### Get the Project
- Clone the repository:
git clone https://github.com/RachelForster/Shinsekai

text
- Or: Download the integrated package from releases: https://github.com/RachelForster/Shinsekai/releases 

### Install Dependencies
If using the integrated package, double-click `install.bat`

1. Create and activate virtual environment:
```
conda create -n shinsekai python=3.10
conda activate shinsekai
```
2. Install requirements:
```
pip install -r requirements.txt
```

### Start Using
If using the integrated package, double-click `start.bat` to launch Web UI

1. Run the following command in project directory:
```
python webui.py

```

### Download GPT-SoVITS Package (Optional)
Required if you want characters to speak their lines aloud

GPT-SoVITS Project: https://github.com/RVC-Boss/GPT-SoVITS

---

