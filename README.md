# EasyAIVtuber

> 驱动你的纸片人老婆。
Simply animate your 2D waifu.

Fork自 [`yuyuyzl/EasyVtuber`](https://github.com/yuyuyzl/EasyVtuber)。由于是AI Vtuber，因此删减了原项目的面捕功能。喜欢请点个星星哦~
本项目配合stable diffusion等文生图模型为最佳食用方式。

**视频教程：制作中...0.0**

## Features not available in the original repo

1. 空闲自动做动作（眨眼、东张西望）
2. 说话动作（自动对口型）
3. 摇子（自动随节奏点头）
4. 唱歌动作（自动对口型，跟随节奏摇摆）
5. 睡大觉（使用`--sleep`参数控制入睡间隔）
6. API调用接口
7. webui方式调用

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

原模型文件地址：https://www.dropbox.com/s/y7b8jl4n2euv8xe/talking-head-anime-3-models.zip?dl=0  
下载后解压到`data/models`文件夹中，与`placeholder.txt`同级  

如果不想下载所有权重（四个版本），也可以在huggingface上下载：https://huggingface.co/ksuriuri/talking-head-anime-3-models

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

> 注：如果电脑上安装过VTube Studio，也许OBS的视频采集设备的设备中就会有 VTubeStudioCam（没做过实验不太确定）。
> 若有此设备，便无需执行下面步骤安装UnityCapture，直接使用 VTubeStudioCam 即可

为了能够在OBS上看到纸片老婆并且使用透明背景，需要安装UnityCapture  
参考 https://github.com/schellingb/UnityCapture#installation  
只需要正常走完Install.bat，在OBS的视频采集设备中便能看到对应的设备（Unity Video Capture）。

#### 如何使背景透明
在OBS添加完视频采集设备以后，右键视频采集设备-设置-取消激活-分辨率类型选自定义-分辨率512x512(与`--output_size`参数一致)-视频格式选ARGB-激活

## Usage
### 快速测试
1. 打开OBS，添加视频采集设备并按要求（[安装UnityCapture](#安装unitycapture)）进行配置
2. 将`main.bat`中第一行的虚拟环境的路径修改为你自己的虚拟环境路径
3. 运行`main.bat`，等待初始化完毕，如配置无误，这时OBS中便能够看到人物在动
4. 二选一
   1. 简单测试：运行`test.py`   
   2. 运行webui：将`webui.bat`中第一行的虚拟环境的路径修改为你自己的虚拟环境路径，然后运行`webui.bat`  

具体使用可参考 [API Details](#api-details) 

### 启动参数

|        参数名        |  类型   |                                             说明                                              |
|:-----------------:|:-----:|:-------------------------------------------------------------------------------------------:|
|    --character    |  str  |                              `data/images`目录下的输入图像文件名，不需要带扩展名                               |
|   --output_size   |  str  |               格式为`512x512`，必须是4的倍数。<br>增大它并不会让图像更清晰，但配合extend_movement会增大可动范围               |
|    --simplify     |  int  |                           可用值为`1` `2` `3` `4`，值越大CPU运算量越小，但动作精度越低                           |
|  --output_webcam  |  str  |                           可用值为`unitycapture`，选择对应的输出种类，不传不输出到摄像头                            |
|      --model      |  str  | 可用值为`standard_float` `standard_half` `separable_float` `separable_half`，<br/>显存占用不同，选择合适的即可 |
|      --port       |  int  |                               本地API的端口号，默认为7888，若7888被占用则需要更改                               |
|      --sleep      |  int  |                           入睡间隔，默认为20，空闲状态下20秒后会睡大觉，设置为-1即可不进入睡觉状态                           |
| --extend_movement | float |                （暂时没有用）根据头部位置，对模型输出图像进一步进行移动和旋转使得上半身可动<br>传入的数值表示移动倍率（建议值为1）                 |

## API Details

API使用Flask来开发，默认运行在 http://127.0.0.1:7888 （默认端口为7888），可在`main.bat`的`--port`中修改端口号。
使用post请求 http://127.0.0.1:7888/alive ，并传入参数即可做出对应动作，具体示例可参考`test.py`。

### 根据音频说话

**`REQUEST`**
```json
{
  "type": "speak",
  "speech_path": "your speech path"
}
```

在`"speech_path"`中填写你的语音音频路径，支持wav, mp3, flac等格式（pygame支持的格式）

**`RESPONSE`**
```json
{
  "status": "success"
}
```

### 根据音乐节奏摇

**`REQUEST`**
```json
{
  "type": "rhythm",
  "music_path": "your music path",
  "beat": 2
}
```

在`"music_path"`中填写你的音频路径，支持wav, mp3, flac等格式（pygame支持的格式）。  
`"beat"`（可选）：取值为 `1` `2` `4`，控制节拍，默认为2

**`RESPONSE`**
```json
{
  "status": "success"
}
```

### 根据音乐和人声唱歌

**`REQUEST`**
```json
{
  "type": "sing",
  "music_path": "your music path",
  "voice_path": "your voice path",
  "mouth_offset": 0.0,
  "beat": 2
}
```

口型驱动的原理是根据音量大小来控制嘴巴的大小，因此需要事先将人声提取出来以更精准地控制口型。
假设你有一首歌，路径为`path/music.wav`，利用UVR5等工具分离出人声音频`path/voice.wav`，然后将`path/music.wav`填入`"music_path"`，
将`path/voice.wav`填入`"voice_path"`，支持wav, mp3, flac等格式（pygame支持的格式）。  
`"mouth_offset"`（可选）：取值区间为 `[0, 1]`，默认为`0`，如果角色唱歌时的嘴张的不够大，可以试试将这个值设大  
`"beat"`（可选）：取值为`1` `2` `4`，默认为`2`，控制节拍

**`RESPONSE`**
```json
{
  "status": "success"
}
```

### 停止当前动作

**`REQUEST`**
```json
{
  "type": "stop"
}
```

**`RESPONSE`**
```json
{
  "status": "success"
}
```

### 更换当前图片

**`REQUEST`**
```json
{
  "type": "change_img", 
  "img": "your image path"
}
```

在`"img"`中填写图片路径，图片大小最好是`512x512`，png格式

**`RESPONSE`**
```json
{
  "status": "success"
}
```

