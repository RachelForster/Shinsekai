# EasyAIVtuber

> 让你的纸片人老婆动起来。
Simply animate your 2D waifu.

## Installation
### 安装依赖库
在虚拟环境中执行以下命令  
```
pip install -r requirements.txt
```
然后安装torch（最好是30系显卡及以上）
```
# CUDA 11.8
pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118
# CUDA 12.1
pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu121
```

### 下载预训练模型  

https://github.com/pkhungurn/talking-head-anime-3-demo#download-the-models  
从原repo中下载（this Dropbox link）的压缩文件  
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

