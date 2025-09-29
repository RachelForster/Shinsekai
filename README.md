# 新世界程序

> AI galgame/乙女游戏/RPG游戏，接入大语言模型，自动切换立绘，支持语音合成

## 核心功能

### AI角色管理
- **角色创建与配置**
  - 自定义角色名称、显示颜色
  - AI辅助生成角色背景故事和性格设定
  - 支持角色导入/导出，方便分享

### 立绘系统
- **视觉展示**
  - 多张立绘上传和管理
  - 立绘缩放调节（0-3倍可调）

- **情绪标注**
  - 为每张立绘标注情绪关键词
  - 智能情绪与立绘匹配
  - 批量情绪标签管理

### 语音系统
- **双模式支持**
  - **全语音模式**：每句台词实时生成语音（需GPT-SoVITS）
  - **预设语音模式**：播放预先上传的语音文件

- **语音管理**
  - 为立绘绑定特定语音
  - 支持多种音频格式
  - 语音文本内容管理

![Wellerman-Uri](assets/2347acc3-799f-4913-8035-ae077ba3dc22.gif)

[![](https://img.shields.io/badge/-完整效果展示Ⅰ-EEE?logo=bilibili)](https://www.bilibili.com/video/BV15H4y1o73x/?share_source=copy_web&vd_source=4641a345db4563ba087d0ed0ba8bdf85)
[![](https://img.shields.io/badge/-完整效果展示Ⅱ-EEE?logo=bilibili)](https://www.bilibili.com/video/BV1Hp4y1c7TU/?share_source=copy_web&vd_source=4641a345db4563ba087d0ed0ba8bdf85)

**视频教程：制作中...0.0**

## 快速使用
### 获取项目
- git clone本项目
```
git clone https://github.com/RachelForster/Shinsekai
```
- 或者：下载整合包并解压


### 安装依赖库
如果是整合包，请双击install.bat
1. 创建并激活虚拟环境  
```
conda create -n shinsekai python=3.10
conda activate shinkekai
```
2. 然后在项目目录下执行以下命令  
```
pip install -r requirements.txt
```
### 开始使用
如果是整合包，双击start.bat则可以开启Web ui
1. 在项目目录下执行：
```
python webui.py
```

### 下载GPT-SOVITS整合包(可选)  
如果你需要角色读出台词，则需要下载该整合包
GPT-SOVITS 项目地址：https://github.com/RVC-Boss/GPT-SoVITS