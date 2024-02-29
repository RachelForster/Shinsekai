# EasyAIVtuber

> 驱动你的纸片人老婆。
Simply animate your 2D waifu.

Fork自 [`EasyVtuber`](https://github.com/yuyuyzl/EasyVtuber)。由于是AI Vtuber，因此去掉了原项目的面捕功能。
本项目配合stable diffusion等文生图模型为最佳食用方式。

## Features not available in the original repo

1. 空闲自动做动作（眨眼、东张西望）
2. 说话动作（自动对口型）
3. 唱歌动作（自动对口型，跟随节奏摇摆）(coming soon...)
4. shaker (coming soon...)
5. API调用接口

Note [2024/2/28]: 阿里推出了[`EMO (Emote Portrait Alive)`](https://humanaigc.github.io/emote-portrait-alive/)。
它能够通过单一参考图像和音频输入，生成具有丰富表情和多样头部姿势的虚拟角色视频。
与其相比，该项目的优点在于：1. 实时性。 2. 可控性。而缺点在于：动作不够生动（纯靠手工调）以及只能使用二次元图片。

## Installation
### 安装依赖库
创建并激活虚拟环境  
```
conda create -n eaiv python=3.10
conda activate eaiv
```
安装torch（最好是30系显卡及以上）
```
# CUDA 11.8
pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118
```
然后在项目目录下执行以下命令  
```
pip install -r requirements.txt
```

### 下载预训练模型  

https://www.dropbox.com/s/y7b8jl4n2euv8xe/talking-head-anime-3-models.zip?dl=0  
解压到`data/models`文件夹中，与`placeholder.txt`同级  
正确的目录层级为  
```
+ models
  - separable_float
  - separable_half
  - standard_float
  - standard_half
  - placeholder.txt
```
### 安装OBS
可在网上自行搜索教程安装

### 安装UnityCapture

> 注：如果电脑上安装过VTube Studio，也许OBS的视频采集设备的设备中便会有 VTubeStudioCam（没做过实验不太确定）。
> 若有此设备，便无需执行下面步骤安装UnityCapture，直接使用 VTubeStudioCam 便可

为了能够在OBS上看到纸片老婆并且使用透明通道输出，需要安装UnityCapture  
参考 https://github.com/schellingb/UnityCapture#installation  
只需要正常走完Install.bat，在OBS的视频采集设备中便能看到对应的设备（Unity Video Capture）。

在OBS添加完摄像头以后，还需要手动配置一次摄像头属性才能支持ARGB    
右键属性-取消激活-分辨率类型自定义-分辨率512x512(与`--output_size`参数一致)-视频格式ARGB-激活

## Usage
1. 打开OBS并配置好视频采集设备
2. 将`main.bat`中第一行的虚拟环境的路径修改为你自己的虚拟环境路径
3. 运行`main.bat`
4. 使用post请求 http://127.0.0.1:7888/alive （默认端口为7888），
并传入相应参数便可使用音频文件自动生成模型的动作，可参考`test.py`

### main.bat params
