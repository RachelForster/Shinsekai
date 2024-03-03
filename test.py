"""
先运行main.bat
"""

import requests

# # 根据音频说话
# data = {
#     "type": "speak",
#     "speech_path": r".\speech_data\uri_speech_0.wav"  # 修改为你的语音音频路径
# }

# 根据音频节奏摇
data = {
    "type": "rhythm",
    "music_path": r"D:\aichat\song\aLIEz\aLIEz.WAV"  # 修改为你的音频路径
}

print(requests.post('http://127.0.0.1:7888/alive', json=data).json())
